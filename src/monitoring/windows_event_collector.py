"""Incremental Windows Event Log collection for relevant diagnostics."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.utils.powershell import run_powershell_json


PROVIDERS = [
    "Microsoft-Windows-WLAN-AutoConfig",
    "Microsoft-Windows-Dhcp-Client",
    "Microsoft-Windows-DNS-Client",
    "Microsoft-Windows-TCPIP",
    "Microsoft-Windows-NetworkProfile",
    "Microsoft-Windows-Kernel-PnP",
    "Microsoft-Windows-UserPnp",
    "DriverFrameworks-UserMode",
    "Microsoft-Windows-Audio",
    "AudioSrv",
    "Microsoft-Windows-Bluetooth",
    "Microsoft-Windows-USB",
    "Microsoft-Windows-Kernel-Power",
    "Microsoft-Windows-Power-Troubleshooter",
]


@dataclass(frozen=True)
class WindowsEvent:
    """Normalized Windows event."""

    occurred_at: datetime
    provider: str
    windows_event_id: int | None
    level: str | None
    category: str
    device_name: str | None
    device_id: str | None
    normalized_type: str
    summary: str
    technical_details: str
    relevance: str
    marker_ids: list[int]

    def to_dict(self) -> dict[str, object]:
        return {
            "occurred_at": self.occurred_at.isoformat(),
            "provider": self.provider,
            "windows_event_id": self.windows_event_id,
            "level": self.level,
            "category": self.category,
            "device_name": self.device_name,
            "device_id": self.device_id,
            "normalized_type": self.normalized_type,
            "summary": self.summary,
            "technical_details": self.technical_details,
            "relevance": self.relevance,
            "marker_ids": self.marker_ids,
        }


class WindowsEventCollector:
    """Collect Windows events incrementally with deduplication."""

    def __init__(
        self,
        providers: list[str] | None = None,
        max_seen: int = 1000,
        runner=run_powershell_json,
    ) -> None:
        self._providers = providers or PROVIDERS
        self._runner = runner
        self._last_query_at: datetime | None = None
        self._seen: deque[str] = deque(maxlen=max(1, max_seen))
        self._seen_set: set[str] = set()

    def collect_since(self, since: datetime, until: datetime | None = None, max_events: int = 80) -> dict[str, Any]:
        """Return normalized events since the previous collection window."""
        start = max(since, self._last_query_at) if self._last_query_at else since
        end = until or datetime.now(UTC)
        self._last_query_at = end
        raw = self._query(start, end, max_events)
        if not raw.get("available"):
            return {"available": False, "error": raw.get("error", "Eventos do Windows indisponiveis."), "events": []}
        items = raw.get("events") or raw.get("items") or []
        if isinstance(items, dict):
            items = [items]
        events = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            event = normalize_windows_event(item)
            key = _event_key(event)
            if key in self._seen_set:
                continue
            self._remember(key)
            events.append(event.to_dict())
        return {"available": True, "events": events, "since": start.isoformat(), "until": end.isoformat()}

    def _query(self, since: datetime, until: datetime, max_events: int) -> dict[str, Any]:
        provider_array = "@(" + ",".join(f"'{provider}'" for provider in self._providers) + ")"
        start = since.isoformat()
        end = until.isoformat()
        script = f"""
