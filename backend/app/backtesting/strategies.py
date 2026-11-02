from datetime import datetime, timedelta
from math import isfinite
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

StrategyType = Literal["sma_cross", "rsi", "macd"]

DEFAULT_STRATEGIES = [
    {
        "id": "30000000-0000-4000-8000-000000000001",
        "name": "SMA Cross",
        "description": "Educational long-only experiment using SMA crossovers.",
        "version": "1.0.0",
        "parameters": {"strategy_type": "sma_cross", "fast_period": 20, "slow_period": 50},
        "indicators_required": ["sma"],
        "entry_conditions": {"rule": "fast SMA crosses above slow SMA"},
        "exit_conditions": {"rule": "fast SMA crosses below slow SMA"},
        "risk_configuration": {"position_fraction": 1.0},
    },
    {
        "id": "30000000-0000-4000-8000-000000000002",
        "name": "RSI Range",
        "description": "Educational long-only experiment using configurable RSI thresholds.",
        "version": "1.0.0",
        "parameters": {"strategy_type": "rsi", "period": 14, "oversold": 30, "overbought": 70},
        "indicators_required": ["rsi"],
        "entry_conditions": {"rule": "RSI crosses into the oversold range"},
        "exit_conditions": {"rule": "RSI crosses into the overbought range"},
        "risk_configuration": {"position_fraction": 1.0},
    },
    {
        "id": "30000000-0000-4000-8000-000000000003",
        "name": "MACD Cross",
        "description": "Educational long-only experiment using MACD and signal-line crossovers.",
        "version": "1.0.0",
        "parameters": {"strategy_type": "macd", "fast_period": 12, "slow_period": 26, "signal_period": 9},
        "indicators_required": ["macd"],
        "entry_conditions": {"rule": "MACD crosses above its signal line"},
        "exit_conditions": {"rule": "MACD crosses below its signal line"},
        "risk_configuration": {"position_fraction": 1.0},
    },
]

_PARAMETER_DEFAULTS = {
    "sma_cross": {"fast_period": 20, "slow_period": 50},
    "rsi": {"period": 14, "oversold": 30, "overbought": 70},
    "macd": {"fast_period": 12, "slow_period": 26, "signal_period": 9},
}


def validate_strategy_parameters(strategy_type: str, values: dict[str, float]) -> dict[str, float]:
    if strategy_type not in _PARAMETER_DEFAULTS:
        raise ValueError("Unsupported strategy type.")
    parameters = {**_PARAMETER_DEFAULTS[strategy_type], **values}
    unknown = set(parameters) - set(_PARAMETER_DEFAULTS[strategy_type])
    if unknown:
        raise ValueError(f"Unknown strategy parameter(s): {', '.join(sorted(unknown))}.")
    if any(not isfinite(float(value)) for value in parameters.values()):
        raise ValueError("Strategy parameters must be finite numbers.")

    period_keys = {
        "sma_cross": ("fast_period", "slow_period"),
        "rsi": ("period",),
        "macd": ("fast_period", "slow_period", "signal_period"),
    }[strategy_type]
    for key in period_keys:
        period = parameters[key]
        if not float(period).is_integer() or not 1 <= period <= 5000:
            raise ValueError(f"{key} must be an integer between 1 and 5000.")
    if strategy_type == "sma_cross" and parameters["slow_period"] <= parameters["fast_period"]:
        raise ValueError("SMA fast_period must be less than slow_period.")
    if strategy_type == "rsi" and (
        parameters["period"] < 2
        or not 0 <= parameters["oversold"] < parameters["overbought"] <= 100
    ):
        raise ValueError("RSI requires period >= 2 and 0 <= oversold < overbought <= 100.")
    if strategy_type == "macd" and (
        parameters["fast_period"] >= parameters["slow_period"]
        or parameters["signal_period"] < 1
    ):
        raise ValueError("MACD fast_period must be less than slow_period.")
    return parameters


class StrategyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=2000)
    version: str = Field(default="1.0.0", min_length=1, max_length=32)
    strategy_type: StrategyType
    parameters: dict[str, float] = Field(default_factory=dict)
    risk_configuration: dict[str, float] = Field(default_factory=lambda: {"position_fraction": 1.0})

    @model_validator(mode="after")
    def validate_strategy(self):
        validate_strategy_parameters(self.strategy_type, self.parameters)
        fraction = self.risk_configuration.get("position_fraction", 1.0)
        if (
            set(self.risk_configuration) - {"position_fraction"}
            or not isfinite(float(fraction))
            or not 0 < fraction <= 1
        ):
            raise ValueError("position_fraction must be greater than 0 and no greater than 1.")
        return self

    def as_record(self, user_id: str | None) -> dict:
        parameters = {
            **validate_strategy_parameters(self.strategy_type, self.parameters),
            "strategy_type": self.strategy_type,
        }
        return {
            "user_id": user_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "parameters": parameters,
            "indicators_required": [self.strategy_type],
            "entry_conditions": {},
            "exit_conditions": {},
            "risk_configuration": self.risk_configuration,
        }


class BacktestRunCreate(BaseModel):
    strategy_id: UUID
    asset_id: UUID
    timeframe: Literal["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
    start_date: datetime
    end_date: datetime
    initial_capital: float = Field(gt=0, le=1_000_000_000)
    fee_rate: float = Field(default=0.001, ge=0, le=0.05)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.05)
    parameters: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date.utcoffset() != timedelta(0) or self.end_date.utcoffset() != timedelta(0):
            raise ValueError("Backtest dates must be expressed in UTC.")
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be later than start_date.")
        return self

    def dates(self):
        return self.start_date, self.end_date

    def as_record(self, user_id: str | None) -> dict:
        start, end = self.dates()
        return {
            "user_id": user_id,
            "strategy_id": str(self.strategy_id),
            "asset_id": str(self.asset_id),
            "timeframe": self.timeframe,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "initial_capital": self.initial_capital,
            "parameters": {
                "strategy_parameters": self.parameters,
                "fee_rate": self.fee_rate,
                "slippage_rate": self.slippage_rate,
            },
            "status": "pending",
        }
