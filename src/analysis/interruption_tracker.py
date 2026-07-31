"""Interruption interval tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.analysis.availability import seconds_between


@dataclass
class OpenInterruption:
    """Currently open interruption for a target."""

    target_name: str
    started_at: datetime
    lost_tests: int = 1
    max_consecutive_failures: int = 1


@dataclass(frozen=True)
class ClosedInterruption:
    """Closed interruption interval."""

    target_name: str
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    lost_tests: int
    max_consecutive_failures: int


class InterruptionTracker:
    """Tracks open and closed interruptions per target."""

    def __init__(self) -> None:
        self._open: dict[str, OpenInterruption] = {}
        self._closed: list[ClosedInterruption] = []

    def mark_failure(self, target_name: str, occurred_at: datetime, consecutive_failures: int) -> None:
        """Open or update an interruption."""
        current = self._open.get(target_name)
        if current is None:
            self._open[target_name] = OpenInterruption(
                target_name=target_name,
                started_at=occurred_at,
                lost_tests=1,
                max_consecutive_failures=consecutive_failures,
            )
            return
        current.lost_tests += 1
        current.max_consecutive_failures = max(current.max_consecutive_failures, consecutive_failures)

    def mark_recovery(self, target_name: str, occurred_at: datetime) -> ClosedInterruption | None:
        """Close an interruption when a target recovers."""
        current = self._open.pop(target_name, None)
        if current is None:
            return None
        closed = ClosedInterruption(
            target_name=target_name,
            started_at=current.started_at,
            ended_at=occurred_at,
            duration_seconds=seconds_between(current.started_at, occurred_at),
            lost_tests=current.lost_tests,
            max_consecutive_failures=current.max_consecutive_failures,
        )
        self._closed.append(closed)
        return closed

    def current_duration(self, target_name: str, now: datetime) -> float:
        """Return current open interruption duration in seconds."""
        current = self._open.get(target_name)
        return seconds_between(current.started_at, now) if current else 0.0

    def summary(self, target_name: str, now: datetime) -> dict[str, float | int]:
        """Return aggregate interruption statistics for one target."""
        closed = [item for item in self._closed if item.target_name == target_name]
        open_current = self._open.get(target_name)
        durations = [item.duration_seconds for item in closed]
        if open_current:
            durations.append(seconds_between(open_current.started_at, now))
        total = sum(durations)
        return {
            "interruption_count": len(closed) + (1 if open_current else 0),
            "current_interruption_seconds": self.current_duration(target_name, now),
            "longest_interruption_seconds": max(durations) if durations else 0.0,
            "total_unavailable_seconds": total,
            "mean_recovery_seconds": (sum(item.duration_seconds for item in closed) / len(closed)) if closed else 0.0,
        }
