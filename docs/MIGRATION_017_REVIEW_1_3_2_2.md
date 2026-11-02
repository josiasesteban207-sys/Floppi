# FLOPPI 1.3.2.2 — Revisión de migration 017

**Estado:** typo corregido; staging inspeccionado en solo lectura; migration 017
ejecutada y verificada con autorización expresa únicamente en un contenedor
scratch offline. No se modificaron credenciales, staging original, producción
ni Supabase.

## Evidencia del archivo y esquema

El archivo `database/migrations/017_worker_credential_expiry.sql` contenía
`awter table`; se corrigió a `alter table`. No se aplicó al staging, Supabase
ni producción; sí se ejecutó dentro del scratch offline autorizado.

La inspección de la base PostgreSQL local staging confirmó que
`public.worker_credentials` **no existe**. Por tanto, en la base staging
actual:

- Filas existentes consultables: 0.
- Filas afectables que se pudieron medir: 0; esto no mide otros proyectos.
- Columnas, tipos, constraints, índices, triggers, RLS/grants efectivos: no
  existen para inspeccionar en esa base.
- Ejecutar 017 directamente contra esta base fallaría porque falta la relación;
  la herramienta no permite ese destino.

El contrato de esquema conocido procede de
`database/migrations/004_worker_credentials.sql`, no de una tabla real presente
en staging:

| Campo/objeto | Definición |
|---|---|
| `id` | `uuid`, PK, default `gen_random_uuid()` |
| `node_id` | `text NOT NULL`, check de longitud 2–64 |
| `token_hash` | `text NOT NULL UNIQUE`, check de 64 caracteres hexadecimales |
| `active` | `boolean NOT NULL DEFAULT true` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |
| `expires_at` | `timestamptz NULL` antes de 017 |
| `last_used_at`, `revoked_at` | `timestamptz NULL` |
| Constraint | `revoked_at IS NULL OR active = false` |
| Índices secundarios | `node_id`; `token_hash WHERE active = true` |
| RLS | habilitada, no forzada; la migración 004 revoca grants a `public`, `anon`, `authenticated`, y concede `SELECT/UPDATE/INSERT` a `service_role` |
| Triggers | ninguno definido por migration 004 |

El esquema y los triggers reales de un proyecto Supabase no se pueden inferir
de esta plantilla; requieren una consulta de catálogo al staging Supabase
autorizado. 017 no crea ni modifica políticas RLS, índices ni triggers.

## Efectos y compatibilidad

La actualización afecta **todas** las filas con `expires_at IS NULL`,
incluyendo credenciales ya inactivas:

- Fuerza `active = false`.
- Conserva `revoked_at` si ya tenía valor; si no, establece `now()`.
- Establece `expires_at = now()`.
- Después convierte la columna a `NOT NULL`.

Las credenciales con vencimiento existente no deberían cambiar. Cualquier
worker activo que use una credencial sin expiración dejará de autenticarse en
la siguiente petición; heartbeats/renovaciones/finalización podrían devolver
401 hasta rotar su token. Un trabajo ya arrendado podría requerir que venza su
lease antes de recuperación/reintento. Deben inventariarse workers y reemitirse
credenciales antes de una aplicación no desechable.

PostgreSQL 16 admite la transacción, `UPDATE ... WHERE`, `COALESCE`, `now()` y
`ALTER COLUMN ... SET NOT NULL`. El update bloquea las filas afectadas y el
`ALTER TABLE` requiere lock exclusivo de tabla; la validación de la restricción
puede recorrer la tabla. El bloque transaccional hace que un error antes del
`COMMIT` revierta los cambios de esta migración.

La RLS de 004 está activada pero no forzada; el rol de ejecución debe poder
actualizar la tabla y cambiar su esquema. El uso del SQL Editor / rol
administrativo de un proyecto y los grants efectivos no se validaron. 017 no
necesita `auth.uid()` ni funciones de aplicación, pero depende de que exista la
tabla `public.worker_credentials`.

## Prueba automatizada ejecutada

