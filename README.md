# FLOPPI 1.3.2.2

FLOPPI is an educational historical-market analysis and paper-backtesting
platform. The synthetic provider is always labeled `DEMO`; this project does
not place real orders, connect to brokers, or manage funds.

## What is implemented

- Experiment comparison in the web console for 2-10 completed backtests, using the existing authenticated comparison endpoint.
- Export of comparison results as JSON or CSV, including a DEMO label and historical-simulation disclaimer.
- Point-in-time API host and worker CPU/RAM/disk observations, system health snapshots, and JSON/CSV health reports.
- Persistent five-minute system-health observations, historical state distributions, Blacki/Blanquita observed availability, queue averages/maxima, period filters, and CSV/JSON exports.
- Intelligent incident diagnostics from observed API failures and health signals, with safe recommendations, history, reports, and manual resolution.
- Centralized, searchable event history for API, system health, workers, and backtest tasks, with correlation IDs and configurable retention.
- Persistent periodic DEMO backtests with priority, per-task concurrency/retry limits, safe cancellation, and execution history.
- Capacity-aware worker assignment from fresh CPU/RAM, active task, observed task-latency, and heartbeat data, with one active job per worker.
- Automatic bounded recovery of expired backtest leases with capped exponential retry backoff and terminal failure at the attempt limit.
- Point-in-time hybrid signals per candle, with timestamp deduplication and five-bar retrospective outcomes that mature as new observations arrive.
- Historical signal summaries and timeframe comparisons with explicit DEMO labels, bounded date filters, and CSV/JSON exports.
- Security Core candidate: explicit environment selection, Supabase Auth/RBAC, browser session, worker credential expiry, and loopback-only Compose binding. External security validation remains required.

- Supabase PostgreSQL migrations for nodes, multimarket assets/candles, data
  quality, strategies, backtest jobs, trades, and metrics, including a provider-scoped candle index.
- OHLCV validation and deterministic, timestamp-stable synthetic demo data.
- SMA, EMA, RSI, MACD, Bollinger Bands, ATR, and cumulative VWAP with explicit
  rejection of NaN and infinite inputs.
- Explainable hybrid engine that groups SMA/EMA as trend, MACD/RSI as momentum,
  and price/VWAP as price-volume confirmation; reports internal and cross-family
  disagreement, evidence coverage, volatility context, and abstains when evidence is thin.
- SMA-cross, RSI, and MACD long-only example strategies.
- A persistent Supabase job queue claimed by the local worker; the API does not
  execute backtests in the cloud.
- Virtual portfolio accounting, fees, slippage, drawdown, return, trade,
  profit-factor, and Sharpe metrics.
- Supabase Auth access-token validation and per-user filtering for strategy and backtest API
  operations. Public market-history reads contain no user data.


## Web dashboard (1.3.2.2)

FLOPPI now serves a responsive web console from the FastAPI application. Start the API using the command above, then open `http://127.0.0.1:8000/`. The dashboard includes:

- Overview of API/storage health, catalog assets, candle counts, worker status, and recent backtests.
- Market explorer with synthetic DEMO dataset generation, historical close-price chart, hybrid evidence summary, indicator readings, multi-timeframe comparison, and signal history.
- Backtest queue form using the existing strategy and worker queue endpoints.
- Task scheduler for recurring historical simulations, with pause/resume/cancel controls, priority and retry limits, plus run history.
- Worker status view (administrators in production; development-only anonymous access) and credential setup guidance.
- Capacity-aware worker assignment status, load scores, recent task latency, and available job slots.
- Performance and health view with host resources, per-worker resource snapshots, component health, and report exports.
- Historical health statistics by 1-hour, 6-hour, 24-hour, 7-day, or 30-day periods, including state distributions, worker availability, resource charts, and queue observations.
- Intelligent diagnostics view with observed incidents, severity and status filters, occurrence history, recommendations, safe CSV/JSON exports, and manual resolution.
- Central event history with date/level/component filters, search, pagination, request/task correlation, and CSV/JSON export.
- Backtest history and links to the API documentation.

