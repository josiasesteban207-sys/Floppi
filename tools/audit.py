#!/usr/bin/env python3
"""Repeatable, non-destructive FLOPPI project audit (Python 3.10+)."""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
REPORTS = ROOT / "reports"
HISTORY = REPORTS / "history"

REQUIRED_PATHS = [
    "backend/app/main.py",
    "backend/app/settings.py",
    "backend/app/api/routes.py",
    "backend/app/api/worker_auth.py",
    "backend/app/api/data_routes.py",
    "backend/app/api/analysis_routes.py",
    "backend/app/api/backtesting_routes.py",
    "backend/app/api/monitoring_routes.py",
    "backend/app/api/diagnostics_routes.py",
    "backend/app/api/event_routes.py",
    "backend/app/api/scheduler_routes.py",
    "backend/app/analysis/history.py",
    "backend/app/diagnostics.py",
    "backend/app/event_log.py",
    "backend/app/scheduler.py",
    "backend/app/worker_balancer.py",
    "backend/app/worker_recovery.py",
    "backend/tests/test_analysis_history.py",
    "backend/app/monitoring.py",
    "backend/app/monitoring_history.py",
    "backend/app/static/monitoring-history.css",
    "backend/app/static/diagnostics.js",
    "backend/app/static/diagnostics.css",
    "backend/app/static/scheduler.js",
    "backend/app/static/scheduler.css",
    "backend/app/static/signal-history.css",
    "backend/app/data/models.py",
    "backend/app/data/repository.py",
    "backend/app/data/validator.py",
    "backend/app/indicators/moving_averages.py",
    "backend/app/indicators/momentum.py",
    "backend/app/indicators/volatility.py",
    "backend/app/indicators/volume.py",
    "backend/app/backtesting/engine.py",
    "worker/local_worker.py",
    "database/migrations/004_worker_credentials.sql",
    "database/migrations/007_worker_resource_metrics.sql",
    "database/migrations/010_system_health_history.sql",
    "database/migrations/011_intelligent_diagnostics.sql",
    "database/migrations/012_centralized_event_log.sql",
    "database/migrations/013_task_scheduler.sql",
    "database/migrations/014_worker_load_balancer.sql",
    "database/migrations/015_expired_job_recovery.sql",
    "database/migrations/016_hybrid_signal_history.sql",
    "database/migrations/017_worker_credential_expiry.sql",
    "web/package.json",
    "web/package-lock.json",
    "web/src/auth.js",
    "backend/app/static/auth.bundle.js",
    "tools/provision_worker.py",
    "tools/staging_environment.py",
    "docker-compose.staging.yml",
    ".env.staging.example",
    "docs/STAGING_ENVIRONMENT_1_3_2_1.md",
    "backend/tests/test_staging_environment.py",
    "backend/tests/test_worker_expiry_migration_runner.py",
    "tools/verify_worker_expiry_migration.py",
    "docs/MIGRATION_017_REVIEW_1_3_2_2.md",
]

