"""Best-effort Wi-Fi diagnostics using Windows netsh."""

from __future__ import annotations

import re

from src.utils.windows_command import run_windows_command


def collect_wifi_info() -> dict[str, object]:
    """Collect Wi-Fi details when a WLAN interface is active."""
    try:
        completed = run_windows_command(["netsh", "wlan", "show", "interfaces"], timeout=5)
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    output = completed.stdout
    lowered = output.lower()
    if completed.returncode != 0 or "there is no wireless interface" in lowered or "nao ha interface sem fio" in lowered or "n\u00e3o h\u00e1 interface sem fio" in lowered:
        return {"available": False}
    state = _value_any(output, ["State", "Estado"])
    signal = _percent(_value_any(output, ["Signal", "Sinal"]))
    receive_rate = _number(_value_any(output, ["Receive rate", "Taxa de Recep\u00e7\u00e3o", "Taxa de Recepcao"]))
    transmit_rate = _number(_value_any(output, ["Transmit rate", "Taxa de Transmiss\u00e3o", "Taxa de Transmissao"]))
    return {
        "available": True,
        "connected": _connected(state),
        "ssid": _value_any(output, ["SSID"]),
        "bssid_masked": _mask_bssid(_value_any(output, ["BSSID"])),
        "signal_percent": signal,
        "radio_type": _value_any(output, ["Radio type", "Tipo de radio", "Tipo de r\u00e1dio"]),
        "channel": _value_any(output, ["Channel", "Canal"]),
        "receive_rate_mbps": receive_rate,
        "transmit_rate_mbps": transmit_rate,
        "state": state,
    }


def _value_any(output: str, labels: list[str]) -> str | None:
    for label in labels:
        value = _value(output, label)
        if value:
            return value
    return None


def _value(output: str, label: str) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(label)}\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(output)
    return match.group(1).strip() if match else None


def _percent(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else None


def _number(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"(\d+(?:[,.]\d+)?)", value)
    return float(match.group(1).replace(",", ".")) if match else None


def _connected(state: str | None) -> bool | None:
    if not state:
        return None
    lowered = state.lower()
    if "connected" in lowered or "conectado" in lowered:
        return True
    if "disconnected" in lowered or "desconectado" in lowered:
        return False
    return None


def _mask_bssid(value: str | None) -> str | None:
    if not value:
        return None
    parts = re.split(r"[:-]", value.strip())
    if len(parts) < 6:
        return value[:4] + "..." if len(value) > 4 else value
    return ":".join([parts[0], parts[1], "**", "**", parts[-2], parts[-1]])
