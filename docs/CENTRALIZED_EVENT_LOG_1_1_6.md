# FLOPPI 1.1.6 - Centralized Event Logging

The event log consolidates selected operational observations from the API,
system health sampler, authenticated workers, and backtest tasks. It is not a
general-purpose request-body logger.

## Upgrade

1. Back up the project and keep `.env` private.
2. Confirm migrations through 011 are applied, then apply
   `database/migrations/012_centralized_event_log.sql` with a Supabase admin
   connection.
3. Configure `EVENT_LOG_RETENTION_DAYS` if needed (default `30`, accepted
   range 1-3650).
4. Deploy the API and worker from 1.1.6. Older workers still process tasks but
   do not submit worker lifecycle events.

Migration 012 creates `system_events`, indexes time/component/severity and
correlation IDs, enables RLS, and grants table access only to `service_role`.
There are no `anon`/`authenticated` policies. A `SECURITY DEFINER` retention
RPC uses a fixed search path and is executable only by `service_role`. Apply
the migration before deploying if Supabase persistence is configured.

## Captured events and privacy

- API responses with 4xx/5xx status and unhandled API exceptions.
- Non-healthy component statuses and observed failed task counts from the
  five-minute health sampler.
- Authenticated worker heartbeat/lease failures, worker task start/completion/
  failure, API connectivity failures, protocol errors, and shutdown.
- Events receive unique IDs and UTC timestamps. API errors have a generated
  `request_id`; worker task events include `task_id`.
- HTTP request bodies, URL query strings, cookies, authorization headers,
  credentials, raw exception messages, and worker tokens are not collected.
  Worker ingestion accepts a fixed event-code allowlist and generates the
  message server-side. Sensitive metadata keys are omitted and sensitive
  values are redacted.
- The worker reports event delivery failure locally without retrying the event
  or storing the event-delivery error as another event.

Retention cleanup runs at API startup and every 24 hours. If Supabase is
unavailable, cleanup failures are logged and surfaced in the application log;
it does not disable RLS or delete anything else. In-memory DEMO events are
pruned on writes and are lost at process restart.

## API

Outside `APP_ENV=development`, event history and exports require a verified user
with server-managed Supabase `app_metadata.role=admin`. Worker ingestion is
separate: it requires the node's `X-Node-Token` and `X-Node-Id`. Production
browser session integration is in progress; use a trusted API client until it
is complete.

- `GET /api/v1/events`: filters `component`, `level`, timezone-aware `since`
  and `until`, `search`, `request_id`, `task_id`, `page`, and `page_size`.
- `GET /api/v1/events/export?format=json|csv`: date, component, level, and
  search filters; defaults to the last 30 days.
- `POST /api/v1/events/worker`: authenticated worker event from the allowed
  event-code set; does not accept a client-supplied message or metadata.
- API responses include a generated `X-Request-ID` header; CORS exposes this
  header to browser clients.

History/export windows are limited to 90 days. Page size is capped at 200;
exports are capped at 5,000 records and JSON reports mark truncation. Search is
case-insensitive across component/code/message and accepts letters, numbers,
spaces, dots, underscores, and hyphens. The dashboard shares the time period
selector with diagnostic incident history.

The automated tests use the in-memory fallback and static migration checks.
They do not apply migration 012 to a live Supabase project or prove remote RPC
permissions; validate those externally after applying the SQL migration.
