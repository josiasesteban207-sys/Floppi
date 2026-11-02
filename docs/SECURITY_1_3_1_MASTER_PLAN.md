# FLOPPI Security Core 1.3.1 — Master Plan

**Estado:** implementación autorizada; bloque local implementado y validado; release bloqueado por verificación externa pendiente  
**Base funcional observada:** `VERSION` = 1.3.0  
**Objetivo:** 1.3.1 — Security Hardening Release  
**Alcance:** hardening de seguridad; sin nuevas funciones de trading ni operaciones financieras reales.

> **Seguimiento:** la autorización fue recibida el 2026-11-01. Ya comenzó el
> hardening de entorno, Auth/RBAC, sesión web, auditoría de mutaciones admin,
> credenciales worker y exposición local. La autorización no aprueba pruebas
> pendientes ni habilita el release.

**Resultados locales del bloque actual:** Python 3.10.0; suite completa
`138 passed`; auditoría local `16/16`; `npm audit` reportó 0 vulnerabilidades
en 36 dependencias y `pip-audit` no encontró vulnerabilidades conocidas en
`requirements.txt`. El smoke test del navegador y los assets pasó en
desarrollo sin Supabase. No se conectó a Supabase ni se aplicó una migración.

## 1. Resumen ejecutivo

La revisión inicial (antes de los cambios autorizados) confirmó que `APP_ENV` tenía valor predeterminado `development`; en ese entorno `optional_user_id` aceptaba solicitudes sin bearer token y `require_development_access` permitía ciertas rutas operativas. Producción validaba HTTPS para Supabase y CORS solo para `prod`/`production`. Docker publica el puerto 8000 y Uvicorn escucha en `0.0.0.0`; el código no demuestra que una instancia de producción esté expuesta. El progreso actual elimina el default de entorno y reemplaza el gate de rutas operativas por verificación admin.

La implementación local hace explícito el entorno, valida identidad Supabase, usa `app_metadata.role` para rutas operativas, mantiene separadas las credenciales de workers y enlaza token a requests web. Compose ahora liga el puerto a loopback. La verificación efectiva de Supabase/RLS, la topología TLS/gateway y límites de rate requieren infraestructura externa y siguen bloqueando el release.

No se propone ninguna función de trading ni cambio de algoritmos. FLOPPI seguirá siendo una plataforma educativa DEMO, sin órdenes financieras ni conexión a brokers.

## 2. Evidencia y límites de la revisión

