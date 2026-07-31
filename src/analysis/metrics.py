"""Running metric aggregation for network probes."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime

from src.analysis.availability import availability_percent, percentile
from src.analysis.interruption_tracker import ClosedInterruption, InterruptionTracker
from src.analysis.jitter import estimate_jitter
from src.storage.models import ProbeResult, ProbeStatus, TargetMetricsSummary


class MetricsAggregator:
    """Accumulates probe metrics per target with bounded latency history."""

    def __init__(
        self,
        latency_window_size: int = 120,
        jitter_window_size: int | None = None,
        minimum_samples_for_jitter: int = 2,
    ) -> None:
        self._jitter_window_size = jitter_window_size or latency_window_size
        self._minimum_samples_for_jitter = max(2, minimum_samples_for_jitter)
        self._tests: defaultdict[str, int] = defaultdict(int)
        self._successes: defaultdict[str, int] = defaultdict(int)
        self._failures: defaultdict[str, int] = defaultdict(int)
        self._known_successes: defaultdict[str, int] = defaultdict(int)
        self._consecutive_failures: defaultdict[str, int] = defaultdict(int)
        self._max_consecutive_failures: defaultdict[str, int] = defaultdict(int)
        self._latencies: defaultdict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=latency_window_size)
        )
        self._current_latency: dict[str, float | None] = {}
        self._last_failure_at: dict[str, datetime | None] = defaultdict(lambda: None)
        self._last_recovery_at: dict[str, datetime | None] = defaultdict(lambda: None)
        self._degraded_periods: defaultdict[str, int] = defaultdict(int)
        self._previous_status: dict[str, ProbeStatus] = {}
        self._interruptions = InterruptionTracker()
        self._closed_interruptions: list[ClosedInterruption] = []

    def add_results(self, results: list[ProbeResult]) -> None:
        """Add a batch of probe results."""
        for result in results:
            name = result.target.name
            self._tests[name] += 1
            self._current_latency[name] = result.latency_ms
            if result.status in {ProbeStatus.ONLINE, ProbeStatus.DEGRADED}:
                self._successes[name] += 1
                self._known_successes[name] += 1
                if self._previous_status.get(name) == ProbeStatus.OFFLINE:
                    closed = self._interruptions.mark_recovery(name, result.collected_at)
                    if closed:
                        self._closed_interruptions.append(closed)
                    self._last_recovery_at[name] = result.collected_at
                self._consecutive_failures[name] = 0
                if result.latency_ms is not None:
                    self._latencies[name].append(result.latency_ms)
                if result.status == ProbeStatus.DEGRADED and self._previous_status.get(name) != ProbeStatus.DEGRADED:
                    self._degraded_periods[name] += 1
            elif result.status == ProbeStatus.OFFLINE:
                self._failures[name] += 1
                self._last_failure_at[name] = result.collected_at
                self._consecutive_failures[name] += 1
                self._max_consecutive_failures[name] = max(
                    self._max_consecutive_failures[name],
                    self._consecutive_failures[name],
                )
                self._interruptions.mark_failure(name, result.collected_at, self._consecutive_failures[name])
            else:
                self._consecutive_failures[name] = 0
            self._previous_status[name] = result.status

    def drain_closed_interruptions(self) -> list[ClosedInterruption]:
        """Return and clear newly closed interruptions."""
        closed = list(self._closed_interruptions)
        self._closed_interruptions.clear()
        return closed

    def summaries(self) -> list[TargetMetricsSummary]:
        """Return current summaries ordered by target name."""
        summaries: list[TargetMetricsSummary] = []
        for name in sorted(self._tests):
            tests = self._tests[name]
            successes = self._successes[name]
            failures = self._failures[name]
            latencies = list(self._latencies[name])
            jitter_latencies = latencies[-self._jitter_window_size :]
            jitter = (
                estimate_jitter(jitter_latencies)
                if len(jitter_latencies) >= self._minimum_samples_for_jitter
                else None
            )
            loss = (failures / tests) * 100 if tests else 0.0
            availability = availability_percent(self._known_successes[name], failures)
            avg = sum(latencies) / len(latencies) if latencies else None
            interruption = self._interruptions.summary(name, datetime.now(UTC))
            summaries.append(
                TargetMetricsSummary(
                    target_name=name,
                    tests=tests,
                    successes=successes,
                    failures=failures,
                    packet_loss_percent=loss,
                    latency_current_ms=self._current_latency.get(name),
                    latency_min_ms=min(latencies) if latencies else None,
                    latency_avg_ms=avg,
                    latency_max_ms=max(latencies) if latencies else None,
                    jitter_ms=jitter,
                    consecutive_failures=self._consecutive_failures[name],
                    max_consecutive_failures=self._max_consecutive_failures[name],
                    availability_percent=availability,
                    last_failure_at=self._last_failure_at[name],
                    last_recovery_at=self._last_recovery_at[name],
                    interruption_count=int(interruption["interruption_count"]),
                    current_interruption_seconds=float(interruption["current_interruption_seconds"]),
                    longest_interruption_seconds=float(interruption["longest_interruption_seconds"]),
                    total_unavailable_seconds=float(interruption["total_unavailable_seconds"]),
                    mean_recovery_seconds=float(interruption["mean_recovery_seconds"]),
                    latency_p95_ms=percentile(latencies, 95),
                    degraded_periods=self._degraded_periods[name],
                )
            )
        return summaries
