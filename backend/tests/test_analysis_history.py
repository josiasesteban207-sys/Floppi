from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.analysis import history as history_module
from app.analysis.history import build_signal_history
from app.api import analysis_routes
from app.data.models import Candle
from app.main import app

client = TestClient(app)
ASSET_ID = UUID("20000000-0000-4000-8000-000000000001")
START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def make_candles(count: int) -> list[Candle]:
    candles = []
    for index in range(count):
        close = Decimal("10") + Decimal(index) / Decimal("10")
        candles.append(Candle(
            asset_id=ASSET_ID,
            timeframe="1h",
            open_time=START + timedelta(hours=index),
            close_time=START + timedelta(hours=index + 1),
            open=close,
            high=close + Decimal("0.2"),
            low=close - Decimal("0.2"),
            close=close,
            volume=Decimal("100"),
        ))
    return candles


def test_signal_history_is_point_in_time_and_scores_only_completed_horizons():
    candles = make_candles(65)
    history = build_signal_history(candles)
    index = 54
    prefix_history = build_signal_history(candles[:index + 1])

    assert history["signals"][index]["summary"] == prefix_history["signals"][index]["summary"]
    assert history["signals"][index]["outcome_direction"] == "aligned"
    assert history["signals"][-1]["outcome_direction"] is None
    assert history["retrospective_metrics"]["pending_tail_signals"] > 0
    assert history["retrospective_metrics"]["observed_alignment_percentage"] == 100
    assert "not a probability" in history["retrospective_metrics"]["metric_basis"]


def test_signal_history_rejects_duplicate_timestamps():
    candles = make_candles(2)
    duplicate = candles[0].model_copy(update={"close": Decimal("12")})

    with pytest.raises(ValueError, match="duplicate candle timestamps"):
        build_signal_history([candles[0], duplicate])


def test_history_endpoint_deduplicates_and_matures_pending_observations(monkeypatch):
    history_module._memory_history.clear()
    monkeypatch.setattr(history_module, "get_supabase", lambda: None)
    candles = make_candles(60)
    monkeypatch.setattr(analysis_routes, "_load_candles", lambda *_args: candles)
    payload = {"asset_id": str(ASSET_ID), "timeframe": "1h", "limit": 60}

    first = client.post("/api/v1/analysis/signals/history", json=payload)
    second = client.post("/api/v1/analysis/signals/history", json=payload)

    assert first.status_code == 200
    assert first.json()["recorded_or_matured_observations"] == 60
    assert second.status_code == 200
    assert second.json()["recorded_or_matured_observations"] == 0
    altered_fingerprint = dict(first.json()["signals"][0], input_fingerprint="f" * 64)
    assert history_module.signal_history_repository.record([altered_fingerprint]) == 0

    previously_pending = {
        row["signal_at"]
        for row in first.json()["signals"]
        if row["bias"] in {"bullish", "bearish"} and row["outcome_direction"] is None
    }
    extended = make_candles(65)
    monkeypatch.setattr(analysis_routes, "_load_candles", lambda *_args: extended)
    matured = client.post("/api/v1/analysis/signals/history", json=payload)

    assert matured.status_code == 200
    assert matured.json()["recorded_or_matured_observations"] > 0
    records = client.get(
        "/api/v1/analysis/signals/history",
        params={"asset_id": str(ASSET_ID), "timeframe": "1h", "limit": 100},
    )
    assert records.status_code == 200
    body = records.json()
    assert body["count"] == 65
    assert body["retrospective_metrics"]["evaluated_signals"] > 0
    extended_timestamps = {
        row["signal_at"] for row in build_signal_history(extended)["signals"]
    }
    assert all(
        next(row for row in body["history"] if row["signal_at"] == timestamp)["outcome_direction"]
        is not None
        for timestamp in previously_pending & extended_timestamps
    )
    one_sample = client.get(
        "/api/v1/analysis/signals/history",
        params={
            "asset_id": str(ASSET_ID),
            "timeframe": "1h",
            "start_at": extended[10].close_time.isoformat(),
            "end_at": extended[10].close_time.isoformat(),
            "limit": 100,
        },
    )
    assert one_sample.status_code == 200
    assert one_sample.json()["count"] == 1


def test_history_endpoint_rejects_invalid_time_range(monkeypatch):
    monkeypatch.setattr(history_module, "get_supabase", lambda: None)
    response = client.get(
        "/api/v1/analysis/signals/history",
        params={
            "asset_id": str(ASSET_ID),
            "timeframe": "1h",
            "start_at": "2025-01-03T00:00:00Z",
            "end_at": "2025-01-02T00:00:00Z",
        },
    )

    assert response.status_code == 422


def test_multi_timeframe_endpoint_marks_missing_series_without_synthetic_fill(monkeypatch):
    candles = make_candles(55)

    def load(_asset_id, timeframe, _limit):
        if timeframe == "4h":
            raise HTTPException(status_code=404, detail="missing")
        return candles

    monkeypatch.setattr(analysis_routes, "_load_candles", load)
    response = client.get(
        "/api/v1/analysis/multi-timeframe",
        params=[
            ("asset_id", str(ASSET_ID)),
            ("timeframes", "1h"),
            ("timeframes", "4h"),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data_kind"] == "DEMO"
    assert body["timeframes"][0]["status"] == "observed"
    assert body["timeframes"][1]["status"] == "unavailable"
    assert body["timeframes"][1]["sample_size"] == 0
    assert body["observed_alignment"]["requested_timeframes"] == 2


def test_signal_history_migration_enforces_rls_and_timestamp_deduplication():
    migration = (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "016_hybrid_signal_history.sql"
    ).read_text(encoding="utf-8").lower()

    assert "enable row level security" in migration
    assert "revoke all on table public.hybrid_signal_history from public, anon, authenticated" in migration
    assert "grant select on table public.hybrid_signal_history to service_role" in migration
    assert "unique (asset_id, timeframe, signal_at)" in migration
    assert "on conflict (asset_id, timeframe, signal_at) do update" in migration
    assert "to service_role" in migration
