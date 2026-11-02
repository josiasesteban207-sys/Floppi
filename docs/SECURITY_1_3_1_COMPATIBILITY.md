# FLOPPI Security Core 1.3.1 — Compatibility Analysis

**Estado:** evaluación actualizada tras hardening local parcial; release/staging todavía pendientes.  
**Baseline en el checkout:** 1.3.0.

## 1. Matriz de compatibilidad

| Componente | Evidencia actual | Impacto esperado del hardening | Compatibilidad y control requerido |
|---|---|---|---|
| Python 3.10 | Docker usa `python:3.10-slim`: [Dockerfile](../Dockerfile#L1-L4); el reporte previo ejecutó Python 3.10: [audit_latest.md](../reports/audit_latest.md#L3-L5). | Settings, dependencias, tests y tooling deben conservar sintaxis/runtime 3.10. | Ejecutar suite y build con Python 3.10; no introducir sintaxis o paquetes que eleven el mínimo sin aprobación. |
| FastAPI / Uvicorn | Una instancia FastAPI monta routers versionados; Docker arranca Uvicorn HTTP. [main.py](../backend/app/main.py#L67-L91), [Dockerfile](../Dockerfile#L7-L8). | Añadir dependencias de autenticación/autorización puede alterar OpenAPI, errores y acceso a rutas. | Mantener prefijo `/api/v1`, métodos y contratos de DEMO; documentar cambios 401/403; smoke test de endpoints. |
| Supabase Auth | `optional_user_id` valida llamando `get_user`: [auth.py](../backend/app/api/auth.py#L20-L47). | Las rutas privadas necesitan sesión y rol; disponibilidad de Auth pasa a ser requisito para usuario/admin. | Tratar timeout/5xx como fallo cerrado; conservar contrato de user ID, revisar expiración/revocación. |
| Supabase PostgreSQL | Migraciones definen RLS/grants y funciones RPC. Ejemplos: [002_multimarket_backtesting.sql](../database/migrations/002_multimarket_backtesting.sql#L203-L246), [006_reliable_job_leases.sql](../database/migrations/006_reliable_job_leases.sql#L77-L98). | La cuenta service role del backend requiere autorización propia; políticas desplegadas deben coincidir con migraciones. | No desactivar RLS; no dar service role a browser/worker; probar user A/B y ACL real antes de despliegue. |
| DB y migraciones | Checkout incluye [017_worker_credential_expiry.sql](../database/migrations/017_worker_credential_expiry.sql) tras [016_hybrid_signal_history.sql](../database/migrations/016_hybrid_signal_history.sql); 008/009 no están presentes. | 017 revoca credenciales sin expiración y hace `expires_at` obligatorio; requiere reinstalar token en workers afectados. | README actualizado. Migración no aplicada; probar en staging/snapshot y reemitir credenciales antes de rollout. No inventar 008/009. |
| Workers distribuidos | API autentica por token individual/nodo; worker exige HTTPS remoto y solo permite HTTP loopback: [worker_auth.py](../backend/app/api/worker_auth.py#L31-L79), [local_worker.py](../worker/local_worker.py#L220-L230). | Endurecer Auth humana no debe cambiar protocolo worker ni hacer al worker usuario/admin. | Mantener `X-Node-Token`, `X-Node-Id`, headers de lease, compatibilidad Blacki/Blanquita; probar rotación y recuperación antes de release. |
| Cola/leases/scheduler | Rutas de worker llaman verificación de nodo; mutaciones usan lease; scheduler depende de usuario autenticado: [backtesting_routes.py](../backend/app/api/backtesting_routes.py#L239-L298), [scheduler_routes.py](../backend/app/api/scheduler_routes.py#L60-L63). | Separar scopes puede afectar claim, heartbeat, complete, fail, pause/resume/cancel. | Reproducir dispatch/idempotencia/recuperación y propietario. Nada de operaciones financieras reales. |
| UI web estática | HTML estático servido por backend; `app.js` agrega bearer token mediante el SDK empaquetado. | Bundle generado con `@supabase/supabase-js`; browser smoke de modo DEMO confirmó UI/assets. | Login, refresh, logout y expiración reales requieren Supabase staging. El rol mostrado por UI es solo conveniencia; backend aplica permisos. |
| Demo/backtesting | README declara plataforma educativa/paper, sin órdenes reales ni brokers: [README.md](../README.md#L1-L5). Tests prueban la etiqueta DEMO y endpoints actuales: [test_api.py](../backend/tests/test_api.py). | Seguridad no debe convertir simulaciones ni eventos en ejecución financiera, ni quitar disclosure. | Regresión obligatoria; conservar disclaimers y ausencia de integración real con broker. |
| CORS | `settings.py` valida exact HTTPS origins para producción; middleware CORS está en FastAPI. [settings.py](../backend/app/settings.py#L36-L51), [main.py](../backend/app/main.py#L76-L82). | El flujo de sesión puede requerir origins adicionales; credenciales y CORS deben ser coherentes. | Sin `*` con credenciales; allowlist explícita; probar preflight desde origen aprobado y no aprobado. |
| Logs/eventos | Registro central sanitiza datos sensibles; las mutaciones admin registran el usuario, método y path autorizado. [auth.py](../backend/app/api/auth.py), [event_log.py](../backend/app/event_log.py#L17-L20). | Evento auditado antes de ejecutar la mutación; falla cerrada si el registro no se puede persistir. | Prueba unitaria/mock ejecutada; sink y retención reales requieren Supabase. Worker ya no persiste el texto bruto de excepciones. |
| Retención | Hay variable `EVENT_LOG_RETENTION_DAYS`; `settings` la restringe entre 1 y 3650. [settings.py](../backend/app/settings.py#L13-L15). | Una política global no asegura retención de todas las tablas, respaldos o logs externos. | Inventariar sinks y retenciones desplegadas antes de establecer ajustes nuevos. |
| Dependencias | Manifest directo Python con rangos; no hay lockfile localizado. [requirements.txt](../requirements.txt#L1-L6). | Pinning/SBOM o SDK web puede cambiar build y superficie de supply chain. | Mantener compatibilidad Python 3.10 y revisar la resolución completa; ningún advisory concreto se confirmó en esta fase. |

## 2. Secuencia de despliegue compatible

1. Confirmar nomenclatura/versionamiento (ver apartado 3) y hacer snapshot del estado actual.
2. Aprobar Auth/session web, orígenes, rol admin y configuración de proxy antes de implementar.
3. Aplicar primero a staging la configuración y cambios compatibles con la API; observar métricas de 401/403 y errores de cliente.
4. Integrar la UI con sesión y probar la API completa en staging. No habilitar producción con una UI que solo puede hacer solicitudes anónimas.
5. Verificar RLS/ACL y workers contra un Supabase aislado; comparar schema y permisos con scripts.
6. Desplegar gradualmente detrás de HTTPS y gateway; verificar Blacki/Blanquita, cola, scheduler y DEMO.
7. Revertir aplicación/configuración solo a una combinación conocida compatible. Nunca mitigar regresión reabriendo endpoints operativos ni desactivando RLS.

## 3. Versionado y paquetes

El candidato de seguridad se identifica como 1.3.1 en `VERSION`, OpenAPI,
worker y consola; el historial híbrido 1.3.0 permanece documentado como
release anterior. Un ZIP de 1.3.1 no representa aprobación de producción.

Los manifests Python siguen usando rangos y no incluyen lockfile.
`npm audit` reportó cero advisories en 36 dependencias y
`pip-audit -r requirements.txt` no encontró vulnerabilidades conocidas. No se
generó SBOM; los resultados no garantizan ausencia de vulnerabilidades futuras.

## 4. Funcionalidades que deben preservarse

- Supabase Auth y separación de datos por usuario.
- PostgreSQL y RLS habilitada.
- Blacki y Blanquita, heartbeats, asignación balanceada, leases y recuperación.
- Backtesting/scheduler DEMO, historial, análisis y consola.
- Endpoints de health necesarios para liveness/readiness con datos mínimos.
- Exportaciones autorizadas, monitoreo y diagnósticos administrativos.
- Python 3.10 y `api/v1`.
- Exclusión permanente de órdenes financieras reales y conexión real a broker.
