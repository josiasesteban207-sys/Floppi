# FLOPPI 1.3.0 Release Report

## Release summary

- Previous version: 1.2.2
- New version: 1.3.0
- Scope: causal, historical hybrid-signal observations and retrospective metrics.

## Implemented

- Added point-in-time classifications for each candle; the signal at index `i`
  uses indicator values only through that candle close.
- Added one-to-four-timeframe comparisons that distinguish observed data from
  unavailable series rather than filling missing values.
- Added persistent, timestamp-deduplicated signal history with incremental
  five-bar outcome maturation.
- Added aligned/opposed/flat observations, pending-tail counts, date filters,
  historical charting, and CSV/JSON reports with summary metrics.
- Kept retrospective agreement explicitly descriptive, not a probability,
  forecast, guarantee, or financial recommendation.
- Preserved the DEMO-only boundary. No broker, real order, or financial
  operation was added.

## Files created

- `backend/app/analysis/history.py`
- `backend/app/static/signal-history.css`
- `backend/tests/test_analysis_history.py`
- `database/migrations/016_hybrid_signal_history.sql`
- `docs/RELEASE_1_3_0.md`
- `FLOPPI-1.3.0.zip` (126 files; ZIP integrity verified)

## Files modified

- `backend/app/analysis/signal_analyzer.py`
- `backend/app/api/analysis_routes.py`
- `backend/app/main.py`
- `backend/app/api/routes.py`
- `backend/app/api/monitoring_routes.py`
- `backend/app/api/diagnostics_routes.py`
- `backend/app/api/event_routes.py`
- `backend/app/static/index.html`
- `backend/app/static/app.js`
- `backend/tests/test_api.py`
- `tools/audit.py`
- `README.md`
- `CHANGELOG.md`
- `VERSION`
- `worker/local_worker.py`

## Database migration

Migration 016 adds `hybrid_signal_history`, deduplicates by asset, timeframe,
and signal close, and stores outcome fields separately from the point-in-time
signal. RLS stays enabled, client roles are revoked, and reads/RPC execution
remain restricted to `service_role`. A conflict can only mature a previously
pending outcome; it cannot duplicate or replace an existing observation.

The migration passed the project's static audit and migration assertions. It
was **not applied to a live Supabase project**, and was not executed through a
PostgreSQL parser or database. Apply it only after confirming migrations
through 015 are present.

## Validation performed

- Python 3.10.0.
- Full automated test suite: **125 passed**.
- Project audit: **15/15 checks passed**, including compile and integrated
  pytest checks.
- Pylance syntax checks passed for the changed Python analysis modules.
- Local smoke checks: `/api/v1/health`, `/openapi.json`, and
  `/api/v1/analysis/signals/history` returned HTTP 200; API reports version
  1.3.0.
- Browser check: generated 500 actual synthetic DEMO candles, rendered the
  hybrid analysis, showed missing timeframes as unavailable, persisted the
  observations in `memory-demo`, and rendered a 100-row history with 90
  evaluated signals and 75.56% observed non-flat alignment. CSV/JSON export
  controls became enabled and their click handlers emitted no JavaScript
  errors; the integrated browser did not capture a file-download event.
- No migration was executed against Supabase; no remote credentials or live
  worker fleet were available.
- Release package: **126 files**, 225,532 bytes; ZIP integrity check passed.
  `.env`, caches, prior ZIPs, and audit history were excluded.

## Risks and limitations

- `memory-demo` signal history is process-local and is lost on API restart.
- Durable history requires applying migration 016 to the target Supabase
  project and validating access there.
- Retrospective results use the next five available candles, not a fixed
  calendar duration. Flat outcomes are excluded from the alignment percentage.
- Market inputs in this release are synthetic DEMO data; history does not
  establish real-market performance or future availability.
- Browser automation confirmed report controls are enabled but did not observe
  a completed file-download event.

## Installation and upgrade

Install dependencies and run the API as described in the project
[`README.md`](../README.md). For an upgrade, back up the project, keep `.env`
private, verify migrations 001-015, apply migration 016 with an administrator
connection, then update and restart the API and workers. Releases without a
configured Supabase project can use `memory-demo`, with the durability
limitation above.

## Next milestone

Continue the supplied roadmap at FLOPPI 1.3.1 after confirming the 1.3.0
package and deployment prerequisites.