The web console uses the existing API and does not expose worker credentials or the Supabase service-role key. The dashboard is served from the same origin as the API. Production access to operational monitoring, events, diagnostics, and worker status requires a verified Supabase user whose server-managed `app_metadata.role` is `admin`. The bundled Supabase Auth flow uses only the public anon key and keeps the browser session in `sessionStorage`; the API independently verifies bearer tokens and admin roles.

## Hybrid signal history (1.3.0)

The market explorer can compare one to four available timeframes and display
persisted hybrid classifications by candle close. A historical signal is
classified using only its own candle prefix; its retrospective outcome is
evaluated against the close five bars later. Pending tail outcomes are
completed idempotently when a later collection supplies the missing bars.
The displayed agreement percentage is a descriptive historical ratio among
completed, non-flat observations. It is not a probability, forecast, guarantee,
or trading recommendation.

For Supabase deployments, apply migration 016 only after confirming migrations
001-015 are present. It enables RLS, keeps client roles revoked, and grants the
history table/RPC only to `service_role`; no RLS policy is disabled or added.
The signal-history API uses the configured server-side Supabase client.
`memory-demo` is process-local and is lost when the API restarts. The migration
was not applied to a live Supabase project as part of this release.

### Upgrade from 1.2.2

1. Back up the project and keep `.env` private.
2. Confirm migrations through 015 are applied; apply
   `database/migrations/016_hybrid_signal_history.sql` using a Supabase admin
   connection.
3. Update and restart the 1.3.0 API and local workers.
4. Generate observations from the market explorer or
   `POST /api/v1/analysis/signals/history`; query them with
   `GET /api/v1/analysis/signals/history`. Multi-timeframe summaries are
   available at `GET /api/v1/analysis/multi-timeframe`.

## Expired job recovery (1.2.2)

The API starts a recovery loop that checks expired backtest leases every 15 seconds in batches of at most 100. An expired task below its attempt limit returns to `pending` with a 5-second exponential backoff capped at 5 minutes; a task at its attempt limit becomes `failed`. The recovery operation clears the expired worker/token so an old worker cannot complete a recovered job. The existing lease-token checks remain authoritative, and a duplicate completion is rejected.

For Supabase deployments, apply migration 015 after 014. Its recovery RPC uses `FOR UPDATE SKIP LOCKED`, is idempotent for already-recovered rows, and is executable only by `service_role`. RLS remains enabled and no client policies are added. The API must stay running for periodic cleanup; a newly available worker can also claim an expired job through the existing atomic queue claim path. Worker/API restarts recover only durable Supabase jobs; `memory-demo` loses all queued jobs on process restart.

### Upgrade from 1.2.1

1. Back up the project and keep `.env` private.
2. Confirm migrations through 014 are applied; apply `database/migrations/015_expired_job_recovery.sql` using a Supabase admin connection.
3. Update and restart the 1.2.2 API and workers.
4. Confirm expired tasks re-enter the queue or reach terminal failure in the development queue history.

See [docs/WORKER_RECOVERY_1_2_2.md](docs/WORKER_RECOVERY_1_2_2.md) for recovery scenarios and operational limits.

## Worker load balancer (1.2.1)

The worker endpoint assigns queued work to the available node with the lowest observed load. Eligibility requires a worker heartbeat and resource observation no older than 90 seconds, an idle/online status, no active job, and an available single-job slot. Ranking uses observed CPU and RAM percentages, active leases, the average duration of up to 20 recent completed tasks, then heartbeat recency and node ID for deterministic ties. Workers without fresh CPU/RAM data are not assigned new jobs. Task durations and resource readings are observations, not performance guarantees.

