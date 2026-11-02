# FLOPPI release validation - 2026-10-31

## Release 0.7.1

- Preserves the 0.7.0 backend features, including per-worker credentials and the existing API contract.
- Adds a responsive Spanish-language web console served by FastAPI.
- Connects the console to existing market, synthetic data collection, candle, indicator, hybrid analysis, strategy, backtest, health, and development-only worker endpoints.
- Adds dashboard and static-asset tests.
- Keeps all market workflows educational and DEMO/simulation-only.

## Verification

- `python -m pytest -q`: **49 passed**.
- `python tools/audit.py`: **8/8 automated checks passed (100%)**.
- `node --check backend/app/static/app.js`: passed.
- API smoke test: synthetic data collection, candles, hybrid analysis, indicator endpoint, dashboard HTML, CSS, and JavaScript all returned successful responses.

The local test runtime used Python 3.13.5. Re-run the tests and audit with the project's target Python 3.10 environment on the user's Windows machine.

## Scope limitations

The audit is an automated local check, not a security certification. The smoke test used local DEMO storage. It does not prove live Supabase migrations, RLS policies, RPCs, credential expiry/revocation, remote TLS, worker concurrency, load handling, or backup/restore behavior. Worker status listing remains development-only. No broker, real-order, or real-money features were added.

## Secret handling

The deliverable excludes `.env`, bytecode, and pytest caches. Keep `.env` local and private. Use only `.env.example` for shared setup instructions. Never paste the Supabase service-role key or a raw worker token into chat or a public repository.


## Release 0.9.0 reliability validation

- Added job lease ownership, periodic renewal, bounded retries, retry backoff, and stale-lease recovery.
- Added tests for lease renewal ownership and retry exhaustion.
- Local automated suite: 54 passed.
- Static audit: 8/8 passed.
- SQL migration 006 is included but has not been executed against the user's live Supabase project in this environment.
