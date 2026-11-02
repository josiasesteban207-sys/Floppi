# FLOPPI Web Console 0.7.1

## Overview

The web console is a same-origin interface served by FastAPI. It uses the existing `/api/v1` endpoints and does not connect directly to Supabase or expose server-side credentials.

Open `http://127.0.0.1:8000/` after starting the API. API documentation remains available at `/docs`.

## Sections

- **Resumen:** API/storage health, asset catalog size, selected candle count, worker count, recent backtests, and a historical close-price chart.
- **Análisis de mercado:** choose an asset and timeframe, generate synthetic DEMO candles, view the close-price history, inspect the hybrid method-family summary, and review the latest indicator values.
- **Backtesting:** queue an existing strategy for a selected asset/date range. A registered worker must claim and process the queued job.
- **Nodos de trabajo:** development-mode status view and local worker setup guidance. The dashboard never displays worker credentials.
- **Historial e informes:** review queued and processed backtests; run `python tools/audit.py` locally for the project audit.

## Data and security boundaries

- The built-in provider is synthetic and explicitly labeled DEMO.
- The dashboard does not place orders, connect to brokers, or manage real funds.
- Worker listing remains development-only, matching the existing API route restriction.
- The browser does not receive `SUPABASE_SERVICE_ROLE_KEY`, worker tokens, or credential hashes.
- The interface does not weaken or disable Supabase RLS.
- The API's existing authentication requirements continue to apply to protected operations.

## Validation

The release was checked with 49 automated tests, the project's 8-check audit, JavaScript syntax validation, and an API smoke test for synthetic data collection, candles, hybrid analysis, indicators, and static dashboard assets. These local checks do not replace a live Supabase migration/RLS/worker integration test.
