from datetime import datetime, timedelta
from math import isclose, isfinite
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class SimulatedTrade(BaseModel):
    entry_time: datetime
    exit_time: datetime
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    simulated_pnl: float
    simulated_fees: float = Field(ge=0)
    result: Literal["win", "loss", "breakeven"]

    @model_validator(mode="after")
    def validate_trade(self):
        if self.entry_time.utcoffset() != timedelta(0) or self.exit_time.utcoffset() != timedelta(0):
            raise ValueError("Trade timestamps must be expressed in UTC.")
        if self.exit_time < self.entry_time:
            raise ValueError("exit_time cannot precede entry_time.")
        if not all(isfinite(value) for value in (
            self.entry_price, self.exit_price, self.quantity, self.simulated_pnl, self.simulated_fees
        )):
            raise ValueError("Trade values must be finite.")
        expected_result = "win" if self.simulated_pnl > 0 else "loss" if self.simulated_pnl < 0 else "breakeven"
        if self.result != expected_result:
            raise ValueError("Trade result must agree with simulated_pnl.")
        return self


class BacktestMetrics(BaseModel):
    total_return: float = Field(gt=-1)
    max_drawdown: float = Field(ge=0, le=1)
    win_rate: float | None = Field(default=None, ge=0, le=1)
    profit_factor: float | None = Field(default=None, ge=0)
    sharpe_ratio: float | None = None
    total_trades: int = Field(ge=0)
    winning_trades: int = Field(ge=0)
    losing_trades: int = Field(ge=0)
    average_gain: float | None = None
    average_loss: float | None = None

    @model_validator(mode="after")
    def validate_counts(self):
        if self.winning_trades + self.losing_trades > self.total_trades:
            raise ValueError("Winning and losing trades cannot exceed total_trades.")
        if not all(
            value is None or isfinite(value)
            for value in (
                self.total_return,
                self.max_drawdown,
                self.win_rate,
                self.profit_factor,
                self.sharpe_ratio,
                self.average_gain,
                self.average_loss,
            )
        ):
            raise ValueError("Metric values must be finite.")
        return self


class BacktestResult(BaseModel):
    final_capital: float = Field(gt=0)
    trades: list[SimulatedTrade] = Field(max_length=5000)
    metrics: BacktestMetrics
    warnings: list[str] = Field(default_factory=list, max_length=50)
    equity_curve: list[float] = Field(default_factory=list, max_length=5000)
    methodology: dict[str, str] = Field(default_factory=dict)
    disclaimer: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_trade_count(self):
        if self.metrics.total_trades != len(self.trades):
            raise ValueError("total_trades must match the number of trade records.")
        if not isfinite(self.final_capital) or any(
            not isfinite(value) or value <= 0 for value in self.equity_curve
        ):
            raise ValueError("Capital and equity values must be finite and positive.")
        if self.metrics.winning_trades != sum(trade.result == "win" for trade in self.trades):
            raise ValueError("winning_trades must match trade records.")
        if self.metrics.losing_trades != sum(trade.result == "loss" for trade in self.trades):
            raise ValueError("losing_trades must match trade records.")
        expected_win_rate = (
            self.metrics.winning_trades / len(self.trades) if self.trades else None
        )
        if expected_win_rate is None:
            if self.metrics.win_rate is not None:
                raise ValueError("win_rate must be null when there are no trades.")
        elif self.metrics.win_rate is None or not isclose(
            self.metrics.win_rate,
            expected_win_rate,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ValueError("win_rate must agree with the trade records.")
        return self
