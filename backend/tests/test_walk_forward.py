from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.backtesting.walk_forward import run_walk_forward
from app.backtesting.strategies import DEFAULT_STRATEGIES
from app.data.models import DEMO_PROVIDER_ID

ASSET_ID = UUID("20000000-0000-4000-8000-000000000001")


def make_candles(count: int) -> list[dict]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    records = []
    for index in range(count):
        # Deterministic oscillation creates repeatable crossover opportunities.
        price = 100 + ((index % 12) - 6) * 1.7 + index * 0.04
        open_time = start + timedelta(minutes=index)
        records.append({
            "asset_id": str(ASSET_ID),
            "provider_id": str(DEMO_PROVIDER_ID),
            "timeframe": "1m",
            "open_time": open_time.isoformat(),
            "close_time": (open_time + timedelta(minutes=1)).isoformat(),
            "open": price,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": 100,
        })
    return records


def strategy() -> dict:
    return {
        **DEFAULT_STRATEGIES[0],
        "parameters": {"strategy_type": "sma_cross", "fast_period": 2, "slow_period": 5},
    }


def test_walk_forward_creates_expanding_context_and_non_overlapping_oos_folds():
    result = run_walk_forward(
        make_candles(110), strategy(), {}, 1000, "1m",
        training_bars=50, testing_bars=20,
    )

    assert result["summary"]["fold_count"] == 3
    assert [fold["training_bars"] for fold in result["folds"]] == [50, 70, 90]
    assert [fold["testing_bars"] for fold in result["folds"]] == [20, 20, 20]
    for previous, current in zip(result["folds"], result["folds"][1:]):
        assert previous["test_end"] <= current["test_start"]
    for fold in result["folds"]:
        assert all(trade["entry_time"] >= fold["test_start"] for trade in fold["trades"])
        assert all(trade["exit_time"] <= fold["test_end"] for trade in fold["trades"])
    assert "does not optimize" in result["methodology"]["parameter_policy"]
    assert 0 <= result["summary"]["positive_fold_ratio"] <= 1


def test_walk_forward_rejects_overlapping_test_windows():
    with pytest.raises(ValueError, match="prevent overlapping"):
        run_walk_forward(
            make_candles(110), strategy(), {}, 1000, "1m",
            training_bars=50, testing_bars=20, step_bars=10,
        )


def test_walk_forward_requires_enough_history_for_one_complete_fold():
    with pytest.raises(ValueError, match="Not enough candles"):
        run_walk_forward(
            make_candles(60), strategy(), {}, 1000, "1m",
            training_bars=50, testing_bars=20,
        )


def test_walk_forward_uses_parameter_overrides_for_indicator_warmup():
    with pytest.raises(ValueError, match="required indicator warm-up"):
        run_walk_forward(
            make_candles(100), strategy(), {"strategy_parameters": {"slow_period": 80}},
            1000, "1m", training_bars=50, testing_bars=20,
        )


def test_walk_forward_rejects_mixed_provider_series():
    records = make_candles(100)
    records[-1]["provider_id"] = "00000000-0000-4000-8000-000000000099"
    with pytest.raises(ValueError, match="one asset, provider, and timeframe"):
        run_walk_forward(
            records, strategy(), {}, 1000, "1m", training_bars=50, testing_bars=20,
        )


def test_walk_forward_api_returns_demo_result(monkeypatch):
    from fastapi.testclient import TestClient
    from app.data.repository import _candles as candle_store
    from app.main import app
    from app.settings import settings

    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr("app.data.repository.get_supabase", lambda: None)
    candle_store.clear()
    records = make_candles(110)
    for record in records:
        key = (record["asset_id"], record["provider_id"], record["timeframe"], record["open_time"])
        candle_store[key] = record

    response = TestClient(app).post(
        "/api/v1/backtesting/walk-forward",
        json={
            "strategy_id": DEFAULT_STRATEGIES[0]["id"],
            "asset_id": str(ASSET_ID),
            "timeframe": "1m",
            "start_date": records[0]["open_time"],
            "end_date": records[-1]["open_time"],
            "initial_capital": 1000,
            "training_bars": 50,
            "testing_bars": 20,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data_kind"] == "DEMO"
    assert payload["summary"]["fold_count"] == 3
    assert payload["methodology"]["parameter_policy"].startswith("Strategy parameters remain fixed")
