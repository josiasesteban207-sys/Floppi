# Changelog

## 1.3.2.2 - Migration 017 Review (isolated scratch validation complete)

- Corrected the `awter` typo in migration 017 and applied it only to an authorized, disposable offline scratch database; no staging, production, Supabase, or worker credential data was changed.
- Inspected local staging read-only: `public.worker_credentials` is absent, so the current staging database has zero inspectable rows and cannot supply actual project constraints, indexes, triggers, or RLS state.
- Documented the schema contract from migration 004, worker impact, PostgreSQL 16 locking/transaction behavior, and forward-only credential recovery.
- Added an opt-in verifier that restores a staging dump into a disposable PostgreSQL container with no network, published ports, or persistent mounts; the verifier requires explicit authorization before running migration 017.
- Validation: 11 focused migration/auth tests passed; the full audit passed 17/17, including the project pytest suite; the PostgreSQL 16 scratch integration assertions passed with zero pre-existing NULL-expiry rows in the backup and synthetic fixtures. Live Supabase schema and affected-row count remain unverified.

## 1.3.2.1 - Staging Environment Preparation (local runtime verified; Supabase staging pending)

- Added a standalone local PostgreSQL Compose service with no published host ports, an internal-only Docker network, and an isolated named volume.
- Added a private staging configuration initializer, strict environment/Compose guards, local database identity checks, safe backup handling, and explicit-confirmation restore.
- Added regression tests for environment separation, production-target rejection, network/port/volume isolation, connectivity identity, secret handling, and restore boundaries.
- Documented initialization, backup/recovery, shutdown, migration 017 staging procedure, and unresolved external security checks.
- Validation: 157 tests passed, local audit 17/17; Docker runtime confirmed an internal-only network and no published ports, and a disposable staging database backup/restore recovered its data. Migration 017 was not executed. Supabase/Auth/RLS/TLS/gateway checks remain pending; this is not production approval.

## 1.3.1 - Security Core (candidate; external validation pending)

- Made `APP_ENV` mandatory and validated production Supabase/CORS settings.
- Added Supabase Auth bearer verification, server-managed admin RBAC, owner-scoped notification preferences, and admin mutation audit events.
- Added a bundled Supabase Auth browser flow using only the public anon key and tab-scoped `sessionStorage`.
- Added worker credential expiry enforcement and migration 017 to revoke legacy credentials without expiry; reissue credentials before rollout.
- Redacted worker exception details and rejected worker API URLs containing credentials, query parameters, or fragments.
- Restricted Docker Compose host binding to loopback; production still requires an HTTPS proxy/gateway and shared rate limits.
- Added security regression coverage and updated the local audit with Security Core checks.
- Validation: Python 3.10.0, 138 tests passed, local audit 16/16, npm and pip audits found no known advisories. Supabase/RLS/TLS/staging/worker-pair checks remain unverified; this is not a production release approval.

## 1.3.0 - Causal Hybrid Signal History

- Added causal per-candle hybrid classifications and multi-timeframe comparison endpoints.
- Added timestamp-deduplicated signal history with persistent Supabase storage, RLS, and service-role-only RPC access.
- Added five-bar retrospective outcome evaluation, including pending-tail maturation as additional candles arrive.
- Added historical signal charts, summary metrics, date filters, and CSV/JSON exports to the market dashboard.
- Clarified that historical agreement is descriptive and is not probability, forecast, guarantee, or financial advice.
- Added regression coverage for no-lookahead behavior, deduplication, maturation, date filters, unavailable timeframes, and migration security.
- Added migration 016; it has static validation only and was not applied to a live Supabase project.
- Preserved the educational DEMO-only boundary; no broker or real-order integration.

## 1.2.2 - Expired Job Recovery

- Added an API-lifecycle recovery worker that checks expired backtest leases every 15 seconds using bounded batches.
- Requeued orphaned jobs with capped exponential backoff; marked jobs failed after their configured attempt limit.
- Added an idempotent, row-locked Supabase recovery RPC restricted to `service_role`, without changing RLS policies.
- Added simulated disconnect/restart, max-attempt, recovery idempotency, backoff, and stale-worker completion tests.

## 1.2.1 - Capacity-aware Worker Balancer

- Added observed worker dispatch ranking from fresh CPU/RAM telemetry, active tasks, recent task latency, and heartbeat availability.
- Limited each worker to one active backtest and excluded stale, disconnected, busy, or unobserved workers from new assignments.
- Added transaction-safe Supabase worker selection and atomic worker-busy recording while preserving service-role-only access.
- Added worker idle heartbeats after completion so recovered capacity becomes visible without waiting for the normal heartbeat interval.
- Added live dispatch/capacity details to the development worker dashboard; missing telemetry is shown as unavailable, not fabricated.

## 1.2.0 - Central Task Scheduler

- Added persistent per-user schedules for repeatable historical DEMO backtests with validated existing data and fingerprints.
- Added priority ordering, per-schedule concurrency limits, configurable worker retry attempts, missed-interval skipping, and task execution history.
- Added an API-lifecycle scheduler that dispatches due tasks through a transaction-safe Supabase RPC or process-local DEMO storage.
- Added pause, resume, and safe cancellation; queued work is cancelled while already leased worker executions may finish.
- Added migration 013 with RLS enabled, service-role-only grants, due-task locking, unique schedule slots, and priority-aware worker claiming.
- Added Backtesting dashboard controls and scheduled-run history; no real financial operation or live market-data collection is enabled.

