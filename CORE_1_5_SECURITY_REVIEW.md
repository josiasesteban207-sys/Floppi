# FLOPPI Core 1.5 — Revisión de seguridad

## Verificado localmente

- Auth WebSocket con `get_user` de Supabase; token solo en primer frame TLS, no query string ni logs.
- `auth.refresh` vuelve a validar usuario y dispositivo; identidad no puede cambiar. Sesión máxima 1 hora y heartbeats limitados a 1 cada 5 segundos; conexión expira con 90 segundos sin actividad.
- Un socket por dispositivo por lease SQL distribuido (90 s) y hasta ocho por cuenta en cada proceso; frames de 8 KiB; Origin debe estar allowlisted si viene presente.
- Registro, listado, heartbeat, revocación, tareas y outbox validan owner en backend. El propietario se deriva del access token, no del body.
- Revocación local cierra el socket; `device.revoked` global se propaga después de activar migration 019/Realtime.
- Device claim exige dispositivo online reciente, assignment propio, estado pending, intentos bajo máximo, sin lease activo concurrente y token de lease nuevo. Worker global excluye filas asignadas.
- Un lease vencido a dispositivo offline/revocado se libera durante recovery; intentos agotados quedan failed.
- RLS activada en las nuevas tablas y grants solo a service-role. Funciones nuevas usan SECURITY INVOKER, `search_path` fijo, y EXECUTE solo para service-role. Se conserva la función legacy de claim SECURITY DEFINER con ACL restringida, existente desde migración previa.
- Sin secretos embebidos en clientes; no hay operación de broker ni dinero real.

## Pendientes

- No se probaron las policies/GRANT de migration 019 en staging; aún no existe allí `client_devices` ni `client_events`.
- Heartbeat HTTP no tiene rate limiter distribuido compartido; REST debe protegerse con el rate limiting de gateway antes de exposición pública. El WS limita heartbeat por conexión.
- La clave service-role habilita subscriber/broadcast internos; rotación, almacenamiento en secret manager y validación de privilegios efectiva quedan pendientes de configuración despliegue.
- El cierre remoto de sockets está implementado por evento privado, pero requiere aplicar 019 y validar bridge para verificarse en staging.
- No se ejecutaron pruebas de fuzzing/carga, conexión duplicada entre dos procesos reales, RLS Advisors ni análisis de dependencias en esta etapa. El claim distribuido de conexión tiene prueba estática/contrato, no integración PostgreSQL.

Las operaciones de eventos, dispositivos y tareas se verificaron localmente; la validación remota de estas nuevas políticas y funciones queda **BLOCKED** hasta autorizar migration 019. No se modificó el historial real.
