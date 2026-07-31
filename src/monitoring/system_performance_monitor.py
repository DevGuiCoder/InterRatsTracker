"""Computer performance sampling."""

from __future__ import annotations

import os
from typing import Any


def collect_system_metrics() -> dict[str, Any]:
    """Collect CPU, memory, disk and current process load."""
    try:
        import psutil
    except Exception as exc:
        return {"available": False, "error": f"psutil indisponivel: {exc}"}
    cpu_percent = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(os.getcwd())
    process_payload: dict[str, Any]
    try:
        process = psutil.Process(os.getpid())
        process_payload = {
            "cpu_percent": process.cpu_percent(interval=None),
            "memory_rss_mb": process.memory_info().rss / 1024 / 1024,
        }
    except Exception as exc:
        process_payload = {"available": False, "error": str(exc)}
    return {
        "available": True,
        "cpu_percent": cpu_percent,
        "memory_used_percent": memory.percent,
        "memory_available_mb": memory.available / 1024 / 1024,
        "disk_used_percent": disk.percent,
        "tool_process": process_payload,
    }