## 1.1.6 - Centralized Event Logging

- Added UTC-normalized operational events with unique IDs and request/task correlation.
- Captured sanitized API errors, observed database/storage/worker/queue/resource health events, and authenticated worker/task lifecycle events.
- Added development-only event search, severity/component/time filters, bounded pagination, and JSON/CSV exports.
- Added configurable event retention through `EVENT_LOG_RETENTION_DAYS` (default 30; allowed range 1-3650 days) with scheduled cleanup.
- Added migration 012 with RLS enabled, no anon/authenticated access, and service-role-only table/RPC privileges.
- Excluded request bodies, query strings, credentials, authorization headers, raw exception messages, and sensitive metadata.
- Integrated event history into the existing intelligent diagnostics dashboard; no financial operation or automatic repair was introduced.

## 1.1.5 - Intelligent Diagnostics

- Added persistent, fingerprint-grouped diagnostic incidents for observed API 5xx errors and real health-check signals from storage, workers, queue, and host resources.
- Deduplicated repeated health sampler runs in the same five-minute observation bucket while counting distinct API failures individually.
- Added severity, occurrence frequency, affected components, sanitized evidence, likely causes, safe recommendations, and manually recorded resolution notes.
- Automatically resolves health-derived incidents only after a healthy observation; API errors remain open until an operator reviews them.
- Added development-only incident summary/history, date and severity filters, CSV/JSON reports, and explicit manual resolution.
- Added migration 011 with RLS enabled, no anon/authenticated access, and service-role-only table/RPC privileges.
- Kept repairs manual and preserved the simulation-only/no-broker boundary.

## 1.1.4 - Historical System Statistics

- Added a FastAPI-lifecycle sampler that records idempotent system-health observations on five-minute UTC boundaries.
- Added Supabase-backed historical observations, with an in-memory DEMO fallback and a 90-day query limit.
- Added actual collection timestamps, API host CPU/RAM/disk/process observations, and overall/component health history.
- Added active/inactive/disconnected Blacki and Blanquita status counts and timelines, plus per-sample task-queue averages and maxima.
- Added 1-hour, 6-hour, 24-hour, 7-day, and 30-day dashboard filters, historical charts, and period-filtered JSON/CSV reports.
- Added migration 010 with RLS enabled, no anon/authenticated policies, and server-role-only table grants.
- Kept monitoring routes development-only until an administrator authorization model exists.
- Added validation for migration RLS/uniqueness and measured system statistics.
- Preserved the educational DEMO-only boundary; no broker or real-order integration.

## 1.0.0 - Experiment Lab & Reporting

- Promoted the API and web console release version to 1.0.0.
- Added a dashboard workflow to select 2-10 completed backtests and compare their saved metrics through the existing comparison API.
- Added downloadable JSON and CSV comparison reports with generation time, DEMO classification, and simulation-only disclaimer.
- Added responsive comparison layout and explicit handling for missing metric values.
- No database migration required; no worker protocol change.
- Kept all functionality educational and simulation-only.


## 0.7.1 - Web Console

- Added a responsive Spanish-first professional dashboard served by FastAPI.
- Added Overview, Market Analysis, Backtesting, Workers, and History views.
- Connected the UI to existing health, market, candle, indicator, hybrid-analysis, strategy, backtest, and development-only worker-list endpoints.
- Added synthetic DEMO dataset generation from the market explorer.
- Added historical close-price visualization using a lightweight local SVG chart.
- Preserved the backend API contract and worker credential flow from 0.7.0.
- Kept all workflows educational and simulation-only; no broker or real-order integration.

## 0.7.0

- Added individual worker credentials, hash storage, expiry, rotation, and revocation support.


## 0.8.0 - Distributed worker telemetry
- Added runtime metadata and busy/idle worker heartbeats.
- Added heartbeat thread so long-running backtests do not appear disconnected.
- Added derived offline status after 90 seconds and worker summary endpoint.
- Added Supabase migration 005 for telemetry columns and busy status.


## 0.9.0 - Reliable distributed jobs
- Added five-minute job leases with unique per-claim lease tokens.
- Added lease renewal while workers run long backtests.
- Added bounded retry behavior with exponential backoff and terminal failure after the attempt limit.
- Added recovery of expired worker leases and protection against stale workers completing reclaimed jobs.
- Added Supabase migration 006 with server-only RPC permissions.
- Preserved DEMO-only backtesting and the existing professional web console.

## 1.1.1 - Performance Metrics & System Health

- Added point-in-time CPU, memory, disk, and API-process memory observations for the API host.
- Added worker resource telemetry to authenticated heartbeats; metrics are validated and stored with collection timestamps.
- Added development-only performance and system-health report endpoints.
- Added dashboard view for API resources, per-worker metrics, component health, and JSON/CSV health exports.
- Added Supabase migration 007 for worker resource metric snapshots; existing server-managed access model is preserved.
- Metrics are snapshots, not historical trends, synthetic values, or hardware benchmarks.
- Kept FLOPPI educational and DEMO-only.