The worker dashboard (admin-only outside explicit development) shows the chosen node, eligibility, observed load score, task-latency sample count, and active/maximum job slots. The worker publishes an idle heartbeat immediately after finishing a job so a recovered slot can be reused. A stale/disconnected node is excluded; its leased job remains subject to existing lease expiry and retry handling.

For Supabase deployments, apply migration 014 after 013. Its claim RPC serializes worker selection, atomically claims the queue row, and marks the chosen node busy. RLS policies are not disabled or expanded; the worker telemetry remains server-managed and the RPC remains `service_role`-only. In memory DEMO mode, worker telemetry and dispatch state are process-local. Monitoring and worker-list routes require admin authorization outside explicit development.

### Upgrade from 1.2.0

1. Back up the project and keep `.env` private.
2. Confirm migrations through 013 are applied; apply `database/migrations/014_worker_load_balancer.sql` with a Supabase admin connection.
3. Update and restart the API and local workers to 1.2.1.
4. Ensure each worker sends authenticated heartbeats with fresh host-resource metrics before expecting it to receive queued work.

See [docs/WORKER_LOAD_BALANCER_1_2_1.md](docs/WORKER_LOAD_BALANCER_1_2_1.md) for operational details and limitations.

## Task scheduler (1.2.0)

Apply migration 013 after 012, then deploy the 1.2.0 API and workers. A schedule captures a bounded historical DEMO dataset and its fingerprint when created; every queued execution is checked against that fingerprint by the worker. Schedules use intervals from 1 minute to 30 days, priority 1-10, per-schedule concurrency 1-4, and 1-10 worker attempts. The API process dispatches due schedules every 10 seconds. Missed intervals are skipped rather than replayed in a burst.

The development dashboard can create, pause, resume, and cancel a schedule. Cancellation disables future executions and cancels queued executions; a worker run that already holds an active lease is allowed to finish. Run records and scheduled tasks retain normal per-user ownership; migration 013 leaves RLS enabled and grants the server service role access without client policies. In memory DEMO mode schedule history is process-local and lost at restart. Run the API continuously for scheduled dispatch; stopping the API stops its scheduler.

Endpoints: `POST /api/v1/scheduler/tasks`, `GET /api/v1/scheduler/tasks`, `GET /api/v1/scheduler/runs`, `GET /api/v1/scheduler/tasks/{task_id}/runs`, and task-specific `pause`, `resume`, and `cancel` POST actions. Schedules only enqueue existing historical backtests. They do not collect fresh market data or execute financial orders.

### Upgrade from 1.1.6

1. Back up the project and keep `.env` private.
2. Confirm migrations through 012 are applied; apply `database/migrations/013_task_scheduler.sql` using a Supabase admin connection.
3. Update and restart the API and local workers to 1.2.0.
4. Open **Backtesting → Planificador DEMO** and create a schedule using a date range with existing candles.

See [docs/TASK_SCHEDULER_1_2_0.md](docs/TASK_SCHEDULER_1_2_0.md) for API details and operational limits.

## Centralized event logging (1.1.6)

Apply migration 012 after 011, then update the API and workers to 1.1.6. API error responses, health samples, and authenticated worker/task lifecycle events are stored with unique event IDs and UTC timestamps. API responses include an `X-Request-ID` header; worker task events carry the associated `task_id`.

Outside explicit development, `GET /api/v1/events` and `GET /api/v1/events/export?format=json|csv` require a verified administrator; worker ingestion at `POST /api/v1/events/worker` uses the worker's own token. The history endpoint supports `component`, `level`, `since`, `until`, `search`, `request_id`, `task_id`, `page`, and `page_size` filters. Search is restricted to alphanumeric characters, spaces, dots, underscores, and hyphens. Queries and reports are limited to 90 days; pages contain at most 200 rows and exports at most 5,000 (the JSON report indicates truncation).

