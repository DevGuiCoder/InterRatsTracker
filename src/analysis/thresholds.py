"""Threshold models shared by future event detection rules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    """Initial thresholds for network quality events."""

    latency_warning_ms: int
    latency_critical_ms: int
    packet_loss_warning_percent: float
    packet_loss_critical_percent: float
    jitter_warning_ms: int
    jitter_critical_ms: int

