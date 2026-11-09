# Evidencia de pruebas — FLOPPI Core 1.4

Entorno: Windows, Python 3.10, backend local; configuración de pruebas no carga secretos (`backend/tests/conftest.py`).

| Ejecución | Comando | Resultado |
|---|---|---|
| Suite previa posterior a integración inicial | `pytest -q` | 162 passed in 9.67s |
| Suite de integración nueva (primer intento) | `pytest -q backend/tests/test_core14_devices_realtime.py` | 1 failed, 4 passed; el test esperaba omitir el evento `device.connected`. Ajustada la aserción al protocolo observado. |
| Suite de integración nueva (segundo intento) | `pytest -q backend/tests/test_core14_devices_realtime.py` | 1 failed, 4 passed; el test esperaba omitir `device.heartbeat`. Ajustada la aserción al protocolo observado. |
| Suite completa tras incluir clientes concurrentes | `pytest -q` | 1 failed, 167 passed; el token de prueba era menor al tamaño mínimo exigido. |
| Suite completa final | `pytest -q` | **168 passed in 13.39s** |

Las fallas intermedias fueron fallas reales de aserción/fixture, quedaron registradas y se corrigieron. La suite final cubre seis pruebas nuevas: aislamiento de dispositivos, auth/heartbeat/eventos WebSocket, rechazo de auth cruzada, dos conexiones de cuentas distintas sin cruce de eventos, propiedad y lease de tareas, y guardas estáticas de migration/RLS.

No hay evidencia de pruebas reales contra Supabase, RLS en PostgreSQL, migraciones aplicadas, staging, producción ni varias instancias de servidor.
