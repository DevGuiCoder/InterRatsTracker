"""Automatic network event detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.storage.models import EventSeverity, ProbeResult, ProbeStatus, TargetMetricsSummary
from src.utils.config_loader import ThresholdConfig


@dataclass(frozen=True)
class DetectedEvent:
    """Detected event ready for persistence."""

    occurred_at: datetime
    severity: EventSeverity
    event_type: str
    message: str
    payload: dict[str, Any]
    target_name: str | None = None
    technical_description: str | None = None
    duration_seconds: float | None = None
    origin: str = "automatic"


class EventDetector:
    """Detects meaningful state transitions and quality threshold events."""

    def __init__(self, thresholds: ThresholdConfig) -> None:
        self._thresholds = thresholds
        self._last_status_by_target: dict[str, ProbeStatus] = {}
        self._open_quality_events: dict[tuple[str, str], datetime] = {}
        self._open_offline_events: dict[str, datetime] = {}
        self._last_max_consecutive_failures: dict[str, int] = {}

    def detect(
        self,
        results: list[ProbeResult],
        metrics: list[TargetMetricsSummary],
    ) -> list[DetectedEvent]:
        """Detect events from latest probe results and metric summaries."""
        events: list[DetectedEvent] = []
        events.extend(self._detect_status_changes(results))
        events.extend(self._detect_quality(metrics))
        return events

    def _detect_status_changes(self, results: list[ProbeResult]) -> list[DetectedEvent]:
        events: list[DetectedEvent] = []
        for result in results:
            previous = self._last_status_by_target.get(result.target.name)
            self._last_status_by_target[result.target.name] = result.status
            if previous == result.status:
                continue
            if result.status == ProbeStatus.OFFLINE:
                self._open_offline_events[result.target.name] = result.collected_at
                events.append(
                    DetectedEvent(
                        occurred_at=result.collected_at,
                        severity=EventSeverity.CRITICAL,
                        event_type=_offline_event_type(result),
                        message=f"{result.target.name} ficou indisponivel.",
                        payload=self._result_payload(result, previous),
                        target_name=result.target.name,
                        technical_description=result.error,
                    )
                )
            elif previous == ProbeStatus.OFFLINE and result.status in {ProbeStatus.ONLINE, ProbeStatus.DEGRADED, ProbeStatus.INCONCLUSIVE}:
                started = self._open_offline_events.pop(result.target.name, result.collected_at)
                duration = max(0.0, (result.collected_at - started).total_seconds())
                events.append(
                    DetectedEvent(
                        occurred_at=result.collected_at,
                        severity=EventSeverity.RECOVERY,
                        event_type=_recovery_event_type(result),
                        message=f"{result.target.name} recuperado apos {duration:.1f} segundos.",
                        payload=self._result_payload(result, previous),
                        target_name=result.target.name,
                        duration_seconds=duration,
                    )
                )
            elif result.status == ProbeStatus.DEGRADED:
                events.append(
                    DetectedEvent(
                        occurred_at=result.collected_at,
                        severity=EventSeverity.WARNING,
                        event_type="target_degraded",
                        message=f"{result.target.name} apresentou latencia elevada.",
                        payload=self._result_payload(result, previous),
                        target_name=result.target.name,
                        technical_description="Latencia acima do limite configurado.",
                    )
                )
            elif previous == ProbeStatus.DEGRADED and result.status == ProbeStatus.ONLINE:
                events.append(
                    DetectedEvent(
                        occurred_at=result.collected_at,
                        severity=EventSeverity.RECOVERY,
                        event_type="latency_normalized",
                        message=f"{result.target.name} normalizou a latencia.",
                        payload=self._result_payload(result, previous),
                        target_name=result.target.name,
                    )
                )
        return events

    def _detect_quality(self, metrics: list[TargetMetricsSummary]) -> list[DetectedEvent]:
        events: list[DetectedEvent] = []
        for summary in metrics:
            failure_metric = _failure_metric_name(summary.target_name)
            events.extend(self._threshold_event(summary, failure_metric, summary.packet_loss_percent))
            if failure_metric == "packet_loss" and summary.jitter_ms is not None:
                events.extend(self._threshold_event(summary, "jitter", summary.jitter_ms))
            previous_max = self._last_max_consecutive_failures.get(summary.target_name, 0)
            if summary.max_consecutive_failures >= 3 and summary.max_consecutive_failures > previous_max:
                events.append(
                    DetectedEvent(
                        occurred_at=datetime.now(UTC),
                        severity=EventSeverity.CRITICAL,
                        event_type="consecutive_failures",
                        message=f"{summary.target_name} teve {summary.max_consecutive_failures} falhas consecutivas.",
                        payload={"summary": summary.__dict__},
                        target_name=summary.target_name,
                        technical_description="Sequencia de falhas consecutivas acima do minimo operacional.",
                    )
                )
            self._last_max_consecutive_failures[summary.target_name] = summary.max_consecutive_failures
        return events

    def _threshold_event(
        self,
        summary: TargetMetricsSummary,
        metric_name: str,
        value: float,
    ) -> list[DetectedEvent]:
        warning, critical = self._limits(metric_name)
        key = (summary.target_name, metric_name)
        if value >= critical:
            if key in self._open_quality_events:
                return []
            self._open_quality_events[key] = datetime.now(UTC)
            return [
                DetectedEvent(
                    occurred_at=datetime.now(UTC),
                    severity=EventSeverity.CRITICAL,
                    event_type=f"{metric_name}_critical",
                    message=f"{summary.target_name} atingiu nivel critico de {_metric_label(metric_name)}.",
                    payload={"value": value, "warning": warning, "critical": critical, "summary": summary.__dict__},
                    target_name=summary.target_name,
                )
            ]
        if value >= warning:
            if key in self._open_quality_events:
                return []
            self._open_quality_events[key] = datetime.now(UTC)
            return [
                DetectedEvent(
                    occurred_at=datetime.now(UTC),
                    severity=EventSeverity.WARNING,
                    event_type=f"{metric_name}_warning",
                    message=f"{summary.target_name} atingiu nivel de atencao de {_metric_label(metric_name)}.",
                    payload={"value": value, "warning": warning, "critical": critical, "summary": summary.__dict__},
                    target_name=summary.target_name,
                )
            ]
        started = self._open_quality_events.pop(key, None)
        if started is not None:
            now = datetime.now(UTC)
            return [
                DetectedEvent(
                    occurred_at=now,
                    severity=EventSeverity.RECOVERY,
                    event_type=f"{metric_name}_normalized",
                    message=f"{summary.target_name} normalizou {_metric_label(metric_name)}.",
                    payload={"value": value, "warning": warning, "critical": critical, "summary": summary.__dict__},
                    target_name=summary.target_name,
                    duration_seconds=max(0.0, (now - started).total_seconds()),
                )
            ]
        return []

    def _limits(self, metric_name: str) -> tuple[float, float]:
        if metric_name in {"packet_loss", "connection_failure_rate", "dns_failure_rate", "tls_failure_rate"}:
            return (
                self._thresholds.packet_loss_warning_percent,
                self._thresholds.packet_loss_critical_percent,
            )
        if metric_name == "jitter":
            return (self._thresholds.jitter_warning_ms, self._thresholds.jitter_critical_ms)
        raise ValueError(f"Unsupported metric: {metric_name}")

    @staticmethod
    def _result_payload(result: ProbeResult, previous: ProbeStatus | None) -> dict[str, Any]:
        return {
            "target": {
                "name": result.target.name,
                "kind": result.target.kind.value,
                "host": result.target.host,
                "port": result.target.port,
                "protocol": result.target.protocol,
            },
            "previous_status": previous.value if previous else None,
            "status": result.status.value,
            "latency_ms": result.latency_ms,
            "error": result.error,
            "details": result.details,
        }


def _offline_event_type(result: ProbeResult) -> str:
    kind = result.target.kind.value
    if kind == "gateway":
        return "gateway_unavailable"
    if kind in {"internet_ip", "custom"}:
        return "internet_unavailable"
    if kind == "dns" or " DNS" in result.target.name:
        return "dns_unavailable"
    if kind == "sip" or "SIP " in result.target.name:
        return "sip_unavailable"
    return "target_offline"


def _recovery_event_type(result: ProbeResult) -> str:
    return _offline_event_type(result).replace("_unavailable", "_recovered").replace("target_offline", "target_recovered")


def _failure_metric_name(target_name: str) -> str:
    upper = target_name.upper()
    if " TCP" in upper:
        return "connection_failure_rate"
    if " TLS" in upper:
        return "tls_failure_rate"
    if " DNS" in upper:
        return "dns_failure_rate"
    return "packet_loss"


def _metric_label(metric_name: str) -> str:
    labels = {
        "packet_loss": "perda de pacotes",
        "connection_failure_rate": "taxa de falhas de conexao TCP",
        "dns_failure_rate": "taxa de falhas de resolucao DNS",
        "tls_failure_rate": "taxa de falhas de conexao TLS",
        "jitter": "jitter",
    }
    return labels.get(metric_name, metric_name)
