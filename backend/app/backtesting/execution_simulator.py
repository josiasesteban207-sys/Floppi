from app.backtesting.portfolio import VirtualPortfolio


def buy_price(open_price: float, slippage_rate: float) -> float:
    return open_price * (1 + slippage_rate)


def sell_price(open_price: float, slippage_rate: float) -> float:
    return open_price * (1 - slippage_rate)


def close_result(pnl: float) -> str:
    if pnl > 0:
        return "win"
    if pnl < 0:
        return "loss"
    return "breakeven"


__all__ = ["VirtualPortfolio", "buy_price", "sell_price", "close_result"]
