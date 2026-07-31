"""Softphone process monitoring with stateful event suppression."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.monitoring.process_snapshot import ProcessInfo


class ProcessFinder(Protocol):
    """Minimal process lookup contract used by the monitor."""

    def find(
        self,
        process_name: str | None = None,
        expected_path: str | None = None,
        expected_pid: int | None = None,
    ) -> list[ProcessInfo]:
        ...


@dataclass(frozen=True)
class SoftphoneMonitorConfig:
    """Configured softphone identity and thresholds."""

    enabled: bool
    process_name: str | None = None
    expected_path: str | None = None
    expected_pid: int | None = None
    high_cpu_percent: float = 85.0
    high_cpu_min_duration_seconds: float = 5.0
    high_memory_mb: float = 1024.0
    high_memory_min_duration_seconds: float = 5.0
    not_responding_min_duration_seconds: float = 3.0


@dataclass(frozen=True)
class SoftphoneSample:
    """Softphone monitoring output for one cycle."""

    collected_at: datetime
    configured: bool
    found: bool
    selected: ProcessInfo | None
    instances: list[ProcessInfo]
    events: list[dict[str, object]]

    def to_metric_payload(self) -> dict[str, object]:
        selected = self.selected.to_dict() if self.selected else None
        return {
            "configured": self.configured,
            "found": self.found,
            "selected": selected,
            "instances": [process.to_dict() for process in self.instances],
            "instance_count": len(self.instances),
        }


class SoftphoneMonitor:
    """Track process presence and resource anomalies without repeated alerts."""

    def __init__(self, config: SoftphoneMonitorConfig, finder: ProcessFinder) -> None:
        self._config = config
        self._finder = finder
        self._last_pid: int | None = None
        self._was_found = False
        self._not_found_active = False
        self._multiple_instances_active = False
        self._cpu_high_since: datetime | None = None
        self._cpu_high_active = False
        self._memory_high_since: datetime | None = None
        self._memory_high_active = False
        self._not_responding_since: datetime | None = None
        self._not_responding_active = False

    def update(self, collected_at: datetime) -> SoftphoneSample:
        """Collect one process sample and emit only state transitions."""
        if not self._config.enabled or not self._has_identity():
            return SoftphoneSample(collected_at, False, False, None, [], [])
        instances = self._finder.find(
            process_name=self._config.process_name,
            expected_path=self._config.expected_path,
            expected_pid=self._config.expected_pid,
        )
        selected = instances[0] if instances else None
        events: list[dict[str, object]] = []
        if selected is None:
            self._handle_missing(collected_at, events)
            return SoftphoneSample(collected_at, True, False, None, [], events)
        self._handle_present(collected_at, selected, instances, events)
        self._handle_cpu(collected_at, selected, events)
        self._handle_memory(collected_at, selected, events)
        self._handle_responsiveness(collected_at, selected, events)
        return SoftphoneSample(collected_at, True, True, selected, instances, events)

    def _has_identity(self) -> bool:
        return bool(self._config.process_name or self._config.expected_pid or self._config.expected_path)

    def _handle_missing(self, collected_at: datetime, events: list[dict[str, object]]) -> None:
        if self._was_found:
            events.append(self._event(collected_at, "softphone_stopped", "warning", "Processo do softphone foi encerrado."))
        if not self._not_found_active:
            events.append(self._event(collected_at, "softphone_not_found", "warning", "Processo do softphone nao encontrado."))
            self._not_found_active = True
        self._was_found = False
        self._last_pid = None
        self._multiple_instances_active = False
        self._reset_threshold_states()

    def _handle_present(
        self,
        collected_at: datetime,
        selected: ProcessInfo,
        instances: list[ProcessInfo],
        events: list[dict[str, object]],
    ) -> None:
        if not self._was_found:
            events.append(self._event(collected_at, "softphone_started", "info", "Processo do softphone encontrado.", selected))
        elif self._last_pid is not None and selected.pid != self._last_pid:
            events.append(self._event(collected_at, "softphone_pid_changed", "warning", "PID do softphone mudou.", selected))
            events.append(self._event(collected_at, "softphone_restarted", "warning", "Processo do softphone aparenta ter reiniciado.", selected))
        if len(instances) > 1 and not self._multiple_instances_active:
            events.append(
                self._event(
                    collected_at,
                    "softphone_multiple_instances",
                    "warning",
                    "Mais de uma instancia do softphone foi encontrada.",
                    selected,
                    {"instance_count": len(instances), "pids": [process.pid for process in instances]},
                )
            )
            self._multiple_instances_active = True
        elif len(instances) <= 1:
            self._multiple_instances_active = False
        self._was_found = True
        self._not_found_active = False
        self._last_pid = selected.pid

    def _handle_cpu(self, collected_at: datetime, selected: ProcessInfo, events: list[dict[str, object]]) -> None:
        cpu = selected.cpu_percent
        if cpu is None or cpu < self._config.high_cpu_percent:
            self._cpu_high_since = None
            if self._cpu_high_active:
                events.append(self._event(collected_at, "softphone_cpu_normalized", "info", "CPU do softphone normalizou.", selected))
                self._cpu_high_active = False
            return
        if self._cpu_high_since is None:
            self._cpu_high_since = collected_at
            return
        duration = (collected_at - self._cpu_high_since).total_seconds()
        if not self._cpu_high_active and duration >= self._config.high_cpu_min_duration_seconds:
            events.append(
                self._event(
                    collected_at,
                    "softphone_cpu_high",
                    "warning",
                    "CPU do softphone permaneceu acima do limite configurado.",
                    selected,
                    {"duration_seconds": duration, "threshold": self._config.high_cpu_percent},
                )
            )
            self._cpu_high_active = True

    def _handle_memory(self, collected_at: datetime, selected: ProcessInfo, events: list[dict[str, object]]) -> None:
        rss_mb = selected.rss_mb
        if rss_mb is None or rss_mb < self._config.high_memory_mb:
            self._memory_high_since = None
            if self._memory_high_active:
                events.append(self._event(collected_at, "softphone_memory_normalized", "info", "Memoria do softphone normalizou.", selected))
                self._memory_high_active = False
            return
        if self._memory_high_since is None:
            self._memory_high_since = collected_at
            return
        duration = (collected_at - self._memory_high_since).total_seconds()
        if not self._memory_high_active and duration >= self._config.high_memory_min_duration_seconds:
            events.append(
                self._event(
                    collected_at,
                    "softphone_memory_high",
                    "warning",
                    "Memoria do softphone permaneceu acima do limite configurado.",
                    selected,
                    {"duration_seconds": duration, "threshold_mb": self._config.high_memory_mb},
                )
            )
            self._memory_high_active = True

    def _handle_responsiveness(self, collected_at: datetime, selected: ProcessInfo, events: list[dict[str, object]]) -> None:
        if selected.not_responding is not True:
            self._not_responding_since = None
            if self._not_responding_active:
                events.append(self._event(collected_at, "softphone_responsive_again", "info", "Softphone voltou a responder.", selected))
                self._not_responding_active = False
            return
        if self._not_responding_since is None:
            self._not_responding_since = collected_at
            return
        duration = (collected_at - self._not_responding_since).total_seconds()
        if not self._not_responding_active and duration >= self._config.not_responding_min_duration_seconds:
            events.append(
                self._event(
                    collected_at,
                    "softphone_not_responding",
                    "critical",
                    "Softphone permaneceu sem responder pelo tempo minimo configurado.",
                    selected,
                    {"duration_seconds": duration},
                )
            )
            self._not_responding_active = True

    def _reset_threshold_states(self) -> None:
        self._cpu_high_since = None
        self._cpu_high_active = False
        self._memory_high_since = None
        self._memory_high_active = False
        self._not_responding_since = None
        self._not_responding_active = False

    @staticmethod
    def _event(
        occurred_at: datetime,
        event_type: str,
        severity: str,
        message: str,
        process: ProcessInfo | None = None,
        extra_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload = {"process": process.to_dict() if process else None}
        if extra_payload:
            payload.update(extra_payload)
        return {
            "occurred_at": occurred_at,
            "event_type": event_type,
            "severity": severity,
            "message": message,
            "payload": payload,
        }
