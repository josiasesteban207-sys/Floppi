# FLOPPI Core 1.4 — WebSocket Architecture

## Estado

Implementado en el backend local. Supabase staging fue inspeccionado en transacción READ ONLY; migration 019 está preparada, pero **no aplicada**. El WebSocket ofrece notificaciones best-effort; REST y PostgreSQL siguen siendo la fuente de verdad.

## Conexión y autenticación

- `GET /api/v1/ws` acepta WebSocket. El cliente envía como primer frame JSON `{ "type":"auth", "access_token":"…", "device_id":"uuid" }`.
- El token se valida con el mismo Supabase Auth `get_user` que HTTP; nunca se coloca en query string ni se registra.
- Se comprueba que el dispositivo no esté revocado y pertenezca al usuario autenticado.
- Si llega `Origin`, debe coincidir exactamente con `CORS_ORIGINS`. Clientes nativos pueden omitirlo y deben autenticar con token.
- Límites: 5 s para autenticación, 8 KiB por frame, 8 conexiones por cuenta y 1 por dispositivo. En Supabase un RPC toma un lease de conexión por 90 s, renovado por heartbeat, lo que previene doble conexión entre instancias.

## Ciclo de vida y eventos

Después de `authenticated`, el cliente puede enviar `ping` y `heartbeat`. El servidor actualiza `last_seen` y estado y publica `device.connected`, `device.disconnected` y `device.heartbeat`. Eventos de tarea son fan-out solo a conexiones del dueño. Cola saliente acotada (64); si se llena se cierra con 1013 y el cliente debe reconectar y reconciliar por REST.

Los IDs de evento son UUID; el timestamp es UTC ISO-8601. El canal no promete entrega durable ni orden tras reconexión. No contiene tokens, credenciales ni payloads completos de backtest.

## Recuperación

Reconectar con backoff exponencial con jitter, renovar el token mediante el flujo Auth de Supabase antes de reconectar si expiró, enviar autenticación de nuevo y consultar por REST dispositivos/tareas antes de actuar. Repetir `claim` no ejecuta dos veces: el claim condicionado al estado `pending` y el lease actual determinan el ganador.

## Límites y operación

El registro usa memoria DEMO si no hay cliente Supabase y no persiste reinicios. Con Supabase configurado, la ausencia de `client_devices` responde 503 (fail closed). Aplicar migration 019 requiere autorización. El modo local es por proceso; en modo Supabase, Supabase Realtime propaga eventos entre instancias y un lease de conexión de DB limita un dispositivo a una instancia. La propagación remota aún no fue probada.