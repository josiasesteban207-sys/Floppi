"""Runtime metrics helpers. Values are point-in-time observations, not benchmarks."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil


def _disk_root() -> str:
    anchor = Path.cwd().anchor
    return anchor or "/"


def collect_host_metrics() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(_disk_root())
    process = psutil.Process()
    try:
        process_memory_mb = process.memory_info().rss / (1024 * 1024)
    except (psutil.Error, OSError):
        process_memory_mb = None
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": memory.percent,
        "memory_used_mb": round(memory.used / (1024 * 1024), 2),
        "memory_total_mb": round(memory.total / (1024 * 1024), 2),
        "disk_percent": disk.percent,
        "disk_free_gb": round(disk.free / (1024 ** 3), 2),
        "process_memory_mb": round(process_memory_mb, 2) if process_memory_mb is not None else None,
        "cpu_count": psutil.cpu_count(logical=True) or 1,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source": "host_observation",
    }
