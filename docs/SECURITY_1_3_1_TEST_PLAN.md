# FLOPPI Security Core 1.3.1 — Test Plan

**Estado:** matriz con pruebas locales ejecutadas y validaciones externas pendientes.  
Los casos marcados `PASS` aplican solo al alcance y evidencia indicados; no implican validación de un despliegue.

## Resultados ejecutados (2026-11-01)

| Grupo / caso | Estado | Evidencia y límite |
|---|---|---|
| T-ENV-01 / T-ENV-03 | PASS local | `test_settings.py`: APP_ENV vacío/desconocido y configuración de producción inválida/rechazada. No prueba variables de un despliegue real. |
| T-AUTH-01 / T-RBAC-01 / T-RBAC-02 | PASS local | `test_api.py`: ruta privada sin token devuelve 401; metadata de usuario no concede admin; rol `app_metadata` se acepta y se registra una mutación. Auth es mock, no Supabase real. |
| T-WKR-01 | PASS unitario | PASS unitario; Supabase/Blacki/Blanquita no probados |
| T-LOG-02 | PASS unitario | PASS parcial; evento mock, retenci?n externa no probada |
| T-AUTH-04 / T-WEB | PASS parcial | Bundle servido y prueba de navegador en modo DEMO; `npm run build` pasó. Login, refresh, logout y expiración contra Supabase no ejecutados. |
| T-NET-01 | PASS parcial | PASS parcial; proxy/TLS no probados |
| T-DEP-01 | PASS parcial | PASS parcial; sin SBOM ni lock Python |
| T-REG-01 | PASS local | PASS local; sin broker |
| T-RLS-01/02/03 | BLOCKED | No hay `.env` ni proyecto Supabase de staging; migraciones/RLS/grants/RPC no se consultaron ni aplicaron. |
| T-WKR-02/03, T-REG-02 | NOT RUN | No se dispuso de Blacki/Blanquita conectados simultáneamente ni entorno distribuido. |
| T-NET-02, T-AUD-01 | BLOCKED | Gateway/rate limits no están configurados; auditoría independiente no realizada. |

Comandos: `python tools\audit.py --version 1.3.1` con Python 3.10.0,
`npm audit --json` y `python -m pip_audit -r requirements.txt --progress-spinner off`.
Ver [audit_latest.md](../reports/audit_latest.md). `pip-audit` fue instalado
temporalmente fuera del proyecto; no se agregó a dependencias runtime/dev.

## 1. Enfoque y entorno

