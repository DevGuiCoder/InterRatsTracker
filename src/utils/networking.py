"""Network utility helpers for Windows-focused diagnostics."""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass

from src.utils.windows_command import run_windows_command


@dataclass(frozen=True)
class InterfaceSnapshot:
    """Best-effort information about the active network path."""

    interface_name: str | None
    local_ip: str | None
    gateway: str | None
    connection_type: str | None
    default_route_metric: int | None = None
    is_default_route: bool = False
    is_up: bool | None = None
    mac_address: str | None = None


def detect_active_interface() -> InterfaceSnapshot:
    """Detect active interface details without requiring administrator privileges."""
    route = _detect_default_route()
    local_ip = route.get("interface_ip") if route else _detect_local_ip()
    gateway = route.get("gateway") if route else detect_default_gateway()
    details = _interface_details_for_ip(local_ip)
    interface_name = details.get("name") or _interface_name_for_ip(local_ip)
    return InterfaceSnapshot(
        interface_name=interface_name,
        local_ip=local_ip,
        gateway=gateway,
        connection_type=_connection_type(interface_name),
        default_route_metric=int(route["metric"]) if route and route.get("metric") is not None else None,
        is_default_route=bool(route),
        is_up=details.get("is_up"),
        mac_address=details.get("mac"),
    )


def detect_default_gateway() -> str | None:
    """Return the IPv4 default gateway from Windows route output when available."""
    route = _detect_default_route()
    if route:
        return route.get("gateway")
    return None


def _detect_default_route() -> dict[str, str | int] | None:
    """Return the best IPv4 default route row parsed from Windows route output."""
    try:
        completed = run_windows_command(["route", "print", "-4", "0.0.0.0"], timeout=5)
    except Exception:
        return None

    routes: list[dict[str, str | int]] = []
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
            gateway = parts[2]
            interface_ip = parts[3]
            metric = _safe_int(parts[4])
            if _is_ipv4(gateway) and _is_ipv4(interface_ip):
                routes.append(
                    {
                        "gateway": gateway,
                        "interface_ip": interface_ip,
                        "metric": metric if metric is not None else 999999,
                    }
                )
    return min(routes, key=lambda item: int(item["metric"])) if routes else None


def is_ip_address(value: str) -> bool:
    """Return True when a value is an IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _detect_local_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return None


def _interface_name_for_ip(local_ip: str | None) -> str | None:
    if not local_ip:
        return None
    try:
        completed = run_windows_command(["ipconfig"], timeout=5)
    except Exception:
        return None

    current_adapter: str | None = None
    for raw_line in completed.stdout.splitlines():
        line = raw_line.rstrip()
        adapter_match = re.match(r"^(.+ adapter .+|Adaptador .+):$", line, flags=re.IGNORECASE)
        if adapter_match:
            current_adapter = adapter_match.group(1).strip()
            continue
        if local_ip in line:
            return current_adapter
    return None


def _interface_details_for_ip(local_ip: str | None) -> dict[str, object]:
    if not local_ip:
        return {}
    try:
        import psutil
    except Exception:
        return {}
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except Exception:
        return {}
    for name, addresses in addrs.items():
        has_ip = any(getattr(address, "address", None) == local_ip for address in addresses)
        if not has_ip:
            continue
        mac = next(
            (
                getattr(address, "address", None)
                for address in addresses
                if str(getattr(address, "family", "")).lower().endswith("af_link")
                or getattr(address, "family", None) == getattr(psutil, "AF_LINK", object())
            ),
            None,
        )
        return {
            "name": name,
            "is_up": stats.get(name).isup if name in stats else None,
            "mac": _mask_mac(mac),
        }
    return {}


def _connection_type(interface_name: str | None) -> str | None:
    if not interface_name:
        return None
    lowered = interface_name.lower()
    if "wi-fi" in lowered or "wireless" in lowered or "wlan" in lowered:
        return "Wi-Fi"
    if "ethernet" in lowered:
        return "Ethernet"
    if "vpn" in lowered or "wireguard" in lowered or "tap" in lowered or "tun" in lowered:
        return "VPN/Virtual"
    return "Unknown"


def _is_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return True


def _safe_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _mask_mac(value: object) -> str | None:
    if not value:
        return None
    text = str(value)
    parts = re.split(r"[:-]", text)
    if len(parts) >= 6:
        return ":".join([parts[0], parts[1], "**", "**", parts[-2], parts[-1]])
    return text[:4] + "..." if len(text) > 4 else text
