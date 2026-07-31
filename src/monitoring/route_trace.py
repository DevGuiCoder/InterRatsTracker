"""Controlled route tracing."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from src.utils.windows_command import run_windows_command


def collect_route_trace(host: str, timeout_seconds: float = 20.0, reason: str = "coleta complementar") -> dict[str, Any]:
    """Run a bounded Windows tracert and parse hops as complementary evidence."""
    started = datetime.now(UTC)
    begin = perf_counter()
    try:
        completed = run_windows_command(["tracert", "-d", "-h", "20", "-w", "1000", host], timeout=timeout_seconds)
    except Exception as exc:
        return {
            "available": False,
            "reason": reason,
            "started_at": started.isoformat(),
            "duration_seconds": perf_counter() - begin,
            "error": str(exc),
            "hops": [],
        }
    return {
        "available": completed.returncode == 0,
        "reason": reason,
        "started_at": started.isoformat(),
        "duration_seconds": perf_counter() - begin,
        "returncode": completed.returncode,
        "hops": _parse_hops(completed.stdout),
        "raw_excerpt": " ".join((completed.stdout or completed.stderr).split())[:1200],
        "note": "Saltos sem resposta nao comprovam falha; traceroute e evidencia complementar.",
    }


def compare_routes(baseline: dict[str, Any] | None, current: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare two parsed routes cautiously."""
    if not baseline:
        return []
    base_hops = [hop.get("address") for hop in baseline.get("hops", [])]
    current_hops = [hop.get("address") for hop in current.get("hops", [])]
    differences: list[dict[str, Any]] = []
    if base_hops and current_hops and len(base_hops) != len(current_hops):
        differences.append({"field_name": "route.hop_count", "message": "Quantidade de saltos mudou."})
    if base_hops[:3] and current_hops[:3] and base_hops[:3] != current_hops[:3]:
        differences.append({"field_name": "route.first_hops", "message": "Primeiros saltos da rota mudaram."})
    return differences


def _parse_hops(output: str) -> list[dict[str, Any]]:
    hops: list[dict[str, Any]] = []
    for line in output.splitlines():
        match = re.match(r"\s*(\d+)\s+(.+)$", line)
        if not match:
            continue
        address_match = re.search(r"((?:\d{1,3}\.){3}\d{1,3})", line)
        times = _parse_times(line)
        timeout = "*" in line and address_match is None
        hops.append(
            {
                "hop": int(match.group(1)),
                "address": address_match.group(1) if address_match else None,
                "time_1_ms": times[0] if len(times) > 0 else None,
                "time_2_ms": times[1] if len(times) > 1 else None,
                "time_3_ms": times[2] if len(times) > 2 else None,
                "timeout": timeout,
            }
        )
    return hops


def _parse_times(line: str) -> list[float | None]:
    values: list[float | None] = []
    for match in re.finditer(r"(<\s*1|\d+)\s*ms", line, flags=re.IGNORECASE):
        value = match.group(1).replace(" ", "")
        values.append(0.5 if value.startswith("<") else float(value))
    return values[:3]