SECRET_PATTERNS = [
    re.compile(r"(?i)\bservice_role_key\s*=\s*['\"]eyJ[A-Za-z0-9._-]{20,}['\"]"),
    re.compile(r"(?i)\b(secret|api[_-]?key|access[_-]?token)\s*=\s*['\"][A-Za-z0-9_./+=-]{28,}['\"]"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def run_command(name: str, command: list[str], cwd: Path) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        proc = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=900)
        elapsed = round(time.perf_counter() - started, 3)
        output = (proc.stdout + ("\n" + proc.stderr if proc.stderr else "")).strip()
        return {
            "name": name,
            "status": "PASS" if proc.returncode == 0 else "FAIL",
            "return_code": proc.returncode,
            "duration_seconds": elapsed,
            "details": output[-12000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {"name": name, "status": "FAIL", "return_code": None,
                "duration_seconds": round(time.perf_counter() - started, 3),
                "details": f"Timeout after {exc.timeout} seconds"}
    except OSError as exc:
        return {"name": name, "status": "FAIL", "return_code": None,
                "duration_seconds": round(time.perf_counter() - started, 3), "details": str(exc)}


def check_structure() -> dict[str, Any]:
    missing = [item for item in REQUIRED_PATHS if not (ROOT / item).is_file()]
    return {"name": "Project structure", "status": "PASS" if not missing else "FAIL",
            "details": "All required files exist." if not missing else "Missing: " + ", ".join(missing)}


def check_indicator_finiteness() -> dict[str, Any]:
    """Probe public moving-average functions with NaN/Inf, without changing files."""
    code = r'''
import math
from app.indicators.moving_averages import sma, ema
cases = [("sma_nan", sma, [1.0, float("nan"), 3.0]),
         ("ema_inf", ema, [1.0, float("inf"), 3.0])]
bad = []
for name, indicator, values in cases:
    try:
        series = indicator(values, 2)
    except ValueError:
        continue  # Explicit rejection is the intended safe behavior.
    if any(value is not None and not math.isfinite(value) for value in series):
        bad.append(name)
if bad:
    print("Non-finite outputs detected: " + ", ".join(bad))
    raise SystemExit(1)
print("SMA/EMA rejected or safely handled all non-finite probes.")
'''
    return run_command("Indicator finite-input probe", [sys.executable, "-c", code], BACKEND)


def check_provider_isolation() -> dict[str, Any]:
    source = (BACKEND / "app/data/repository.py").read_text(encoding="utf-8")
    # Conservative static heuristic: require provider filtering in candle reads and
    # provider identity in the in-memory candle key.
    has_provider_filter = bool(re.search(r'\.eq\(["\']provider_id["\']', source))
    has_provider_key = bool(re.search(r'key\s*=\s*\([^\n]*provider_id', source))
    ok = has_provider_filter and has_provider_key
    return {"name": "Provider isolation (static heuristic)",
            "status": "PASS" if ok else "WARN",
            "details": ("Provider filter and memory-key references found." if ok else
                        "Could not confirm provider_id is used in both Supabase candle reads and in-memory keys. Review repository.py manually.")}


def check_gap_detection() -> dict[str, Any]:
    source = (BACKEND / "app/data/validator.py").read_text(encoding="utf-8").lower()
    has_gap_logic = any(token in source for token in ("gap", "missing candle", "expected_time", "timeframe_delta"))
    return {"name": "Candle-gap validation (static heuristic)",
            "status": "PASS" if has_gap_logic else "WARN",
            "details": "Gap-related validation markers found." if has_gap_logic else
                       "No general candle-gap detection marker found in validator.py; review continuity checks manually."}


def check_secret_hygiene() -> dict[str, Any]:
    gitignore = ROOT / ".gitignore"
    ignore_text = gitignore.read_text(encoding="utf-8", errors="ignore") if gitignore.exists() else ""
    env_ignored = any(line.strip() in {".env", ".env.*"} for line in ignore_text.splitlines())
    findings: list[str] = []
    allowed = {".py", ".sql", ".toml", ".ini", ".yaml", ".yml", ".json"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        if any(part in {".git", ".venv", "venv", "__pycache__", "reports"} for part in path.parts):
            continue
        if path.name.lower() in {".env", ".env.example"}:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                findings.append(str(path.relative_to(ROOT)))
                break
    if findings:
        return {"name": "Secret hygiene (static scan)", "status": "FAIL",
                "details": "Possible hard-coded secret pattern in: " + ", ".join(sorted(set(findings)))}
    worker_auth_path = ROOT / "backend/app/api/worker_auth.py"
    worker_migration_path = ROOT / "database/migrations/004_worker_credentials.sql"
    worker_auth = worker_auth_path.read_text(encoding="utf-8") if worker_auth_path.exists() else ""
    worker_migration = worker_migration_path.read_text(encoding="utf-8") if worker_migration_path.exists() else ""
    worker_controls = all(token in worker_auth for token in ("hashlib.sha256", "expires_at", "secrets.compare_digest"))
    worker_storage = all(token in worker_migration.lower() for token in ("token_hash", "enable row level security", "revoke all"))
    if not worker_controls or not worker_storage:
        return {"name": "Secret hygiene (static scan)", "status": "FAIL",
                "details": "Per-worker hash, expiry, node-binding, or database access controls are incomplete."}
    if not env_ignored:
        return {"name": "Secret hygiene (static scan)", "status": "WARN",
                "details": ".env is not clearly excluded by .gitignore. The audit deliberately does not read .env files."}
    return {"name": "Secret hygiene (static scan)", "status": "PASS",
            "details": "No high-confidence hard-coded secrets found; per-worker hash/expiry/RLS controls detected. .env files were not read; this is not a full secret scanner."}


def check_demo_label() -> dict[str, Any]:
    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="ignore") if (ROOT / "README.md").exists() else ""
    found = "DEMO" in readme and ("simulation" in readme.lower() or "simulations" in readme.lower())
    return {"name": "DEMO/simulation disclosure", "status": "PASS" if found else "WARN",
            "details": "README documents DEMO/simulation scope." if found else
                       "Could not confirm clear DEMO/simulation disclosure in README.md."}


def check_security_core_controls() -> dict[str, Any]:
    auth_path = ROOT / "backend/app/api/auth.py"
    worker_auth_path = ROOT / "backend/app/api/worker_auth.py"
    worker_migration_path = ROOT / "database/migrations/017_worker_credential_expiry.sql"
    worker_path = ROOT / "worker/local_worker.py"
    web_auth_path = ROOT / "web/src/auth.js"
    web_bundle_path = ROOT / "backend/app/static/auth.bundle.js"
    compose_path = ROOT / "docker-compose.yml"
    auth = auth_path.read_text(encoding="utf-8").lower() if auth_path.exists() else ""
    worker_auth = worker_auth_path.read_text(encoding="utf-8").lower() if worker_auth_path.exists() else ""
    worker_migration = worker_migration_path.read_text(encoding="utf-8").lower() if worker_migration_path.exists() else ""
    worker = worker_path.read_text(encoding="utf-8").lower() if worker_path.exists() else ""
    web_auth = web_auth_path.read_text(encoding="utf-8").lower() if web_auth_path.exists() else ""
    web_bundle = web_bundle_path.read_text(encoding="utf-8", errors="ignore").lower() if web_bundle_path.exists() else ""
    compose = compose_path.read_text(encoding="utf-8").lower() if compose_path.exists() else ""
    controls = (
        'app_metadata.get("role")' in auth
        and "admin_operation_authorized" in auth
        and "if not expires_at" in worker_auth
        and "set active = false" in worker_migration
        and "alter column expires_at set not null" in worker_migration
        and "disable row level security" not in worker_migration
        and "details redacted" in worker
        and "must not include credentials, query parameters, or fragments" in worker
        and "window.sessionstorage" in web_auth
        and "signinwithpassword" in web_bundle
        and "supabase_service_role_key" not in web_bundle
        and "127.0.0.1:8000:8000" in compose
    )
    return {
        "name": "Security Core controls (static check)",
        "status": "PASS" if controls else "FAIL",
        "details": (
            "Verified admin metadata, mutation auditing, expiring worker tokens, browser-only public Auth, safe worker errors, and loopback Compose binding."
            if controls
            else "One or more Security Core source, migration, bundle, or network controls are missing."
        ),
    }


def check_staging_isolation() -> dict[str, Any]:
    compose_path = ROOT / "docker-compose.staging.yml"
    env_example_path = ROOT / ".env.staging.example"
    gitignore_path = ROOT / ".gitignore"
    compose = compose_path.read_text(encoding="utf-8").lower() if compose_path.exists() else ""
    env_example = env_example_path.read_text(encoding="utf-8").lower() if env_example_path.exists() else ""
    gitignore = gitignore_path.read_text(encoding="utf-8").lower() if gitignore_path.exists() else ""
    controls = (
        "ports:" not in compose
        and "internal: true" in compose
        and "floppi-staging-postgres-data" in compose
        and "staging_postgres_password" in env_example
        and "replace_with_a_unique_random_secret" in env_example
        and ".env.*" in gitignore
        and "!.env.staging.example" in gitignore
        and "backups/staging/" in gitignore
        and "SUPABASE_URL" not in env_example
    )
    return {
        "name": "Staging isolation (static configuration)",
        "status": "PASS" if controls else "FAIL",
        "details": (
            "No host ports, internal-only network, dedicated storage, private settings and no Supabase target are configured; runtime connectivity is checked separately."
            if controls
            else "Staging Compose, example settings, or ignore rules violate the expected local-only contract."
        ),
    }


def check_monitoring_history_rls() -> dict[str, Any]:
    migration_path = ROOT / "database/migrations/010_system_health_history.sql"
    migration = migration_path.read_text(encoding="utf-8").lower() if migration_path.exists() else ""
    repository_path = ROOT / "backend/app/monitoring_history.py"
    repository = repository_path.read_text(encoding="utf-8").lower() if repository_path.exists() else ""
    controls = (
        "enable row level security" in migration
        and "revoke all on table public.system_health_observations from anon, authenticated" in migration
        and "grant select, insert on table public.system_health_observations to service_role" in migration
        and "create unique index if not exists system_health_observations_sample_bucket_key" in migration
        and "system_health_observations_sampled_at_idx" in migration
        and "resource_metrics jsonb" in migration
        and 'on_conflict="sample_bucket"' in repository
        and "ignore_duplicates=true" in repository
    )
    return {
        "name": "Monitoring history RLS (static check)",
        "status": "PASS" if controls else "FAIL",
        "details": (
                       "RLS remains enabled and table privileges are limited to the service role."
                       if controls
                       else                        "Monitoring migration must enforce RLS, unique sample buckets, resource history, and service-role-only access."
        ),
    }


def check_diagnostics_rls() -> dict[str, Any]:
    migration_path = ROOT / "database/migrations/011_intelligent_diagnostics.sql"
    migration = migration_path.read_text(encoding="utf-8").lower() if migration_path.exists() else ""
    repository_path = ROOT / "backend/app/diagnostics.py"
    repository = repository_path.read_text(encoding="utf-8").lower() if repository_path.exists() else ""
    controls = (
        "create table if not exists public.diagnostic_incidents" in migration
        and "fingerprint text not null unique" in migration
        and "enable row level security" in migration
        and "revoke all on table public.diagnostic_incidents from public, anon, authenticated" in migration
        and "grant select on table public.diagnostic_incidents to service_role" in migration
        and "create policy" not in migration
        and "grant execute on function public.record_diagnostic_incident" in migration
        and "grant execute on function public.resolve_diagnostic_incident" in migration
        and '"p_occurrence_key": incident["occurrence_key"]' in repository
        and 'occurrence_count": existing["occurrence_count"] +' in repository
    )
    return {
        "name": "Diagnostic history RLS (static check)",
        "status": "PASS" if controls else "FAIL",
        "details": (
            "Incident history uses unique fingerprints, deduplicated observations, enabled RLS, and server-role-only access."
            if controls
            else "Diagnostic migration must enforce RLS, unique grouping, idempotent observations, and service-role-only access."
        ),
    }


def check_event_log_rls() -> dict[str, Any]:
    migration_path = ROOT / "database/migrations/012_centralized_event_log.sql"
    migration = migration_path.read_text(encoding="utf-8").lower() if migration_path.exists() else ""
    repository_path = ROOT / "backend/app/event_log.py"
    repository = repository_path.read_text(encoding="utf-8").lower() if repository_path.exists() else ""
    routes_path = ROOT / "backend/app/api/event_routes.py"
    routes = routes_path.read_text(encoding="utf-8").lower() if routes_path.exists() else ""
    controls = (
        "create table if not exists public.system_events" in migration
        and "event_id uuid primary key" in migration
        and "request_id uuid" in migration
        and "task_id uuid" in migration
        and "enable row level security" in migration
        and "revoke all on table public.system_events from public, anon, authenticated" in migration
        and "grant select, insert on table public.system_events to service_role" in migration
        and "grant execute on function public.prune_system_events(integer)" in migration
        and "create policy" not in migration
        and "event_log_retention_days" in repository
        and "sensitive_key" in repository
        and "verify_node(" in routes
        and "workereventcode" in routes
    )
    return {
        "name": "Central event log RLS/privacy (static check)",
        "status": "PASS" if controls else "FAIL",
        "details": (
            "Events have unique/correlation IDs, configurable retention, sensitive-key filtering, RLS, and service-role-only storage."
            if controls
            else "Event migration must enforce RLS, service-role access, retention, correlation, and worker-ingestion controls."
        ),
    }


def check_scheduler_security() -> dict[str, Any]:
    migration_path = ROOT / "database/migrations/013_task_scheduler.sql"
    migration = migration_path.read_text(encoding="utf-8").lower() if migration_path.exists() else ""
    scheduler_path = ROOT / "backend/app/scheduler.py"
    scheduler = scheduler_path.read_text(encoding="utf-8").lower() if scheduler_path.exists() else ""
    routes_path = ROOT / "backend/app/api/scheduler_routes.py"
    routes = routes_path.read_text(encoding="utf-8").lower() if routes_path.exists() else ""
    controls = (
        "create table if not exists public.scheduled_tasks" in migration
        and "enable row level security" in migration
        and "revoke all on table public.scheduled_tasks from public, anon, authenticated" in migration
        and "grant select, insert, update on table public.scheduled_tasks to service_role" in migration
        and "backtest_runs_schedule_slot_idx" in migration
        and "dispatch_due_scheduled_tasks" in migration
        and "cancel_scheduled_task" in migration
        and "order by priority desc, created_at, id" in migration
        and "enforce_scheduled_task_limit" in migration
        and "data_fingerprint" in routes
        and "cancel_pending" in scheduler
        and "no financial orders" in routes
    )
    return {
        "name": "Task scheduler RLS/deduplication (static check)",
        "status": "PASS" if controls else "FAIL",
        "details": (
            "Schedules use RLS/service-role grants, unique execution slots, bounded ownership, priority claims, and safe cancellation."
            if controls
            else "Scheduler migration must enforce RLS, service-role access, deduplication, priority, cancellation, and DEMO controls."
        ),
    }


def check_worker_balancer_security() -> dict[str, Any]:
    migration_path = ROOT / "database/migrations/014_worker_load_balancer.sql"
    migration = migration_path.read_text(encoding="utf-8").lower() if migration_path.exists() else ""
    balancer_path = ROOT / "backend/app/worker_balancer.py"
    balancer = balancer_path.read_text(encoding="utf-8").lower() if balancer_path.exists() else ""
    controls = (
        "create or replace function public.claim_backtest_run" in migration
        and "node.last_seen >= now() - interval '90 seconds'" in migration
        and "node.metrics_collected_at >= now() - interval '90 seconds'" in migration
        and "for update of node skip locked" in migration
        and "revoke all on function public.claim_backtest_run(text)" in migration
        and "grant execute on function public.claim_backtest_run(text)" in migration
        and "to service_role" in migration
        and "enable row level security" not in migration
        and "max_concurrent_jobs = 1" in balancer
        and "average_task_latency_ms" in balancer
        and "active_jobs" in balancer
    )
    return {
        "name": "Worker load balancing/RPC access (static check)",
        "status": "PASS" if controls else "FAIL",
        "details": (
            "Claims use fresh resource/heartbeat observations, task history, one-job capacity, row locking, and service-role-only RPC access."
            if controls
            else "Worker assignment must use fresh observations, bounded capacity, atomic locking, and service-role-only RPC access."
        ),
    }


def check_worker_recovery_security() -> dict[str, Any]:
    migration_path = ROOT / "database/migrations/015_expired_job_recovery.sql"
    migration = migration_path.read_text(encoding="utf-8").lower() if migration_path.exists() else ""
    recovery_path = ROOT / "backend/app/worker_recovery.py"
    recovery = recovery_path.read_text(encoding="utf-8").lower() if recovery_path.exists() else ""
    controls = (
        "recover_expired_backtest_runs" in migration
        and "for update skip locked" in migration
        and "run.lease_expires_at <= now()" in migration
        and "run.attempt_count < run.max_attempts" in migration
        and "make_interval" in migration
        and "revoke all on function public.recover_expired_backtest_runs(integer)" in migration
        and "grant execute on function public.recover_expired_backtest_runs(integer)" in migration
        and "to service_role" in migration
        and "disable row level security" not in migration
        and "asyncio.to_thread" in recovery
        and "logger.exception" in recovery
    )
    return {
        "name": "Expired worker lease recovery/access (static check)",
        "status": "PASS" if controls else "FAIL",
        "details": (
            "Recovery is bounded/idempotent, uses row locking and retry backoff, and exposes its RPC only to service_role."
            if controls
            else "Recovery must be bounded, retry-safe, transaction-locked, and service-role-only."
        ),
    }


def check_signal_history_storage() -> dict[str, Any]:
    migration_path = ROOT / "database/migrations/016_hybrid_signal_history.sql"
    migration = migration_path.read_text(encoding="utf-8").lower() if migration_path.exists() else ""
    history_path = ROOT / "backend/app/analysis/history.py"
    history = history_path.read_text(encoding="utf-8").lower() if history_path.exists() else ""
    routes_path = ROOT / "backend/app/api/analysis_routes.py"
    routes = routes_path.read_text(encoding="utf-8").lower() if routes_path.exists() else ""
    controls = (
        "create table if not exists public.hybrid_signal_history" in migration
        and "unique (asset_id, timeframe, signal_at)" in migration
        and "enable row level security" in migration
        and "revoke all on table public.hybrid_signal_history from public, anon, authenticated" in migration
        and "grant select on table public.hybrid_signal_history to service_role" in migration
        and "record_hybrid_signal_history" in migration
        and "on conflict (asset_id, timeframe, signal_at) do update" in migration
        and "grant execute on function public.record_hybrid_signal_history(jsonb)" in migration
        and "to service_role" in migration
        and "disable row level security" not in migration
        and "classify_at(indicators, index)" in history
        and "input_fingerprint" in history
        and "outcome_direction" in history
        and '"/analysis/multi-timeframe"' in routes
        and '"/analysis/signals/history"' in routes
    )
    return {
        "name": "Hybrid signal history RLS/deduplication (static check)",
        "status": "PASS" if controls else "FAIL",
        "details": (
            "Point-in-time signals use unique timestamps, completed-outcome updates, RLS, and service-role-only storage."
            if controls
            else "Signal history must preserve RLS, timestamp deduplication, causal classification, and server-role-only persistence."
        ),
    }


def load_previous() -> dict[str, Any] | None:
    latest = REPORTS / "audit_latest.json"
    if not latest.exists():
        return None
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def score(results: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [item for item in results if item["status"] in {"PASS", "FAIL"}]
    passed = sum(item["status"] == "PASS" for item in scored)
    return {"passed": passed, "failed": len(scored) - passed,
            "total": len(scored), "percentage": round(100 * passed / len(scored), 1) if scored else 0.0,
            "note": "This is an automated-check pass rate, not a certification or the weighted expert score from the manual audit."}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [f"# FLOPPI Audit Report {report['version']}", "",
             f"- Generated: {report['generated_at']}",
             f"- Python: `{report['python_version']}`",
             f"- Automated check pass rate: **{report['score']['percentage']}%** ({report['score']['passed']}/{report['score']['total']})",
             "", "> This automated pass rate is not a production certification or a replacement for manual/security/integration review.",
             "", "## Results", "", "| Check | Status | Details |", "|---|---|---|"]
    for item in report["checks"]:
        details = str(item.get("details", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {item['name']} | **{item['status']}** | {details[:500]} |")
    lines += ["", "## Test command output", ""]
    for item in report["checks"]:
        if "duration_seconds" in item:
            lines += [f"### {item['name']} ({item['duration_seconds']} s)", "", "```text", item.get("details", ""), "```", ""]
    lines += ["## Manual checks still required", "",
              "- Real Supabase migrations, RLS, JWT isolation and worker RPC integration.",
              "- Separate Supabase staging project, Auth/RLS/RPC isolation, and execution of migration 017.",
              "- External provider behavior and multi-provider reconciliation.",
              "- Load, concurrency, p95/p99 latency, memory and recovery tests.",
              "- Walk-forward/out-of-sample methodology review and strategy-overfit review.",
              "- Review of deployment TLS, rate limits, backups and restore procedures.", ""]
    if report.get("comparison"):
        c = report["comparison"]
        lines += ["## Comparison with previous audit", "",
                  f"- Previous report: `{c['previous_generated_at']}`",
                  f"- Checks improved: {c['improved']}", f"- Checks regressed: {c['regressed']}",
                  f"- Checks unchanged: {c['unchanged']}", ""]
    else:
        lines += ["## Baseline", "", "No previous report was found. This run establishes the first comparison baseline.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a non-destructive FLOPPI audit and save JSON/Markdown reports.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip pytest (not recommended).")
    version_path = ROOT / "VERSION"
    default_version = version_path.read_text(encoding="utf-8").strip() if version_path.exists() else "unknown"
    parser.add_argument("--version", default=default_version, help="Project version label for this report.")
    args = parser.parse_args()

    REPORTS.mkdir(exist_ok=True)
    HISTORY.mkdir(parents=True, exist_ok=True)
    previous = load_previous()
    checks = [check_structure()]
    checks.append(run_command("Compile application and worker", [sys.executable, "-m", "compileall", "-q", "app", str(ROOT / "worker")], BACKEND))
    if not args.skip_tests:
        checks.append(run_command("Pytest suite", [sys.executable, "-m", "pytest", "-q"], BACKEND))
    else:
        checks.append({"name": "Pytest suite", "status": "WARN", "details": "Skipped by user."})
    checks.extend([
        check_indicator_finiteness(),
        check_provider_isolation(),
        check_gap_detection(),
        check_secret_hygiene(),
        check_demo_label(),
        check_security_core_controls(),
        check_staging_isolation(),
        check_monitoring_history_rls(),
        check_diagnostics_rls(),
        check_event_log_rls(),
        check_scheduler_security(),
        check_worker_balancer_security(),
        check_worker_recovery_security(),
        check_signal_history_storage(),
    ])

    comparison = None
    if previous:
        old = {item["name"]: item["status"] for item in previous.get("checks", [])}
        new = {item["name"]: item["status"] for item in checks}
        names = set(old) & set(new)
        comparison = {
            "previous_generated_at": previous.get("generated_at", "unknown"),
            "improved": sum(old[n] in {"FAIL", "WARN"} and new[n] == "PASS" for n in names),
            "regressed": sum(old[n] == "PASS" and new[n] in {"FAIL", "WARN"} for n in names),
            "unchanged": sum(old[n] == new[n] for n in names),
        }

    report = {
        "project": "FLOPPI", "version": args.version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "checks": checks, "score": score(checks), "comparison": comparison,
        "scope": "Local static checks and tests only; no live trading, broker, or production database actions.",
    }
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (REPORTS / "audit_latest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORTS / "audit_latest.md").write_text(render_markdown(report), encoding="utf-8")
    (HISTORY / f"audit_{stamp}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (HISTORY / f"audit_{stamp}.md").write_text(render_markdown(report), encoding="utf-8")

    print(f"\nFLOPPI AUDIT {args.version}")
    print(f"Automated pass rate: {report['score']['percentage']}% ({report['score']['passed']}/{report['score']['total']})")
    for item in checks:
        print(f"[{item['status']:<4}] {item['name']}")
    print(f"\nReports saved to: {REPORTS}")
    print("No application source files were modified by the audit.")
    return 1 if any(item["status"] == "FAIL" for item in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
