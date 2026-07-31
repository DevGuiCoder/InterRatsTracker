"""Audio PnP and driver inspection."""

from __future__ import annotations

from typing import Any

from src.utils.powershell import run_powershell_json


CONFIG_MANAGER_ERROR_MESSAGES = {
    0: "O dispositivo esta funcionando corretamente.",
    10: "O dispositivo nao pode ser iniciado.",
    22: "O dispositivo esta desabilitado.",
    28: "Driver nao instalado",
    43: "O Windows interrompeu este dispositivo porque relatou problemas.",
}


def inspect_audio_drivers(timeout_seconds: float = 8.0) -> dict[str, Any]:
    """Return PnP/driver information for audio-related devices."""
    script = r"""
$devices = Get-CimInstance Win32_PnPEntity |
  Where-Object {
    $_.PNPClass -in @('AudioEndpoint','MEDIA','Bluetooth') -or
    $_.Name -match 'audio|microphone|speaker|headset|bluetooth|jabra|realtek|nvidia high definition'
  } |
  Select-Object PNPDeviceID, Name, Manufacturer, Status, ConfigManagerErrorCode, Service, PNPClass, Present
$drivers = Get-CimInstance Win32_PnPSignedDriver |
  Where-Object {
    $_.DeviceClass -in @('MEDIA','AudioEndpoint','Bluetooth') -or
    $_.DeviceName -match 'audio|microphone|speaker|headset|bluetooth|jabra|realtek|nvidia high definition'
  } |
  Select-Object DeviceID, DeviceName, DriverVersion, DriverDate, Manufacturer
[pscustomobject]@{ devices = $devices; drivers = $drivers } | ConvertTo-Json -Depth 5 -Compress
"""
    result = run_powershell_json(script, timeout=timeout_seconds)
    if not result.get("available"):
        return result
    devices = _list(result.get("devices"))
    drivers = _list(result.get("drivers"))
    driver_by_id = {str(item.get("DeviceID", "")).lower(): item for item in drivers if isinstance(item, dict)}
    enriched = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        instance_id = str(device.get("PNPDeviceID") or "")
        driver = driver_by_id.get(instance_id.lower(), {})
        code = _optional_int(device.get("ConfigManagerErrorCode"))
        enriched.append(
            {
                "instance_id": instance_id,
                "friendly_name": device.get("Name"),
                "manufacturer": device.get("Manufacturer") or driver.get("Manufacturer"),
                "status": device.get("Status"),
                "config_manager_error_code": code,
                "problem": interpret_config_manager_error(code),
                "driver_version": driver.get("DriverVersion"),
                "driver_date": driver.get("DriverDate"),
                "service": device.get("Service"),
                "class": device.get("PNPClass"),
                "present": device.get("Present"),
            }
        )
    return {"available": True, "drivers": enriched}


def interpret_config_manager_error(code: int | None) -> str:
    """Return cautious interpretation for a Windows ConfigManager error code."""
    if code is None:
        return "Codigo indisponivel."
    return CONFIG_MANAGER_ERROR_MESSAGES.get(code, "Codigo de erro do Windows nao mapeado.")


def _list(value: object) -> list[object]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
