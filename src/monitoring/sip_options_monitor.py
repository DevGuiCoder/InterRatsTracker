"""SIP OPTIONS monitor without credentials."""

from __future__ import annotations

import asyncio
import socket
import ssl
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4


_ACCESSIBLE_CODES = {200, 401, 403, 404}
_UNAVAILABLE_CODES = {408, 480, 500, 502, 503, 504}


async def sip_options_once(
    host: str,
    port: int,
    transport: str = "UDP",
    timeout_seconds: float = 3.0,
    cseq: int = 1,
) -> dict[str, Any]:
    """Send one SIP OPTIONS request and classify the response cautiously."""
    transport = transport.upper()
    started = datetime.now(UTC)
    begin = perf_counter()
    call_id = f"{uuid4()}@vigos-monitor"
    request = _build_options_request(host, port, transport, call_id, cseq)
    try:
        if transport == "UDP":
            response = await _udp_options(host, port, request, timeout_seconds)
        elif transport == "TCP":
            response = await _tcp_options(host, port, request, timeout_seconds, tls=False)
        elif transport == "TLS":
            response = await _tcp_options(host, port, request, timeout_seconds, tls=True)
        else:
            return _result(started, transport, host, port, perf_counter() - begin, "unknown", error="transporte nao suportado")
    except TimeoutError:
        status = "inconclusive" if transport == "UDP" else "offline"
        return _result(started, transport, host, port, perf_counter() - begin, status, error="timeout")
    except ssl.SSLError as exc:
        return _result(started, transport, host, port, perf_counter() - begin, "offline", error=f"erro TLS: {exc}")
    except OSError as exc:
        return _result(started, transport, host, port, perf_counter() - begin, "offline", error=str(exc))

    code, reason = parse_sip_status(response)
    classification = classify_sip_code(code, transport)
    return _result(
        started,
        transport,
        host,
        port,
        perf_counter() - begin,
        classification,
        code=code,
        reason=reason,
        response_excerpt=response[:500],
    )


async def test_sip_transport(host: str, port: int, transport: str, timeout_seconds: float = 3.0) -> dict[str, Any]:
    """Test TCP/TLS connection or report UDP as options-dependent."""
    transport = transport.upper()
    started = datetime.now(UTC)
    begin = perf_counter()
    if transport == "UDP":
        return {
            "transport": "UDP",
            "host": host,
            "port": port,
            "started_at": started.isoformat(),
            "status": "inconclusive",
            "message": "UDP sem resposta de aplicacao nao comprova porta fechada.",
        }
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout_seconds)
        certificate: dict[str, Any] | None = None
        if transport == "TLS":
            writer.close()
            await writer.wait_closed()
            context = ssl.create_default_context()
            certificate = await asyncio.to_thread(_tls_certificate, host, port, timeout_seconds, context)
        else:
            writer.close()
            await writer.wait_closed()
        del reader
    except Exception as exc:
        return {
            "transport": transport,
            "host": host,
            "port": port,
            "started_at": started.isoformat(),
            "duration_ms": (perf_counter() - begin) * 1000,
            "status": "offline",
            "error": str(exc),
        }
    return {
        "transport": transport,
        "host": host,
        "port": port,
        "started_at": started.isoformat(),
        "duration_ms": (perf_counter() - begin) * 1000,
        "status": "online",
        "certificate": certificate,
    }


def parse_sip_status(response: str) -> tuple[int | None, str | None]:
    """Parse SIP status code and reason phrase."""
    first_line = response.splitlines()[0] if response.splitlines() else ""
    parts = first_line.split(maxsplit=2)
    if len(parts) >= 2 and parts[0].upper().startswith("SIP/"):
        try:
            return int(parts[1]), parts[2] if len(parts) > 2 else ""
        except ValueError:
            return None, None
    return None, None


def classify_sip_code(code: int | None, transport: str) -> str:
    """Classify SIP response without treating only 200 as available."""
    if code in _ACCESSIBLE_CODES:
        return "online"
    if code in _UNAVAILABLE_CODES:
        return "degraded"
    if code is None:
        return "inconclusive" if transport.upper() == "UDP" else "unknown"
    if 100 <= code < 700:
        return "online"
    return "inconclusive"


def _build_options_request(host: str, port: int, transport: str, call_id: str, cseq: int) -> bytes:
    target = f"sip:{host}:{port}"
    message = "\r\n".join(
        [
            f"OPTIONS {target} SIP/2.0",
            f"Via: SIP/2.0/{transport} vigos-monitor.local;branch=z9hG4bK-{uuid4().hex}",
            "Max-Forwards: 70",
            f"To: <{target}>",
            f"From: <sip:vigos-monitor@localhost>;tag={uuid4().hex[:8]}",
            f"Call-ID: {call_id}",
            f"CSeq: {cseq} OPTIONS",
            "Contact: <sip:vigos-monitor@localhost>",
            "User-Agent: InterRatsTracker",
            "Content-Length: 0",
            "",
            "",
        ]
    )
    return message.encode("utf-8")


async def _udp_options(host: str, port: int, request: bytes, timeout_seconds: float) -> str:
    def run() -> str:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout_seconds)
            sock.sendto(request, (host, port))
            data, _addr = sock.recvfrom(4096)
            return data.decode("utf-8", errors="replace")

    try:
        return await asyncio.to_thread(run)
    except socket.timeout as exc:
        raise TimeoutError from exc


async def _tcp_options(host: str, port: int, request: bytes, timeout_seconds: float, tls: bool) -> str:
    if tls:
        context = ssl.create_default_context()
        raw_reader, raw_writer = await asyncio.wait_for(asyncio.open_connection(host, port, ssl=context, server_hostname=host), timeout=timeout_seconds)
    else:
        raw_reader, raw_writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout_seconds)
    raw_writer.write(request)
    await raw_writer.drain()
    data = await asyncio.wait_for(raw_reader.read(4096), timeout=timeout_seconds)
    raw_writer.close()
    await raw_writer.wait_closed()
    return data.decode("utf-8", errors="replace")


def _tls_certificate(host: str, port: int, timeout_seconds: float, context: ssl.SSLContext) -> dict[str, Any]:
    with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
        with context.wrap_socket(sock, server_hostname=host) as secure:
            cert = secure.getpeercert()
    return {
        "validated": True,
        "not_after": cert.get("notAfter"),
        "issuer": cert.get("issuer"),
        "subject": cert.get("subject"),
    }


def _result(
    started: datetime,
    transport: str,
    host: str,
    port: int,
    duration_seconds: float,
    status: str,
    code: int | None = None,
    reason: str | None = None,
    response_excerpt: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "started_at": started.isoformat(),
        "transport": transport,
        "host": host,
        "port": port,
        "duration_ms": duration_seconds * 1000,
        "status": status,
        "sip_code": code,
        "sip_reason": reason,
        "response_excerpt": response_excerpt,
        "error": error,
    }