$providers = {provider_array}
$start = [datetime]::Parse('{start}')
$end = [datetime]::Parse('{end}')
$items = foreach ($provider in $providers) {{
  try {{
    Get-WinEvent -FilterHashtable @{{ProviderName=$provider; StartTime=$start; EndTime=$end}} -MaxEvents {int(max_events)} -ErrorAction Stop |
      Select-Object TimeCreated, ProviderName, Id, LevelDisplayName, TaskDisplayName, Message
  }} catch {{
    [pscustomobject]@{{ TimeCreated=$null; ProviderName=$provider; Id=$null; LevelDisplayName='N/D'; TaskDisplayName='unavailable'; Message=$_.Exception.Message }}
  }}
}}
[pscustomobject]@{{ events = @($items) }} | ConvertTo-Json -Depth 4 -Compress
"""
        return self._runner(script, timeout=10.0)

    def _remember(self, key: str) -> None:
        if len(self._seen) == self._seen.maxlen and self._seen:
            old = self._seen.popleft()
            self._seen_set.discard(old)
        self._seen.append(key)
        self._seen_set.add(key)


def normalize_windows_event(raw: dict[str, Any]) -> WindowsEvent:
    provider = str(raw.get("ProviderName") or raw.get("provider") or "N/D")
    message = _compact(str(raw.get("Message") or raw.get("message") or ""))
    event_id = _optional_int(raw.get("Id") or raw.get("windows_event_id"))
    occurred_at = _parse_datetime(raw.get("TimeCreated") or raw.get("occurred_at")) or datetime.now(UTC)
    normalized_type, category, relevance = _classify(provider, event_id, message)
    return WindowsEvent(
        occurred_at=occurred_at,
        provider=provider,
        windows_event_id=event_id,
        level=_optional_str(raw.get("LevelDisplayName") or raw.get("level")),
        category=category,
        device_name=_extract_device_name(message),
        device_id=_extract_device_id(message),
        normalized_type=normalized_type,
        summary=_summary(normalized_type, provider, event_id),
        technical_details=message[:500],
        relevance=relevance,
        marker_ids=[],
    )


def _classify(provider: str, event_id: int | None, message: str) -> tuple[str, str, str]:
    lowered = f"{provider} {message}".lower()
    if "wlan" in lowered or "wi-fi" in lowered or "wireless" in lowered:
        if any(token in lowered for token in ("disconnect", "desconect", "disassociated")):
            return "windows_wifi_disconnected", "wifi", "alta"
        if any(token in lowered for token in ("connect", "conect", "associated")):
            return "windows_wifi_connected", "wifi", "media"
        return "windows_network_profile_changed", "wifi", "media"
    if "dhcp" in lowered:
        return "windows_dhcp_renewed", "network", "media"
    if "dns" in lowered:
        return "windows_dns_failure", "dns", "media"
    if "networkprofile" in lowered or "tcpip" in lowered:
        return "windows_network_profile_changed", "network", "media"
    if "usb" in lowered:
        if any(token in lowered for token in ("remove", "removed", "desconect")):
            return "windows_usb_disconnected", "usb", "alta"
        return "windows_usb_connected", "usb", "media"
    if "audio" in lowered or "audiosrv" in lowered:
        if any(token in lowered for token in ("remove", "removed", "desconect")):
            return "windows_audio_device_removed", "audio", "alta"
        if "service" in lowered or "servico" in lowered:
            return "windows_audio_service_restarted", "audio", "alta"
        return "windows_audio_device_connected", "audio", "media"
    if "bluetooth" in lowered:
        if any(token in lowered for token in ("disconnect", "desconect", "remove")):
            return "windows_bluetooth_disconnected", "bluetooth", "alta"
        return "windows_bluetooth_connected", "bluetooth", "media"
    if "power-troubleshooter" in lowered or event_id == 1:
        return "windows_resume", "power", "alta"
    if "kernel-power" in lowered:
        return "windows_power_state_changed", "power", "alta"
    if "pnp" in lowered or "driverframeworks" in lowered:
        return "windows_adapter_reset", "driver", "media"
    return "windows_event_relevant", "system", "baixa"


def _summary(normalized_type: str, provider: str, event_id: int | None) -> str:
    return f"{normalized_type} registrado por {provider}" + (f" (ID {event_id})." if event_id else ".")


def _event_key(event: WindowsEvent) -> str:
    return f"{event.provider}|{event.windows_event_id}|{event.occurred_at.isoformat()}|{event.normalized_type}"


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _extract_device_name(message: str) -> str | None:
    for marker in ("Device Name:", "Nome do dispositivo:", "Device:"):
        if marker in message:
            return message.split(marker, 1)[1].splitlines()[0][:120].strip()
    return None


def _extract_device_id(message: str) -> str | None:
    for marker in ("Device ID:", "Instance ID:", "ID da instancia:"):
        if marker in message:
            return message.split(marker, 1)[1].splitlines()[0][:160].strip()
    return None


def _compact(value: str) -> str:
    return " ".join(value.split())


def _optional_str(value: object) -> str | None:
    return None if value in (None, "") else str(value)


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
