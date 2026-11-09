# FLOPPI — Contratos API compartidos

**Estado:** contratos propuestos para evolución; las rutas etiquetadas “existente” están presentes en el backend local. Las rutas propuestas no se presentan como implementadas.

## Convenciones comunes

- Base: `/api/v1`.
- JSON UTF-8; timestamps ISO-8601 UTC.
- `Authorization: Bearer <Supabase access token>` para usuario; credenciales worker separadas y limitadas para heartbeat/ejecución.
- `X-Request-ID` se acepta o genera en servidor y se devuelve para correlación.
- Errores consistentes: `{"error":{"code":"...","message":"...","request_id":"..."}}`.
- Paginación propuesta: `limit` acotado (default 50, máximo 200), `cursor` opaco; respuesta incluye `items`, `next_cursor` y `has_more`.
- El servidor valida dueño, rol, permisos del recurso y estado permitido. No usar permisos enviados por el cliente como autoridad.
- Números de mercado/backtest deben indicar fuente y modalidad DEMO/histórica/simulada. Nunca representan orden real.

## Rutas existentes observadas

| Grupo | Rutas observadas | Estado |
|---|---|---|
| Sistema y nodos | `/health`, `/auth/config`, `/nodes/heartbeat`, `/nodes`, `/nodes/summary`, preferencias de notificación | Presente; permisos difieren por ruta. |
| Datos | `/markets`, `/assets`, `/data/collect`, `/candles`, `/providers/status`, `/data/quality` | Presente; proveedor DEMO/sintético. |
| Análisis | `/analysis/indicators`, `/analysis/technical`, `/analysis/history`, `/analysis/hybrid`, `/analysis/multi-timeframe`, `/analysis/signals/history` | Presente. |
| Backtesting | `/strategies`, `/backtesting/run`, `/backtesting/walk-forward`, `/backtesting/queue/summary`, `/backtesting/runs`, `/backtesting/compare`, endpoints de worker | Presente. |
| Monitoreo | `/monitoring/performance`, `/monitoring/health`, `/monitoring/statistics` y rutas de historial | Presente. |
| Diagnóstico | `/diagnostics/summary`, `/diagnostics/incidents`, resolución y exportación | Presente. |
| Eventos | `/events/worker`, `/events`, `/events/export` | Presente. |
| Scheduler | `/scheduler/tasks`, `/scheduler/runs`, pause/resume/cancel | Presente. |

## Contratos propuestos

Estas rutas son una propuesta de interfaz, no evidencia de código existente. Antes de implementarlas hay que contrastar esquema y tabla `nodes`/jobs para evitar duplicar almacenamiento.

### Registro y administración de dispositivos

`POST /api/v1/devices` — requiere usuario autenticado. Crea un cliente para el usuario actual; no recibe un `owner_id` confiable del cuerpo.

Request:

```json
{
  "display_name": "Equipo de análisis",
  "platform": "windows",
  "client_version": "1.0.0",
  "capabilities": ["backtest", "heartbeat"]
}
```

Response `201`:

```json
{
  "device": {
    "device_id": "uuid",
    "status": "registered",
    "platform": "windows",
    "capabilities": ["backtest", "heartbeat"],
    "created_at": "2026-11-04T12:00:00Z"
  }
}
```

`GET /api/v1/devices` enumera solo los dispositivos accesibles al usuario.  
`POST /api/v1/devices/{device_id}/revoke` revoca el dispositivo actual del dueño/administrador autorizado; respuesta idempotente. Los secretos de registro se entregan una sola vez por un flujo seguro, nunca se almacenan en claro ni se devuelven en GET.

### Heartbeat

`POST /api/v1/devices/{device_id}/heartbeat` — autenticación de dispositivo acotada; `device_id` debe estar vinculado a la credencial y al usuario autorizados.

Request:

```json
{
  "observed_at": "2026-11-04T12:00:00Z",
  "status": "idle",
  "resources": {"cpu_percent": 12.5, "memory_percent": 48.0},
  "capabilities": ["backtest"]
}
```

Valores fuera de rango, payloads excesivos, timestamps futuros y capacidades no permitidas se rechazan o normalizan según regla documentada. Servidor deriva frescura/desconexión.

### Tareas

`POST /api/v1/tasks` crea una tarea DEMO autorizada y valida parámetros contra tipo/capacidad. `GET /api/v1/tasks` lista tareas del dueño con cursor. `GET /api/v1/tasks/{task_id}` consulta una tarea propia/compartida explícitamente. `POST /api/v1/tasks/{task_id}/cancel` es idempotente y valida transición.

Forma común propuesta:

```json
{
  "task_id": "uuid",
  "task_type": "historical_backtest",
  "state": "QUEUED",
  "owner_id": "uuid",
  "assigned_device_id": null,
  "progress": {"completed": 0, "total": 0},
  "created_at": "2026-11-04T12:00:00Z",
  "updated_at": "2026-11-04T12:00:00Z"
}
```

El cliente no establece libremente estado, propietario, lease ni dispositivo destino. Reasignación manual requiere permiso y comprobación del estado actual. Estados propuestos se definen en `MULTIPLATFORM_ARCHITECTURE.md` y deben adaptarse al modelo real existente antes de exponerlos.

### Eventos y tiempo real

El REST existente `/events` conserva búsqueda/paginación/export. WebSocket **no existe actualmente**. Si se implementa, ruta propuesta `/api/v1/ws` requiere bearer válido, suscripción por recurso autorizado, mensajes versionados y límites. Los mensajes son notificaciones, no autoridad para cambiar estado; cliente consulta REST al reconectar.

