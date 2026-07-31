"""Centralized Windows command execution with conservative decoding."""

from __future__ import annotations

import ctypes
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class WindowsCommandResult:
    """Decoded command result."""

    returncode: int
    stdout: str
    stderr: str
    encoding: str


def run_windows_command(args: list[str], timeout: float = 5.0) -> WindowsCommandResult:
    """Run a Windows command and decode output using the OEM code page when available."""
    encoding = _oem_encoding()
    completed = subprocess.run(
        args,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return WindowsCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout.decode(encoding, errors="replace"),
        stderr=completed.stderr.decode(encoding, errors="replace"),
        encoding=encoding,
    )


def _oem_encoding() -> str:
    if hasattr(ctypes, "windll"):
        try:
            code_page = ctypes.windll.kernel32.GetOEMCP()
            if code_page:
                return f"cp{code_page}"
        except Exception:
            pass
    return "utf-8"
