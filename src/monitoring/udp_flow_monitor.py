"""Optional UDP flow test scaffold."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import perf_counter
from typing import Any


async def run_udp_flow_test(config: dict[str, Any]) -> dict[str, Any]:
    """Run an optional controlled UDP echo-like flow test when configured."""
    host = str(config.get("host") or "").strip()
    port = int(config.get("port") or 0)
    if not host or not 1 <= port <= 65535:
        return {
            "enabled": False,
            "status": "not_configured",
            "message": "Teste UDP avancado nao configurado.",
        }
    duration_seconds = float(config.get("duration_seconds", 10.0))
    interval_seconds = float(config.get("interval_seconds", 0.02))
    payload_size = int(config.get("payload_size_bytes", 64))
    started = datetime.now(UTC)
    begin = perf_counter()
    sent = 0
    transport = None
    try:
        loop = asyncio.get_running_loop()
        transport, _protocol = await loop.create_datagram_endpoint(
            lambda: asyncio.DatagramProtocol(),
            remote_addr=(host, port),
        )
        payload = b"vigos-udp-test".ljust(payload_size, b"0")
        while perf_counter() - begin < duration_seconds:
            transport.sendto(payload)
            sent += 1
            await asyncio.sleep(interval_seconds)
    except OSError as exc:
        return {
            "enabled": True,
            "status": "failed",
            "started_at": started.isoformat(),
            "error": str(exc),
            "packets_sent": sent,
        }
    finally:
        if transport is not None:
            transport.close()
    return {
        "enabled": True,
        "status": "sent_only",
        "started_at": started.isoformat(),
        "duration_seconds": perf_counter() - begin,
        "packets_sent": sent,
        "packets_received": None,
        "packet_loss_percent": None,
        "jitter_ms": None,
        "message": "Sem servidor de retorno configurado, o teste mede apenas envio controlado.",
    }
