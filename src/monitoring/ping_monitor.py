"""Asynchronous ICMP ping monitor using the Windows ping command."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import UTC, datetime

from src.storage.models import ProbeResult, ProbeStatus, TargetDefinition

_LATENCY_PATTERNS = [
    re.compile(r"\btime\s*[=<]\s*(\d+(?:[.,]\d+)?)\s*ms", re.IGNORECASE),
    re.compile(r"\btempo\s*[=<]\s*(\d+(?:[.,]\d+)?)\s*ms", re.IGNORECASE),
    re.compile(r"\btime\s+(\d+(?:[.,]\d+)?)\s*ms", re.IGNORECASE),
    re.compile(r"\btempo\s+(\d+(?:[.,]\d+)?)\s*ms", re.IGNORECASE),
    re.compile(r"\bminima\s*=\s*(\d+(?:[.,]\d+)?)\s*ms", re.IGNORECASE),
    re.compile(r"\bminimum\s*=\s*(\d+(?:[.,]\d+)?)\s*ms", re.IGNORECASE),
]


async def ping_once(target: TargetDefinition, timeout_ms: int = 1000) -> ProbeResult:
    """Run one ping probe against a target."""
    started = datetime.now(UTC)
    try:
        process = await asyncio.create_subprocess_exec(
            "ping",
            "-n",
            "1",
            "-w",
            str(timeout_ms),
            target.host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=(timeout_ms / 1000) + 2)
    except (OSError, TimeoutError, asyncio.TimeoutError) as exc:
        return ProbeResult(
            target=target,
            collected_at=started,
            status=ProbeStatus.UNKNOWN,
            latency_ms=None,
            error=str(exc),
            details={"probe": "ping"},
        )

    output = _decode(stdout) + "\n" + _decode(stderr)
    latency = _parse_latency_ms(output)
    details = {
        "probe": "ping",
        "returncode": process.returncode,
        "latency_parse_status": "parsed" if latency is not None else "not_found",
        "output_excerpt": _output_excerpt(output),
    }
    if process.returncode == 0:
        return ProbeResult(
            target=target,
            collected_at=started,
            status=ProbeStatus.ONLINE,
            latency_ms=latency,
            error=None,
            details=details,
        )
    return ProbeResult(
        target=target,
        collected_at=started,
        status=ProbeStatus.OFFLINE,
        latency_ms=None,
        error=_compact_error(output),
        details=details,
    )


def _parse_latency_ms(output: str) -> float | None:
    normalized_output = _strip_accents(output)
    for pattern in _LATENCY_PATTERNS:
        match = pattern.search(normalized_output)
        if match:
            return float(match.group(1).replace(",", "."))
    compact = normalized_output.replace(" ", "").replace("\t", "").lower()
    if any(token in compact for token in ("<1ms", "tempo<1ms", "time<1ms")):
        return 1.0
    return None


def _strip_accents(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )


def _decode(value: bytes) -> str:
    for encoding in ("utf-8", "cp850", "latin-1"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode(errors="replace")


def _compact_error(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else "ping failed"


def _output_excerpt(output: str, limit: int = 800) -> str:
    cleaned = "\n".join(line.strip() for line in output.splitlines() if line.strip())
    return cleaned[:limit]
