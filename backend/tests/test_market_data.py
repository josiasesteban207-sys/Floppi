from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.data.models import DEMO_PROVIDER_ID, Candle
from app.data.repository import _candles as candle_store
from app.data.repository import _jobs, _quality_logs
from app.data.validator import validate_records
from app.main import app
from app.providers.synthetic_provider import SyntheticProvider
from app.settings import settings

client = TestClient(app)
ASSET_ID = UUID("20000000-0000-4000-8000-000000000001")

def setup_function():
    candle_store.clear()
    _jobs.clear()
    _quality_logs.clear()


def test_synthetic_provider_is_deterministic_and_labels_demo():
    provider = SyntheticProvider()
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 0, 3, tzinfo=timezone.utc)

    first = provider.fetch("AAPL", "1m", start, end, 10)
    second = provider.fetch("AAPL", "1m", start, end, 10)

    assert provider.is_demo is True
    assert first == second
    assert len(first) == 3
    assert first[0]["open_time"] == start

def test_synthetic_provider_returns_identical_overlapping_candles():
    provider = SyntheticProvider()
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    later_start = start + timedelta(minutes=1)
    end = start + timedelta(minutes=4)

    full_range = provider.fetch("AAPL", "1m", start, end, 10)
    partial_range = provider.fetch("AAPL", "1m", later_start, end, 10)

    assert full_range[1:] == partial_range


def test_validator_rejects_bad_ohlc_and_ignores_duplicate_times():
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    valid = {
        "open_time": timestamp,
        "close_time": datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
        "open": 10,
        "high": 12,
        "low": 9,
        "close": 11,
        "volume": 5,
    }
    invalid = {**valid, "open_time": datetime(2024, 1, 1, 0, 2, tzinfo=timezone.utc), "high": 8}

    candles, issues = validate_records(
        [valid, valid, invalid],
        ASSET_ID,
        "1m",
        DEMO_PROVIDER_ID,
    )

    assert len(candles) == 1
    assert {issue.severity for issue in issues} == {"warning", "error"}


def test_normalization_rejects_timezone_naive_dates():
    candles, issues = validate_records(
        [{
            "open_time": datetime(2024, 1, 1),
            "close_time": datetime(2024, 1, 1, 0, 1),
            "open": 10,
            "high": 12,
            "low": 9,
            "close": 11,
            "volume": 5,
        }],
        ASSET_ID,
        "1m",
        DEMO_PROVIDER_ID,
    )

    assert candles == []
    assert issues[0].severity == "error"

def test_candle_close_time_must_match_timeframe():
    with pytest.raises(ValueError, match="duration"):
        Candle.model_validate({
            "asset_id": ASSET_ID,
            "provider_id": DEMO_PROVIDER_ID,
            "timeframe": "1m",
            "open_time": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "close_time": datetime(2024, 1, 1, 0, 2, tzinfo=timezone.utc),
            "open": 10,
            "high": 12,
            "low": 9,
            "close": 11,
            "volume": 5,
        })


def test_collect_endpoint_persists_demo_candles(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    response = client.post(
        "/api/v1/data/collect",
        json={
            "asset_id": str(ASSET_ID),
            "timeframe": "1m",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-01T00:03:00Z",
            "limit": 10,
        },
    )

    assert response.status_code == 200
    assert response.json()["data_kind"] == "DEMO"
    assert response.json()["records_processed"] == 3

    history = client.get(
        "/api/v1/candles",
        params={"asset_id": str(ASSET_ID), "timeframe": "1m", "limit": 10},
    )
    assert history.status_code == 200
    assert len(history.json()["candles"]) == 3


def test_validator_reports_missing_candle_intervals():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    records = []
    for minute in (0, 1, 4):
        opened = start + timedelta(minutes=minute)
        records.append({
            "open_time": opened,
            "close_time": opened + timedelta(minutes=1),
            "open": 10, "high": 12, "low": 9, "close": 11, "volume": 5,
        })

    candles, issues = validate_records(records, ASSET_ID, "1m", DEMO_PROVIDER_ID)

    assert len(candles) == 3
    assert any("2 expected interval(s) missing" in issue.description for issue in issues)


def test_repository_isolates_candles_by_provider(monkeypatch):
    from app.data.repository import MarketRepository

    monkeypatch.setattr("app.data.repository.get_supabase", lambda: None)
    repository = MarketRepository()
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    other_provider = UUID("00000000-0000-4000-8000-000000000099")
    first = Candle(
        asset_id=ASSET_ID, provider_id=DEMO_PROVIDER_ID, timeframe="1m",
        open_time=timestamp, close_time=timestamp + timedelta(minutes=1),
        open=10, high=12, low=9, close=11, volume=5,
    )
    second = Candle(
        asset_id=ASSET_ID, provider_id=other_provider, timeframe="1m",
        open_time=timestamp, close_time=timestamp + timedelta(minutes=1),
        open=20, high=22, low=19, close=21, volume=5,
    )
    repository.save_candles([first, second])

    demo = repository.list_candles(ASSET_ID, "1m")
    alternate = repository.list_candles(ASSET_ID, "1m", provider_id=other_provider)

    assert len(demo) == len(alternate) == 1
    assert demo[0]["close"] == "11"
    assert alternate[0]["close"] == "21"
