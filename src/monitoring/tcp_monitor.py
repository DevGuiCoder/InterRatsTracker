"""TCP connectivity probes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import perf_counter

from src.storage.models import ProbeResult, ProbeStatus, TargetDefinition


async def tcp_connect_once(target: TargetDefinition, timeout_seconds: float = 2.0) -> ProbeResult:
    """Open and close one TCP connection to a target."""
    started = datetime.now(UTC)
    begin = perf_counter()
    if target.port is None:
        return ProbeResult(
            target=target,
            collected_at=started,
            status=ProbeStatus.UNKNOWN,
            latency_ms=None,
            error="target port not configured",
            details={"probe": "tcp"},
        )

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(target.host, target.port),
            timeout=timeout_seconds,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        del reader
    except (OSError, TimeoutError, asyncio.TimeoutError) as exc:
        return ProbeResult(
            target=target,
            collected_at=started,
            status=ProbeStatus.OFFLINE,
            latency_ms=None,
            error=str(exc),
            details={"probe": "tcp", "port": target.port},
        )

    return ProbeResult(
        target=target,
        collected_at=started,
        status=ProbeStatus.ONLINE,
        latency_ms=(perf_counter() - begin) * 1000,
        error=None,
        details={"probe": "tcp", "port": target.port},
    )
