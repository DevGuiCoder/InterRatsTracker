"""DNS resolution probes."""

from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime
from time import perf_counter

from src.storage.models import ProbeResult, ProbeStatus, TargetDefinition


async def resolve_once(target: TargetDefinition, timeout_seconds: float = 2.0) -> ProbeResult:
    """Resolve a hostname and measure resolution time."""
    started = datetime.now(UTC)
    begin = perf_counter()
    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, target.host, None),
            timeout=timeout_seconds,
        )
    except (OSError, TimeoutError, asyncio.TimeoutError) as exc:
        return ProbeResult(
            target=target,
            collected_at=started,
            status=ProbeStatus.OFFLINE,
            latency_ms=None,
            error=str(exc),
            details={"probe": "dns"},
        )

    resolved_ips = sorted({item[4][0] for item in results if item[4]})
    return ProbeResult(
        target=target,
        collected_at=started,
        status=ProbeStatus.ONLINE if resolved_ips else ProbeStatus.OFFLINE,
        latency_ms=(perf_counter() - begin) * 1000,
        error=None if resolved_ips else "no addresses returned",
        details={"probe": "dns", "resolved_ips": resolved_ips},
    )
