import asyncio
import logging

from app.backtesting.repository import backtest_repository
from app.devices import device_registry

logger = logging.getLogger(__name__)
RECOVERY_INTERVAL_SECONDS = 15
RECOVERY_BATCH_SIZE = 100


async def run_worker_recovery() -> None:
    while True:
        try:
            offline = await asyncio.to_thread(device_registry.mark_stale_offline)
            if offline:
                logger.info("Marked %s stale client device(s) offline", offline)
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
