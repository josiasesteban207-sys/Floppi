# FLOPPI Core 1.4 — Informe de cambios

## Resultado

Se implementó un núcleo inicial de comunicación para clientes genéricos: registro y revocación de dispositivos, autenticación WebSocket, heartbeat/liveness, eventos privados por usuario y coordinación de backtests DEMO asignados reutilizando leases existentes. El claim del cliente asignado utiliza la misma hidratación/validación histórica de datos del worker existente.

## Archivos

- Nuevos: `backend/app/devices.py`, `backend/app/realtime.py`, `backend/app/api/device_routes.py`, `backend/tests/test_core14_devices_realtime.py`, `database/migrations/018_client_devices_and_assigned_tasks.sql` (propuesta no aplicada), `WEBSOCKET_ARCHITECTURE.md`, `DEVICE_PROTOCOL.md`, `TASK_COORDINATOR_DESIGN.md`.
- Modificados: `backend/app/main.py`, `backend/app/api/backtesting_routes.py`, `backend/app/backtesting/repository.py`, `API_CONTRACTS.md`.

## Verificación ejecutada

- Suite anterior tras integración inicial: `pytest -q` — 162 passed.
- Suite completa final: `pytest -q` — **168 passed in 13.39s**.
- Seis pruebas nuevas cubren aislamiento entre usuarios, handshake/heartbeat/eventos, rechazo de auth cruzada, dos conexiones simultáneas sin cruce de eventos, autorización/estado de leases y guardas de migration/RLS.
- No se conectó a Supabase staging, no se ejecutaron consultas reales a PostgreSQL y no se aplicó migration 018.

## Seguridad y limitaciones

El token se envía únicamente en el primer frame WS; no se registra ni devuelve. REST y tareas verifican propietario; claims y acciones usan el lease actual. La revocación cierra conexiones existentes en la misma instancia. Migración/RLS tienen solo revisión estática. El modo local es memoria DEMO. WebSocket fan-out es por proceso y best-effort; multi-instancia requiere pub/sub. Una revocación en otra instancia no cierra el socket remoto todavía. Las interfaces completas Web/Desktop/Mobile no forman parte de este cambio. No se ejecutan operaciones financieras.

## Próximo paso

Revisar migration 018 y ejecutarla exclusivamente en staging con autorización expresa; después correr pruebas reales de grants/RLS/RPC y de concurrencia multi-instancia antes de promover el núcleo. No declarar release final hasta esa validación.
