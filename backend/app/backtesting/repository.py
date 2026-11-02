from datetime import datetime, timedelta, timezone
from math import isclose
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.backtesting.strategies import DEFAULT_STRATEGIES
from app.data.fingerprint import candle_fingerprint
from app.data.models import Timeframe
from app.data.repository import market_repository
from app.supabase_store import get_supabase

_lock = RLock()
_strategies: dict[str, dict[str, Any]] = {}
_runs: dict[str, dict[str, Any]] = {}
_trades: dict[str, list[dict[str, Any]]] = {}
_metrics: dict[str, dict[str, Any]] = {}


def _belongs_to(record: dict[str, Any], user_id: str | None) -> bool:
    return record.get("user_id") == user_id

def _validate_completion(run: dict[str, Any], result: dict[str, Any]) -> None:
    metrics = result["metrics"]
    initial = float(run["initial_capital"])
    expected_return = float(result["final_capital"]) / initial - 1
    points = [initial, *result["equity_curve"]]
    peak = initial
    expected_drawdown = 0.0
    for equity in points:
        peak = max(peak, equity)
        expected_drawdown = max(expected_drawdown, (peak - equity) / peak)
    if not result["equity_curve"] or not isclose(
        result["equity_curve"][-1],
        result["final_capital"],
        rel_tol=1e-8,
        abs_tol=1e-8,
    ):
        raise HTTPException(status_code=422, detail="Final capital must match the final equity-curve value.")
    if not isclose(metrics["total_return"], expected_return, rel_tol=1e-8, abs_tol=1e-8):
        raise HTTPException(status_code=422, detail="total_return does not match the simulated capital.")
    if not isclose(metrics["max_drawdown"], expected_drawdown, rel_tol=1e-8, abs_tol=1e-8):
        raise HTTPException(status_code=422, detail="max_drawdown does not match the equity curve.")
    pnls = [trade["simulated_pnl"] for trade in result["trades"]]
    gains = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    gross_loss = abs(sum(losses))
    expected_profit_factor = sum(gains) / gross_loss if gross_loss else None
    if expected_profit_factor is None:
        if metrics["profit_factor"] is not None:
            raise HTTPException(status_code=422, detail="profit_factor must be null when there are no losses.")
    elif metrics["profit_factor"] is None or not isclose(
        metrics["profit_factor"],
        expected_profit_factor,
        rel_tol=1e-8,
        abs_tol=1e-8,
    ):
        raise HTTPException(status_code=422, detail="profit_factor does not match the simulated trades.")


