# FLOPPI 1.2.0 Release Report

## Release summary

- Previous version: 1.1.6
- New version: 1.2.0
- Scope: persistent scheduling of historical DEMO backtests.

## Implemented

- API-lifecycle scheduler dispatching due work every 10 seconds.
- Per-user recurring schedules with a 1-minute to 30-day interval, priority
  1-10, per-schedule concurrency 1-4, and 1-10 worker attempts.
- Existing-candle validation and captured data fingerprints; workers reject
  runs if the historical input changes.
- Supabase RPC dispatch with row locking, unique schedule slots, and
  priority-aware worker claims. Process-local DEMO fallback for development.
- Task execution history and dashboard controls to create, pause, resume, and
  cancel schedules. Cancellation stops future and queued work while allowing an
  already leased run to finish.
- Continued DEMO-only behavior. Scheduled runs enqueue simulations only; they
  do not fetch fresh market data or place financial orders.

## Files created

- `backend/app/scheduler.py`
- `backend/app/api/scheduler_routes.py`
- `backend/app/static/scheduler.js`
- `backend/app/static/scheduler.css`
- `backend/tests/test_scheduler.py`
- `database/migrations/013_task_scheduler.sql`
- `docs/TASK_SCHEDULER_1_2_0.md`

## Files modified

- API lifecycle, backtest repository and worker registration/version metadata.
- Monitoring, diagnostic, event-export, and release version metadata.
- Dashboard markup, historical report filenames, and API static-asset tests.
- Project audit, `README.md`, `CHANGELOG.md`, and `VERSION`.

## Database migration

Migration 013 adds `scheduled_tasks`, its due index, a unique scheduled-run
slot, task-limit enforcement, dispatch/cancellation RPCs, and priority-aware
worker claims. RLS stays enabled; schedule-table access and RPC execution are
restricted to `service_role`. It also seeds built-in strategy rows needed by
the existing backtest foreign key.

The migration was statically checked and covered by tests, but was **not
applied to or verified against a live Supabase project**. Apply it only after
confirming migration 012 is present.

## Validation performed

- Python 3.10.0.
- Full automated test suite: **104 passed**.
- Project audit: **12/12 checks passed**.
- Compilation: application and worker passed.
- Local smoke checks: scheduler API, existing monitoring/diagnostic/event API,
  and scheduler JavaScript/CSS assets returned HTTP 200.
- Browser check: 1.2.0 dashboard loaded; Backtesting showed schedule controls
  and the empty state for schedules/history in `memory-demo`.
- Migration validation was static only; no external database was available.

## Limitations and risks

- Supabase migration, remote RLS policies, RPC behavior, and authenticated
  multi-user isolation still require remote verification.
- Without Supabase, task definitions and execution history are lost when the
  API process restarts.
- Scheduled work only runs while the API is running; a missed interval is
  skipped rather than replayed.
- Schedules pin a fixed historical date range and candle fingerprint. They do
  not collect new data; changed inputs fail safely.
- Any registered worker may claim a task from the shared priority queue;
  capacity-aware node assignment is part of 1.2.1.

## Next milestone

FLOPPI 1.2.1: load-aware worker assignment using real CPU/RAM/task/latency and
availability observations, with disconnect/recovery tests. The 2.0.0 release
remains gated on completing and validating the intervening roadmap milestones.
