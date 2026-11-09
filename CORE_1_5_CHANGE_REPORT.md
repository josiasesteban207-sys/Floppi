# FLOPPI Core 1.5 — Informe de cambios

## Resultado

Se avanzó el candidato Core 1.5 sin desplegar a producción ni aplicar migraciones remotas. Se auditó Supabase staging en lectura, se corrigió la numeración 018/019, se implementó persistencia/outbox, puente Realtime, control de dispositivos y coordinador híbrido en el backend local.

## Archivos nuevos

- `CORE_1_5_BASELINE.md`
- `CORE_1_5_ARCHITECTURE_REVIEW.md`
- `CORE_1_5_IMPLEMENTATION_PLAN.md`
- `CORE_1_5_PERSISTENCE_DESIGN.md`
- `CORE_1_5_DISTRIBUTED_EVENTS.md`
- `CORE_1_5_SECURITY_REVIEW.md`
- `CORE_1_5_MIGRATION_REVIEW.md`
- `CORE_1_5_TEST_EVIDENCE.md`
- `CORE_1_5_CHANGE_REPORT.md`
- `backend/app/client_events.py`
- `backend/app/distributed_events.py`
- `database/migrations/019_core_1_5_devices_events_coordination.sql`

## Archivos modificados

- `backend/app/devices.py`, `backend/app/realtime.py`, `backend/app/api/device_routes.py`
- `backend/app/api/backtesting_routes.py`, `backend/app/backtesting/repository.py`
- `backend/app/main.py`, `backend/app/event_log.py`
- `backend/tests/test_core14_devices_realtime.py`, `API_CONTRACTS.md`
- Renombrado archivo local previo `018_client_devices_and_assigned_tasks.sql` a 019 para no colisionar con staging 018.

## Cambios implementados

- Registro persistente de dispositivos y marcas separadas de conexión/heartbeat; memoria DEMO limitada a 10.000 eventos.
- Auth WebSocket con refresh, sesión de una hora, heartbeat máximo cada cinco segundos, timeout a los 90 segundos, un socket por dispositivo (lease distribuido de 90 s en Supabase), heartbeat máximo cada 5 s y límites de frames/conexiones.
- Broadcast privado entre procesos vía Supabase Realtime, outbox duradero `client_events`, replay acotado y endpoint owner-scoped para catch-up.
- Asignación manual/automática por capacidad reciente, pausa/reanudación de pending, cancelación segura, un lease activo por dispositivo y liberación de assignment al recuperar un lease de dispositivo offline, y cierre de estado stale por timeout de heartbeat.
- Estados coherentes: pending, running, completed, failed, cancelled y paused. No se habilitó ejecución financiera real.

## Pruebas/evidencia

`pytest -q`: **176 passed in 5.06s**. Detalle y límites en `CORE_1_5_TEST_EVIDENCE.md`. Staging se inspeccionó con transacción READ ONLY; migration 018 real es de hardening y no crea tablas de dispositivos. No se aplicó DDL remoto.

## Recursos estimados, no medidos

Cada proceso API mantiene una suscripción Realtime. El outbox de reintento local limita 2.048 eventos; con payload de datos limitado a 6 KiB, el contenido bruto máximo ronda 12 MiB por proceso más overhead de Python/colas. Cada socket permite 64 eventos de salida, hasta aproximadamente 384 KiB de payload por conexión. El límite es por cuenta/dispositivo; no hay benchmark de RSS ni throughput en servidor 8 GB, por lo que son cotas de payload, no consumo de memoria medido.

## Problemas y riesgos

- La migration 019 requiere revisión y aplicación aprobada; staging todavía no ofrece persistencia de dispositivo/outbox.
- El bridge usa una suscripción Realtime por proceso; consumo facturable/limits según proyecto deben revisarse.
- Falta prueba real de dos instancias, RLS/RPC después de 019, carga de 8GB, session Auth remota, rate limiting HTTP distribuido y análisis formal de dependencias.
- Heartbeat REST requiere protección en gateway para servicio público.
- No se cambió `VERSION` ni `FastAPI.version`: Core 1.5 no es release validada. Interfaces completas siguen fuera del alcance.

## Próximo objetivo

Tras autorización explícita, aplicar 019 solo a FLOPPI-STAGING, verificar grants/RLS/RPC y prueba de dos instancias; luego completar benchmark y hallazgos pendientes de Core 1.6. Producción queda fuera de esta entrega.

## Estado de criterios de aceptación

| Criterio | Estado | Evidencia/pendiente |
|---|---|---|
| Registrar dispositivos con persistencia | PARTIAL | Repositorio Supabase implementado; staging no tiene tabla porque 019 no se aplicó. |
| Owner isolation | VERIFIED local | Tests HTTP/WebSocket multiusuario y cursor de eventos. |
| Varios clientes simultáneos | VERIFIED local | WebSocket y hubs simulados; no es prueba de despliegue distribuido real. |
| Dos instancias comparten eventos | PARTIAL | Bridge Supabase Realtime privado + test de hubs simulados; requiere prueba con dos procesos en staging. |
| Revocación global | PARTIAL | RPC/outbox/close remoto preparados en 019; no validado en servidor real. |
| Persistencia/outbox y catch-up | PARTIAL | Código y paginación cursor; DB remota no tiene tabla aún. |
| Auth, refresh, heartbeat y duplicado de conexión | PARTIAL | Controles implementados; autenticación/RPC y carrera cross-instance requieren Supabase staging. |
| Assignment manual, automático, pause, resume y cancel | VERIFIED local | Pruebas DEMO en memoria y API. |
| Lease, recuperación offline y límites de intentos | PARTIAL | Recuperación local probada; SQL real posterior a 019 pendiente. |
| RLS, GRANT, EXECUTE de nuevas tablas/RPC | BLOCKED | Migración 019 no aplicada ni autorizada. |
| Soportar 8 GB bajo carga | BLOCKED | Estimación de payload documentada; no se midió RSS/throughput. |
| Mantener modo educativo y no tocar producción | VERIFIED | Solo SELECTs staging; sin brokers/órdenes. |
| Web/Desktop/Mobile completos | MISSING | Explícitamente fuera de este núcleo. |

La selección del transporte sigue [Supabase Broadcast](https://supabase.com/docs/guides/realtime/broadcast) (documentado por Supabase como opción recomendada frente a Postgres Changes para escala/seguridad); limits y costes requieren revisión del plan. `LISTEN/NOTIFY` se descartó como transporte principal porque [PostgreSQL lo define como IPC ligero](https://www.postgresql.org/docs/current/sql-notify.html), pero es efímero y necesita outbox/reconciliación para reconexión.
