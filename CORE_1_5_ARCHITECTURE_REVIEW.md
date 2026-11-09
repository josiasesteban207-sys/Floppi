# FLOPPI Core 1.5 — Revisión de arquitectura

## Arquitectura preservada

FastAPI sigue siendo el punto de entrada para REST y WebSocket. Supabase Auth valida la identidad. Supabase/PostgreSQL mantiene datos persistentes; RLS sigue activa y el backend utiliza service-role solo en servidor. `backtest_runs` y sus leases continúan siendo la autoridad de ejecución. Scheduler, worker balancer y recovery existentes se conservan.

## Extensión implementada

- `DeviceRegistry`: SQL en modo Supabase; memoria marcada `memory-demo` si no hay configuración. Errores de escritura remota responden 503 y nunca hacen fallback silencioso.
- `RealtimeHub`: conexiones locales acotadas, aislamiento por owner, deduplicación acotada y fan-out best-effort.
- `DistributedEventBridge`: una suscripción privada Supabase Realtime por proceso API; Broadcast interno propaga eventos a las otras instancias. La credencial service-role permanece solo en servidor.
- `client_events`: outbox duradero owner-scoped; REST sirve reconciliación al reconectar. El transporte Broadcast es efímero, no fuente de verdad.
- Coordinador: assignment RPC condicionado, una concurrencia por dispositivo, capacidades y métricas recientes; usa los leases actuales.

## Transporte elegido

Supabase Realtime Broadcast es la opción distribuida del candidato. Supabase recomienda Broadcast frente a Postgres Changes para escalabilidad y seguridad; permite emitir desde REST/servidor y proteger suscripciones con canales privados. Es una pieza gestionada por el servicio existente, sin Redis ni listener PostgreSQL adicional en cada proceso, lo cual reduce conexiones y memoria propia en un servidor de 8 GB. Cada proceso API mantiene una suscripción; el volumen y el plan Realtime deben vigilarse porque se contabilizan conexiones y mensajes. La documentación oficial: [Broadcast](https://supabase.com/docs/guides/realtime/broadcast), [límites](https://supabase.com/docs/guides/realtime/limits).

PostgreSQL `LISTEN/NOTIFY` es ligero y útil entre procesos, pero sus notificaciones son efímeras, visibles a todos los listeners del canal y requieren un listener de sesión dedicado; necesitaría el outbox/reconciliación de todos modos. No se incorpora en paralelo. Redis sería otra infraestructura y no aporta una ventaja demostrada para el volumen esperado.

## Límites

- Core 1.5 usa un tópico interno privado compartido entre procesos API; todos los procesos backend de confianza reciben cada evento y filtran por `user_id` antes de fan-out local.
- La respuesta WebSocket no incluye `user_id`, tokens ni datos ajenos.
- Los avisos son at-least-once al recuperarse desde outbox; `event_id` identifica duplicados. REST `GET /api/v1/client-events` es la reconciliación.
- La revocación remota solo funciona cuando staging tenga 019 y el bridge esté conectado.
- Sin Supabase, el modo local es temporal y no simula distribución entre procesos.
- No hay interfaz completa, despliegue ni carga real de 8 GB ejecutada.