## Códigos de estado propuestos

- `400`: formato/filtro inválido.
- `401`: token ausente, inválido, vencido o revocado.
- `403`: rol/permisos insuficientes.
- `404`: recurso no visible o inexistente (evitar revelar pertenencia ajena).
- `409`: transición de tarea incompatible/idempotency conflict.
- `422`: parámetros semánticamente inválidos.
- `429`: cuota/rate limit.
- `503`: dependencia temporalmente no disponible, sin fallback permisivo.

## Versionado y compatibilidad

Conservar las rutas existentes y sus esquemas durante la transición. Antes de publicar nuevos contratos, generar OpenAPI real, pruebas de compatibilidad y ejemplos basados en respuestas actuales; no reutilizar estos ejemplos propuestos como datos de producción.

## FLOPPI Core 1.4 — rutas de comunicación y coordinación

Estas rutas están presentes en el backend local y requieren autenticación Supabase de usuario, salvo el handshake WS descrito. La persistencia en Supabase depende de migration 019, escrita pero no aplicada. En modo local, dispositivos son memoria DEMO no persistente.

| Ruta | Propósito | Seguridad/estado |
|---|---|---|
| `POST /api/v1/devices` | Registrar dispositivo | Auth; owner desde token; 201 |
| `GET /api/v1/devices` | Listar dispositivos | Solo dueño |
| `POST /api/v1/devices/{id}/heartbeat` | Heartbeat REST | Solo dueño; métricas limitadas |
| `POST /api/v1/devices/{id}/revoke` | Revocar | Solo dueño |
| `GET /api/v1/ws` | WebSocket, primer frame `auth` | Token validado; device ownership; origin allowlist |
| `POST /api/v1/backtesting/runs/{id}/assign` | Asignar run pendiente | Solo owner, dispositivo del owner |
| `POST /api/v1/backtesting/runs/{id}/cancel` | Cancelar run pendiente | Solo owner; no cancela lease activo |
| `POST /api/v1/devices/{device_id}/backtesting/runs/{run_id}/claim` | Reclamar tarea asignada | Owner/device y estado comprobados; lease existente |
| `POST /api/v1/devices/{device_id}/backtesting/runs/{run_id}/heartbeat` | Renovar lease | Requiere `X-Job-Lease-Token`; misma asignación |
| `POST /api/v1/devices/{device_id}/backtesting/runs/{run_id}/complete` | Completar simulación | Requiere lease y validador existente |
| `POST /api/v1/devices/{device_id}/backtesting/runs/{run_id}/fail` | Reportar fallo | Requiere lease; reintento existente |

El contrato anterior tenía algunos nombres de campo ilustrativos distintos; para registro implementado usar `device_name`, y para heartbeat REST `cpu_percent`, `memory_percent`, `active_tasks`. Eventos WebSocket son best-effort, no almacenamiento durable. Los contratos preexistentes no se presentan como verificados contra staging.

## FLOPPI Core 1.5 — dispositivos, eventos y coordinación

| Ruta | Función | Permisos/estado |
|---|---|---|
| `POST /api/v1/devices` | Registrar cliente genérico | usuario Auth; owner no viene del body |
| `GET /api/v1/devices` | Listar dispositivos | solo propietario |
| `POST /api/v1/devices/{id}/heartbeat` | Actualizar recursos/liveness | solo propietario; persistencia según storage |
| `POST /api/v1/devices/{id}/revoke` | Revocar y cerrar conexiones | solo propietario |
| `GET /api/v1/client-events?cursor=<opaque>&limit=100` | Reconciliar eventos tras reconexión | solo propietario; DB o memory-demo |
| `GET /api/v1/ws` | WS; primer frame `auth` | identity + device ownership; Origin allowlisted |
| `POST /api/v1/backtesting/runs/{id}/assign` | Asignación/reasignación manual | propietario; pending, sin lease; dispositivo online |
| `POST /api/v1/backtesting/runs/{id}/assign/automatic` | Elegir capacidad | backtest capability, online ≤90 s, CPU/RAM ≤85%, sin tarea activa |
| `POST /api/v1/backtesting/runs/{id}/pause` | Pausar | pending sin lease; status `paused` |
| `POST /api/v1/backtesting/runs/{id}/resume` | Reanudar | dueño, status paused; vuelve a pending |
| `POST /api/v1/backtesting/runs/{id}/cancel` | Cancelar | pending sin lease |
| `POST /api/v1/devices/{device}/backtesting/runs/{run}/claim` | Claim asignado | dueño/device verificados, una ejecución activa, lease existente |
| `POST /api/v1/devices/{device}/backtesting/runs/{run}/heartbeat` | Renovar lease | access token y `X-Job-Lease-Token` |
| `POST /api/v1/devices/{device}/backtesting/runs/{run}/complete` | Completar backtest | resultado DEMO validado + lease |
| `POST /api/v1/devices/{device}/backtesting/runs/{run}/fail` | Reportar fallo | lease vigente; política actual reintenta |

Mensajes WebSocket admitidos: `auth`, `auth.refresh`, `ping`, `heartbeat`. Eventos privados: `device.connected`, `device.disconnected`, `device.heartbeat`, `device.revoked`, `task.assigned`, `task.started`, `task.paused`, `task.resumed`, `task.cancelled`, `task.completed`, `task.failed`. Frame inválido recibe cierre; timeout/limit usa códigos 4408/4429. El broadcast es best-effort; consultar REST para recuperar estado.

Persistencia Supabase de estas rutas depende de migration 019 aún no aplicada; Supabase configurado con tabla ausente falla cerrado (503).