`tools/verify_worker_expiry_migration.py` permite una prueba PostgreSQL real
solo con `--authorize-scratch-migration-017`. Se ejecutó con esa autorización.
El proceso:

1. Verifica que el backup sea un `.dump` dentro de `backups/staging/` y que la
   instancia staging local esté aislada; toma un fingerprint de solo lectura
   de la tabla antes y después.
2. Crea un contenedor temporal con la imagen PostgreSQL 16 fijada por digest,
   `--network none`, sin puertos, mounts persistentes ni volumen; sus datos son
   temporales.
3. Restaura la copia de seguridad dentro de ese contenedor y crea roles
   Supabase de prueba. Conserva sin cambios el esquema de credenciales si el
   backup ya lo contiene; usa migration 004 solo si la tabla está ausente.
4. Comprueba el esquema restaurado contra migration 004, incluyendo índices,
   constraints, RLS, triggers y grants; captura los conteos provenientes del
   backup y agrega cuatro credenciales sintéticas de prueba.
5. Ejecuta 017 exclusivamente en ese scratch y valida revocación, conservación
   de `revoked_at` previo, preservación de credenciales ya expirables,
   eliminación de expiraciones nulas y rechazo de un INSERT con expiry NULL.
6. Destruye el contenedor scratch. No envía conexiones al staging original,
   Supabase ni producción; la migración no está incluida en Compose ni se
   ejecuta al arrancar.

Comando usado con autorización expresa:

```powershell
python tools\verify_worker_expiry_migration.py `
  --backup backups\staging\floppi-staging-20261102T163209Z.dump `
  --authorize-scratch-migration-017
```

El backup restaurado no contenía la tabla, por lo que el preflight midió **0**
filas preexistentes con `expires_at IS NULL` y **0** activas entre ellas. El
verificador creó el esquema base 004 solo en el scratch y agregó cuatro
credenciales sintéticas: tres sin expiración (una activa y dos inactivas) y
una activa con expiración. Migration 017 pasó las aserciones: revocó la
credencial activa legacy, preservó el `revoked_at` anterior de una inactiva,
convirtió todos los expiries nulos, conservó la credencial válida y rechazó un
nuevo `NULL`. El contenedor scratch se eliminó y el fingerprint de staging no
cambió.

Las 11 pruebas enfocadas de autenticación/migración pasaron. La suite también
comprueba que la herramienta no llama al verificador sin el flag de
autorización y que migration 004 no sobrescribe un esquema de credenciales ya
presente en el backup.

## Rollback y recuperación

Antes del `COMMIT`, cualquier fallo del bloque transaccional debe provocar
rollback; verificar que no quede una transacción abierta ni filas modificadas.
El scratch automatizado se elimina por completo al finalizar.

Después de un `COMMIT`, no se debe reactivar ninguna credencial ni restaurar
`expires_at = NULL`. Hacer `ALTER COLUMN expires_at DROP NOT NULL` reabriría el
estado inseguro y no recuperaría el valor original de `active` o `revoked_at`.
La migración no conserva esos valores anteriores en una tabla de auditoría.
Una restauración de backup debe hacerse en otra scratch para investigación;
no restaurar sobre la base de origen ni usarla para reactivar tokens. Recuperar
operativamente mediante credenciales nuevas, actualizar workers y mantener
revocados los tokens anteriores. El rollback de aplicación no debe eliminar la
validación de expiración.

## Estado de autorización y riesgos

- La base staging local inspeccionada no contiene `worker_credentials`; no
  puede dar un conteo de usuarios/filas reales ni validar RLS de Supabase.
- La copia de backup disponible es la base PostgreSQL local, no un backup
  Supabase ni de producción.
- La prueba autorizada en scratch pasó con cero filas legacy en el backup; las
  únicas filas afectadas durante la integración fueron fixtures sintéticas.
- No se modificaron credenciales ni se alteró la base original.
- La aplicación a Supabase staging y el conteo real de credenciales legacy
  quedan fuera de esta autorización y deben permanecer pendientes.
