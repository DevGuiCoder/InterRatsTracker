"""Windows microphone permission diagnostics."""

from __future__ import annotations

from typing import Any

from src.utils.powershell import run_powershell_json


def check_microphone_permissions(timeout_seconds: float = 5.0) -> dict[str, Any]:
    """Read Windows privacy registry keys without changing permissions."""
    script = r"""
$base = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone'
$global = $null
$desktop = $null
try { $global = (Get-ItemProperty -Path $base -ErrorAction Stop).Value } catch {}
try { $desktop = (Get-ItemProperty -Path (Join-Path $base 'NonPackaged') -ErrorAction Stop).Value } catch {}
[pscustomobject]@{
  global_access = $global
  desktop_apps = $desktop
  source = 'CapabilityAccessManager'
} | ConvertTo-Json -Compress
"""
    result = run_powershell_json(script, timeout=timeout_seconds)
    if not result.get("available"):
        return result
    return {
        "available": True,
        "global_access": _permission_state(result.get("global_access")),
        "desktop_apps": _permission_state(result.get("desktop_apps")),
        "source": result.get("source"),
        "can_change_permissions": False,
        "note": "Diagnostico apenas leitura; a aplicacao nao altera permissoes.",
    }


def _permission_state(value: object) -> str:
    if value is None:
        return "N/D"
    text = str(value)
    if text == "Allow":
        return "ATIVA"
    if text == "Deny":
        return "BLOQUEADA"
    return text
