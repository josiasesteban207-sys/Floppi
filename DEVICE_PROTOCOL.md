# FLOPPI Core 1.4 — Device Protocol

## Registro REST (implementado)

`POST /api/v1/devices` requiere `Authorization: Bearer <Supabase access token>`.

```json
{"device_name":"Desktop","platform":"windows","client_version":"1.4.0","capabilities":["backtest"]}
```

Plataformas permitidas: `web`, `windows`, `macos`, `linux`, `android`, `ios`. El dueño se deriva del token. La respuesta devuelve `device_id`, `node_id`, nombre, plataforma, versión, capacidades, estado y fechas; no se emiten secretos de dispositivo.

`GET /api/v1/devices` lista únicamente los dispositivos activos del usuario. `POST /api/v1/devices/{device_id}/heartbeat` acepta métricas acotadas; `POST /api/v1/devices/{device_id}/revoke` revoca el dispositivo. El acceso cruzado devuelve 404.

## WebSocket (implementado)

URL: `wss://<host>/api/v1/ws`. Primer frame obligatorio:

```json
{"type":"auth","access_token":"<access token>","device_id":"<uuid registrado>"}
```

Mensajes cliente permitidos después de autenticar:

```json
{"type":"ping"}
{"type":"heartbeat","resources":{"cpu_percent":12.5,"memory_percent":44}}
```

Las métricas deben estar entre 0 y 100. Mensajes desconocidos cierran la conexión. Respuestas servidor: `authenticated`, `pong`, `heartbeat.ack` y eventos con `event_id`, `type`, `occurred_at`, `data`.

## Seguridad y compatibilidad

Access tokens: solo primer frame TLS; nunca URL, almacenamiento del dispositivo en BD, logs ni eventos. El cliente debe usar secure storage del sistema operativo donde exista. Renovación de sesión delegada a Supabase Auth. Revocar el dispositivo invalida futuras conexiones/heartbeats y claims. El control actual es por identidad de usuario más registro/revocación de dispositivo; no es una credencial criptográfica específica por dispositivo. El pinning/rotación de secretos por dispositivo queda pendiente.

## Tareas DEMO

Rutas autenticadas implementadas:

- `POST /api/v1/backtesting/runs/{run_id}/assign` `{ "device_id":"uuid" }`.
- `POST /api/v1/backtesting/runs/{run_id}/cancel`.
- `POST /api/v1/devices/{device_id}/backtesting/runs/{run_id}/claim`.
- `POST /api/v1/devices/{device_id}/backtesting/runs/{run_id}/heartbeat` con `X-Job-Lease-Token`.
- `POST /api/v1/devices/{device_id}/backtesting/runs/{run_id}/complete` con `X-Job-Lease-Token` y resultado DEMO validado.
- `POST /api/v1/devices/{device_id}/backtesting/runs/{run_id}/fail` con `X-Job-Lease-Token`.

Solo se cancelan/asignan trabajos pendientes sin lease. Solo el dispositivo del propietario puede reclamar el trabajo asignado; operaciones activas exigen el lease existente. El endpoint claim devuelve la ejecución, estrategia, velas verificadas y market code que necesita el motor; los demás detalles se consultan por REST. No se admiten órdenes financieras.

