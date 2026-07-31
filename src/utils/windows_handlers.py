"""Windows signal handling for accidental close attempts."""

from __future__ import annotations

import signal
from collections.abc import Callable
from types import FrameType


class SignalGuard:
    """Temporarily intercept common console interruption signals."""

    def __init__(self, on_attempt: Callable[[str], None]) -> None:
        self._on_attempt = on_attempt
        self._previous: dict[int, object] = {}

    def install(self) -> None:
        """Install handlers for Ctrl+C and Ctrl+Break when available."""
        self._install_one(signal.SIGINT, "Ctrl+C")
        sigbreak = getattr(signal, "SIGBREAK", None)
        if sigbreak is not None:
            self._install_one(sigbreak, "Ctrl+Break")

    def restore(self) -> None:
        """Restore previous signal handlers."""
        for sig, handler in self._previous.items():
            signal.signal(sig, handler)
        self._previous.clear()

    def _install_one(self, sig: int, label: str) -> None:
        self._previous[sig] = signal.getsignal(sig)

        def handler(_signum: int, _frame: FrameType | None) -> None:
            self._on_attempt(label)

        signal.signal(sig, handler)
