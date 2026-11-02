"""Explainable, rule-based hybrid analysis for historical DEMO candles.

This module deliberately emits descriptive classifications, not forecasts or
trade instructions. Correlated indicators are grouped into method families so
that several moving averages cannot outvote an independent method by count.
"""

from __future__ import annotations

from math import isfinite
from typing import Any


FAMILY_COUNT = 3
MIN_DIRECTIONAL_FAMILIES = 2
CONCORDANCE_THRESHOLD = 0.80


def _latest(
    indicators: dict[str, list[float | None]],
    name: str,
    index: int | None = None,
) -> float | None:
    values = indicators.get(name, [])
    last_index = min(index, len(values) - 1) if index is not None else len(values) - 1
    for position in range(last_index, -1, -1):
        value = values[position]
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if isfinite(numeric):
            return numeric
    return None


def _vote(name: str, direction: str | None, detail: str, available: bool) -> dict[str, Any]:
    return {
        "family": name,
        "direction": direction or "neutral",
        "included_in_consensus": direction in {"bullish", "bearish"},
        "available": available,
        "detail": detail,
    }


def classify_latest(indicators: dict[str, list[float | None]]) -> dict[str, Any]:
    return classify_at(indicators, None)


def classify_at(
    indicators: dict[str, list[float | None]],
    index: int | None,
) -> dict[str, Any]:
    """Classify indicators using values through one index, without future bars."""
    if index is not None and index < 0:
        raise ValueError("Classification index cannot be negative.")

    def latest(name: str) -> float | None:
        return _latest(indicators, name, index)

    observations: list[str] = []
    internal_conflicts: list[str] = []

    sma_fast, sma_slow = latest("sma_20"), latest("sma_50")
    ema_fast, ema_slow = latest("ema_12"), latest("ema_26")
    trend: str
    trend_available = False
    trend_direction: str | None = None
    trend_detail = "Trend family is unavailable until a moving-average pair is ready."
    if sma_fast is not None and sma_slow is not None and ema_fast is not None and ema_slow is not None:
        sma_direction = "bullish" if sma_fast > sma_slow else "bearish" if sma_fast < sma_slow else None
        ema_direction = "bullish" if ema_fast > ema_slow else "bearish" if ema_fast < ema_slow else None
        if sma_direction and ema_direction and sma_direction != ema_direction:
            trend = "mixed_by_moving_averages"
            trend_available = True
            internal_conflicts.append("trend")
            trend_detail = "SMA and EMA pairs disagree; the trend family casts no directional vote."
        else:
            trend_direction = sma_direction or ema_direction
            trend = f"{trend_direction}_by_moving_averages" if trend_direction else "neutral_by_moving_averages"
            trend_available = True
            trend_detail = "SMA 20/50 and EMA 12/26 are aligned." if trend_direction else "Moving-average pairs are equal."
    elif sma_fast is not None and sma_slow is not None:
        trend_direction = "bullish" if sma_fast > sma_slow else "bearish" if sma_fast < sma_slow else None
        trend = f"{trend_direction}_by_sma_comparison" if trend_direction else "neutral_by_sma_comparison"
        trend_available = True
        trend_detail = "Trend family uses the SMA 20/50 comparison."
    elif ema_fast is not None and ema_slow is not None:
        trend_direction = "bullish" if ema_fast > ema_slow else "bearish" if ema_fast < ema_slow else None
        trend = f"{trend_direction}_by_ema_comparison" if trend_direction else "neutral_by_ema_comparison"
        trend_available = True
        trend_detail = "Trend family uses the EMA 12/26 comparison."
    else:
        trend = "insufficient_data"
        observations.append("There are not enough observations for a moving-average comparison.")

    # MACD and RSI belong to one momentum family. If they disagree, do not
    # double-count either one and do not let them create a directional vote.
    macd_line, macd_signal = latest("macd"), latest("signal")
    macd_hist = latest("histogram")
    rsi_value = latest("rsi_14")
    macd_direction: str | None = None
    if macd_line is not None and macd_signal is not None:
        macd_direction = "bullish" if macd_line > macd_signal else "bearish" if macd_line < macd_signal else None
    elif macd_hist is not None:
        macd_direction = "bullish" if macd_hist > 0 else "bearish" if macd_hist < 0 else None

    rsi_direction: str | None = None
    if rsi_value is not None:
        if rsi_value > 55:
            rsi_direction = "bullish"
        elif rsi_value < 45:
            rsi_direction = "bearish"

    momentum_available = macd_direction is not None or rsi_value is not None or macd_hist is not None
    momentum_direction: str | None = None
    if macd_direction and rsi_direction and macd_direction != rsi_direction:
        internal_conflicts.append("momentum")
        momentum_detail = "MACD and RSI disagree; the momentum family casts no directional vote."
    else:
        momentum_direction = macd_direction or rsi_direction
        if momentum_direction:
            momentum_detail = "MACD and RSI support the same direction, or only one is available."
        elif momentum_available:
            momentum_detail = "Momentum evidence is inside its neutral range or has no directional spread."
        else:
            momentum_detail = "Momentum family is unavailable until MACD or RSI is ready."

    # VWAP is cumulative for the requested sample. It is treated as one
    # confirmation family, not as an independent forecast.
    close_value, vwap_value = latest("close"), latest("vwap")
    volume_direction: str | None = None
    volume_available = close_value is not None and vwap_value is not None
    if close_value is not None and vwap_value is not None:
        volume_direction = "bullish" if close_value > vwap_value else "bearish" if close_value < vwap_value else None
        volume_detail = "Latest close is compared with cumulative VWAP for this sample."
    else:
        volume_detail = "Price/VWAP confirmation is unavailable, often because volume is missing or zero."

    latest_rsi = rsi_value
    if latest_rsi is None:
        momentum_label = "insufficient_data"
    elif latest_rsi >= 70:
        momentum_label = "upper_range"
        observations.append("RSI is at or above 70; this is a descriptive threshold, not a forecast.")
    elif latest_rsi <= 30:
        momentum_label = "lower_range"
        observations.append("RSI is at or below 30; this is a descriptive threshold, not a forecast.")
    elif 45 <= latest_rsi <= 55:
        momentum_label = "middle_range"
    else:
        momentum_label = "directional_range"

    latest_atr, latest_close = latest("atr_14"), close_value
    volatility = "insufficient_data" if latest_atr is None else "measured"
    atr_pct = None
    if latest_atr is not None:
        observations.append(f"Latest ATR 14: {latest_atr:.8g}.")
        if latest_close is not None and latest_close > 0:
            atr_pct = round((latest_atr / latest_close) * 100, 6)

    family_votes = [
        _vote("trend", trend_direction, trend_detail, trend_available),
        _vote("momentum", momentum_direction, momentum_detail, momentum_available),
        _vote("price_volume", volume_direction, volume_detail, volume_available),
    ]
    directional = [item for item in family_votes if item["included_in_consensus"]]
    bullish = sum(item["direction"] == "bullish" for item in directional)
    bearish = sum(item["direction"] == "bearish" for item in directional)
    total = len(directional)
    ratio = (max(bullish, bearish) / total) if total else 0.0
    contradictions = [item["family"] for item in directional] if bullish and bearish else []

    if total < MIN_DIRECTIONAL_FAMILIES or bullish == bearish:
        bias = "undetermined"
        status = "abstain"
        confidence = 0
        reason = "Fewer than two directional families agree, or the available families are evenly split."
    else:
        bias = "bullish" if bullish > bearish else "bearish"
        confidence = round(ratio * 100)
        status = "concordant" if ratio >= CONCORDANCE_THRESHOLD else "provisional"
        reason = "Descriptive family agreement only; this is not a forecast or a probability."

    if internal_conflicts:
        observations.append("At least one method family contains conflicting indicators and was excluded from directional voting.")
    if contradictions:
        observations.append("Independent method families disagree; the combined result is provisional or abstains.")

    return {
        "trend": trend,
        "momentum": momentum_label,
        "volatility": volatility,
        "observations": observations,
        "hybrid": {
            "engine_version": "0.5.0",
            "status": status,
            "bias": bias,
            "confidence_score": confidence,
            "confidence_basis": "Raw agreement percentage among directional method families; not a probability, calibrated confidence, or forecast.",
            "agreement_ratio": round(ratio, 4),
            "evidence_coverage": round(len([item for item in family_votes if item["available"]]) / FAMILY_COUNT, 4),
            "directional_family_count": total,
            "required_directional_families": MIN_DIRECTIONAL_FAMILIES,
            "votes": family_votes,
            "contradictions_present": bool(contradictions or internal_conflicts),
            "contradictory_families": contradictions,
            "internal_conflicts": internal_conflicts,
            "volatility_context": {
                "atr_14": latest_atr,
                "atr_percent_of_close": atr_pct,
                "directional_vote": False,
            },
            "reason": reason,
        },
        "disclaimer": "Historical indicators describe past DEMO data. They are not predictions, trade instructions, or personalized financial advice.",
    }