Retention is controlled by `EVENT_LOG_RETENTION_DAYS` (default 30, minimum 1, maximum 3650). The API runs scheduled pruning through a service-role RPC. Without Supabase, in-memory events are pruned on writes and are lost when the process restarts. RLS stays enabled with no client-facing policies. Event messages are code-generated; request bodies, query strings, authorization data, tokens, private keys, and raw exception messages are not collected. Workers from 1.1.6 onward submit authenticated worker/task events; older workers remain compatible but do not submit them.

### Upgrade from 1.1.5

1. Back up the project and keep `.env` private.
2. Confirm migrations through 011 are applied; apply `database/migrations/012_centralized_event_log.sql` using a Supabase admin connection.
3. Set `EVENT_LOG_RETENTION_DAYS` if the 30-day default is not suitable.
4. Update and restart the API and workers. Update worker node credentials only through the existing provisioning process; the worker event endpoint reuses its authenticated node credential.
5. Open **Diagnóstico inteligente** to query, filter, search, paginate, and export observed event history.

## Intelligent diagnostics (1.1.5)

Apply migration 011 after migration 010, then update the API to 1.1.5. The API groups observed health incidents by component/code, stores API 5xx failures, records occurrence counts, and only automatically resolves health-derived incidents after a healthy observation. API failure incidents require operator review. Recommendations are informational and never trigger repair actions. Outside explicit development, diagnostic endpoints require a verified Supabase administrator.

Incident history uses Supabase persistence when configured and process-local DEMO memory otherwise; DEMO incident history is lost on restart. Reports are limited to 90 days and at most 200 matching incident groups. API incidents intentionally omit request bodies, headers, and exception messages to avoid recording secrets or user data. No live Supabase migration execution was performed by the local test suite.

### Upgrade from 1.1.4

1. Back up the project and keep `.env` private.
2. Confirm migrations through 010 are applied; apply `database/migrations/011_intelligent_diagnostics.sql` using a Supabase admin connection.
3. Update the API to 1.1.5 and restart it. No worker protocol change is required.
4. Open **Diagnóstico inteligente** in the development dashboard. Incidents appear when actual observations or API failures are collected; a clean system can correctly show no incidents.
5. To return to an earlier release, first back up and retain the incident table. The prior application does not use this table; no destructive rollback is required.

## FLOPPI Security Core 1.3.1 candidate

This checkout contains the 1.3.1 hardening candidate, 1.3.2.1 local staging
preparation, and the 1.3.2.2 migration 017 review candidate. None is approved
for production until Supabase/RLS, TLS, gateway limits, and worker integration
are verified in isolated staging.

## Local staging preparation (1.3.2.1)

The optional `docker-compose.staging.yml` defines an isolated local PostgreSQL
16 service only; it does not start the FLOPPI API or apply migrations. It
publishes no host ports, uses an internal Docker network and a dedicated named
volume. Database checks and backup operations run through `docker compose exec`
inside the container. It accepts no Supabase/production URL or application
connection settings. Initialize and verify it with:

```powershell
python tools\staging_environment.py init
python tools\staging_environment.py validate
python tools\staging_environment.py start
python tools\staging_environment.py check
python tools\staging_environment.py backup
python tools\staging_environment.py stop
```

`init` creates an ignored `.env.staging` with a unique random local password
without displaying it. The backup command writes ignored dumps under
`backups/staging/`; restore requires an explicit
`--confirm-staging-restore` flag and a backup from that directory. The local
PostgreSQL container has no host-published port. If upgrading an existing
staging config from the earlier loopback-port setup, run
`python tools\staging_environment.py migrate-config` to remove the obsolete
host/port settings without changing its password.
The local PostgreSQL container is not a Supabase replacement: its internal
network/no-port isolation and scratch backup/restore were verified locally.
Migration 017 passed in a disposable offline PostgreSQL scratch using
synthetic credentials because the available staging backup contains no
`worker_credentials` table. The live Supabase schema and real affected-row
count remain unverified. See
[docs/STAGING_ENVIRONMENT_1_3_2_1.md](./docs/STAGING_ENVIRONMENT_1_3_2_1.md)
for initialization, recovery, migration, and pending security checks.

