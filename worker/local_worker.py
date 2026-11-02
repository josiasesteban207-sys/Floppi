import logging
import os
import time
import platform
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import psutil

BACKEND_PATH = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_PATH))

from backend.app.backtesting.engine import run_backtest

API_URL = os.getenv("FLOPPI_API_URL", "http://127.0.0.1:8000").rstrip("/")
NODE_ID = os.getenv("FLOPPI_NODE_ID", "main-pc")
NODE_TOKEN = os.getenv("FLOPPI_NODE_TOKEN", "")
INTERVAL = int(os.getenv("FLOPPI_HEARTBEAT_SECONDS", "30"))
WORKER_VERSION = "1.3.2.2"
_state_lock = threading.Lock()
_active_job_id: str | None = None
_worker_status = "idle"
logger = logging.getLogger("floppi.worker")


def _send_event(client: httpx.Client, code: str, task_id: str | None = None) -> None:
    try:
        response = client.post(
            f"{API_URL}/api/v1/events/worker",
            json={"code": code, "task_id": task_id},
            headers={"X-Node-Token": NODE_TOKEN, "X-Node-Id": NODE_ID},
            timeout=5.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(
            "Central event delivery failed for %s (%s).",
            code,
            type(exc).__name__,
        )


def capabilities():
    # Inventory is descriptive only; no hardware benchmark or tuning is performed.
    return [platform.system(), platform.machine(), "python-worker", "heartbeat", "backtesting"]


def collect_resource_metrics():
    memory = psutil.virtual_memory()
    disk_root = Path.home().anchor or "/"
    disk = psutil.disk_usage(disk_root)
    process = psutil.Process()
    try:
        process_memory_mb = round(process.memory_info().rss / (1024 * 1024), 2)
    except (psutil.Error, OSError):
        process_memory_mb = None
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": memory.percent,
        "memory_used_mb": round(memory.used / (1024 * 1024), 2),
        "memory_total_mb": round(memory.total / (1024 * 1024), 2),
        "disk_percent": disk.percent,
        "disk_free_gb": round(disk.free / (1024 ** 3), 2),
        "process_memory_mb": process_memory_mb,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source": "worker_host_observation",
    }


def heartbeat_payload():
    with _state_lock:
        status = _worker_status
        active_job_id = _active_job_id
    return {
        "node_id": NODE_ID,
        "node_name": platform.node() or "Worker node",
        "capabilities": capabilities(),
        "status": status,
        "worker_version": WORKER_VERSION,
        "python_version": platform.python_version(),
        "platform": platform.platform()[:120],
        "processor": (platform.processor() or "unknown")[:120],
        "cpu_count": max(1, os.cpu_count() or 1),
        "active_job_id": active_job_id,
        "resource_metrics": collect_resource_metrics(),
    }


def heartbeat_loop(stop_event: threading.Event):
    # A separate connection keeps heartbeats flowing during long local simulations.
    with httpx.Client(timeout=10.0) as heartbeat_client:
        while not stop_event.is_set():
            try:
                response = heartbeat_client.post(
                    f"{API_URL}/api/v1/nodes/heartbeat",
                    json=heartbeat_payload(),
                    headers={"X-Node-Token": NODE_TOKEN},
                )
                response.raise_for_status()
                logger.info("Heartbeat accepted (%s).", heartbeat_payload()["status"])
            except httpx.HTTPError as exc:
                logger.warning("Heartbeat failed; will retry: %s", exc)
                _send_event(heartbeat_client, "WORKER_HEARTBEAT_FAILED")
            stop_event.wait(INTERVAL)

