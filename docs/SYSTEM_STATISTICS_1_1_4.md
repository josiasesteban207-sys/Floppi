# FLOPPI 1.1.4 - Historical System Statistics

## Scope

FLOPPI samples system health every five minutes while the FastAPI application is running. Each observation records its actual UTC collection timestamp and is keyed by its UTC five-minute bucket, so multiple API instances do not store duplicate observations for the same interval.

Each observation stores the actual collection time and its unique five-minute bucket, overall and component health states (API, database, storage, workers, queue, and system resources), measured API-host CPU/RAM/disk/process memory, Blacki and Blanquita status, and queue counts for pending, active, completed, and failed jobs. Historical reports calculate percentages and resource averages/maxima from stored observations and include the observed per-sample history. Queue metrics are the average and maximum queue size observed per sample; they are not counts of unique jobs.

Worker states are grouped as **active** (`online` or `busy`), **inactive** (`idle`), **disconnected** (`offline`, including a registered heartbeat older than the existing 90-second liveness threshold), or **unknown** (no worker record or telemetry could not be read). Missing workers are not assumed disconnected. Workers not named Blacki or Blanquita remain part of the aggregate worker-component status but are not included in the named worker history.

## Endpoints

- `GET /api/v1/monitoring/statistics`: historical distributions and queue/worker summaries.
- `GET /api/v1/monitoring/statistics/export?format=json`: downloadable JSON report.
- `GET /api/v1/monitoring/statistics/export?format=csv`: downloadable CSV report.

Both endpoints accept optional timezone-aware `start_at` and `end_at` query parameters. If omitted, the report covers the previous 24 hours. Reports include their selected period, generation timestamp, sample count, summary distributions, and persisted per-sample history. The maximum query interval is 90 days. The dashboard offers 1-hour, 6-hour, 24-hour, 7-day, and 30-day periods.

The statistics, health, performance, and worker-list routes allow anonymous
access only when `APP_ENV=development` is explicitly selected. Outside that
mode, a verified Supabase user with server-managed
`app_metadata.role=admin` is required. The production browser session
integration is in progress; these metrics are not unauthenticated in production.

## Database and RLS

Apply `database/migrations/010_system_health_history.sql` after migrations 001-007. It adds a unique five-minute bucket key and a timestamp index; if the earlier 1.1.4 draft table already exists, it backfills the bucket and collection timestamps before enforcing the uniqueness key. Existing draft rows cannot recover their true collection timestamp and retain their previously stored timestamp. This checkout has no 008 or 009 migration files; migration 010 has no dependency on them.

The migration enables RLS, revokes table privileges from `anon` and `authenticated`, and grants the backend `service_role` select/insert access. It adds no client-facing policies. Do not disable RLS or expose the service-role key.

## Installation and upgrade

Use Python 3.10. Install/update with:

```powershell
pip install -r requirements-dev.txt
```

For an existing Supabase installation, apply migration 010 before updating the API to 1.1.4. Restart the API after deployment. Workers may be upgraded to 1.1.4 for consistent version metadata; the worker protocol is unchanged.

Without Supabase credentials, the development DEMO backend stores observations in process memory; they are lost when the process restarts. The sampler does not run while the API is stopped.

## Interpretation and limitations

- These are sampled observations, not continuous uptime measurements, an SLA, or a future-availability guarantee.
- The sampler records while the API process runs; a process outage cannot record its own downtime.
- Host resources are measured by `psutil`; resource health is degraded at 85% CPU/RAM/disk and unhealthy at 95%. These thresholds classify observations and are not forecasts.
- Workers without a registered heartbeat are reported unknown; stale registered heartbeats are reported disconnected. A telemetry read failure is reported unknown.
- Worker history charts display representative persisted observations when a selected period contains more than 900 samples; report/API data retains every sample.
- Historical statistics require admin authorization outside explicit development mode; production browser session integration remains pending.
- Migration 010 and RLS behavior have not been tested against a live Supabase project in this local release validation.
- RLS remains enabled. No browser code accesses the Supabase database directly.
- FLOPPI remains an educational simulation platform; no broker, real-order, or real-money functionality is included.
