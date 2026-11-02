# FLOPPI 1.1.5 - Intelligent Diagnostics

The diagnostics center groups actual runtime observations into incidents. It does
not synthesize outages, inspect user request bodies, or execute repairs.

## Upgrade

1. Back up the project and keep `.env` private.
2. Confirm migrations through 010 are applied, then apply
   `database/migrations/011_intelligent_diagnostics.sql` with a Supabase admin
   connection.
3. Deploy the API as Python 3.10+ and install the existing requirements:
   `pip install -r requirements-dev.txt`.
4. Restart the API and open **Diagnóstico inteligente** in the development
   dashboard. No worker protocol update is required.

Migration 011 creates a unique fingerprint for each incident group, indexes
status/severity and component history, enables RLS, and grants table access and
RPC execution only to `service_role`. It adds no `anon` or `authenticated`
policies. Do not disable RLS or expose the service-role key. The migration is
designed to be applied after 010; the repository does not run it automatically.

## Runtime signals

- API responses with HTTP 5xx and unhandled API exceptions are recorded without
  their request body, headers, URL query, or exception message.
- The five-minute health sampler evaluates observed storage/database queries,
  worker heartbeats, queue counts, and host CPU/memory/disk measurements.
- A repeated health sample in the same five-minute UTC bucket does not increase
  a group's frequency; a new bucket does. Each distinct API error request
  increments its matching group.
- Health-derived groups close after the relevant component reports healthy.
  API error groups remain open until an operator resolves them.
- Missing telemetry is unknown or warning-level context, not proof of failure.
  Resource thresholds follow the existing system health checks (85% degraded,
  95% unhealthy).

Possible causes and recommended checks are deterministic guidance based on the
observed component and code. They are not confirmed root-cause analysis. No
restart, retry, migration, credential rotation, queue action, or other repair
is started automatically.

## Endpoints

These endpoints require a verified user with the server-managed Supabase
`app_metadata.role=admin` outside `APP_ENV=development`. The production browser
session integration is still in progress; use a trusted API client with a
verified administrator bearer token until it is complete. `user_metadata` does
not grant administrator access.

- `GET /api/v1/diagnostics/summary`
- `GET /api/v1/diagnostics/incidents?status=open&severity=critical&since=<ISO-8601>&limit=100`
- `POST /api/v1/diagnostics/incidents/{uuid}/resolve` with a `resolution_note`
- `GET /api/v1/diagnostics/export?format=json&since=<ISO-8601>&until=<ISO-8601>`
- `GET /api/v1/diagnostics/export?format=csv&since=<ISO-8601>&until=<ISO-8601>`

List and report periods are limited to 90 days; list/report results are capped
at 200 incident groups. Defaults cover the last 30 days for exports. Timestamps
must include a timezone. The system health sampler is process-lifecycle-bound,
and in-memory DEMO incident history is lost on restart. A clean system may
correctly have no incident records.

The tests exercise the in-memory fallback, grouping, five-minute idempotency,
resolution, report formats, route access, and migration security declarations.
They do not apply SQL against a live Supabase project; use a staging project to
verify the migration and RPC permissions before production deployment.
