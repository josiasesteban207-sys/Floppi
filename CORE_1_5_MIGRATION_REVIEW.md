# FLOPPI Core 1.5 — Revisión de migraciones

## Evidencia de staging (consulta read-only, 2026-11-04)

`.env.staging` fue validado por su marcador `staging` y el host Supabase. La conexión se ejecutó en transacción PostgreSQL `READ ONLY`; no hubo DDL/DML.

El historial `supabase_migrations.schema_migrations` contiene `20261104205150 / 018_staging_security_performance_hardening`. La migration 018 real tiene un bloque SQL que revoca grants generales a `anon`/`authenticated`, permite catálogo de mercados de lectura, concede acceso propio a preferencias/estrategias/backtests, quita acceso cliente a datos operativos, ajusta default privileges y recrea políticas con `(select auth.uid())`. El registro tiene 1 statement y no incluye rollback.

Catálogo remoto confirmó que no existen `client_devices`, `client_events` ni `backtest_runs.assigned_device_id`. `backtest_runs`, `system_events` y `worker_credentials` tienen RLS activada (no FORCE RLS). `anon` carece de permisos efectivos SELECT/INSERT/UPDATE en backtest runs y system events. `authenticated` tiene SELECT/INSERT sobre backtest runs con políticas de propietario; system_events está restringido a server-role. `service_role` tiene los permisos de servidor esperados. Las políticas de backtest runs limitan `user_id` a `auth.uid()`.

La tabla `backtest_runs` contiene FK a auth.users, assets, strategies y scheduled_tasks; status CHECK con pending/running/completed/failed/cancelled; lease y retry columns; índices de prioridad, expiración, retry, worker, usuario y scheduler. Las funciones legacy de lease son SECURITY DEFINER, con búsqueda fija de esquema y EXECUTE concedido a service_role (además del dueño postgres). La migration local 019 solo reemplaza claim global para excluir asignados y recovery para soltar assignments offline.

La historia real es timestamped y algunos timestamps de 006/007 no siguen el orden numérico de los nombres. También existen migraciones timestamped para credenciales que no coinciden exactamente con el nombre local 017. No inferir equivalencia sin revisar el SQL aplicado completo. Los nombres locales 008/009 no aparecen en el historial.

## Nueva migración local

La propuesta está en `database/migrations/019_core_1_5_devices_events_coordination.sql`; el SQL previo etiquetado localmente como 018 fue renumerado. No se sobrescribió migration 018 de staging. 019 contiene `client_devices`, `client_events`, `assigned_device_id`, status `paused`, RPC owner-scoped, claim individual por dispositivo, exclusión del worker global, recovery que libera dispositivos offline/revocados, RLS y grants server-only. Las nuevas funciones usan SECURITY INVOKER, `search_path` fijo y EXECUTE solo para service_role; la función legacy de claim conserva su seguridad existente y ACL limitada. Se añade retención de outbox.

El rollback es manual y condicionado: apagar listeners, exportar datos necesarios y confirmar referencias antes de eliminar tabla/columna. No se borran datos automáticamente.

## Compatibilidad y límites

El repositorio usa `database/migrations/001..019`; CLI/config Supabase no está instalada (`supabase` ni `npx`). Se siguió el esquema local numerado; la migration está preparada, no aplicada. No se validó SQL en un PostgreSQL temporal ni se ejecutaron RLS/RPC de 019. Antes de staging hay que cotejar el SQL completo real, hacer respaldo y obtener autorización explícita.
