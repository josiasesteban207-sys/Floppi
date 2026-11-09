# FLOPPI Core 1.5 — Plan de implementación

| Secuencia | Trabajo | Estado verificable |
|---|---|---|
| 1 | Auditoría Core 1.4 y migración real staging | Hecha, lectura remota `READ ONLY`; ver `CORE_1_5_BASELINE.md` |
| 2 | Persistencia de dispositivos y outbox | Código más migration propuesta 019; bloqueado en Supabase hasta aplicar autorización |
| 3 | Broadcast privado entre instancias | Bridge implementado; pruebas simuladas locales; staging no desplegado |
| 4 | Auth, sesión, revocación y rate limits WS | Reautenticación por frame, máximo 1 socket por dispositivo, límite de heartbeat, sesión de 1h y timeout de liveness; pendiente de prueba con Supabase Auth real |
| 5 | Coordinador | Manual/automático, pause/resume, leases y liberación de assignment al recuperar lease offline; implementación local |
| 6 | Pruebas | Suite local completa; escenarios remotos/multiinstancia real pendientes |
| 7 | Documentación | Documentos CORE_1_5 y contratos actualizados |
| 8 | Staging | Espera aprobación explícita para ejecutar migration 019 y validar RPC/RLS/Realtime remoto |

## Secuencia segura de promoción

1. Revisar migration 019 y compatibilidad con instalación limpia y staging.
2. Respaldar/confirmar staging, y aplicar 019 solo tras autorización explícita.
3. Ejecutar pruebas SQL de RLS, grants, RPC, status check y recuperación en staging.
4. Desplegar dos instancias API de prueba; verificar Broadcast, desconexión, reconexión, revocación y outbox.
5. Medir memoria, conexiones, throughput y límites Realtime con carga gradual.
6. Resolver hallazgos y aprobar Core 1.5 localmente antes de producción (que no forma parte de este trabajo).
