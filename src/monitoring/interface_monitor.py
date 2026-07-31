"""Network interface snapshot helpers."""

from __future__ import annotations

from src.utils.networking import InterfaceSnapshot, detect_active_interface


def collect_interface_snapshot() -> InterfaceSnapshot:
    """Return current active interface snapshot."""
    return detect_active_interface()