| Hecho observado | Evidencia |
|---|---|
| `app_env` tiene valor predeterminado `development`; la validación específica se ejecuta solo en `prod`/`production`. | [settings.py](../backend/app/settings.py#L6-L20) |
| Sin token, `optional_user_id` devuelve identidad nula en desarrollo; con token llama a `auth.get_user`. | [auth.py](../backend/app/api/auth.py#L20-L47) |
| `require_development_access` protege listados operativos y preferencias mediante un gate de entorno, no una comprobación de rol. | [routes.py](../backend/app/api/routes.py#L52-L56), [event_routes.py](../backend/app/api/event_routes.py#L151-L163), [diagnostics_routes.py](../backend/app/api/diagnostics_routes.py#L70-L106), [monitoring_routes.py](../backend/app/api/monitoring_routes.py#L279-L284) |
| Credenciales de worker se validan de forma separada, se asocian a un nodo y admiten expiración; el fallback de credenciales locales solo se habilita en desarrollo. | [worker_auth.py](../backend/app/api/worker_auth.py#L18-L46), [worker_auth.py](../backend/app/api/worker_auth.py#L48-L89) |
| El cliente Supabase del backend usa la clave de service role. | [supabase_store.py](../backend/app/supabase_store.py#L14-L19) |
| La API declara CORS y expone las rutas desde una sola aplicación FastAPI. | [main.py](../backend/app/main.py#L67-L91) |
| Docker enlaza Uvicorn a `0.0.0.0:8000` y Compose publica `8000:8000`; esos archivos no configuran TLS. | [Dockerfile](../Dockerfile#L1-L8), [docker-compose.yml](../docker-compose.yml#L1-L8) |
| El frontend estático usa `fetch` sin agregar `Authorization`; no se encontró un flujo de inicio de sesión en ese cliente. | [app.js](../backend/app/static/app.js#L7) |
| Las migraciones muestran políticas RLS y grants distintos por tabla; su estado efectivo en el proyecto Supabase desplegado no fue consultado. | [001_initial.sql](../database/migrations/001_initial.sql#L39-L57), [002_multimarket_backtesting.sql](../database/migrations/002_multimarket_backtesting.sql#L203-L246), [004_worker_credentials.sql](../database/migrations/004_worker_credentials.sql#L21-L23), [010_system_health_history.sql](../database/migrations/010_system_health_history.sql#L54-L57), [012_centralized_event_log.sql](../database/migrations/012_centralized_event_log.sql#L36-L38) |
| Los requisitos de Python son rangos; no se identificó un lockfile ni se ejecutó una consulta de advisories en esta fase. | [requirements.txt](../requirements.txt#L1-L6) |

El informe automatizado existente señala verificaciones externas pendientes para RLS/JWT en Supabase, workers, TLS, límites de solicitudes y recuperación de backups: [audit_latest.md](../reports/audit_latest.md#L51-L57). Dicho informe no es una certificación de producción.

## 3. Alcance

La versión objetivo se divide en los módulos solicitados:

1. **1.3.1.1 Environment Hardening:** entornos permitidos explícitos, configuración fail-closed y validación de variables.
2. **1.3.1.2 Authentication Hardening:** tokens Supabase, expiración, revocación, errores de Auth y separación de rutas públicas/privadas.
3. **1.3.1.3 Administrator RBAC:** permisos por operación y administración confiable, sin confundir usuario, worker y administrador.
4. **1.3.1.4 API Security:** autorización por endpoint, validación, límites y datos operativos mínimos.
5. **1.3.1.5 Supabase & RLS Verification:** inventario de tablas/RPC, políticas y permisos efectivos en un entorno de prueba aislado.
6. **1.3.1.6 Worker Security:** ciclo de vida de credenciales, nodo, lease, expiración, revocación y Blacki/Blanquita.
7. **1.3.1.7 TLS & Network Protection:** HTTPS extremo a extremo donde corresponda, TLS en proxy, puertos y contenedores.
8. **1.3.1.8 Secrets & Logging:** gestión/redacción, auditoría de seguridad y retención.
9. **1.3.1.9 Dependency Security:** inventario reproducible, advisories y actualizaciones controladas.
10. **1.3.1.10 Security Regression Testing:** pruebas positivas, negativas, de integración y regresión.
11. **1.3.1.11 Final Security Audit:** revisión separada de evidencias, riesgos residuales y criterios de salida.

**Fuera de alcance:** nuevas capacidades de trading, estrategias, indicadores, algoritmos de señal, órdenes reales, conexión a brokers, desactivación de RLS, cambios de datos en Supabase durante la fase documental o reparación destructiva automática.

## 4. Decisiones recomendadas

- Fallar al arrancar si el entorno falta, está vacío o no pertenece a una lista cerrada (`development`, `test`, `production`); nunca interpretar un nombre desconocido como desarrollo o producción.
- En producción, permitir rutas de salud mínimas y explícitamente aprobadas; proteger datos de usuario con autenticación y operaciones de administración con autorización administrativa.
- Para RBAC, verificar el token con Supabase Auth y leer un atributo administrado por servidor (preferentemente `app_metadata`); no confiar en `user_metadata`, headers de rol ni parámetros enviados por el cliente. Denegar por defecto y separar el permiso `admin` de la credencial de nodo.
- Mantener service role exclusivamente en el backend. Workers reciben tokens individuales de nodo y no credenciales Supabase.
- Terminar HTTPS en un proxy/gateway administrado; restringir el puerto del contenedor a la red privada o loopback y aplicar límites compartidos en el perímetro. Un limiter solo en memoria de un proceso no satisface un despliegue distribuido.
- No crear una migración por anticipado. La revisión de archivos no demuestra que haga falta una nueva tabla: auditar primero permisos desplegados y capacidad del registro de eventos existente. Una migración posterior solo se justificaría por un hallazgo reproducible o un requisito de persistencia que no pueda cubrirse con el esquema actual.

### Decisión de sesión aprobada e implementación aplicada

El propietario aprobó `@supabase/supabase-js` empaquetado. El bundle usa la clave anon pública, conserva la sesión en `sessionStorage` y adjunta bearer tokens; el backend sigue siendo la autoridad. El manifiesto y lockfile están en `web/`; el bundle fue generado y el smoke test local no requiere credenciales. El login real, refresh, logout y expiración con Supabase siguen sin verificarse.

La revisión del esquema encontró `expires_at` nullable en `worker_credentials`. La migración 017 revoca registros sin expiración y pasa la columna a `NOT NULL`; las instalaciones afectadas tendrán que emitir credenciales nuevas. La migración está creada y probada estáticamente, pero no aplicada.

## 5. Orden propuesto

| Orden | Módulos | Salida / puerta de avance |
|---|---|---|
| 0 | Descubrimiento de despliegue y decisión de sesión web | Inventario firmado de entorno, proyecto Supabase de prueba, proxy y clientes compatibles. |
| 1 | Environment Hardening + Authentication Hardening | Configuración cerrada; pruebas de token ausente, inválido, expirado, revocado y Auth indisponible. |
| 2 | Administrator RBAC + API Security | Matriz endpoint/rol y denegación por defecto; regresión funcional de rutas existentes. |
| 3 | Supabase & RLS Verification | Evidencia de RLS, grants, RPC y aislamiento en instancia de prueba; migración solo si hay brecha demostrada. |
| 4 | Worker Security | Pruebas independientes para Blacki y Blanquita, expiración/revocación, nodo cruzado y leases obsoletos. |
| 5 | TLS & Network Protection + Secrets & Logging | Despliegue de prueba por HTTPS, límites, redacción y retención comprobados. |
| 6 | Dependency Security + Security Regression Testing | Inventario/advisories reproducibles y matriz regresiva completa. |
| 7 | Final Security Audit | Revisión independiente de cambios, evidencia, limitaciones y aprobación explícita. |

Complejidad estimada: **alta**. La causa es transversal (API, autenticación, UI, workers, base de datos y despliegue), con dependencia de un entorno Supabase y una decisión de sesión frontend. La implementación debe dividirse en cambios revisables, no en un reemplazo global de módulos.

## 6. Reversión y compatibilidad

La reversión debe ser por release y no debilitar seguridad: conservar despliegue anterior conocido, aplicar cambios de configuración en un ambiente de staging, respaldar los objetos SQL antes de cualquier migración y preparar una migración compensatoria revisada si un cambio de esquema fuese inevitable. No revertir una política relajando RLS. Si el frontend nuevo no autentica, detener el rollout en lugar de reabrir rutas operativas anónimas.

La compatibilidad concreta con FastAPI, Supabase Auth/PostgreSQL, Python 3.10, workers distribuidos, scheduler, backtesting y la UI se detalla en [SECURITY_1_3_1_COMPATIBILITY.md](./SECURITY_1_3_1_COMPATIBILITY.md).

## 7. Estado de pruebas y autorización

La autorización permite implementar y fue recibida el 2026-11-01. Se ejecutó
`python tools\audit.py --version 1.3.1` con Python 3.10.0: compilación, suite
completa (138 pruebas) y 16 checks estáticos pasaron. `npm audit --json` no
reportó vulnerabilidades para las 36 dependencias resueltas; `pip-audit -r
requirements.txt` no encontró vulnerabilidades conocidas. El browser smoke
local respondió para HTML, health, auth config, bundle y CSS.

No se ejecutaron login contra Supabase, pruebas reales de RLS/ACL/RPC,
migración en PostgreSQL, pruebas simultáneas de Blacki/Blanquita, comprobación
de TLS externo/rate limit ni auditoría independiente. La auditoría local no
es una certificación. El release continúa bloqueado hasta completar esas
validaciones y confirmar el plan de actualización/reemisión de workers.
