"""Windows time synchronization diagnostics."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.utils.windows_command import run_windows_command


def collect_time_sync() -> dict[str, Any]:
    """Collect local time and Windows Time service status without changing time."""
    payload: dict[str, Any] = {
        "local_time": datetime.now().isoformat(),
        "timezone": datetime.now().astimezone().tzname(),
        "windows_time": {},
    }
    try:
        completed = run_windows_command(["w32tm", "/query", "/status"], timeout=5)
    except Exception as exc:
        payload["windows_time"] = {"available": False, "error": str(exc)}
        return payload
    payload["windows_time"] = {
        "available": completed.returncode == 0,
        "raw": _compact(completed.stdout or completed.stderr),
        "source": _line_value(completed.stdout, "Source") or _line_value(completed.stdout, "Origem"),
        "last_successful_sync": _line_value(completed.stdout, "Last Successful Sync Time")
        or _line_value(completed.stdout, "Ultima sincronizacao bem-sucedida"),
        "stratum": _line_value(completed.stdout, "Stratum") or _line_value(completed.stdout, "Camada"),
        "offset": _line_value(completed.stdout, "Phase Offset") or _line_value(completed.stdout, "Deslocamento"),
        "service_active": completed.returncode == 0,
    }
    return payload


def _line_value(output: str, label: str) -> str | None:
    for line in output.splitlines():
        if label.lower() in line.lower() and ":" in line:
            return line.split(":", 1)[1].strip()
    return None


def _compact(value: str, limit: int = 800) -> str:
    return " ".join(value.split())[:limit]
