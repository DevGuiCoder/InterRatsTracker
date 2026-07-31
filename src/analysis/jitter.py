"""Jitter calculation helpers."""

from __future__ import annotations


def estimate_jitter(latencies_ms: list[float]) -> float | None:
    """Estimate jitter as the average absolute delta between consecutive latencies."""
    if len(latencies_ms) < 2:
        return None
    deltas = [
        abs(current - previous)
        for previous, current in zip(latencies_ms, latencies_ms[1:], strict=False)
    ]
    return sum(deltas) / len(deltas)
