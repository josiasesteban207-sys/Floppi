from dataclasses import dataclass


@dataclass
class Position:
    quantity: float
    entry_price: float
    entry_time: str
    entry_cost: float
    entry_fees: float


class VirtualPortfolio:
    def __init__(self, initial_capital: float):
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.position: Position | None = None

    def equity(self, mark_price: float) -> float:
        return self.cash + (self.position.quantity * mark_price if self.position else 0.0)

    def open_long(
        self,
        price: float,
        timestamp: str,
        fee_rate: float,
        position_fraction: float,
    ) -> Position:
        if self.position is not None:
            raise ValueError("A position is already open.")
        budget = self.cash * position_fraction
        quantity = budget / (price * (1 + fee_rate))
        notional = quantity * price
        fees = notional * fee_rate
        self.cash -= notional + fees
        self.position = Position(quantity, price, timestamp, notional + fees, fees)
        return self.position

    def close_long(self, price: float, fee_rate: float) -> tuple[Position, float, float]:
        if self.position is None:
            raise ValueError("No position is open.")
        position = self.position
        notional = position.quantity * price
        exit_fees = notional * fee_rate
        self.cash += notional - exit_fees
        net_pnl = notional - exit_fees - position.entry_cost
        self.position = None
        return position, net_pnl, position.entry_fees + exit_fees
