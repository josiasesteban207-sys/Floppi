# FLOPPI Core 1.5 — Baseline de Core 1.4

## Alcance y evidencia previa

Core 1.4 incorporó registro DEMO en memoria/Supabase, WebSocket FastAPI con token Supabase en primer frame, heartbeat y leases compartidos para backtests. El informe de Core 1.4 registra 168 pruebas pasadas. En Core 1.5 volví a ejecutar la suite completa; el resultado vigente se registra en `CORE_1_5_TEST_EVIDENCE.md`.

## Inventario auditado

- API: FastAPI bajo `/api/v1`; autenticación de usuarios con `auth.get_user`; credenciales de workers separadas.
- Persistencia: cliente Supabase service-role del servidor; PostgreSQL/Supabase. Cuando Supabase no está configurado, los repositorios DEMO usan memoria.
- Tareas: tabla existente `backtest_runs`, `claim_backtest_run`, leases (`lease_token`, `lease_expires_at`), recuperación `recover_expired_backtest_runs` y scheduler existente. No se añadió una segunda cola.
- Observabilidad: `system_events` es un log operativo server-managed, sin propietario de usuario; por eso no se reutiliza como canal privado.
- Dispositivos: el Core 1.4 dependía de `client_devices` y `assigned_device_id` propuestos en un archivo local `018_client_devices_and_assigned_tasks.sql`; esa numeración colisionaba con staging.
- Configuración: `.env.staging` contiene la conexión a Supabase staging. No se imprimieron credenciales.

## Verificación remota de solo lectura

El 2026-11-04 se validó el marcador de entorno `staging` y se abrió una transacción PostgreSQL `READ ONLY` contra el host configurado. Staging registró `018_staging_security_performance_hardening` como aplicada. La consulta confirmó que allí todavía no existen `client_devices`, `client_events` ni `backtest_runs.assigned_device_id`; tampoco existen políticas para esas tablas inexistentes. La historia incluye migraciones timestamped hasta 018, con nombres locales de 001–016 y hardening de credenciales previo. No se ejecutó DDL/DML ni se consultó producción.

La migration CLI de Supabase no está instalada; el intento `npx supabase --version` no pudo ejecutarse porque `npx` no existe. La migración se conservó en el esquema secuencial usado por `database/migrations`, como propuesta `019`; no se validó su aplicación en PostgreSQL.

## Estado al iniciar Core 1.5

| Área | Estado base |
|---|---|
| Auth de conexión | Implementada; Core 1.4 validaba identidad en el handshake |
| Persistencia de dispositivos | Parcial; configuración Supabase fallaba cerrado si faltaba la tabla; staging no tenía la tabla |
| Heartbeats | Implementados; faltaban marcas separadas de conexión y heartbeat |
| Eventos entre instancias | Faltaban; fan-out era en memoria por proceso |
| Tareas asignadas | Parcial; leases existentes pero migración numerada en conflicto; el worker global podía tomar tareas asignadas hasta aplicar la propuesta |
| Recuperación | Existente; lease expirado reiniciaba tarea, pero no liberaba asignación offline |
| Pausa/reasignación | Faltaban |
| Interfaces multiplataforma completas | Fuera de alcance |
