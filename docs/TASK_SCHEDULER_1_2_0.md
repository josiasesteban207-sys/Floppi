# FLOPPI 1.2.0 - Task Scheduler

The scheduler creates periodic jobs for existing, bounded historical DEMO
backtests. It does not retrieve new market data or place financial orders.

## Upgrade

1. Back up the project and keep `.env` private.
2. Confirm migrations through 012 are applied, then apply
   `database/migrations/013_task_scheduler.sql` using a Supabase admin
   connection.
3. Deploy the 1.2.0 API and workers. The API process dispatches due schedules
   every 10 seconds; workers use the existing authenticated lease protocol.

Migration 013 seeds the built-in strategy rows needed by the existing foreign
key, adds per-user schedule records and unique scheduled-run slots, keeps RLS
enabled, and grants database access only to `service_role`. It also changes
worker claims to honor priority while retaining expiring leases and bounded
retries.

## Schedule behavior

- Each task snapshots its strategy, asset, timeframe, historical date range,
  costs, and candle fingerprint. Creation is rejected if the selected asset
  has no candles or exceeds 5,000.
- Intervals range from 60 seconds to 30 days. Priority ranges from 1 to 10;
  larger values are claimed first. Per-task concurrency ranges from 1 to 4
  active queued/running runs. Worker attempts range from 1 to 10.
- Runs are deduplicated by `(scheduled_task_id, scheduled_for)`. If the API
  misses one or more intervals, it skips the backlog and schedules the next
  occurrence rather than dispatching a burst.
- Workers compare the queued data fingerprint with the selected historical
  candles before running. A mismatch fails the run rather than using changed
  input silently.
- Any registered worker can claim a due run from the shared priority queue;
  schedules do not pin runs to a specific node. Capacity-aware assignment is
  the next 1.2.1 milestone.
- Pausing stops future scheduling but leaves already queued runs intact.
  Cancellation disables the schedule and cancels its pending runs. A run
  holding a valid worker lease is not interrupted; it can finish normally.
  Cancelled tasks cannot be resumed; create a new schedule instead.
- The scheduler only enqueues work while the API is running. Supabase is
  required for durable cross-restart history; without it, the DEMO fallback is
  process-local.

The maximum is 10 enabled schedules per account. Scheduler administration
endpoints use the authenticated user's ownership in production and the
existing development-mode identity in local DEMO mode.

## API

- `POST /api/v1/scheduler/tasks`: create an enabled schedule.
- `GET /api/v1/scheduler/tasks?limit=100`: list owned schedules.
- `GET /api/v1/scheduler/runs?limit=100`: list recent owned scheduled runs.
- `GET /api/v1/scheduler/tasks/{task_id}/runs?limit=100`: list runs for one
  owned schedule.
- `POST /api/v1/scheduler/tasks/{task_id}/pause`
- `POST /api/v1/scheduler/tasks/{task_id}/resume`
- `POST /api/v1/scheduler/tasks/{task_id}/cancel`

Creation requires an available strategy and asset plus historical candles
inside a UTC start/end range. The task history and standard backtest history
retain their normal user ownership.

## Validation boundary

Automated tests cover DEMO scheduling, unique slots, concurrency, priority,
limits, retry configuration, task cancellation, and existing worker-queue
behavior. Static checks verify migration grants and RLS declarations. These
checks do not apply migration 013 or verify its functions in a live Supabase
project; validate it remotely after confirming migration 012 is present.
