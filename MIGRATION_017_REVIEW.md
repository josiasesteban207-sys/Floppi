# FLOPPI — Revisión de migration 017

**Migración:** `database/migrations/017_worker_credential_expiry.sql`  
**Dependencia directa:** `database/migrations/004_worker_credentials.sql`  
**Estado local:** código y pruebas inspeccionados; suite pytest ejecutada en esta sesión, 162/162 aprobada.  
**Estado Supabase staging:** BLOCKED; no se consultó ni modificó una base remota.

## SQL y efecto

La migration ejecuta una transacción que:

1. Actualiza toda fila de `public.worker_credentials` con `expires_at IS NULL`.
2. Fuerza `active = false`.
3. Conserva `revoked_at` existente o lo establece a `now()`.
4. Establece `expires_at = now()` para esas filas.
5. Cambia `expires_at` a NOT NULL.

No cambia políticas RLS, grants, índices, funciones ni otras tablas. Su precondición es que exista `public.worker_credentials` con columnas compatibles definidas por la migración 004. La migración 004 habilita RLS, revoca todos los privilegios cliente y otorga SELECT/UPDATE/INSERT a `service_role`.

## Compatibilidad del historial local

El checkout contiene migraciones 001–007 y 010–017; 008 y 009 faltan deliberadamente. Búsqueda del SQL muestra que, en las migraciones presentes entre 004 y 017, las menciones a `worker_credentials` se limitan a 004 y 017. Las referencias a `lease_expires_at` en migraciones posteriores pertenecen a `backtest_runs`, no a la expiración de credenciales worker.

Esto prueba compatibilidad estática del checkout, no que todas esas migraciones estén aplicadas o que el esquema remoto coincida. El ledger de staging y el catálogo real siguen sin verificarse.

## Pruebas examinadas y ejecutadas

En esta sesión, `python -m pytest -q` ejecutó la suite completa: **162 passed in 14.40s**.

`test_worker_auth.py` contiene pruebas de token hasheado asociado a nodo correcto, nodo incorrecto, credencial vencida, sin expiración y revocada; también inspecciona el SQL para confirmar revocación de filas sin expiry, NOT NULL, transacción y ausencia de `DISABLE ROW LEVEL SECURITY`.

`test_worker_expiry_migration_runner.py` verifica que el runner exija `--authorize-scratch-migration-017`, se configure sin red con almacenamiento temporal y solo aplique migration 004 en scratch cuando el backup restaurado no contiene la tabla. Estos tests de runner son principalmente unitarios/estáticos; no aplican 017 a Supabase.

El informe histórico `docs/MIGRATION_017_REVIEW_1_3_2_2.md` describe una corrida aislada anterior con backup local sin tabla y cuatro filas sintéticas. No se repitió el runner en esta sesión; no se presenta esa corrida anterior como ejecución actual.

## Riesgos operativos

- Todas las credenciales activas sin expiración pierden autorización tras el cambio. La cantidad real se desconoce.
- Workers desplegados con credenciales legacy podrían recibir 401; trabajos en lease pueden esperar a expiración/recuperación.
- `ALTER TABLE ... SET NOT NULL` necesita lock de tabla y valida el contenido de la columna; tamaño/latencia real del staging se desconocen.
- La migración no conserva una tabla de valores previos para reactivar credenciales. Tras commit, la recuperación prevista es emitir credenciales nuevas, no deshacer expiraciones.
- El bloque BEGIN/COMMIT y la ejecución a través del mecanismo migratorio seleccionado deben validarse en staging antes de decidir el procedimiento operacional.

## Preflight y postcondiciones requeridas

1. Confirmar identidad del proyecto staging separado y acceso de solo lectura.
2. Confirmar migrations 001–007, 010–016 y estado del ledger.
3. Comparar definición/constraints/índices/RLS/grants de tabla con migration 004.
4. Medir cantidad de filas total, filas con NULL expiry y credenciales activas afectadas; no exportar hashes ni tokens.
5. Identificar workers afectados y preparar reemisión/actualización sin revelar secretos.
6. Confirmar backup y plan de recuperación. Revisar/autorizar explícitamente la aplicación.
7. Aplicar solo en staging autorizado y verificar que no hay NULL expiry, que credenciales legacy están inactivas/revocadas y que las credenciales válidas no cambiaron.
8. Comprobar autorización de worker, rechazo de token legacy, RLS/grants/RPC y recuperación de jobs DEMO.

**Resultado de staging y migración remota:** PENDIENTE DE VALIDACIÓN. No aplicar a producción.
