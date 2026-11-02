# FLOPPI Security Core 1.3.1 — Architecture Proposal

**Estado:** arquitectura actualizada con implementación local parcial; despliegue externo pendiente.  
**Compatibilidad objetivo:** conservar FastAPI, Supabase Auth/PostgreSQL, workers distribuidos y la aplicación DEMO actual.

## 0. Delta implementado y límites

- `APP_ENV` es obligatorio; producción valida URL/keys Supabase y orígenes HTTPS.
- Supabase Auth verifica bearer tokens; las rutas operativas consultan el rol
  confiable `app_metadata.role`; mutaciones admin intentan registrar un evento
  de autorización en el log central.
- La UI usa el SDK oficial con clave anon y `sessionStorage`; no se publica
  service role.
- Worker credentials persistidas requieren expiración; migration 017 revoca
  las legacy sin fecha. Los errores enviados por worker omiten el texto de
  excepción; URLs con credenciales, query o fragment son rechazadas.
- Docker Compose publica el puerto solo en loopback. No se configuró un proxy,
  TLS externo ni rate limiting distribuido.

Las pruebas locales no demuestran configuración efectiva de Supabase,
ejecución/aplicación de migraciones ni estado del perímetro desplegado.

## 1. Límites de confianza

```text
Browser (public/untrusted)
  ├─ Supabase Auth session (user access token; never service role)
  └─ HTTPS ──> edge proxy / API gateway
                 └─ private network ──> FastAPI
                     ├─ Supabase Auth get_user(token)
                     ├─ PostgreSQL through server-only service role
                     └─ user/admin routes with explicit authorization

Blacki / Blanquita (separate principals)
  └─ HTTPS + per-node token + node ID
       └─ worker-only endpoints
            └─ lease token + node binding for job mutations
```

