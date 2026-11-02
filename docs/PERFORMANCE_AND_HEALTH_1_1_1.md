# FLOPPI 1.1.1 - Performance Metrics & System Health

## Scope

This subversion adds point-in-time resource observations and a system health snapshot. It does not run hardware benchmarks and does not retain a time series of metrics.

## Measurements

- API host: CPU utilization, RAM utilization and used/total MB, disk utilization and free GB, Python API process RSS, logical CPU count.
- Worker host: CPU utilization, RAM utilization and used/total MB, disk utilization and free GB, worker process RSS.
- Worker measurements are sent in the authenticated heartbeat and carry their own collection timestamp.
- Missing worker telemetry is reported as unavailable, not zero.

## Endpoints

- `GET /api/v1/monitoring/performance`: API host metrics and latest worker snapshots.
- `GET /api/v1/monitoring/health`: API, storage, worker fleet, and task queue health components.

Outside `APP_ENV=development`, both endpoints and worker-list endpoints require
a verified user with server-managed Supabase `app_metadata.role=admin`.
Anonymous requests are denied; production browser session integration is in
progress.

## Supabase migration

Apply `database/migrations/007_worker_resource_metrics.sql` after migrations 001-006. The migration only adds resource telemetry columns and an object-type check. It does not add anon/authenticated policies or weaken RLS. `node_status` remains server-managed through the backend service role.

## Upgrade

1. Back up the project and keep `.env` private.
2. Install updated dependencies: `pip install -r requirements-dev.txt`.
3. Apply migration 007 in Supabase after 001-006.
4. Update the API and both worker programs to 1.1.1.
5. Restart the API and workers. Older workers remain visible but will not report resource metrics until updated.
6. Open the web console and select **Rendimiento y salud**.

## Interpretation and limitations

- CPU is a point-in-time host sample from `psutil`, not a benchmark score.
- RAM and disk percentages refer to the host, not only FLOPPI.
- API process RSS and worker process RSS refer to the respective Python process.
- Health is a point-in-time check. A healthy snapshot is not an uptime guarantee.
- Worker fleet health is degraded when no worker has registered; it is unhealthy when all registered workers are offline.
- Metrics are not retained as a historical series in this release.
- Reports contain operational metadata and should be treated as internal diagnostics.

## Safety

FLOPPI remains a DEMO educational platform. This release does not add broker connectivity, live orders, or real-money trading features.
