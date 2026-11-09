# FLOPPI Core 1.5 — Evidencia de pruebas

## Pruebas locales

| Comando | Resultado |
|---|---|
| `pytest -q` | **176 passed in 5.06s** (Python 3.10, Windows) |
| `python -m compileall -q backend/app` | Ejecutado al cierre: exit 0, sin errores de sintaxis |
| `git diff --check` | Ejecutado al cierre; sin errores de whitespace (Git puede advertir normalización LF/CRLF en archivos existentes) |

La suite incluye los 168 casos que pasaban en Core 1.4 y ocho casos nuevos Core 1.5 sobre escritura remota fail-closed, pause/resume/cancel, event history owner-scoped, fan-out simulado entre dos hubs y liberación de asignación offline tras lease vencido. Las pruebas de core4 existentes cubren auth WebSocket, heartbeats, aislamiento entre usuarios, y validación estática de migraciones.

Hubo una falla inicial en la prueba simulada de dos hubs: el sender no tenía loop activo. Se corrigió el fixture para conectar un socket simulado al sender; la prueba aislada pasó y la suite completa final pasó. No se ocultó la ejecución fallida.

## Staging Supabase (solo lectura)

El 2026-11-04 se validó `.env.staging` por marcador de entorno y host Supabase. La sesión PostgreSQL reportó `transaction_read_only=on`; se ejecutaron solo SELECTs a historia de migraciones y catálogos. Resultado relevante: `018_staging_security_performance_hardening` existe; RLS activa en backtest_runs, system_events y worker_credentials; anon no tiene SELECT/INSERT/UPDATE en backtest_runs ni system_events; authenticated tiene SELECT/INSERT en backtest_runs con policy owner; service_role tiene acceso server-side; `client_devices`, `client_events` y `assigned_device_id` aún no existen. Se inspeccionó también el SQL guardado de migration 018 (1 statement; no rollback). Ninguna migración fue aplicada.

## Límites de evidencia

No se ejecutó la migration 019, test RLS/RPC posterior a 019, prueba con dos procesos API reales, caída real de Supabase, carga de conexiones ni medición de RAM. El Broadcast multiinstancia solo se probó con dos hubs simulados en proceso; no equivale a staging. `supabase` CLI y `npx` no están instalados.
