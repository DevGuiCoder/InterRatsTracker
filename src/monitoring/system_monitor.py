"""Best-effort system information collector."""

from __future__ import annotations

import getpass
import platform
import socket
from datetime import datetime

from src.monitoring.wifi_monitor import collect_wifi_info
from src.utils.networking import detect_active_interface


def collect_system_info() -> dict[str, object]:
    """Collect diagnostic system and network metadata without sensitive content."""
    interface = detect_active_interface()
    return {
        "computer_name": platform.node() or socket.gethostname(),
        "current_user": _safe_user(),
        "windows_version": platform.platform(),
        "python_version": platform.python_version(),
        "captured_local_time": datetime.now().isoformat(),
        "active_interface": interface.interface_name,
        "local_ip": interface.local_ip,
        "gateway": interface.gateway,
        "connection_type": interface.connection_type,
        "default_route": interface.is_default_route,
        "default_route_metric": interface.default_route_metric,
        "interface_up": interface.is_up,
        "mac_address": interface.mac_address,
        "wifi": collect_wifi_info(),
    }


def _safe_user() -> str | None:
    try:
        return getpass.getuser()
    except Exception:
        return None
