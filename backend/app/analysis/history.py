import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from threading import RLock
from typing import Any, Sequence

from app.analysis.signal_analyzer import classify_at
from app.data.models import Candle
from app.supabase_store import get_supabase

DEFAULT_FORWARD_HORIZON_BARS = 5
MAX_SIGNAL_HISTORY_ROWS = 1000
_lock = RLock()
_memory_history: dict[tuple[str, str, str], dict[str, Any]] = {}


def build_signal_history(candles: Sequence[Candle]) -> dict[str, Any]:
    if not candles:
        raise ValueError("At least one candle is required to build signal history.")
    ordered = sorted(candles, key=lambda candle: candle.open_time)
    if any(
        candle.asset_id != ordered[0].asset_id
        or candle.timeframe != ordered[0].timeframe
        for candle in ordered
    ):
        raise ValueError("Signal history requires candles for one asset and timeframe.")
    if any(left.open_time == right.open_time for left, right in zip(ordered, ordered[1:])):
        raise ValueError("Signal history cannot contain duplicate candle timestamps.")

    from app.analysis.technical_engine import calculate_indicators

    indicators = calculate_indicators(ordered)
    prefix_hash = hashlib.sha256(b"FLOPPI-hybrid-history-v1").digest()
    signals = []
    for index, candle in enumerate(ordered):
        candle_payload = json.dumps(
            candle.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        prefix_hash = hashlib.sha256(prefix_hash + b"\0" + candle_payload).digest()
        summary = classify_at(indicators, index)
        hybrid = summary["hybrid"]
        outcome = _retrospective_outcome(ordered, index, hybrid["bias"], DEFAULT_FORWARD_HORIZON_BARS)
        signals.append({
            "asset_id": str(candle.asset_id),
            "timeframe": candle.timeframe,
            "signal_at": candle.close_time.isoformat(),
            "input_fingerprint": prefix_hash.hex(),
            "sample_size": index + 1,
            "status": hybrid["status"],
            "bias": hybrid["bias"],
            "agreement_ratio": hybrid["agreement_ratio"],
            "evidence_coverage": hybrid["evidence_coverage"],
            "directional_family_count": hybrid["directional_family_count"],
            **outcome,
            "summary": summary,
        })

    metrics = summarize_signal_history(signals)
    return {
        "signals": signals,
        "retrospective_metrics": metrics,
        "signal_count": len(signals),
        "input_count": len(ordered),
    }


def _retrospective_outcome(
    candles: Sequence[Candle],
    index: int,
    bias: str,
    horizon_bars: int,
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "outcome_horizon_bars": horizon_bars if bias in {"bullish", "bearish"} else None,
        "outcome_direction": None,
        "outcome_change_pct": None,
        "outcome_close_price": None,
    }
    future_index = index + horizon_bars
    if bias not in {"bullish", "bearish"} or future_index >= len(candles):
        return outcome

    initial = candles[index].close
    future = candles[future_index].close
    if future == initial:
        direction = "flat"
    elif (future > initial and bias == "bullish") or (future < initial and bias == "bearish"):
        direction = "aligned"
    else:
        direction = "opposed"
    change_pct = (future - initial) / initial * Decimal("100")
    outcome.update({
        "outcome_direction": direction,
        "outcome_change_pct": format(change_pct, "f"),
        "outcome_close_price": format(future, "f"),
    })
    return outcome


def summarize_signal_history(signals: Sequence[dict[str, Any]]) -> dict[str, Any]:
    directional = [signal for signal in signals if signal["bias"] in {"bullish", "bearish"}]
    evaluated = [
        signal for signal in directional
        if signal.get("outcome_direction") in {"aligned", "opposed", "flat"}
    ]
    aligned = sum(signal["outcome_direction"] == "aligned" for signal in evaluated)
    opposed = sum(signal["outcome_direction"] == "opposed" for signal in evaluated)
    flat = sum(signal["outcome_direction"] == "flat" for signal in evaluated)
    scored_directional = aligned + opposed
    horizon_bars = next(
        (signal["outcome_horizon_bars"] for signal in directional if signal.get("outcome_horizon_bars")),
        DEFAULT_FORWARD_HORIZON_BARS,
    )

    return {
        "horizon_bars": horizon_bars,
        "directional_signals": len(directional),
        "evaluated_signals": len(evaluated),
        "pending_tail_signals": len(directional) - len(evaluated),
        "aligned_observations": aligned,
        "opposed_observations": opposed,
        "flat_observations": flat,
        "observed_alignment_percentage": (
            round(aligned / scored_directional * 100, 4)
            if scored_directional
            else None
        ),
        "metric_basis": "Historical directional alignment among completed, non-flat observations; not a probability, forecast, or guarantee.",
        "lookahead_policy": "Each signal uses candles through its own close; only retrospective outcomes use the following horizon bars.",
    }


class SignalHistoryRepository:
    @property
    def storage_mode(self) -> str:
        return "supabase" if get_supabase() is not None else "memory-demo"

    def record(self, rows: list[dict[str, Any]]) -> int:
        if len(rows) > MAX_SIGNAL_HISTORY_ROWS:
            raise ValueError(f"Signal history batches are limited to {MAX_SIGNAL_HISTORY_ROWS} rows.")
        if not rows:
            return 0
        client = get_supabase()
        if client is not None:
            result = client.rpc(
                "record_hybrid_signal_history",
                {"p_rows": rows},
            ).execute()
            data = result.data or []
            return int(data[0]["recorded_count"]) if data else 0

        inserted = 0
        with _lock:
            for row in rows:
                key = (
                    row["asset_id"],
                    row["timeframe"],
                    row["signal_at"],
                )
                if key in _memory_history:
                    existing = _memory_history[key]
                    if (
                        existing.get("outcome_direction") is None
                        and row.get("outcome_direction") is not None
                    ):
                        existing.update({
                            field: row[field]
                            for field in (
                                "outcome_horizon_bars",
                                "outcome_direction",
                                "outcome_change_pct",
                                "outcome_close_price",
                            )
                        })
                        inserted += 1
                    continue
                _memory_history[key] = {**row, "created_at": datetime.now(timezone.utc).isoformat()}
                inserted += 1
        return inserted

    def list_history(
        self,
        asset_id: str,
        timeframe: str,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("Signal history limit must be between 1 and 500.")
        client = get_supabase()
        if client is not None:
            query = (
                client.table("hybrid_signal_history")
                .select("*")
                .eq("asset_id", asset_id)
                .eq("timeframe", timeframe)
            )
            if start_at is not None:
                query = query.gte("signal_at", start_at.isoformat())
            if end_at is not None:
                query = query.lte("signal_at", end_at.isoformat())
            return query.order("signal_at", desc=True).limit(limit).execute().data or []

        with _lock:
            records = [
                dict(row) for row in _memory_history.values()
                if row["asset_id"] == asset_id and row["timeframe"] == timeframe
                and (start_at is None or datetime.fromisoformat(row["signal_at"]) >= start_at)
                and (end_at is None or datetime.fromisoformat(row["signal_at"]) <= end_at)
            ]
        return sorted(records, key=lambda row: row["signal_at"], reverse=True)[:limit]


signal_history_repository = SignalHistoryRepository()