class BacktestRepository:
    def list_strategies(self, user_id: str | None) -> list[dict[str, Any]]:
        client = get_supabase()
        if client is not None:
            query = client.table("strategies").select("*")
            query = query.eq("user_id", user_id) if user_id else query.is_("user_id", "null")
            saved = query.order("created_at", desc=True).execute().data
        else:
            saved = [record for record in _strategies.values() if _belongs_to(record, user_id)]
        return [*DEFAULT_STRATEGIES, *saved]

    def get_strategy(self, strategy_id: UUID, user_id: str | None) -> dict[str, Any]:
        for strategy in DEFAULT_STRATEGIES:
            if strategy["id"] == str(strategy_id):
                return strategy
        client = get_supabase()
        if client is not None:
            query = client.table("strategies").select("*").eq("id", str(strategy_id))
            query = query.eq("user_id", user_id) if user_id else query.is_("user_id", "null")
            records = query.limit(1).execute().data
            if records:
                return records[0]
        else:
            record = _strategies.get(str(strategy_id))
            if record and _belongs_to(record, user_id):
                return record
        raise HTTPException(status_code=404, detail="Strategy not found")

    def create_strategy(self, record: dict[str, Any]) -> dict[str, Any]:
        client = get_supabase()
        if client is not None:
            result = client.table("strategies").insert(record).execute()
            return result.data[0]
        strategy = {**record, "id": str(uuid4()), "created_at": datetime.now(timezone.utc).isoformat()}
        with _lock:
            _strategies[strategy["id"]] = strategy
        return strategy

    def update_strategy(
        self,
        strategy_id: UUID,
        user_id: str | None,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        self.get_strategy(strategy_id, user_id)
        if str(strategy_id) in {item["id"] for item in DEFAULT_STRATEGIES}:
            raise HTTPException(status_code=400, detail="Built-in strategies cannot be modified.")
        values = {key: value for key, value in record.items() if key != "user_id"}
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        client = get_supabase()
        if client is not None:
            query = client.table("strategies").update(values).eq("id", str(strategy_id))
            query = query.eq("user_id", user_id) if user_id else query.is_("user_id", "null")
            result = query.execute()
            if not result.data:
                raise HTTPException(status_code=404, detail="Strategy not found")
            return result.data[0]
        with _lock:
            _strategies[str(strategy_id)].update(values)
            return _strategies[str(strategy_id)]

    def create_run(self, record: dict[str, Any]) -> dict[str, Any]:
        client = get_supabase()
        if client is not None:
            result = client.table("backtest_runs").insert(record).execute()
            return result.data[0]
        run = {
            **record,
            "id": str(uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with _lock:
            _runs[run["id"]] = run
        return run

    def enqueue_scheduled_run(
        self,
        record: dict[str, Any],
        *,
        max_concurrency: int,
    ) -> dict[str, Any] | None:
        task_id = record["scheduled_task_id"]
        scheduled_for = record["scheduled_for"]
        with _lock:
            if any(
                run.get("scheduled_task_id") == task_id
                and run.get("scheduled_for") == scheduled_for
                for run in _runs.values()
            ):
                return None
            active = sum(
                run.get("scheduled_task_id") == task_id
                and run.get("status") in {"pending", "running"}
                for run in _runs.values()
            )
            if active >= max_concurrency:
                return None
            run = {
                **record,
                "id": str(uuid4()),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "attempt_count": 0,
                "retry_after": None,
                "lease_token": None,
                "lease_expires_at": None,
            }
            _runs[run["id"]] = run
            return run

    def list_scheduled_runs(
        self,
        task_id: str,
        user_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        with _lock:
            runs = [
                run for run in _runs.values()
                if run.get("scheduled_task_id") == task_id
                and _belongs_to(run, user_id)
            ]
        return sorted(
            runs,
            key=lambda run: run.get("scheduled_for") or run["created_at"],
            reverse=True,
        )[:limit]

    def list_recent_scheduled_runs(
        self,
        user_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        with _lock:
            runs = [
                run for run in _runs.values()
                if run.get("scheduled_task_id") is not None
                and _belongs_to(run, user_id)
            ]
        return sorted(
            runs,
            key=lambda run: run.get("scheduled_for") or run["created_at"],
            reverse=True,
        )[:limit]

    def cancel_scheduled_runs(self, task_id: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cancelled = 0
        with _lock:
            for run in _runs.values():
                if (
                    run.get("scheduled_task_id") == task_id
                    and run.get("status") == "pending"
                ):
                    run.update({
                        "status": "cancelled",
                        "completed_at": now,
                        "error_message": "Cancelled by the schedule owner before execution.",
                    })
                    cancelled += 1
        return cancelled

    def list_runs(self, user_id: str | None, limit: int = 100) -> list[dict[str, Any]]:
        client = get_supabase()
        if client is not None:
            query = client.table("backtest_runs").select("*")
            query = query.eq("user_id", user_id) if user_id else query.is_("user_id", "null")
            return query.order("created_at", desc=True).limit(limit).execute().data
        records = [run for run in _runs.values() if _belongs_to(run, user_id)]
        return sorted(records, key=lambda run: run["created_at"], reverse=True)[:limit]

    def count_pending_runs(self, user_id: str | None) -> int:
        client = get_supabase()
        if client is not None:
            query = client.table("backtest_runs").select("id", count="exact").eq("status", "pending")
            query = query.eq("user_id", user_id) if user_id else query.is_("user_id", "null")
            return query.execute().count or 0
        return sum(
            1 for run in _runs.values()
            if run["status"] == "pending" and _belongs_to(run, user_id)
        )

    def count_runs_by_status(self) -> dict[str, int]:
        statuses = ("pending", "running", "completed", "failed")
        client = get_supabase()
        if client is not None:
            counts: dict[str, int] = {}
            for status in statuses:
                result = (
                    client.table("backtest_runs")
                    .select("id", count="exact")
                    .eq("status", status)
                    .execute()
                )
                counts[status] = result.count or 0
            return counts

        with _lock:
            return {
                status: sum(run.get("status") == status for run in _runs.values())
                for status in statuses
            }

    def get_run(self, run_id: UUID, user_id: str | None) -> dict[str, Any]:
        client = get_supabase()
        if client is not None:
            query = client.table("backtest_runs").select("*").eq("id", str(run_id))
            query = query.eq("user_id", user_id) if user_id else query.is_("user_id", "null")
            records = query.limit(1).execute().data
            if records:
                return records[0]
        else:
            record = _runs.get(str(run_id))
            if record and _belongs_to(record, user_id):
                return record
        raise HTTPException(status_code=404, detail="Backtest run not found")

    def claim_next_run(self, node_id: str) -> dict[str, Any] | None:
        client = get_supabase()
        if client is not None:
            result = client.rpc("claim_backtest_run", {"p_node_id": node_id}).execute()
            if not result.data:
                return None
            run = result.data[0]
        else:
            with _lock:
                now = datetime.now(timezone.utc)
                for existing in _runs.values():
                    if existing.get("status") != "running" or existing.get("node_id") != node_id:
                        continue
                    lease_expiry = existing.get("lease_expires_at")
                    if lease_expiry and datetime.fromisoformat(
                        lease_expiry.replace("Z", "+00:00")
                    ) > now:
                        return None
                for existing in _runs.values():
                    if existing.get("status") == "running" and existing.get("lease_expires_at"):
                        expiry = datetime.fromisoformat(existing["lease_expires_at"].replace("Z", "+00:00"))
                        if expiry <= now and int(existing.get("attempt_count", 0)) >= int(existing.get("max_attempts", 3)):
                            existing.update({
                                "status": "failed", "node_id": None, "lease_token": None,
                                "lease_expires_at": None,
                                "error_message": existing.get("last_error") or "Worker lease expired after maximum attempts.",
                                "completed_at": now.isoformat(),
                            })
                pending = []
                for existing in _runs.values():
                    retry_after = existing.get("retry_after")
                    retry_ready = not retry_after or datetime.fromisoformat(retry_after.replace("Z", "+00:00")) <= now
                    lease_expired = False
                    if existing.get("status") == "running" and existing.get("lease_expires_at"):
                        lease_expired = datetime.fromisoformat(existing["lease_expires_at"].replace("Z", "+00:00")) <= now
                    if ((existing.get("status") == "pending" and retry_ready) or
                            (lease_expired and int(existing.get("attempt_count", 0)) < int(existing.get("max_attempts", 3)))):
                        pending.append(existing)
                pending.sort(
                    key=lambda run: (
                        -int(run.get("priority", 5)),
                        run["created_at"],
                        run["id"],
                    )
                )
                if not pending:
                    return None
                run = pending[0]
                lease_token = str(uuid4())
                run.update({
                    "status": "running",
                    "node_id": node_id,
                    "started_at": now.isoformat(),
                    "claimed_at": now.isoformat(),
                    "lease_expires_at": (now + timedelta(minutes=5)).isoformat(),
                    "lease_token": lease_token,
                    "attempt_count": int(run.get("attempt_count", 0)) + 1,
                    "max_attempts": int(run.get("max_attempts", 3)),
                    "last_error": None,
                    "retry_after": None,
                })
        strategy_id = UUID(run["strategy_id"])
        strategy = self.get_strategy(strategy_id, run.get("user_id"))
        start = datetime.fromisoformat(run["start_date"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(run["end_date"].replace("Z", "+00:00"))
        candles = market_repository.list_candles(
            UUID(run["asset_id"]),
            run["timeframe"],
            start,
            end,
            5000,
        )
        if not candles:
            self.fail_run(UUID(run["id"]), node_id, run["lease_token"], "No candles available for the requested period.", retryable=False)
            raise HTTPException(status_code=422, detail="No candles available for the requested period.")
        if candle_fingerprint(candles) != run["data_fingerprint"]:
            self.fail_run(UUID(run["id"]), node_id, run["lease_token"], "Historical candle data changed after the run was queued.", retryable=False)
            raise HTTPException(status_code=409, detail="Historical candle data changed after the run was queued.")
        asset = market_repository.get_asset(UUID(run["asset_id"]))
        market_code = asset.get("market_code") or asset.get("markets", {}).get("code")
        return {
            "run": run,
            "strategy": strategy,
            "candles": candles,
            "market_code": market_code,
        }

    def list_worker_runs(self, limit: int = 1000) -> list[dict[str, Any]]:
        if not 1 <= limit <= 5000:
            raise ValueError("Worker runtime history limit must be between 1 and 5000.")
        client = get_supabase()
        if client is not None:
            result = (
                client.table("backtest_runs")
                .select("node_id,status,started_at,completed_at,lease_expires_at")
                .not_.is_("node_id", "null")
                .order("started_at", desc=True)
                .limit(limit)
                .execute()
            )
            return result.data or []
        with _lock:
            runs = [dict(run) for run in _runs.values() if run.get("node_id")]
        return sorted(
            runs,
            key=lambda run: run.get("started_at") or run.get("created_at") or "",
            reverse=True,
        )[:limit]

    def recover_expired_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("Recovery batch limit must be between 1 and 500.")
        client = get_supabase()
        if client is not None:
            result = client.rpc(
                "recover_expired_backtest_runs",
                {"p_limit": limit},
            ).execute()
            return result.data or []

        now = datetime.now(timezone.utc)
        recovered = []
        with _lock:
            expired = []
            for run in _runs.values():
                if run.get("status") != "running" or not run.get("lease_expires_at"):
                    continue
                expiry = datetime.fromisoformat(run["lease_expires_at"].replace("Z", "+00:00"))
                if expiry <= now:
                    expired.append(run)
            expired.sort(key=lambda run: (run.get("lease_expires_at", ""), run.get("id", "")))
            for run in expired[:limit]:
                attempts = int(run.get("attempt_count", 1))
                max_attempts = int(run.get("max_attempts", 3))
                message = run.get("last_error") or "Worker lease expired before the task completed."
                run.update({
                    "last_error": message,
                    "last_failed_at": now.isoformat(),
                    "node_id": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "retry_after": None,
                })
                if attempts < max_attempts:
                    run.update({
                        "status": "pending",
                        "error_message": None,
                        "completed_at": None,
                        "retry_after": (
                            now + timedelta(seconds=min(300, 5 * (2 ** max(0, attempts - 1))))
                        ).isoformat(),
                    })
                else:
                    run.update({
                        "status": "failed",
                        "error_message": message,
                        "completed_at": now.isoformat(),
                    })
                recovered.append(dict(run))
        return recovered

    def renew_run_lease(self, run_id: UUID, node_id: str, lease_token: str) -> dict[str, Any]:
        client = get_supabase()
        if client is not None:
            result = client.rpc("renew_backtest_run_lease", {
                "p_run_id": str(run_id), "p_node_id": node_id, "p_lease_token": lease_token,
            }).execute()
            if not result.data:
                raise HTTPException(status_code=409, detail="Job lease is no longer valid.")
            return result.data[0]
        with _lock:
            run = _runs.get(str(run_id))
            if not run or run.get("status") != "running" or run.get("node_id") != node_id or run.get("lease_token") != lease_token:
                raise HTTPException(status_code=409, detail="Job lease is no longer valid.")
            now = datetime.now(timezone.utc)
            expires = datetime.fromisoformat(run["lease_expires_at"].replace("Z", "+00:00"))
            if expires <= now:
                raise HTTPException(status_code=409, detail="Job lease has expired.")
            run["lease_expires_at"] = (now + timedelta(minutes=5)).isoformat()
            run["last_lease_renewed_at"] = now.isoformat()
            return run

    def complete_run(
        self,
        run_id: UUID,
        node_id: str,
        lease_token: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        client = get_supabase()
        if client is not None:
            current = client.table("backtest_runs").select(
                "id,node_id,status,initial_capital,lease_token,lease_expires_at"
            ).eq("id", str(run_id)).limit(1).execute().data
            if (not current or current[0]["status"] != "running" or current[0]["node_id"] != node_id
                    or current[0].get("lease_token") != lease_token):
                raise HTTPException(status_code=409, detail="Run lease is not assigned to this worker.")
            _validate_completion(current[0], result)
            updated = client.rpc(
                "complete_backtest_run",
                {"p_run_id": str(run_id), "p_node_id": node_id, "p_lease_token": lease_token, "p_result": result},
            ).execute()
            if not updated.data:
                raise HTTPException(status_code=409, detail="Run is not assigned to this worker.")
            return updated.data[0]
        with _lock:
            run = _runs.get(str(run_id))
            if (not run or run["status"] != "running" or run.get("node_id") != node_id
                    or run.get("lease_token") != lease_token):
                raise HTTPException(status_code=409, detail="Run lease is not assigned to this worker.")
            expires = datetime.fromisoformat(run["lease_expires_at"].replace("Z", "+00:00"))
            if expires <= datetime.now(timezone.utc):
                raise HTTPException(status_code=409, detail="Run lease has expired.")
            _validate_completion(run, result)
            run.update({
                "status": "completed",
                "lease_token": None,
                "lease_expires_at": None,
                "final_capital": result["final_capital"],
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "result_summary": {
                    "warnings": result["warnings"],
                    "equity_curve": result["equity_curve"],
                    "methodology": result["methodology"],
                    "disclaimer": result["disclaimer"],
                },
            })
            _trades[str(run_id)] = [{**trade, "run_id": str(run_id)} for trade in result["trades"]]
            _metrics[str(run_id)] = {"run_id": str(run_id), **result["metrics"]}
            return run

    def fail_run(
        self, run_id: UUID, node_id: str, lease_token: str, message: str, retryable: bool = True
    ) -> dict[str, Any]:
        client = get_supabase()
        if client is not None:
            result = client.rpc("fail_backtest_run", {
                "p_run_id": str(run_id), "p_node_id": node_id,
                "p_lease_token": lease_token, "p_error": message[:1000],
                "p_retryable": retryable,
            }).execute()
            if not result.data:
                raise HTTPException(status_code=409, detail="Run lease is not assigned to this worker.")
            return result.data[0]
        with _lock:
            run = _runs.get(str(run_id))
            if (not run or run.get("status") != "running" or run.get("node_id") != node_id
                    or run.get("lease_token") != lease_token):
                raise HTTPException(status_code=409, detail="Run lease is not assigned to this worker.")
            now = datetime.now(timezone.utc)
            expires = datetime.fromisoformat(run["lease_expires_at"].replace("Z", "+00:00"))
            if expires <= now:
                raise HTTPException(status_code=409, detail="Run lease has expired.")
            attempts = int(run.get("attempt_count", 1))
            max_attempts = int(run.get("max_attempts", 3))
            run["last_error"] = message[:1000]
            run["last_failed_at"] = now.isoformat()
            run["node_id"] = None
            run["lease_token"] = None
            run["lease_expires_at"] = None
            if retryable and attempts < max_attempts:
                run["status"] = "pending"
                delay_seconds = min(300, 5 * (2 ** max(0, attempts - 1)))
                run["retry_after"] = (now + timedelta(seconds=delay_seconds)).isoformat()
            else:
                run["status"] = "failed"
                run["error_message"] = message[:1000]
                run["completed_at"] = now.isoformat()
            return run

    def list_trades(self, run_id: UUID, user_id: str | None) -> list[dict[str, Any]]:
        self.get_run(run_id, user_id)
        client = get_supabase()
        if client is not None:
            return client.table("backtest_trades").select("*").eq("run_id", str(run_id)).order("entry_time").execute().data
        return list(_trades.get(str(run_id), []))

    def get_metrics(self, run_id: UUID, user_id: str | None) -> dict[str, Any] | None:
        self.get_run(run_id, user_id)
        client = get_supabase()
        if client is not None:
            records = client.table("backtest_metrics").select("*").eq("run_id", str(run_id)).limit(1).execute().data
            return records[0] if records else None
        return _metrics.get(str(run_id))


backtest_repository = BacktestRepository()
