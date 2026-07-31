"""Public IP discovery with provider fallback."""

from __future__ import annotations

import ipaddress
import urllib.request
from typing import Any


def collect_public_ip(providers: list[str], timeout_seconds: float = 3.0) -> dict[str, Any]:
    """Discover public IP with multiple providers and safe failure handling."""
    attempts: list[dict[str, Any]] = []
    ipv4: str | None = None
    ipv6: str | None = None
    for provider in providers:
        try:
            with urllib.request.urlopen(provider, timeout=timeout_seconds) as response:
                value = response.read(128).decode("utf-8", errors="replace").strip()
            parsed = ipaddress.ip_address(value)
            if parsed.version == 4 and ipv4 is None:
                ipv4 = str(parsed)
            if parsed.version == 6 and ipv6 is None:
                ipv6 = str(parsed)
            attempts.append({"provider": provider, "status": "ok", "value": str(parsed)})
        except Exception as exc:
            attempts.append({"provider": provider, "status": "failed", "error": str(exc)})
    return {
        "ipv4": ipv4,
        "ipv6": ipv6,
        "attempts": attempts,
        "possible_cgnat": False,
        "note": "CGNAT e apresentado como indicio somente quando houver dados suficientes.",
    }