def process_next_job(client: httpx.Client) -> bool:
    headers = {"X-Node-Token": NODE_TOKEN, "X-Node-Id": NODE_ID}
    response = client.post(f"{API_URL}/api/v1/worker/backtesting/next", headers=headers)
    response.raise_for_status()
    job = response.json().get("job")
    if job is None:
        return False

    run = job["run"]
    lease_token = str(run.get("lease_token") or "")
    if len(lease_token) < 32:
        logger.error("Claimed job did not include a valid lease token; refusing to process it.")
        _send_event(client, "WORKER_PROTOCOL_ERROR", str(run.get("id") or "") or None)
        return False
    lease_headers = {**headers, "X-Job-Lease-Token": lease_token}
    global _active_job_id, _worker_status
    with _state_lock:
        _active_job_id = str(run["id"])
        _worker_status = "busy"
    lease_stop = threading.Event()
    def renew_lease_loop():
        with httpx.Client(timeout=10.0) as lease_client:
            while not lease_stop.wait(30):
                try:
                    renewed = lease_client.post(
                        f"{API_URL}/api/v1/worker/backtesting/runs/{run['id']}/heartbeat",
                        headers=lease_headers,
                    )
                    renewed.raise_for_status()
                    logger.info("Job lease renewed: %s", run["id"])
                except httpx.HTTPError as exc:
                    logger.warning("Job lease renewal failed: %s", exc)
                    _send_event(lease_client, "WORKER_LEASE_RENEWAL_FAILED", str(run["id"]))
    lease_thread = threading.Thread(target=renew_lease_loop, name=f"lease-{run['id']}", daemon=True)
    lease_thread.start()
    try:
        _send_event(client, "BACKTEST_STARTED", str(run["id"]))
        result = run_backtest(
            job["candles"],
            job["strategy"],
            run["parameters"],
            float(run["initial_capital"]),
            run["timeframe"],
            job.get("market_code"),
        )
        response = client.post(
            f"{API_URL}/api/v1/worker/backtesting/runs/{run['id']}/complete",
            headers=lease_headers,
            json=result,
        )
        response.raise_for_status()
        logger.info("Backtest completed: %s", run["id"])
        _send_event(client, "BACKTEST_COMPLETED", str(run["id"]))
    except Exception as exc:
        logger.error("Backtest failed for %s (%s).", run["id"], type(exc).__name__)
        _send_event(client, "BACKTEST_FAILED", str(run["id"]))
        try:
            response = client.post(
                f"{API_URL}/api/v1/worker/backtesting/runs/{run['id']}/fail",
                headers=lease_headers,
                json={"message": f"{type(exc).__name__} (details redacted)"},
            )
            response.raise_for_status()
        except httpx.HTTPError as report_error:
            logger.error(
                "Could not report backtest failure for %s (%s).",
                run["id"],
                type(report_error).__name__,
            )
    finally:
        lease_stop.set()
        lease_thread.join(timeout=2)
        with _state_lock:
            _active_job_id = None
            _worker_status = "idle"
        try:
            heartbeat = client.post(
                f"{API_URL}/api/v1/nodes/heartbeat",
                json=heartbeat_payload(),
                headers={"X-Node-Token": NODE_TOKEN},
                timeout=5.0,
            )
            heartbeat.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Idle worker heartbeat failed after task completion: %s", exc)
    return True

def main():
    if len(NODE_TOKEN) < 32:
        raise SystemExit("Set a per-node FLOPPI_NODE_TOKEN of at least 32 characters before starting the worker.")
    if not NODE_ID or len(NODE_ID) < 2 or len(NODE_ID) > 64:
        raise SystemExit("FLOPPI_NODE_ID must contain between 2 and 64 characters.")
    api_parts = urlsplit(API_URL)
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    if (
        not api_parts.hostname
        or api_parts.username
        or api_parts.password
        or api_parts.query
        or api_parts.fragment
    ):
        raise SystemExit("FLOPPI_API_URL must not include credentials, query parameters, or fragments.")
    if api_parts.scheme != "https" and not (api_parts.scheme == "http" and api_parts.hostname in local_hosts):
        raise SystemExit("Remote FLOPPI workers require an HTTPS API URL; HTTP is allowed only for loopback development.")
    if INTERVAL < 1:
        raise SystemExit("FLOPPI_HEARTBEAT_SECONDS must be at least 1.")
    print(f"FLOPPI worker {WORKER_VERSION} started: {NODE_ID} -> {api_parts.hostname}")
    stop_event = threading.Event()
    heartbeat_thread = threading.Thread(
        target=heartbeat_loop, args=(stop_event,), name=f"heartbeat-{NODE_ID}", daemon=True
    )
    heartbeat_thread.start()
    try:
        with httpx.Client(timeout=60.0) as client:
            while True:
                try:
                    processed = process_next_job(client)
                    if not processed:
                        time.sleep(min(INTERVAL, 10))
                except httpx.HTTPError as exc:
                    logger.warning("API unavailable; retrying later (%s).", type(exc).__name__)
                    time.sleep(INTERVAL)
    except KeyboardInterrupt:
        logger.info("Worker shutdown requested.")
        with httpx.Client(timeout=5.0) as client:
            _send_event(client, "WORKER_SHUTDOWN")
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=12)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
