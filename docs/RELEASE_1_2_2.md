# FLOPPI 1.2.2 Release Report

## Release summary

- Previous version: 1.2.1
- New version: 1.2.2
- Scope: fault-tolerant recovery for expired backtest worker leases.

## Implemented

- Added an API-lifecycle recovery worker that scans expired leases immediately
  at startup and every 15 seconds thereafter, using bounded batches.
- Added retry recovery with a 5-second exponential backoff capped at 5 minutes
  and terminal failure after the configured attempt limit.
- Added a row-locked, idempotent Supabase recovery RPC that clears stale
  ownership and preserves service-role-only access.
- Kept completion/failure ownership tied to active lease tokens so a stale
  worker cannot overwrite recovered or completed work.
- Added simulated crash, restart/repository-reload, lease expiry, retry,
  attempt-limit, idempotency, and duplicate-completion tests.
- Preserved single-job worker capacity and the educational DEMO-only boundary.

## Files created

- `backend/app/worker_recovery.py`
- `backend/tests/test_worker_recovery.py`
- `database/migrations/015_expired_job_recovery.sql`
- `docs/WORKER_RECOVERY_1_2_2.md`
- `docs/RELEASE_1_2_2.md`

## Files modified

- API lifecycle and backtest repository.
- API, worker, dashboard, report, and release version metadata.
- Backtesting/API tests, project audit, `README.md`, `CHANGELOG.md`, and
  `VERSION`.

## Database migration

Migration 015 adds an index over expired running leases and a bounded recovery
RPC using `FOR UPDATE SKIP LOCKED`. It leaves existing RLS in place, adds no
client-facing policies, and grants the RPC only to `service_role`.

The migration received static checks and test coverage; it was **not applied to
or verified against a live Supabase project**. Apply it only after confirming
migrations through 014 are present.

## Validation performed

- Python 3.10.0.
- Full automated test suite: **119 passed** on Python 3.10.0.
- Project audit: **14/14 checks passed**, including compilation and its
  integrated pytest run.
- Local smoke checks: `/`, `/openapi.json`, health, queue summary, node
  summary, monitoring, events, diagnostics, scheduler, and dashboard JS
  returned HTTP 200; invalid worker credentials were rejected with HTTP 401.
- Browser check: the 1.2.2 dashboard loaded and showed the expected DEMO empty
  state.
- Supabase RPC/RLS and actual API/worker process termination were not
  externally available for validation.

## Risks and limitations

- The recovery loop runs only while the API is running. On API startup it
  immediately checks persisted Supabase jobs, then repeats every 15 seconds.
- Supabase durability and RPC behavior require applying migration 015 and
  testing against the target database.
- Recovery of `memory-demo` jobs is process-local; a process restart loses
  those jobs and they cannot be reconstructed.
- If an eligible worker claims an expired lease before the recovery loop, the
  existing atomic claim path can retry immediately; otherwise the recovery
  backoff applies.
- Automated failure tests simulate lease state changes; they do not prove
  production network partition or multi-instance behavior.

## Next milestone

FLOPPI 1.3.0: complete hybrid signal analysis, multi-timeframe explanations,
signal history, and retrospective metrics with no unsupported probability
claims.
