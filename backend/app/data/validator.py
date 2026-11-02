from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.data.models import Candle, TIMEFRAME_SECONDS, Timeframe
from app.data.normalizer import normalize_candle


@dataclass(frozen=True)
class QualityIssue:
    severity: str
    description: str


def validate_records(
    records: list[dict[str, Any]],
    asset_id: UUID,
    timeframe: Timeframe,
    provider_id: UUID,
) -> tuple[list[Candle], list[QualityIssue]]:
    valid: list[Candle] = []
    issues: list[QualityIssue] = []
    seen: set[tuple[UUID, str]] = set()
    previous_time = None
    expected_step = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])

    for index, record in enumerate(records):
        try:
            candle = normalize_candle(record, asset_id, timeframe, provider_id)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            issues.append(QualityIssue("error", f"Record {index} is invalid: {exc}"))
            continue

        identity = (candle.asset_id, candle.open_time.isoformat())
        if identity in seen:
            issues.append(QualityIssue("warning", f"Duplicate candle at {candle.open_time.isoformat()} was ignored."))
            continue
        if previous_time is not None:
            if candle.open_time < previous_time:
                issues.append(QualityIssue("warning", f"Out-of-order candle at {candle.open_time.isoformat()}."))
            elif candle.open_time - previous_time > expected_step:
                missing = int((candle.open_time - previous_time) / expected_step) - 1
                issues.append(QualityIssue(
                    "warning",
                    f"Candle gap detected: {missing} expected interval(s) missing between "
                    f"{previous_time.isoformat()} and {candle.open_time.isoformat()}.",
                ))
        seen.add(identity)
        if previous_time is None or candle.open_time > previous_time:
            previous_time = candle.open_time
        valid.append(candle)
    return valid, issues
