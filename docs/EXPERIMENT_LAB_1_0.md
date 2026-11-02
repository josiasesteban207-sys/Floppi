# FLOPPI 1.0.0 - Experiment Lab & Reporting

## Purpose

This release adds a professional comparison and export workflow to the existing web console. It reuses the existing `POST /api/v1/backtesting/compare` endpoint and does not introduce a new storage model.

## Compare experiments

1. Open **Historial e informes**.
2. Select 2 to 10 completed backtests in the comparison selector.
3. Choose **Comparar resultados**.
4. Review total return, maximum drawdown, win rate, profit factor, Sharpe ratio, and trade count.
5. Export the displayed comparison as JSON or CSV.

Only completed runs can be selected. The backend remains responsible for user ownership checks and rejects runs that are not complete or not accessible to the caller.

## Report format

- JSON includes product/version metadata, generation timestamp, `DEMO` classification, disclaimer, and comparison payload.
- CSV contains one row per experiment and the available metric values.
- Undefined metrics remain empty/unavailable; they are not replaced with zero.

## Deployment

No new database migration is required. Keep migrations 001-006 as previously applied. Worker protocol and credentials are unchanged. Update the API/web application to 1.0.0 and keep each worker on its compatible 0.9.0 protocol until a separately versioned worker release is published.

## Limitations

Comparison is descriptive and historical. It does not tune parameters, estimate the probability of future success, or place real orders. CSV/JSON downloads are generated in the user's browser from the comparison response.
