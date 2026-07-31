"""VPN, proxy and virtual adapter context."""

from __future__ import annotations

from typing import Any

from src.utils.windows_command import run_windows_command


_VIRTUAL_TOKENS = ("vpn", "wireguard", "tap", "tun", "hyper-v", "vmware", "virtualbox", "wsl", "zerotier")


def collect_network_environment() -> dict[str, Any]:
    """Collect non-sensitive network environment context."""
    adapters = _adapters()
    virtual_adapters = [
        adapter for adapter in adapters if any(token in adapter.lower() for token in _VIRTUAL_TOKENS)
    ]
    return {
        "adapters": adapters,
        "virtual_adapters": virtual_adapters,
        "vpn_detected": any("vpn" in adapter.lower() for adapter in virtual_adapters),
        "proxy": _winhttp_proxy(),
    }


def _adapters() -> list[str]:
    try:
        completed = run_windows_command(["netsh", "interface", "show", "interface"], timeout=5)
    except Exception:
        return []
    adapters: list[str] = []
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].lower() in {"enabled", "habilitado", "connected", "conectado"}:
            adapters.append(" ".join(parts[3:]))
    return adapters


def _winhttp_proxy() -> dict[str, Any]:
    try:
        completed = run_windows_command(["netsh", "winhttp", "show", "proxy"], timeout=5)
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    output = " ".join(completed.stdout.split())
    enabled = "direct access" not in output.lower() and "acesso direto" not in output.lower()
    return {"available": True, "enabled": enabled, "details": output[:500]}
