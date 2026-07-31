"""Availability and percentile helpers."""

from __future__ import annotations

from datetime import datetime

from src.storage.models import ProbeStatus


def percentile(values: list[float], percentile_value: float) -> float | None:
    """Return a nearest-rank percentile for a non-empty list."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((percentile_value / 100) * (len(ordered) - 1))))
    return ordered[index]


def availability_percent(successes: int, failures: int) -> float:
    """Calculate availability excluding inconclusive and unknown probes."""
    denominator = successes + failures
    return (successes / denominator) * 100 if denominator else 0.0


def is_unavailable(status: ProbeStatus) -> bool:
    """Return True when status is reliable unavailability evidence."""
    return status == ProbeStatus.OFFLINE


def seconds_between(start: datetime, end: datetime) -> float:
    """Return positive seconds between two datetimes."""
    return max(0.0, (end - start).total_seconds())
