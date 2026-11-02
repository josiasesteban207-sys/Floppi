import asyncio
import logging

from app.backtesting.repository import backtest_repository

logger = logging.getLogger(__name__)
RECOVERY_INTERVAL_SECONDS = 15
RECOVERY_BATCH_SIZE = 100


async def run_worker_recovery() -> None:
    while True:
        try:
            recovered = await asyncio.to_thread(
                backtest_repository.recover_expired_runs,
                RECOVERY_BATCH_SIZE,
            )
            if recovered:
                logger.warning(
                    "Recovered %s expired backtest lease(s).",
                    len(recovered),
                )
        except Exception:
            logger.exception("Could not recover expired backtest leases")
        await asyncio.sleep(RECOVERY_INTERVAL_SECONDS)
