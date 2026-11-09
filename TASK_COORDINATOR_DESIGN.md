# FLOPPI Core 1.4 — Task Coordinator Design

## Reutilización

El coordinador reutiliza `backtest_runs`, `claim_backtest_run`, `renew_backtest_run_lease`, `complete_backtest_run`, `fail_backtest_run` y `recover_expired_backtest_runs`. No introduce scheduler, cola ni mecanismo de lease alternativo. El alcance de la nueva asignación es exclusivamente backtesting DEMO.

## Flujo

1. Usuario autenticado registra dispositivo (dueño derivado del token).
2. Usuario asigna una ejecución propia `pending` y sin lease a su dispositivo.
3. Dispositivo autenticado reclama por CAS: la ejecución pasa a `running`, se fija `node_id`, token de lease aleatorio y expiración de cinco minutos, incrementando `attempt_count`.
4. Cliente renueva lease con el token. Completa/falla mediante las operaciones existentes, que validan estado, worker, token y expiración; los resultados siguen sujetos a validación de backtesting.
5. Eventos `task.assigned`, `task.started`, `task.completed`, `task.failed` y `task.cancelled` notifican al usuario; REST reconcilia el estado.

## Concurrencia y aislamiento

La BD usa RPC transaccional `UPDATE … WHERE` y columna existente `lease_token`, con permisos EXECUTE limitados a `service_role`. El endpoint siempre toma user ID desde Supabase Auth, valida ownership de dispositivo y run, y no acepta `owner_id` del cliente. El claim local DEMO usa el lock actual del repositorio. La reclamación del worker global excluye las filas con `assigned_device_id`, tanto en modo memoria como en la definición propuesta para SQL.

Asignar/cancelar un job activo o con lease vigente falla con 409; no hay cancelación forzada del proceso. Un reintento solo queda elegible cuando el mecanismo actual de recuperación vuelve el run a `pending` y llega `retry_after`. Un dispositivo revocado no puede reclamar ni renovar mediante rutas autenticadas.

## Migración y límites

`database/migrations/019_core_1_5_devices_events_coordination.sql` prepara client_devices/outbox, RLS, grants server-only, assigned_device_id, pausa y RPCs protegidas. Staging fue verificado en lectura: migration 018 real es de hardening y allí faltan dispositivos/outbox/assigned_device_id. Migration 019 no se aplicó; RLS/RPC nuevas permanecen sin validación remota.

El fan-out de cada proceso es local, pero Supabase Realtime privado distribuye el evento entre instancias cuando 019 esté aplicada. La identidad se valida al conectar y en cada ruta REST; la sesión WS requiere refresh dentro de una hora.