1. Unit y API tests aislados en Python 3.10, sin credenciales locales; el fixture actual limpia Supabase variables: [conftest.py](../backend/tests/conftest.py#L1-L6).
2. Integración en un proyecto Supabase de staging con cuentas de prueba A/B, roles controlados, esquema construido por migraciones existentes y datos DEMO. Nunca usar producción ni secretos del desarrollador.
3. Pruebas de worker con tokens de un solo uso y dos nodos identificados como Blacki y Blanquita; no enviar órdenes reales ni conectarse a brokers.
4. Pruebas de TLS/red en ambiente controlado y desde redes internas/externas definidas; no realizar escaneo no autorizado.
5. Repetir regresión funcional de salud, análisis, datos DEMO, backtesting, scheduler, eventos y consola tras cada cambio de autorización.

## 2. Matriz de casos

| ID | Módulo / componente | Riesgo | Prueba propuesta | Resultado esperado | Prioridad | Dependencias | Estado |
|---|---|---|---|---|---|---|---|
| T-ENV-01 | Environment / Settings | Arrancar accidentalmente como desarrollo cuando falta configuración. | Construir Settings con `APP_ENV` ausente/vacío. | Fallo explícito de configuración; no se levanta API ni se asume desarrollo. | Critical | Cambio aprobado de settings; Python 3.10. | PASS local |
| T-ENV-02 | Environment / Settings | Aceptar typo o ambiente ambiguo y omitir validaciones. | Probar alias desconocido, mayúsculas/minúsculas y `prod`/`production`. | Solo los valores documentados se aceptan; equivalencia o rechazo consistente y probado. | High | T-ENV-01. | Pendiente |
| T-ENV-03 | Environment / Production | Placeholder, Supabase HTTP o CORS inseguro pasa producción. | Tabla de casos negativos para URL, key vacía/placeholder, wildcard y origins con path. | Inicio rechazado con error sin filtrar secreto; origins exactos HTTPS pasan. | Critical | Proyecto de test de configuración. | PASS local |
| T-ENV-04 | Environment / local DEMO | Hardening rompe uso local educativo. | Arranque explícito `development`, sin Supabase, con token de worker local válido. | DEMO funciona en loopback; rutas de usuario anónimas solo según política local documentada. | High | T-ENV-01 y baseline de tests. | PASS local |
| T-AUTH-01 | Supabase Auth | Acceso privado sin bearer. | Llamar a estrategias, backtesting y scheduler en modo producción sin Authorization. | 401; no hay operación ni lectura/escritura lateral. | Critical | Proyecto staging y token config. | PASS local; sin Supabase |
| T-AUTH-02 | Supabase Auth | Token malformado, expirado, revocado o firmado por otro proyecto es aceptado. | Enviar casos inválidos/expirados y usuario revocado contra rutas privadas. | 401 y respuesta sin claims/datos; no fallback anónimo. | Critical | Auth staging y fixtures de tokens de prueba. | Pendiente |
| T-AUTH-03 | Supabase Auth availability | Auth fuera de servicio provoca acceso permisivo o respuestas confusas. | Simular timeout/5xx de `get_user`. | 503/denegación explícita, sin degradar a `user_id=None`; no filtrar tokens. | High | Mock de Auth; contrato de timeout. | Pendiente |
| T-AUTH-04 | Session / web | La consola no manda token y deja de funcionar o intenta usar secretos privilegiados. | Inicio, expiración, renovación y logout desde el flujo web aprobado; inspeccionar requests/browser storage. | Requests privados llevan token válido; logout/expiración deniega; service role nunca aparece en cliente, logs o assets. | Critical | Decisión de sesión web; manifiesto/cliente aprobado. | PASS parcial; ciclo Supabase no probado |
| T-RBAC-01 | Admin RBAC | Usuario normal puede acceder a estado operativo. | Acceder a nodos, eventos, diagnósticos, monitoreo y exports con usuario válido no-admin. | 403/404 según política uniforme; no se devuelven registros ni mutaciones. | Critical | Admin test user y matriz de rutas. | PASS local; Auth mock |
| T-RBAC-02 | Admin RBAC | Elevación mediante metadata editable, ID de path o header. | Cambiar `user_metadata`, enviar `X-Role: admin`, cambiar user ID de path. | Ninguna entrada del cliente concede permisos; admin solo por fuente confiable servidor. | Critical | Cuentas de staging con claims diferenciados. | PASS local; Auth mock |
| T-RBAC-03 | Admin RBAC | Admin revocado conserva acceso por caché o token antiguo. | Revocar rol y repetir petición con token previo y renovado. | Acceso denegado según la política de revocación definida; tiempo máximo de propagación medido. | High | Procedimiento de rol y Auth staging. | Pendiente |
| T-API-01 | API authorization | Usuario A lee/modifica objetos del usuario B. | Crear recursos A/B y probar IDs cruzados en rutas backtesting/scheduler/preferencias. | Denegación/no-existencia indistinguible según contrato; datos de B no filtrados ni alterados. | Critical | Dos usuarios staging, RLS habilitada. | Pendiente |
| T-API-02 | API inputs | Filtros, fechas, IDs, exports o bodies grandes agotan recursos o eluden restricciones. | Casos límites, fechas invertidas/timezone, campos desconocidos, tamaños extremos y periodo máximo. | 422/413/429 documentado; consumo acotado y sin traceback/datos internos. | High | Límites de esquema y gateway. | Pendiente |
| T-API-03 | API operations | Exportaciones muestran secretos o exponen rutas no protegidas. | Usuario anon/no-admin/admin sobre export CSV/JSON y buscar tokens señuelo en output. | Solo rol aprobado exporta; salida no contiene secretos ni fórmula CSV ejecutable no neutralizada. | High | T-RBAC-01 y fixtures con token señuelo. | Pendiente |
| T-RLS-01 | Supabase RLS | Usuario A puede consultar filas de B o anon accede a contenido privado. | Ejecutar operaciones directas con roles `anon`, `authenticated` (A/B) y service role en staging. | RLS y grants producen aislamiento esperado; anon no lee/escribe privados; evidencia de tabla/rol guardada. | Critical | Staging aislado, migraciones aplicadas en orden. | Pendiente |
| T-RLS-02 | Supabase grants | Privilegio implícito a `PUBLIC` o grants heredados permiten acceso no previsto. | Inspeccionar ACL de cada tabla/función del inventario y ejecutar prueba negativa por rol. | No hay grants efectivos no justificados; diferencia respecto a migraciones documentada. | Critical | Permiso de lectura catálogo staging. | Pendiente |
| T-RLS-03 | SECURITY DEFINER | RPC cambia datos fuera de alcance, tiene search_path inseguro o acceso público. | Enumerar funciones, revisar firma/search_path/owner/EXECUTE; invocar como cada rol en transacción de prueba. | Solo service role llama RPC privilegiadas; argumentos inválidos fallan; cambios no autorizados no ocurren. | High | Lista completa de funciones, staging SQL. | Pendiente |
| T-WKR-01 | Worker auth | Token corto, ausente, revocado, vencido o de nodo ajeno funciona. | Probar headers incompletos, longitud baja, expiración, revocación y nodo cruzado con Blacki/Blanquita. | 401 sin mutación ni revelar existencia del token; credenciales de nodo aisladas. | Critical | Workers de prueba y credenciales efímeras. | PASS unitario; Supabase/Blacki/Blanquita no probados |
| T-WKR-02 | Worker leases | Worker puede finalizar job con lease ajeno, expirado o reutilizado. | Reclamar job con nodo A; intentar heartbeat/complete/fail desde B y reusar lease tras transición. | Solo combinación válida nodo+lease activo muta; solicitudes repetidas no alteran resultado. | Critical | Staging con migration 006/015 y jobs DEMO. | Pendiente |
| T-WKR-03 | Worker lifecycle | Rotación, recuperación o caída perjudican worker legítimo o dejan job bloqueado. | Rotar/revocar token, desconectar nodo durante lease y ejecutar recuperación. | Token viejo denegado; trabajo se recupera/reintenta según backoff actual; no se duplican resultados. | High | Worker Recovery baseline; job aislado. | Pendiente |
| T-WKR-04 | Worker transport | Worker remoto transmite token por HTTP. | Configurar URL HTTP remota y URL HTTPS staging; probar loopback HTTP. | Remoto HTTP falla antes de transmitir; HTTPS funciona; loopback HTTP solo en desarrollo. | Critical | Endpoint TLS controlado. | Pendiente |
| T-NET-01 | TLS / Docker | API queda expuesta directamente por puerto de contenedor sin TLS. | Desplegar composición de producción y verificar desde red pública/privada binding, TLS y redirect. | Solo proxy publica HTTPS; upstream inaccesible públicamente; TLS/certificado válidos. | High | Infra de staging y aprobación de red. | PASS parcial; proxy/TLS no probados |
| T-NET-02 | Rate limit | Abuso de Auth, export, worker o cómputo sin límite compartido. | Superar cuota configurada desde una IP/principal y distribuir llamadas entre instancias. | Respuesta 429 y retry policy; contador consistente entre instancias; llamadas legítimas recuperan acceso. | High | Gateway distribuido y umbrales acordados. | Pendiente |
| T-LOG-01 | Secrets/logging | Token o secreto aparece en logs, eventos, diagnósticos o informes. | Enviar tokens señuelo en rutas válidas/inválidas, errores de worker y metadatos; buscar en todos los sinks/exports. | Cero ocurrencias de secreto/token; evento conserva solo datos operativos necesarios. | Critical | Fixture con sinks/logs de staging. | Pendiente |
| T-LOG-02 | Audit/retention | Cambios de rol/credencial no auditados o retención elimina evidencia demasiado pronto. | Asignar/revocar admin y worker; validar actor/acción/resultado; ejecutar limpieza con fecha controlada. | Evento atribuible, protegido de usuario cliente y retenido según política aprobada. | High | Política de retención; registro actual evaluado. | PASS parcial; evento mock, retenci?n externa no probada |
| T-DEP-01 | Dependencies | Transitorio vulnerable/desconocido o resolución no reproducible. | Generar inventario/SBOM de entorno limpio; consultar advisories con fecha; reconstruir Python 3.10. | Todos los componentes identificados; hallazgos triados; build reproducible y pruebas verdes antes de aprobar cambios. | High | Acceso a feeds aprobados y CI. | PASS parcial; sin SBOM ni lock Python |
| T-REG-01 | Regression / demo | Seguridad altera uso DEMO/backtesting y permite accidentalmente operación financiera real. | Ejecutar suite existente, endpoints demo, scheduler y flujos de worker; confirmar no existe broker/order route nueva. | Flujos demo conservados; no se envían órdenes reales; etiquetas y disclaimers siguen visibles. | Critical | Suite base y build web. | PASS local; sin broker |
| T-REG-02 | Regression / Blacki/Blanquita | Cambio de permisos rompe uno de los dos workers o asignación balanceada. | Prueba en paralelo de ambos nodos, heartbeat, dispatch, lease, complete y recuperación. | Ambos identificadores operan solo con sus credenciales y reciben carga según comportamiento actual. | High | Dos workers aislados y migraciones de queue vigentes. | Pendiente |
| T-AUD-01 | Final audit | Aprobación sin evidencias o con riesgo desconocido. | Revisor independiente verifica diff, matriz, configuración staging, pruebas y límites no probados. | Aprobación explícita con hallazgos/riesgos y alcance verificable; ningún test pendiente se etiqueta PASS. | Critical | Todos los casos críticos y artefactos disponibles. | Pendiente |

## 3. Suites y pruebas existentes para ampliar

- Configuración/autenticación: [test_settings.py](../backend/tests/test_settings.py), [test_api.py](../backend/tests/test_api.py).
- Worker credenciales y nodos: [test_worker_auth.py](../backend/tests/test_worker_auth.py).
- Leases, recuperación y balanceo: [test_worker_recovery.py](../backend/tests/test_worker_recovery.py), [test_worker_balancer.py](../backend/tests/test_worker_balancer.py).
- Scheduler, diagnóstico, registro y monitoreo: [test_scheduler.py](../backend/tests/test_scheduler.py), [test_diagnostics.py](../backend/tests/test_diagnostics.py), [test_event_log.py](../backend/tests/test_event_log.py), [test_monitoring.py](../backend/tests/test_monitoring.py).
- Contrato de la API estática y assets: [test_api.py](../backend/tests/test_api.py).

El reporte previo contiene un resultado histórico de 125 tests y 15/15 checks; no es resultado de los casos nuevos: [audit_latest.md](../reports/audit_latest.md#L11-L27).

## 4. Criterio de reporte

Para cada ejecución guardar commit/hash probado, versión de Python, sistema, comando, entorno (sin secretos), resultado exacto, logs sanitizados y evidencia de staging. Marcar `PASS`, `FAIL`, `BLOCKED` o `NOT RUN`; una matriz con resultados esperados no equivale a un resultado ejecutado. Fallas en Auth/RLS/TLS críticas bloquean release.
