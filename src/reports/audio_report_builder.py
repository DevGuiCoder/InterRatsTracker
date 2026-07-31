"""Build presentation-ready audio report data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AudioDeviceReportRow:
    """Audio device row for reports."""

    stable_id: str
    name: str
    direction: str
    state: str
    is_default: bool
    is_default_communications: bool
    volume_percent: float | None
    muted: bool | None
    signal: str
    connection_type: str | None
    is_virtual: bool
    driver_version: str | None
    driver_date: str | None
    pnp_status: str | None
    pnp_error_code: int | None
    pnp_error_interpretation: str | None


@dataclass(frozen=True)
class AudioEventReportRow:
    """Audio event row for reports."""

    occurred_at: datetime
    event_type: str
    device_name: str | None
    previous_state: str | None
    current_state: str | None
    severity: str
    message: str


@dataclass(frozen=True)
class AudioReportView:
    """Audio report view."""

    available: bool
    level_monitoring_enabled: bool
    default_input: str | None
    communication_input: str | None
    default_output: str | None
    communication_output: str | None
    device_count: int
    input_count: int
    output_count: int
    virtual_device_count: int
    driver_error_count: int
    event_count: int
    microphone_test_count: int
    output_test_count: int
    permission_summary: str
    devices: list[AudioDeviceReportRow]
    events: list[AudioEventReportRow]
    microphone_tests: list[dict[str, Any]]
    output_tests: list[dict[str, Any]]
    limitations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_audio_report_view(records_by_table: dict[str, list[object]], level_monitoring_enabled: bool) -> AudioReportView:
    """Build audio report view from diagnostic records."""
    inventory_records = records_by_table.get("audio_device_states") or records_by_table.get("audio_devices") or []
    initial_records = records_by_table.get("audio_devices") or []
    latest_inventory = inventory_records[-1].payload if inventory_records else {}
    devices = [_device_row(item) for item in latest_inventory.get("devices", []) if isinstance(item, dict)]
    if initial_records:
        devices = _merge_driver_rows(devices, initial_records[-1].payload.get("devices", []))
    events = [
        _event_row(record.payload, record.collected_at)
        for record in records_by_table.get("audio_events", [])
    ]
    permissions = (records_by_table.get("audio_permissions") or [])
    permission_payload = permissions[-1].payload if permissions else {}
    microphone_tests = [_public_test_payload(record.payload) for record in records_by_table.get("microphone_tests", [])]
    output_tests = [_public_test_payload(record.payload) for record in records_by_table.get("output_tests", [])]
    return AudioReportView(
        available=bool(latest_inventory.get("available", devices)),
        level_monitoring_enabled=level_monitoring_enabled,
        default_input=_device_name(devices, latest_inventory.get("default_input_id")),
        communication_input=_device_name(devices, latest_inventory.get("communication_input_id")),
        default_output=_device_name(devices, latest_inventory.get("default_output_id")),
        communication_output=_device_name(devices, latest_inventory.get("communication_output_id")),
        device_count=len(devices),
        input_count=sum(1 for item in devices if item.direction == "input"),
        output_count=sum(1 for item in devices if item.direction == "output"),
        virtual_device_count=sum(1 for item in devices if item.is_virtual),
        driver_error_count=sum(1 for item in devices if item.pnp_error_code not in (None, 0)),
        event_count=len(events),
        microphone_test_count=len(microphone_tests),
        output_test_count=len(output_tests),
        permission_summary=_permission_summary(permission_payload),
        devices=devices,
        events=events,
        microphone_tests=microphone_tests,
        output_tests=output_tests,
        limitations=[
            "O modulo de audio nao grava chamadas, nao armazena audio bruto e nao faz reconhecimento de fala.",
            "Teste de reproducao aceito pelo Windows nao comprova funcionamento fisico sem confirmacao auditiva do usuario.",
            "Ausencia de sinal no monitoramento continuo nao e defeito automatico se o usuario nao estava falando.",
        ],
    )


def _device_row(payload: dict[str, Any]) -> AudioDeviceReportRow:
    return AudioDeviceReportRow(
        stable_id=str(payload.get("stable_id") or ""),
        name=str(payload.get("name") or "Dispositivo sem nome"),
        direction=str(payload.get("direction") or "unknown"),
        state=str(payload.get("state") or "UNKNOWN"),
        is_default=bool(payload.get("is_default")),
        is_default_communications=bool(payload.get("is_default_communications")),
        volume_percent=_optional_float(payload.get("volume_percent")),
        muted=payload.get("muted") if isinstance(payload.get("muted"), bool) else None,
        signal="N/D",
        connection_type=payload.get("connection_type"),
        is_virtual=bool(payload.get("is_virtual")),
        driver_version=payload.get("driver_version"),
        driver_date=payload.get("driver_date"),
        pnp_status=payload.get("pnp_status"),
        pnp_error_code=_optional_int(payload.get("pnp_error_code")),
        pnp_error_interpretation=_pnp_interpretation(_optional_int(payload.get("pnp_error_code"))),
    )


def _merge_driver_rows(devices: list[AudioDeviceReportRow], initial_devices: object) -> list[AudioDeviceReportRow]:
    if not isinstance(initial_devices, list):
        return devices
    driver_by_id = {
        str(item.get("stable_id")): item
        for item in initial_devices
        if isinstance(item, dict) and (item.get("driver_version") or item.get("pnp_status") or item.get("pnp_error_code") is not None)
    }
    merged = []
    for device in devices:
        driver = driver_by_id.get(device.stable_id)
        if not driver:
            merged.append(device)
            continue
        merged.append(
            AudioDeviceReportRow(
                **{
                    **asdict(device),
                    "driver_version": device.driver_version or driver.get("driver_version"),
                    "driver_date": device.driver_date or driver.get("driver_date"),
                    "pnp_status": device.pnp_status or driver.get("pnp_status"),
                    "pnp_error_code": device.pnp_error_code if device.pnp_error_code is not None else _optional_int(driver.get("pnp_error_code")),
                    "pnp_error_interpretation": device.pnp_error_interpretation or _pnp_interpretation(_optional_int(driver.get("pnp_error_code"))),
                }
            )
        )
    return merged


def _event_row(payload: dict[str, Any], fallback_at: datetime) -> AudioEventReportRow:
    return AudioEventReportRow(
        occurred_at=_optional_datetime(payload.get("occurred_at")) or fallback_at,
        event_type=str(payload.get("event_type") or "audio_event"),
        device_name=payload.get("device_name"),
        previous_state=payload.get("previous_state"),
        current_state=payload.get("current_state"),
        severity=str(payload.get("severity") or "info"),
        message=str(payload.get("message") or ""),
    )


def _public_test_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "started_at",
        "device_id",
        "device_name",
        "duration_seconds",
        "frames",
        "rms",
        "average_level",
        "peak",
        "silence_percent",
        "saturation",
        "clipping",
        "signal_detected",
        "opened",
        "state",
        "format_used",
        "stream_accepted",
        "user_confirmation",
        "left_channel_tested",
        "right_channel_tested",
        "result",
        "error",
        "privacy_note",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _device_name(devices: list[AudioDeviceReportRow], stable_id: object) -> str | None:
    if not stable_id:
        return None
    match = next((item for item in devices if item.stable_id == stable_id), None)
    return match.name if match else None


def _permission_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "N/D"
    global_access = payload.get("global_access", "N/D")
    desktop = payload.get("desktop_apps", "N/D")
    return f"Microfone global: {global_access}; aplicativos desktop: {desktop}"


def _pnp_interpretation(code: int | None) -> str | None:
    mapping = {
        0: "O dispositivo esta funcionando corretamente.",
        10: "O dispositivo nao pode ser iniciado.",
        22: "O dispositivo esta desabilitado.",
        28: "Driver nao instalado.",
        43: "O Windows interrompeu este dispositivo porque relatou problemas.",
    }
    if code is None:
        return None
    return mapping.get(code, "Codigo de erro do Windows nao mapeado.")


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