## Migration 017 review (1.3.2.2 candidate)

The migration typo is corrected and the PostgreSQL 16 offline scratch test
passed. The current local staging database and its backup do not contain
`public.worker_credentials`; the test therefore used migration 004 and
synthetic fixtures and cannot establish the real Supabase schema or affected
credential count. Review details and rollback guidance are in
[docs/MIGRATION_017_REVIEW_1_3_2_2.md](./docs/MIGRATION_017_REVIEW_1_3_2_2.md).
The verifier requires `--authorize-scratch-migration-017` and restores only a
local staging backup into a disposable container with no network, host ports,
or persistent mounts. Do not apply migration 017 to shared Supabase staging or
production based on this scratch result; first verify the actual schema,
affected rows, worker impact, and obtain separate authorization.

For an existing Supabase installation:

1. Do not use the local scratch result as authorization to change Supabase.
   For a separately approved isolated Supabase staging operation, inspect the
   actual schema, RLS/grants, migration state, affected rows, and active worker
   credentials before proceeding.
2. After that separate approval, back up the target and apply available
   migrations in order, including
   `database/migrations/017_worker_credential_expiry.sql` after 016. Do not
   invent migrations 008 or 009.
3. Migration 017 deactivates every worker credential with no expiry, marks it
   revoked, and makes `expires_at` required. Provision a replacement 90-day
   credential for each affected worker, update its secret environment, and
   restart it. Rollback must not reactivate old credentials; issue new tokens
   instead.
4. Configure production Supabase values and exact HTTPS CORS origins, build
   the web bundle with `npm ci` and `npm run build`, then deploy behind an
   HTTPS proxy with the API port private.
5. Run the tests and audit below. Do not treat local pass results as evidence
   of live Supabase, TLS, or RLS behavior.

## Set up Supabase

1. Copy `.env.example` to `.env`.
2. Set `APP_ENV` explicitly to `development` for an isolated local DEMO or
   `production` for a deployment. An empty or unknown value prevents startup.
3. Set `SUPABASE_URL`, the public `SUPABASE_ANON_KEY`, and the server-side
   `SUPABASE_SERVICE_ROLE_KEY`. The anon key is delivered to the browser only
   for Supabase Auth; it is not a secret and must still be constrained by RLS.
   Never place the service-role key in a client app or commit it.
4. In the Supabase SQL Editor, apply migrations in order:
   [001_initial.sql](./database/migrations/001_initial.sql),
   [002_multimarket_backtesting.sql](./database/migrations/002_multimarket_backtesting.sql),
   [003_provider_scoped_candle_index.sql](./database/migrations/003_provider_scoped_candle_index.sql),
   [004_worker_credentials.sql](./database/migrations/004_worker_credentials.sql),
   [005_distributed_worker_telemetry.sql](./database/migrations/005_distributed_worker_telemetry.sql),
   [006_reliable_job_leases.sql](./database/migrations/006_reliable_job_leases.sql),
   [007_worker_resource_metrics.sql](./database/migrations/007_worker_resource_metrics.sql),
   [010_system_health_history.sql](./database/migrations/010_system_health_history.sql),
   [011_intelligent_diagnostics.sql](./database/migrations/011_intelligent_diagnostics.sql),
   [012_centralized_event_log.sql](./database/migrations/012_centralized_event_log.sql),
   [013_task_scheduler.sql](./database/migrations/013_task_scheduler.sql),
   [014_worker_load_balancer.sql](./database/migrations/014_worker_load_balancer.sql),
   [015_expired_job_recovery.sql](./database/migrations/015_expired_job_recovery.sql),
   [016_hybrid_signal_history.sql](./database/migrations/016_hybrid_signal_history.sql),
   and [017_worker_credential_expiry.sql](./database/migrations/017_worker_credential_expiry.sql).
   Existing installations should apply the missing migrations in numeric order.
   This checkout does not contain migrations 008 or 009; do not invent or
   apply placeholder migrations for them.