La API actual concentra routers de nodos, datos, análisis, backtesting, monitoreo, diagnósticos, eventos y scheduler en una aplicación FastAPI: [main.py](../backend/app/main.py#L67-L91). La propuesta conserva esa arquitectura y añade límites claros en dependencias por ruta; no crea microservicios ni distribuye claves privilegiadas.

## 2. Entorno y arranque seguro

Evidencia actual: `Settings.app_env` tiene valor inicial `development`, y el validador retorna sin validar si el entorno no es `prod`/`production`: [settings.py](../backend/app/settings.py#L6-L20). La configuración ejemplo vuelve a seleccionar `development`: [.env.example](../.env.example#L1-L8).

Diseño:

- Parsear un conjunto cerrado de entornos; ausencia, vacío, error tipográfico o alias desconocido deben detener el arranque.
- Mantener configuración DEMO local solo cuando `development` se seleccione intencionalmente.
- Aplicar validación de producción para todo modo no local de forma inequívoca. Comprobar URL HTTPS Supabase, secreto requerido en servidor, origins exactos, configuración de proxy confiable y ausencia de placeholders.
- No usar `APP_ENV` como autenticador. El modo decide política/configuración, no concede permisos.
- El modo `test` debe aislar variables de entorno y credenciales; [conftest.py](../backend/tests/conftest.py#L1-L6) ya limpia variables Supabase para pruebas locales.

## 3. Identidad, autorización y clases de principal

### Usuario

La dependencia actual valida bearer tokens consultando `client.auth.get_user` y devuelve el ID; admite identidad nula sin token solo en desarrollo: [auth.py](../backend/app/api/auth.py#L20-L47). Mantener validación de token con Auth evita confiar solo en claims del cliente, pero la dependencia es remota: diseñar respuestas denegadas y disponibilidad explícitas y probar latencia/caídas sin fallback permisivo.

### Administrador

Propuesta recomendada: una dependencia `require_admin` construida sobre el usuario ya verificado, con rol administrado por servidor (`app_metadata`) y lista de permisos por operación. `user_metadata`, `X-Role`, IDs en paths y otros datos modificables por el propio usuario no conceden privilegios. El rol no se infiere de que la llamada venga del frontend ni de `APP_ENV`. La asignación y revocación de administradores se realizará mediante el canal administrativo confiable de Supabase, fuera de las APIs públicas de FLOPPI.

Definir permisos mínimos diferentes para:

- Usuario autenticado: recursos de su propio usuario, según controles de dueño existentes y RLS.
- Administrador: consultas/acciones operativas explícitamente listadas, con trazabilidad.
- Worker: heartbeat, eventos propios y operaciones de trabajo permitidas para su nodo y lease.
- Anónimo: solo superficies públicas revisadas (por ejemplo, liveness sin información sensible), nunca paneles operativos.

El backend usa un cliente con `SUPABASE_SERVICE_ROLE_KEY`: [supabase_store.py](../backend/app/supabase_store.py#L14-L19). Dicho cliente omite las barreras normales de RLS; por ello toda consulta efectuada con él debe comprobar autorización/propiedad dentro del backend y el secreto jamás se publica al navegador o worker.

### UI / sesión web

El helper de red estático realiza `fetch` sin token por defecto: [app.js](../backend/app/static/app.js#L7). Introducir auth en API sin adaptar sesión hará que operaciones de la consola fallen en producción. La estrategia de sesión es puerta de aprobación. Cualquier cliente web debe usar clave pública Supabase cuando corresponda, conservar el access token con ciclo de vida seguro y nunca recibir service role ni credenciales de worker. No exponer respuestas operativas a todo usuario autenticado: exigir rol administrativo.

## 4. Inventario de superficies API a autorizar

| Superficie | Referencias actuales | Diseño de autorización |
|---|---|---|
| Health | [routes.py](../backend/app/api/routes.py#L56-L73) | Separar liveness pública mínima de readiness con datos internos; ambos contratos documentados. |
| Heartbeat de nodo | [routes.py](../backend/app/api/routes.py#L74-L117) | Solo principal worker; token ligado al `node_id`; límites de tamaño/frecuencia. |
| Nodos y preferencias | [routes.py](../backend/app/api/routes.py#L118-L177) | Nodos: admin; preferencias: usuario autenticado y `user_id == auth.uid()` o derivar dueño del token. No confiar en path user ID. |
| Eventos | [event_routes.py](../backend/app/api/event_routes.py#L126-L163) | Ingesta worker: token/node; consulta/exportación: admin. |
| Diagnósticos | [diagnostics_routes.py](../backend/app/api/diagnostics_routes.py#L70-L143) | Lectura, resolución y exportación: admin; auditoría de resolución. |
| Monitoreo/estadísticas | [monitoring_routes.py](../backend/app/api/monitoring_routes.py#L279-L284), [monitoring_routes.py](../backend/app/api/monitoring_routes.py#L424-L430) | Admin; limitar campos de plataforma e intervalo consultable. |
| Estrategias, backtests, scheduler | [backtesting_routes.py](../backend/app/api/backtesting_routes.py#L67-L101), [scheduler_routes.py](../backend/app/api/scheduler_routes.py#L60-L63) | Usuario autenticado, propietario por ID y política RLS; endpoints de worker siguen principal separado. |
| Data/markets | [data_routes.py](../backend/app/api/data_routes.py#L15-L66) | Clasificar lectura pública frente a recolección que muta/consume recursos; no permitir ejecución financiera real. |

El gate operativo actual es un chequeo del entorno, no un permiso: [routes.py](../backend/app/api/routes.py#L52-L56). Su sustitución requiere matriz completa de rutas y tests de regresión; no basta con cambiar esa función sin migrar consumidores y rutas.

## 5. Trabajadores, credenciales y leases

La API valida forma del token, usa comparación constante en fallback DEMO, busca hash en `worker_credentials`, asocia credencial al nodo y comprueba expiración: [worker_auth.py](../backend/app/api/worker_auth.py#L31-L79). La tabla está bajo RLS y grants limitados a `service_role`: [004_worker_credentials.sql](../database/migrations/004_worker_credentials.sql#L21-L23). Las rutas de trabajo también requieren nodo y lease para mutar resultados: [backtesting_routes.py](../backend/app/api/backtesting_routes.py#L239-L298).

Controles por diseñar/verificar:

- Token individual de alta entropía, hash almacenado, nodo vinculado, expiración obligatoria para credenciales de producción, revocación comprobable y sin secretos compartidos entre Blacki/Blanquita.
- No poner tokens en URL, reportes, logs o payloads; minimizar mensaje de error del worker guardado como incidente.
- El lease debe ser impredecible, temporal, vinculado a trabajo/nodo y no reutilizable tras completar, expirar o revocar. La recuperación de trabajos existente es parte de la regresión.
- Mantener HTTPS para workers remotos. El worker rechaza HTTP remoto y permite HTTP solo en loopback: [local_worker.py](../worker/local_worker.py#L220-L230).
- Probar simultáneamente Blacki y Blanquita, incluyendo token cruzado, nodo desconectado, lease expirado y fallo de Auth/DB.

## 6. Supabase, PostgreSQL y RLS

Las migraciones históricas muestran políticas de propietario para ciertas tablas de aplicación y restricciones servidor-solo para credenciales, historial de salud, diagnósticos, eventos y señales. Como ejemplos: [001_initial.sql](../database/migrations/001_initial.sql#L39-L57), [002_multimarket_backtesting.sql](../database/migrations/002_multimarket_backtesting.sql#L203-L246), [010_system_health_history.sql](../database/migrations/010_system_health_history.sql#L54-L57), [011_intelligent_diagnostics.sql](../database/migrations/011_intelligent_diagnostics.sql#L40-L42) y [016_hybrid_signal_history.sql](../database/migrations/016_hybrid_signal_history.sql#L35-L37).

Cada función `SECURITY DEFINER` debe inventariarse por firma, propietario, `search_path`, SQL dinámico, validación de argumentos y roles `EXECUTE`. Las funciones de lease ya fijan `search_path` y revocan/grant de ejecución en las migraciones existentes: [006_reliable_job_leases.sql](../database/migrations/006_reliable_job_leases.sql#L77-L98). La auditoría debe verificar estado efectivo en staging con roles `anon`, `authenticated`, `service_role` y usuario A/B; revisar grants de `PUBLIC`, que no se infieren solo mirando las políticas.

No desactivar RLS ni conceder `service_role` al cliente. La migración 017 no
cambia políticas ni grants: revoca filas de credenciales worker sin expiración
y endurece `expires_at` a `NOT NULL`. Debe probarse y aplicarse en staging
antes de desplegar el código; su aplicación no se verificó localmente.

## 7. Red, TLS y límites de solicitudes

Uvicorn ejecuta HTTP en `0.0.0.0:8000` dentro del contenedor; Compose liga el host a `127.0.0.1`: [Dockerfile](../Dockerfile#L7-L8), [docker-compose.yml](../docker-compose.yml#L6-L8). El diseño de producción sigue requiriendo TLS en un proxy/gateway administrado, upstream privado, redirección/denegación de HTTP en el borde y encabezados forwarded aceptados solo desde proxies de confianza. No se verificó que exista ni que TLS termine correctamente.

Aplicar rate limiting compartido en gateway para autenticación, endpoints de worker y operaciones costosas. Si no se dispone de gateway con límites, seleccionar almacenamiento distribuido antes de implementar; limitar solo en memoria falla con varios procesos/instancias. Mantener límites de payload, parámetros de consultas y exportaciones; las rutas de eventos ya acotan periodos y búsquedas: [event_routes.py](../backend/app/api/event_routes.py#L71-L106).

## 8. Secretos, registros y dependencia

Existe sanitización por claves/patrones en el registro central: [event_log.py](../backend/app/event_log.py#L17-L20), y el endpoint de exportación documenta exclusión de tokens y cuerpos: [event_routes.py](../backend/app/api/event_routes.py#L194-L194). El diseño debe verificar redacción antes de almacenamiento y en logs de Python, errors de worker, incidentes, CSV/JSON y trazas de proxy. Definir política separada de retención para eventos, Auth/auditoría, diagnósticos y backups; `EVENT_LOG_RETENTION_DAYS` ya tiene un parámetro: [settings.py](../backend/app/settings.py#L13-L15). No suponer que este ajuste cubre todas las tablas.

Python usa rangos de versiones en `requirements.txt` y no se identificó lockfile: [requirements.txt](../requirements.txt#L1-L6). La fase de implementación debe producir inventario reproducible (incluidos transitivos), consultar advisories, registrar fecha/fuente y probar actualizaciones en Python 3.10. Ningún paquete se debe actualizar únicamente por estar desactualizado sin revisar compatibilidad.

## 9. Persistencia/migraciones

No se identificó una necesidad obligatoria de nueva tabla para cerrar el hallazgo de entorno/autorización: el trabajo inmediato es de configuración, API, UI y despliegue. Para RBAC por metadata server-managed no se necesita migración SQL propuesta. Reutilizar el registro central solo si se verifica que registra actor, acción, objetivo, resultado y retención requeridos. Si el análisis real demuestra que hacen falta campos/tablas/políticas, diseñar una migración independiente con RLS habilitado, ACL explícitas, funciones seguras e idempotencia antes de tocar una base.
