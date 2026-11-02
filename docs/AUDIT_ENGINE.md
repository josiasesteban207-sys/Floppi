# FLOPPI AUDIT ENGINE

The audit engine runs repeatable, non-destructive checks against the local project. It does not modify application code, database records, strategies, credentials, or market data.

## Run on Windows PowerShell

From the project root (the directory containing `backend`, `worker`, and `tools`):

```powershell
python tools/audit.py
```

To label a report for a later release:

```powershell
python tools/audit.py --version 0.5.0
```

To skip tests intentionally (not recommended):

```powershell
python tools/audit.py --skip-tests
```

## Generated reports

- `reports/audit_latest.md`: readable report.
- `reports/audit_latest.json`: machine-readable report.
- `reports/history/`: timestamped report snapshots for version-to-version comparison.

The first run establishes a baseline. Later runs compare check statuses against the previous `audit_latest.json`. Preserve the `reports/history` directory to retain the audit trail.

## Checks included

1. Required project structure.
2. Python bytecode compilation of the backend application and worker.
3. Automated test suite (`pytest`).
4. SMA/EMA probe for non-finite values (`NaN` and infinity).
5. Static heuristic for provider isolation.
6. Static heuristic for candle-gap validation.
7. Static secret-pattern scan of source/config files, excluding `.env`, `.env.example`, generated reports and caches. The `.env` file is deliberately never read.
8. README disclosure of DEMO/simulation scope.

`PASS`, `FAIL`, and `WARN` are evidence states, not a guarantee of correctness. Static heuristics can produce false positives/negatives. The displayed percentage is only the pass rate of checks with a definitive PASS/FAIL result; it is not a weighted expert score and must not be compared directly with the manual audit's 69.4/100.

## Manual gates not automated

A local audit cannot certify a deployed Supabase project. Before production, separately test migrations, RLS with at least two real test users, JWT authorization, worker RPC permissions, external providers, TLS, rate limiting, concurrency, load, backups and restore. Keep all tests in DEMO/sandbox environments.

## Exit behavior

The command exits with code `1` if a definitive automated check fails, and `0` if no definitive failures are present. Warnings and manual gates remain visible in the reports.