5. Create an individual credential for each worker. Generate a one-time token and SQL hash with:

   ```powershell
   python tools\provision_worker.py --node-id main-pc --expires-in-days 90
   ```

   Copy the generated SQL into the Supabase SQL Editor. The raw token is shown
   only once; the database stores its SHA-256 hash, never the token itself.
6. In Supabase project authentication, create normal user accounts for API
   clients. Send each user's Supabase access token as a `Bearer` token for
   strategy, data-collection, and backtest operations. Grant operational
   administrator access only by setting `app_metadata.role` to `admin` through
   a trusted server-side Supabase administrative channel; never use
   `user_metadata` or a client-supplied role.
7. Migration 017 disables and marks as revoked any worker credential that has
   no expiry, then makes `expires_at` required. After applying it, provision a
   new expiring credential for each affected worker and update its secret
   environment before restarting that worker.

The API uses the service-role key server-side and therefore explicitly verifies
user access tokens and filters user-owned rows. `SUPABASE_ANON_KEY` is a public
key used by the bundled browser Auth SDK; it is not a substitute for RLS or API
authorization. Each worker uses a distinct random credential; only its
SHA-256 hash is stored in `worker_credentials`. Production startup requires the
Supabase URL, public anon key, service-role key, and exact HTTPS CORS origins.
The browser session uses tab-scoped `sessionStorage`; operational APIs remain
server-authorized and never trust the browser's role display.

## Install and run (PowerShell)

From the project directory:

Copy `.env.example` to `.env`, then set `APP_ENV=development` before starting
the local demo. The sample intentionally leaves this value blank so the
application cannot silently start in development mode.

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
Set-Location web
npm ci
npm run build
Set-Location ..
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

The web build generates the bundled Supabase Auth SDK at
`backend/app/static/auth.bundle.js`; run it after changing `web/src/auth.js` or
the web dependencies. Docker Compose binds the API to loopback by default.
Production deployments still require an HTTPS reverse proxy/gateway and a
private upstream; do not expose Uvicorn's HTTP port directly to the internet.

Open `http://127.0.0.1:8000/docs`. `/api/v1/health` reports storage status. Operational `/api/v1/monitoring/health`, `/api/v1/monitoring/performance`, and `/api/v1/monitoring/statistics` endpoints require an admin bearer token outside development and feed the Rendimiento y salud page. Historical exports are available from `/api/v1/monitoring/statistics/export?format=json` or `?format=csv`; both accept optional timezone-aware `start_at` and `end_at` filters, up to 90 days.
Without Supabase credentials the app uses process-local demo storage in
development; data, queued work, and monitoring history are lost when that process stops. The sampler records one observation every five minutes and aligns samples to UTC five-minute boundaries. Multiple API instances use the same unique time bucket to avoid duplicate observations.

## Run the local worker

In another PowerShell terminal, set the node-specific token generated for this
worker. Never reuse another node's token:

```powershell
$env:FLOPPI_API_URL = "http://127.0.0.1:8000"
$env:FLOPPI_NODE_ID = "main-pc"
$env:FLOPPI_NODE_TOKEN = "<one-time token generated for main-pc>"
python worker\local_worker.py
```

The worker sends an outbound heartbeat, polls for one queued backtest, computes
it locally, and posts the result. For remote deployments set
`FLOPPI_API_URL` to the HTTPS API URL; no inbound port forwarding is required.
Abandoned jobs are eligible for reassignment after one hour.

## API workflow

- `GET /api/v1/markets`, `/assets`, `/candles`,
  `/providers/status`, `/data/quality`
- `POST /api/v1/data/collect` creates historical **DEMO** candles. The seeded
  sample asset IDs are available from `GET /api/v1/assets`.
- `GET /api/v1/analysis/indicators`, `/analysis/technical`,
  `/analysis/history`, `/analysis/hybrid`
