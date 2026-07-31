"""PowerShell helpers with JSON-first parsing."""

from __future__ import annotations

import json
import subprocess
from typing import Any


def run_powershell_json(script: str, timeout: float = 8.0) -> dict[str, Any]:
    """Run PowerShell and parse a JSON object result."""
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); " + script,
        ],
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0:
        return {"available": False, "error": stderr or stdout or f"PowerShell retornou {completed.returncode}"}
    if not stdout:
        return {"available": True, "items": []}
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return {"available": False, "error": f"JSON invalido do PowerShell: {exc}", "raw_excerpt": stdout[:500]}
    if isinstance(parsed, dict):
        return {"available": True, **parsed}
    return {"available": True, "items": parsed}
