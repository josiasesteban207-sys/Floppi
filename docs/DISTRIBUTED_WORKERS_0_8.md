# FLOPPI 0.8.0 · Distributed worker telemetry

## Scope

This milestone adds worker runtime telemetry and liveness visibility to the existing local backtesting worker architecture. Workers continue to claim historical DEMO backtests through the existing queue. No broker, real order, account funding, or live trading functionality is introduced.

## What changed

- Worker heartbeat now reports worker/Python version, OS/platform, processor label, CPU logical count, capabilities, current state, and active backtest ID.
- A dedicated heartbeat thread keeps reporting status while a long local backtest is running.
- The API marks a node as `offline` in read responses when its last heartbeat is older than 90 seconds. This is derived status; it does not rewrite the stored database row.
- `GET /api/v1/nodes/summary` reports online, busy, idle, and offline counts in development mode.
- `GET /api/v1/nodes` includes `heartbeat_age_seconds` and the stale threshold.
- Migration `005_distributed_worker_telemetry.sql` adds telemetry columns and the `busy` state to `node_status`.

## Apply migration

If migrations 001-004 are already applied in Supabase, apply only:

`database/migrations/005_distributed_worker_telemetry.sql`

Keep RLS enabled and do not add direct client policies to `node_status`. The API continues to access server-managed node state through its server-side Supabase client.

## Start Blacki and Blanquita

Provision a separate credential for each machine. Example node IDs:

```powershell
python tools\provision_worker.py --node-id blacki --expires-in-days 90
python tools\provision_worker.py --node-id blanquita --expires-in-days 90
```

Run the generated SQL for each credential in Supabase. Keep each raw token private and use only its matching machine:

```powershell
$env:FLOPPI_API_URL = "https://YOUR-FLOPPI-API.example"
$env:FLOPPI_NODE_ID = "blacki"
$env:FLOPPI_NODE_TOKEN = "<BLACKI_TOKEN>"
$env:FLOPPI_HEARTBEAT_SECONDS = "30"
python worker\local_worker.py
```

On Blanquita, use its own node ID and token. Remote worker connections require HTTPS. For a single-PC local test, loopback HTTP remains allowed.

## Liveness semantics

- `online`: worker is connected and polling.
- `idle`: worker has no active backtest.
- `busy`: worker is processing a backtest; `active_job_id` identifies the current run.
- `offline`: the dashboard derives this when the last heartbeat exceeds 90 seconds or is invalid.

The offline label is observational, not a command to stop a process. A temporarily disconnected worker may still finish its local computation; completion is accepted only when the existing run ownership check still matches.

## Validation gates

Automated tests cover telemetry validation, busy-state reporting, stale-heartbeat interpretation, and summary counts. Before relying on remote nodes, manually verify: apply migration 005; start the API with Supabase; register two distinct worker credentials; connect one worker at a time; confirm heartbeat timestamps and state changes; enqueue one DEMO backtest; verify exactly one worker claims it; then disconnect a worker and observe the 90-second offline threshold.

Automated tests and local audit do not prove a live Supabase deployment, remote TLS configuration, or multi-machine reliability.


## 0.9.0 reliability layer

The 0.9.0 release adds a lease token to each claimed backtest. The worker renews the lease every 30 seconds. If a worker disappears, the lease expires after five minutes and another worker may claim the job, subject to the maximum attempt count. A stale worker cannot renew, complete, or fail a job after its lease expires or has been replaced. Retryable failures use bounded exponential backoff; data fingerprint and missing-candle integrity failures are terminal. Apply migration 006 after migration 005.