- `GET/POST/PUT /api/v1/strategies`
- `POST /api/v1/backtesting/run` returns `202` and queues a local job;
  `GET /api/v1/backtesting/runs` and run subroutes retrieve status, trades,
  metrics, and comparisons.

Production strategy and backtest APIs require Supabase-authenticated access
tokens. Worker-only queue routes require `X-Node-Token` and `X-Node-Id`; the token must be active, unexpired, and registered to that exact node.
Backtests are limited to 5,000 candles and each account may have at most five pending runs. Jobs store a
fingerprint of their candles; a run fails rather than silently using candle
data changed after it was queued.

## Indicators and methodology

- SMA uses a rolling arithmetic mean; EMA seeds from an SMA and then uses
  `alpha = 2 / (period + 1)`.
- RSI uses Wilder smoothing; MACD uses EMA 12/26 with EMA 9 signal.
- Bollinger Bands use a rolling mean and population standard deviation;
  ATR uses Wilder smoothing of true range.
- VWAP is cumulative over the requested candle series; it does not infer
  session boundaries.
- The hybrid agreement score is a raw percentage of directional method-family
  votes. SMA/EMA count as one family; MACD/RSI count as one family. Price/VWAP
  provides a third family. ATR is context only. The score is not a probability,
  calibrated confidence estimate, or forecast. Internal family disagreement
  removes that family from directional voting; fewer than two directional families
  or an even split produces an abstention.
- Candle reads and in-memory keys are scoped by asset, provider, and timeframe.
  The default API history remains the seeded DEMO provider.
- Signals use data through a candle's close and are filled at the next candle
  open. The final open position is liquidated at the last close.
- Sharpe annualization is approximate and market/timeframe dependent; profit
  factor is undefined when there are no losing trades. Small samples and data
  gaps are explicitly reported.

These are historical descriptions and simulations, not predictions or
personalized financial recommendations.

## Tests

```powershell
python -m pytest
```

The tests cover API/auth boundaries, normalization, deterministic demo data,
indicator formulas, worker queue transitions, fees, next-bar execution,
historical system statistics, diagnostic incidents, and centralized event
logging, task scheduling, and safe queue cancellation. Migration checks are
static; an actual Supabase deployment/worker connection still requires project
credentials and the migrations above. No live credentials are included here.

## Security and scope

The Supabase service-role key bypasses RLS and must remain server-only. Direct
client access is limited by the migration's RLS policies. Node listings and
operational telemetry require an administrator outside explicit development;
notification preferences are process-local in development and persist to
Supabase for the authenticated owner in production.
Before a public launch, add rate limiting, operational monitoring, backup and
restore drills, and automated credential-expiry monitoring. Revoke a worker by
setting its `active` flag to false and `revoked_at` to `now()` in Supabase; rotate
by provisioning a new token and then revoking the old credential.

There is no Telegram, Flutter client, external price provider, adaptive AI, or
real-money/broker functionality in this backend milestone.

## Repeatable project audit

FLOPPI includes a non-destructive local audit runner. From the project root:

```powershell
python tools/audit.py
```

It compiles the backend/worker, runs pytest, probes indicator handling of non-finite values, checks selected data-quality/security signals, and writes Markdown/JSON reports under `reports/`. Timestamped snapshots are retained in `reports/history/` for comparison across runs. See [docs/AUDIT_ENGINE.md](docs/AUDIT_ENGINE.md) for scope, limitations, and manual production gates.


## Walk-forward evaluation (0.6.0)

See `docs/WALK_FORWARD_0_6.md` for the chronological out-of-sample evaluation endpoint `POST /api/v1/backtesting/walk-forward`, its window constraints, and methodological limitations. Strategy parameters remain fixed in this release; no automatic parameter optimization is performed.

## Worker credentials (0.7.0)

See [docs/WORKER_SECURITY_0_7.md](docs/WORKER_SECURITY_0_7.md) for provisioning, rotation, revocation, and the development-only fallback.


