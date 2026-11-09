# FLOPPI Core 1.5 — Diseño de persistencia

## `client_devices`

La migration 019 define `id`, `owner_id -> auth.users(id)`, `node_id`, nombre, plataforma, versión, capacidades, métricas JSON, `status`, `last_seen`, `last_connected_at`, `last_heartbeat_at`, revocación y timestamps. Índices cubren propietario/fecha y dispositivos online recientes. RLS está habilitada; anon/authenticated no tienen grants ni policy. El backend service-role filtra owner explícitamente en todas las operaciones. Supabase staging confirmado por consulta de solo lectura aún no tiene esta tabla.

## `backtest_runs`

019 agrega `assigned_device_id` con FK a `client_devices`, mantiene lease existente y agrega `paused` a la restricción de status. Cada actualización RPC condiciona propietario, estado, lease y dispositivo. Revoke/cancel/pause no interrumpen ejecuciones activas; solo aceptan pending sin lease.

## `client_events` (outbox)

Registra `event_id`, `owner_id`, tipo, payload controlado, fecha de creación y estado/intentos de publicación. RLS activa, sin grants para anon/authenticated y sin policy directa. El API filtra por owner y ofrece cursor de reconexión; el payload no debe incluir secretos ni resultados completos innecesarios. Retención sigue `EVENT_LOG_RETENTION_DAYS` (por defecto 30; acotada 1–3650) y corre con el worker de retención existente. Modo local limita memoria a 10.000 eventos y reporta `memory-demo`.

## Fallo de escritura

Si Supabase está configurado y la tabla no existe o falla, endpoint de lectura devuelve 503 y los registros de dispositivos no hacen fallback a memoria. Broadcast solo se intenta después de insertar en el outbox. Si el Broadcast falla, el registro queda pendiente; cliente debe reconciliar por REST. No afirmar persistencia en staging antes de probar la tabla remotamente.


La tarea de recovery existente marca desconectados los dispositivos Supabase cuyo lease/heartbeat venció; el RPC acota el timeout a 30–300 s y limpia la propiedad de instancia. El estado offline se obtiene también durante el modo DEMO en memoria.
