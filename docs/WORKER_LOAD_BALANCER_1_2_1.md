# FLOPPI 1.2.1 - Worker Load Balancer

The worker queue now assigns each new backtest to one eligible worker using
recent observations. It does not benchmark hosts or invent missing metrics.

## Eligibility and ranking

A worker is eligible only when its heartbeat and CPU/RAM observation are no
older than 90 seconds, its reported state is `online` or `idle`, it has no
active job, and it has fewer than one unexpired active lease. Missing or stale
resource observations make the worker ineligible.

Eligible workers are ranked by:

1. Observed CPU percentage + observed RAM percentage.
2. The average runtime in seconds of up to 20 recent completed tasks, added to
   the resource score; if there is no runtime history, latency is shown as
   unavailable and used only as a deterministic tie-breaker.
3. Most recent heartbeat, then node ID.

The worker process currently executes one job at a time. This release reports
that limit and does not create background concurrency. Active jobs consume the
single slot. After a task completes, the worker sends an immediate idle
heartbeat instead of waiting for the normal heartbeat interval.

The development-only `/api/v1/nodes` response includes each worker's dispatch
eligibility, resource score, task-latency sample count, active jobs, and slot
limit. `/api/v1/nodes/summary` includes the selected node and eligible worker
count. The development worker dashboard displays those observed values.

## Supabase migration

Apply `database/migrations/014_worker_load_balancer.sql` after migration 013.
The migration adds indexes for worker runtime history and replaces the
`claim_backtest_run` RPC. The RPC selects and locks the least-loaded eligible
node, claims one queue row atomically, and marks the node busy in the same
transaction.

The migration does not disable RLS, add client-facing policies, or grant
`anon`/`authenticated` access. RPC execution remains restricted to
`service_role`. Apply the migration with an authorized Supabase administrator
and verify it against the target database before deploying the 1.2.1 API and
workers.

## Development and recovery behavior

In `memory-demo`, telemetry and jobs are process-local. When observed workers
are registered, only the selected worker may claim a new job. Existing
single-worker development setups without any heartbeat retain their
authenticated claim behavior for compatibility; this fallback is not a
capacity observation and is not used by the Supabase RPC.

Stale/disconnected workers cannot receive new work. Existing leases continue
through the lease/retry policy from migration 006; once a lease expires, a
different eligible worker may claim the retry. A worker that cannot submit a
fresh heartbeat will not receive another job until telemetry recovers.

All work remains historical DEMO backtesting. No live market order, broker
connection, or financial operation is introduced.