## Distributed worker telemetry (0.8.0)

See [docs/DISTRIBUTED_WORKERS_0_8.md](docs/DISTRIBUTED_WORKERS_0_8.md). Workers report runtime metadata and busy/idle state through periodic heartbeats, including during long backtests. The development dashboard derives `offline` after 90 seconds without a heartbeat and exposes `/api/v1/nodes/summary`. Apply migration 005 after migrations 001-004. This is telemetry and task coordination for historical DEMO backtests, not live trading.


## Reliable distributed jobs (0.9.0)

Migration 006 adds bounded job attempts, five-minute worker leases, unique lease tokens, retry backoff, and lease-aware completion/failure RPCs. Workers renew their lease every 30 seconds while a backtest is running. A worker can complete, renew, or fail only a job carrying its current lease token. Retryable worker errors are requeued with a short exponential delay and stop after the configured attempt limit (default: three). Data-integrity failures are terminal and are not retried.

Apply migration 006 after 005 before deploying this release. The automated suite exercises in-memory lease ownership and retry behavior; it does not substitute for testing the SQL functions against your own Supabase project. Keep RLS enabled and never expose the service-role key or node tokens to the browser.


## Experiment Lab & Reporting (1.0.0)

Open **Historial e informes** in the web console. Select between two and ten completed backtests, choose **Comparar resultados**, and export the comparison as JSON or CSV. The comparison uses metrics already persisted by the backtesting workflow; it does not optimize strategies, forecast future returns, or create investment recommendations. Missing or undefined metrics are displayed as unavailable rather than converted to zero.

This release requires no new Supabase migration and does not change the worker protocol. Existing migrations through 006 remain the deployment baseline.


## Performance metrics and system health (1.1.1)

Apply migration 007 after migrations 001-006, then update the API and workers to 1.1.1. Workers include CPU, RAM, disk, and worker-process memory observations in their authenticated heartbeat. The API exposes its own host/process snapshot and a component health report. These are point-in-time observations, not benchmark scores or historical trends. Missing metrics remain unavailable. See [docs/PERFORMANCE_AND_HEALTH_1_1_1.md](docs/PERFORMANCE_AND_HEALTH_1_1_1.md) for upgrade steps, endpoint details, interpretation, and limitations.

## Historical system statistics (1.1.4)

Apply migration 010 after all migrations present in this checkout (001-007), then update the API and workers to 1.1.4. The API records health, API host resources, component, worker, and task-queue observations every five minutes. The dashboard compares state distributions and Blacki/Blanquita active, inactive, and disconnected observations over 1-hour, 6-hour, 24-hour, 7-day, or 30-day windows. Resource charts, worker history, and CSV/JSON reports use persisted observations only. Queue values are averages and maxima per sample, not counts of unique tasks. Statistics endpoints require verified administrator access outside explicit development.

RLS remains enabled on `system_health_observations`, with no client-facing policies; only the backend service role receives table privileges. In-memory DEMO mode is not persistent and its history is lost on restart. The sampler is process-lifecycle-bound; it stops when the API stops. Observed availability is not continuous uptime or an SLA.

### Upgrade from 1.1.1

1. Back up the project and keep `.env` private.
2. Activate a Python 3.10 environment and install `pip install -r requirements-dev.txt`.
3. Apply `database/migrations/010_system_health_history.sql` using a Supabase admin connection after migrations 001-007.
4. Update the API and workers to 1.1.4, then restart them.
5. Open **Rendimiento y salud**, choose a period, and allow the sampler to collect observations. The first sample is recorded at startup; later samples align to five-minute UTC boundaries.
6. Export a JSON or CSV summary from the same panel.

The repository versions itself as 1.1.1 before this requested 1.1.4 milestone. Migrations 008 and 009 are not present in the checkout; migration 010 is designed to apply after 007 and does not depend on either missing file.
# Floppi
