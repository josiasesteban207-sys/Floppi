from app.indicators.momentum import macd, rsi
from app.indicators.moving_averages import ema, sma
from app.indicators.volatility import atr, bollinger_bands
from app.indicators.volume import vwap


def test_sma_and_ema_use_simple_average_seed_and_leave_input_unchanged():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    original = list(values)

    assert sma(values, 3) == [None, None, 2.0, 3.0, 4.0]
    assert ema(values, 3) == [None, None, 2.0, 3.0, 4.0]
    assert values == original


def test_rsi_handles_rising_falling_and_flat_series_without_division_by_zero():
    rising = rsi([float(value) for value in range(16)], 14)
    falling = rsi([float(20 - value) for value in range(16)], 14)
    flat = rsi([5.0] * 16, 14)

    assert rising[-1] == 100
    assert falling[-1] == 0
    assert flat[-1] == 50
    assert all(value is None for value in rsi([1.0] * 10, 14))


def test_macd_requires_warmup_and_returns_aligned_series():
    result = macd([float(index) for index in range(40)])

    assert all(len(series) == 40 for series in result.values())
    assert result["macd"][24] is None
    assert result["signal"][32] is None
    assert result["signal"][33] is not None
    assert result["histogram"][-1] is not None


def test_bollinger_bands_and_atr():
    bands = bollinger_bands([7.0, 7.0, 7.0], period=2)
    ranges = atr([11.0, 12.0], [9.0, 10.0], [10.0, 11.0], period=2)

    assert bands["lower"] == [None, 7.0, 7.0]
    assert bands["upper"] == [None, 7.0, 7.0]
    assert ranges == [None, 2.0]

def test_atr_uses_wilder_smoothing_after_initial_average():
    result = atr(
        highs=[11.0, 12.0, 13.0],
        lows=[9.0, 10.0, 11.0],
        closes=[10.0, 11.0, 12.0],
        period=2,
    )

    assert result == [None, 2.0, 2.0]


def test_vwap_is_volume_weighted_and_zero_volume_is_missing():
    result = vwap(
        highs=[11.0, 21.0],
        lows=[9.0, 19.0],
        closes=[10.0, 20.0],
        volumes=[1.0, 3.0],
    )

    assert result == [10.0, 17.5]
    assert vwap([1.0], [1.0], [1.0], [0.0]) == [None]


def test_moving_averages_reject_nan_and_infinite_inputs():
    import math
    import pytest

    for invalid in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError, match="must be finite"):
            sma([1.0, invalid, 3.0], 2)
        with pytest.raises(ValueError, match="must be finite"):
            ema([1.0, invalid, 3.0], 2)


def test_hybrid_analyzer_reports_agreement_and_abstains_on_conflict():
    from app.analysis.signal_analyzer import classify_latest

    agreed = classify_latest({
        "sma_20": [12.0], "sma_50": [10.0],
        "ema_12": [13.0], "ema_26": [11.0],
        "macd": [2.0], "signal": [1.0], "rsi_14": [60.0], "atr_14": [1.0],
    })
    conflict = classify_latest({
        "sma_20": [12.0], "sma_50": [10.0],
        "ema_12": [13.0], "ema_26": [11.0],
        "macd": [-1.0], "signal": [0.0], "rsi_14": [40.0], "atr_14": [1.0],
    })
    insufficient = classify_latest({"sma_20": [None], "sma_50": [None]})

    assert agreed["hybrid"]["bias"] == "bullish"
    assert agreed["hybrid"]["confidence_score"] == 100
    assert agreed["hybrid"]["status"] == "concordant"
    # Trend and momentum are independent families. A 1:1 split must abstain;
    # MACD and RSI must not be counted as two separate votes.
    assert conflict["hybrid"]["bias"] == "undetermined"
    assert conflict["hybrid"]["status"] == "abstain"
    assert conflict["hybrid"]["contradictions_present"] is True
    assert insufficient["hybrid"]["status"] == "abstain"


def test_all_indicator_families_reject_non_finite_series():
    import math
    import pytest

    with pytest.raises(ValueError, match="must be finite"):
        rsi([1.0, math.nan, 3.0], 2)
    with pytest.raises(ValueError, match="must be finite"):
        atr([2.0, math.inf], [1.0, 1.0], [1.5, 1.5], 1)
    with pytest.raises(ValueError, match="must be finite"):
        vwap([2.0], [1.0], [1.5], [math.inf])
    with pytest.raises(ValueError, match="finite"):
        bollinger_bands([1.0, 2.0], period=2, deviations=math.nan)


def test_hybrid_engine_counts_method_families_not_correlated_indicators():
    from app.analysis.signal_analyzer import classify_latest

    result = classify_latest({
        "sma_20": [12.0], "sma_50": [10.0],
        "ema_12": [13.0], "ema_26": [11.0],
        "macd": [2.0], "signal": [1.0], "histogram": [1.0],
        "rsi_14": [62.0], "close": [12.0], "vwap": [10.0],
        "atr_14": [0.5],
    })

    hybrid = result["hybrid"]
    assert hybrid["engine_version"] == "0.5.0"
    assert hybrid["status"] == "concordant"
    assert hybrid["bias"] == "bullish"
    assert hybrid["directional_family_count"] == 3
    assert [vote["family"] for vote in hybrid["votes"]] == ["trend", "momentum", "price_volume"]
    assert hybrid["confidence_score"] == 100
    assert hybrid["volatility_context"]["directional_vote"] is False


def test_hybrid_engine_abstains_when_macd_and_rsi_conflict_inside_momentum_family():
    from app.analysis.signal_analyzer import classify_latest

    result = classify_latest({
        "sma_20": [12.0], "sma_50": [10.0],
        "macd": [-1.0], "signal": [0.0], "rsi_14": [65.0],
    })

    hybrid = result["hybrid"]
    assert hybrid["status"] == "abstain"
    assert hybrid["bias"] == "undetermined"
    assert "momentum" in hybrid["internal_conflicts"]
    assert hybrid["directional_family_count"] == 1


def test_hybrid_engine_reports_evidence_coverage_and_neutral_rsi():
    from app.analysis.signal_analyzer import classify_latest

    result = classify_latest({
        "sma_20": [10.0], "sma_50": [10.0],
        "rsi_14": [50.0], "atr_14": [0.2], "close": [10.0],
    })

    hybrid = result["hybrid"]
    assert result["momentum"] == "middle_range"
    assert hybrid["status"] == "abstain"
    assert hybrid["evidence_coverage"] == 0.6667
    assert hybrid["confidence_score"] == 0
