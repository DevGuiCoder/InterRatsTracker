"""Interface traffic sampling."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any


@dataclass
class TrafficSampler:
    """Calculate interface upload/download rates from monotonic counter deltas."""

    interface_name: str | None = None
    _last_sent: int | None = None
    _last_recv: int | None = None
    _last_at: float | None = None
    _upload_peak_mbps: float = 0.0
    _download_peak_mbps: float = 0.0
    _upload_total_mbps: float = 0.0
    _download_total_mbps: float = 0.0
    _samples: int = 0

    def sample(self, active_interface: str | None) -> dict[str, Any]:
        """Return current traffic counters and rates."""
        try:
            import psutil
        except Exception as exc:
            return {"available": False, "error": f"psutil indisponivel: {exc}"}

        counters = psutil.net_io_counters(pernic=True)
        selected_name = _select_counter_name(counters, active_interface) if counters else None
        mode = "per_interface"
        if selected_name:
            counter = counters[selected_name]
        else:
            counter = psutil.net_io_counters(pernic=False)
            selected_name = "Todas as interfaces"
            mode = "aggregate_fallback"
        if not counter:
            return {"available": False, "error": "contador da interface nao encontrado"}
        now = perf_counter()
        interface_changed = self.interface_name is not None and selected_name != self.interface_name
        upload_mbps: float | None = None
        download_mbps: float | None = None
        rate_available = False
        if interface_changed:
            self._upload_peak_mbps = 0.0
            self._download_peak_mbps = 0.0
            self._upload_total_mbps = 0.0
            self._download_total_mbps = 0.0
            self._samples = 0
        if (
            self._last_sent is not None
            and self._last_recv is not None
            and self._last_at is not None
            and not interface_changed
        ):
            elapsed = max(now - self._last_at, 0.001)
            upload_mbps = max(0.0, (counter.bytes_sent - self._last_sent) * 8 / elapsed / 1_000_000)
            download_mbps = max(0.0, (counter.bytes_recv - self._last_recv) * 8 / elapsed / 1_000_000)
            rate_available = True
            self._samples += 1
            self._upload_total_mbps += upload_mbps
            self._download_total_mbps += download_mbps
            self._upload_peak_mbps = max(self._upload_peak_mbps, upload_mbps)
            self._download_peak_mbps = max(self._download_peak_mbps, download_mbps)

        self.interface_name = selected_name
        self._last_sent = counter.bytes_sent
        self._last_recv = counter.bytes_recv
        self._last_at = now
        return {
            "available": True,
            "interface": selected_name,
            "requested_interface": active_interface,
            "interface_changed": interface_changed,
            "mode": mode,
            "counter_source": "psutil.net_io_counters",
            "rate_available": rate_available,
            "bytes_sent": counter.bytes_sent,
            "bytes_recv": counter.bytes_recv,
            "upload_mbps": upload_mbps,
            "download_mbps": download_mbps,
            "upload_avg_mbps": self._upload_total_mbps / self._samples if self._samples else None,
            "download_avg_mbps": self._download_total_mbps / self._samples if self._samples else None,
            "upload_peak_mbps": self._upload_peak_mbps,
            "download_peak_mbps": self._download_peak_mbps,
        }


def _select_counter_name(counters: dict[str, object], active_interface: str | None) -> str | None:
    if active_interface:
        lowered = active_interface.lower()
        for name in counters:
            if name.lower() in lowered or lowered in name.lower():
                return name
        return None
    for name, counter in counters.items():
        if getattr(counter, "bytes_recv", 0) or getattr(counter, "bytes_sent", 0):
            return name
    return next(iter(counters), None)
