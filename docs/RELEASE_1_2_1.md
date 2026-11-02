# FLOPPI 1.2.1 Release Report

## Release summary

- Previous version: 1.2.0
- New version: 1.2.1
- Scope: load-aware worker assignment for historical DEMO backtests.

## Implemented

- Ranks eligible workers from observed CPU/RAM, recent completed-task runtime,
  active leases, and heartbeat availability.
- Uses the 20 most recent valid completed task durations; unavailable latency
  history stays explicitly null.
- Requires fresh resource telemetry and a heartbeat within 90 seconds; excludes
  busy, stale, disconnected, and unobserved nodes from new Supabase claims.
- Limits each worker to one active run, atomically locks/claims the selected
  queue item, and marks the selected Supabase worker busy.
- Sends an immediate idle heartbeat after completion so recovered worker
  capacity can receive work without waiting for the normal heartbeat interval.
- Exposes dispatch eligibility, assignment, score, latency samples, and slot
  counts in the development worker API/dashboard.
- Preserves service-role-only RPC access, existing RLS, lease recovery, and
  educational simulation-only behavior.

## Files created

- `backend/app/worker_balancer.py`
- `backend/tests/test_worker_balancer.py`
- `database/migrations/014_worker_load_balancer.sql`
- `docs/WORKER_LOAD_BALANCER_1_2_1.md`
- `docs/RELEASE_1_2_1.md`

## Files modified

- Worker claim route, node telemetry API, backtest repository, and local worker.
- API/OpenAPI and dashboard version labels and dispatch/load details.
- Worker, API, health, diagnostics, and event report release metadata.
- Backtesting/API tests, project audit, `README.md`, `CHANGELOG.md`, and `VERSION`.

## Database migration

Migration 014 adds indexes for worker runtime history and replaces
`claim_backtest_run` with a capacity-aware, row-locked claim flow. It leaves RLS
enabled, adds no client-facing policies, and grants the RPC only to
`service_role`.

The migration received static checks and test coverage; it was **not applied to
or verified against a live Supabase project**. Apply it only after confirming
migrations through 013 are present.

## Validation performed

- Python 3.10.0.
- Full automated test suite: **111 passed**.
- Project audit: **13/13 checks passed**, including compilation and its
  integrated pytest run.
- Local smoke checks: worker list/summary, OpenAPI, and dashboard JavaScript
  returned HTTP 200; an invalid worker token was rejected with HTTP 401.
- Browser check: 1.2.1 dashboard loaded and the worker page rendered the
  no-worker empty state.
- No live worker, Supabase database, or remote migration was available; actual
  distributed assignment and RPC execution remain externally unverified.

## Risks and limitations

- No fresh CPU/RAM heartbeat means a registered Supabase worker is ineligible
  for new jobs; deploy updated workers and verify their heartbeat before use.
- Worker concurrency is deliberately one job per node; this release does not
  run tasks in parallel inside a worker.
- The development UI/node listing is not exposed in production.
- `memory-demo` telemetry and tasks are process-local and are not durable.
- A worker that disconnects while holding a lease relies on the existing lease
  expiry/backoff policy before another eligible worker can retry the task.
- Remote RLS/RPC behavior, simultaneous claims, and multi-worker recovery still
  require integration validation against Supabase.

## Next milestone

FLOPPI 1.2.2: fault tolerance for orphaned runs, lease recovery, retry/backoff,
and restart/failure scenarios. Migration 014 and other pending Supabase
migrations remain part of the final external validation gate.
