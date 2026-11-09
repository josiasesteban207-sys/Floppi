# FLOPPI Core 1.5 — Eventos distribuidos

## Diseño

- Canal fijo privado: `floppi-core-events`, evento `user-event`.
- Cada proceso API con configuración Supabase mantiene una conexión realtime asíncrona como suscriptor de confianza.
- Publicación usa el Broadcast REST de Supabase con credencial server-side y `private=true`.
- Sobre persistido lleva `event_id`, `user_id`, `type`, `occurred_at`, `data`. El receiver valida UUIDs, tipo y forma antes de fan-out local y elimina `user_id` antes de enviarlo al cliente.
- La publicación inserta `client_events` primero. Si la DB falla, no se transmite el mensaje global. Si Realtime falla, se marca intento y se mantiene pendiente; el bridge reintenta acotadamente y REST permite catch-up.
- `event_id` sirve para deduplicación; clientes deben tolerar duplicados y reconectar consultando `/api/v1/client-events?cursor=<opaque>&limit=100`.

## Coste y fiabilidad

No se agrega Redis ni listener PostgreSQL, evitando servicio adicional y conexión SQL por proceso. El outbox reside en PostgreSQL y Broadcast se usa solo para latencia baja. Límites de plan Realtime/consumo deben verificarse con el propietario del proyecto antes de producción. La suscripción interna recibe todos los eventos de backend; mantener el payload pequeño y jamás incluir tokens.

La entrega de Broadcast no es durable. Outbox + consulta REST recuperan eventos guardados; si un usuario permanece desconectado más allá de retención, se conserva el estado actual por recursos REST, pero no necesariamente cada notificación histórica. Fuentes primarias: [Supabase Broadcast](https://supabase.com/docs/guides/realtime/broadcast), [Realtime limits](https://supabase.com/docs/guides/realtime/limits), [PostgreSQL NOTIFY](https://www.postgresql.org/docs/current/sql-notify.html).

## Recuperación

El subscriber reconecta con backoff exponencial limitado; vuelve a emitir eventos pendientes (posibles duplicados) y detecta pérdida de conexión. Se cierra al apagar FastAPI. Un error de bridge no derriba REST/WebSocket local; queda registrado sin secretos. No se validó aún un segundo proceso remoto real.
