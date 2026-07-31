"""Audio device enumeration with optional Windows/audio backends."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.audio.audio_models import AudioDevice, AudioDeviceState, AudioDirection, AudioInventory
from src.audio.driver_inspector import inspect_audio_drivers

_VIRTUAL_TOKENS = (
    "vb-audio",
    "voicemeeter",
    "virtual audio",
    "virtual cable",
    "obs virtual",
    "remote audio",
    "teams audio",
    "zoom audio",
)


def collect_audio_inventory(include_driver_info: bool = True) -> AudioInventory:
    """Collect best-effort audio inventory without capturing audio content."""
    errors: list[str] = []
    devices: list[AudioDevice] = []
    default_input_id: str | None = None
    default_output_id: str | None = None

    sounddevice_payload = _sounddevice_devices(errors)
    devices.extend(sounddevice_payload["devices"])
    default_input_id = sounddevice_payload.get("default_input_id")
    default_output_id = sounddevice_payload.get("default_output_id")

    if include_driver_info:
        driver_payload = inspect_audio_drivers()
        if not driver_payload.get("available"):
            if driver_payload.get("error"):
                errors.append(str(driver_payload["error"]))
        else:
            devices = _merge_driver_info(devices, driver_payload.get("drivers", []))

    return AudioInventory(
        collected_at=datetime.now(UTC),
        available=bool(devices) or not errors,
        devices=devices,
        default_input_id=default_input_id,
        default_output_id=default_output_id,
        communication_input_id=None,
        communication_output_id=None,
        errors=errors,
    )


def inventory_summary(inventory: AudioInventory) -> dict[str, Any]:
    """Return a compact summary for console and snapshots."""
    inputs = [device for device in inventory.devices if device.direction == AudioDirection.INPUT]
    outputs = [device for device in inventory.devices if device.direction == AudioDirection.OUTPUT]
    default_input = _find(inventory.devices, inventory.default_input_id)
    default_output = _find(inventory.devices, inventory.default_output_id)
    driver_errors = [
        device for device in inventory.devices
        if device.state == AudioDeviceState.DRIVER_ERROR or (device.pnp_error_code not in (None, 0))
    ]
    return {
        "available": inventory.available,
        "collected_at": inventory.collected_at.isoformat(),
        "input_count": len(inputs),
        "output_count": len(outputs),
        "device_count": len(inventory.devices),
        "default_input": default_input.name if default_input else None,
        "default_output": default_output.name if default_output else None,
        "communication_input": _find(inventory.devices, inventory.communication_input_id).name if inventory.communication_input_id else None,
        "communication_output": _find(inventory.devices, inventory.communication_output_id).name if inventory.communication_output_id else None,
        "driver_error_count": len(driver_errors),
        "virtual_device_count": sum(1 for device in inventory.devices if device.is_virtual),
        "errors": inventory.errors or [],
    }


def _sounddevice_devices(errors: list[str]) -> dict[str, Any]:
    try:
        import sounddevice as sd
    except Exception as exc:
        errors.append(f"sounddevice indisponivel: {exc}")
        return {"devices": [], "default_input_id": None, "default_output_id": None}

    try:
        raw_devices = sd.query_devices()
        default_input, default_output = sd.default.device
    except Exception as exc:
        errors.append(f"falha ao consultar dispositivos de audio: {exc}")
        return {"devices": [], "default_input_id": None, "default_output_id": None}

    devices: list[AudioDevice] = []
    for index, raw in enumerate(raw_devices):
        name = str(raw.get("name") or f"Audio device {index}")
        max_input = int(raw.get("max_input_channels") or 0)
        max_output = int(raw.get("max_output_channels") or 0)
        if max_input <= 0 and max_output <= 0:
            direction = AudioDirection.UNKNOWN
        elif max_input >= max_output:
            direction = AudioDirection.INPUT
        else:
            direction = AudioDirection.OUTPUT
        stable_id = f"sounddevice:{index}:{name}"
        devices.append(
            AudioDevice(
                stable_id=stable_id,
                name=name,
                direction=direction,
                state=AudioDeviceState.ACTIVE,
                device_type="endpoint",
                is_default=(direction == AudioDirection.INPUT and index == default_input)
                or (direction == AudioDirection.OUTPUT and index == default_output),
                is_default_communications=False,
                channels=max(max_input, max_output) or None,
                sample_rate_hz=_optional_int(raw.get("default_samplerate")),
                connection_type=_connection_type(name),
                is_virtual=_is_virtual(name),
                source="sounddevice",
            )
        )
    return {
        "devices": devices,
        "default_input_id": _default_id(devices, default_input),
        "default_output_id": _default_id(devices, default_output),
    }


def _merge_driver_info(devices: list[AudioDevice], drivers: object) -> list[AudioDevice]:
    driver_rows = drivers if isinstance(drivers, list) else []
    merged = list(devices)
    used_indexes: set[int] = set()
    for index, driver in enumerate(driver_rows):
        if not isinstance(driver, dict):
            continue
        name = str(driver.get("friendly_name") or "")
        if not name:
            continue
        match_index = _best_name_match(merged, name)
        state = _state_from_driver(driver)
        if match_index is not None:
            current = merged[match_index]
            merged[match_index] = AudioDevice(
                stable_id=current.stable_id,
                name=current.name,
                direction=current.direction,
                state=state if state == AudioDeviceState.DRIVER_ERROR else current.state,
                manufacturer=current.manufacturer or driver.get("manufacturer"),
                device_type=current.device_type,
                is_default=current.is_default,
                is_default_communications=current.is_default_communications,
                volume_percent=current.volume_percent,
                muted=current.muted,
                channels=current.channels,
                sample_rate_hz=current.sample_rate_hz,
                bit_depth=current.bit_depth,
                connection_type=current.connection_type,
                is_virtual=current.is_virtual,
                driver_version=driver.get("driver_version"),
                driver_date=driver.get("driver_date"),
                pnp_status=driver.get("status"),
                pnp_error_code=driver.get("config_manager_error_code"),
                source=current.source,
            )
            used_indexes.add(index)
            continue
        merged.append(
            AudioDevice(
                stable_id=str(driver.get("instance_id") or f"pnp:{name}"),
                name=name,
                direction=_direction_from_name(name),
                state=state,
                manufacturer=driver.get("manufacturer"),
                device_type=str(driver.get("class") or "PnP"),
                connection_type=_connection_type(name),
                is_virtual=_is_virtual(name),
                driver_version=driver.get("driver_version"),
                driver_date=driver.get("driver_date"),
                pnp_status=driver.get("status"),
                pnp_error_code=driver.get("config_manager_error_code"),
                source="pnp",
            )
        )
    return merged


def _best_name_match(devices: list[AudioDevice], name: str) -> int | None:
    lowered = name.lower()
    for index, device in enumerate(devices):
        device_name = device.name.lower()
        if device_name in lowered or lowered in device_name:
            return index
    return None


def _state_from_driver(driver: dict[str, Any]) -> AudioDeviceState:
    code = driver.get("config_manager_error_code")
    status = str(driver.get("status") or "").lower()
    present = driver.get("present")
    if code not in (None, 0):
        return AudioDeviceState.DISABLED if code == 22 else AudioDeviceState.DRIVER_ERROR
    if present is False:
        return AudioDeviceState.NOT_PRESENT
    if "error" in status:
        return AudioDeviceState.DRIVER_ERROR
    return AudioDeviceState.ACTIVE if status in {"ok", "degraded"} else AudioDeviceState.UNKNOWN


def _direction_from_name(name: str) -> AudioDirection:
    lowered = name.lower()
    if any(token in lowered for token in ("microphone", "mic", "entrada", "input", "capture")):
        return AudioDirection.INPUT
    if any(token in lowered for token in ("speaker", "headphone", "saida", "output", "alto-falante", "monitor")):
        return AudioDirection.OUTPUT
    return AudioDirection.UNKNOWN


def _connection_type(name: str) -> str | None:
    lowered = name.lower()
    if "bluetooth" in lowered or "hands-free" in lowered or "hands free" in lowered:
        return "Bluetooth"
    if "usb" in lowered or "jabra" in lowered or "plantronics" in lowered:
        return "USB"
    if "hdmi" in lowered or "nvidia high definition" in lowered or "monitor" in lowered:
        return "HDMI"
    if "realtek" in lowered or "integrated" in lowered:
        return "Audio integrado/P2"
    if _is_virtual(name):
        return "Virtual"
    return None


def _is_virtual(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in _VIRTUAL_TOKENS)


def _default_id(devices: list[AudioDevice], index: object) -> str | None:
    try:
        numeric = int(index)
    except (TypeError, ValueError):
        return None
    for device in devices:
        if device.stable_id.startswith(f"sounddevice:{numeric}:"):
            return device.stable_id
    return None


def _find(devices: list[AudioDevice], stable_id: str | None) -> AudioDevice | None:
    if not stable_id:
        return None
    return next((device for device in devices if device.stable_id == stable_id), None)


def _optional_int(value: object) -> int | None:
    try:
        return int(float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None
