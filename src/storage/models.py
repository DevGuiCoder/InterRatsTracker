"""Shared storage and application models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class SessionStatus(str, Enum):
    """Allowed monitoring session states."""

    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    ARCHIVED = "archived"


class TargetKind(str, Enum):
    """Network target categories monitored in Etapa 2."""

    GATEWAY = "gateway"
    INTERNET_IP = "internet_ip"
    DNS = "dns"
    SIP = "sip"
    CUSTOM = "custom"


class ProbeStatus(str, Enum):
    """Normalized probe result states."""

    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    INCONCLUSIVE = "inconclusive"
    WARMING_UP = "warming_up"
    UNKNOWN = "unknown"


class CustomerMarkContextStatus(str, Enum):
    """Context collection state for a customer mark."""

    PENDING_AFTER_CONTEXT = "pending_after_context"
    COMPLETE = "complete"
    PARTIAL = "partial"


class EventSeverity(str, Enum):
    """Event severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    RECOVERY = "recovery"
    USER_MARKER = "user_marker"


class ConfidenceLevel(str, Enum):
    """Automatic conclusion confidence levels."""

    HIGH = "alta"
    MEDIUM = "media"
    LOW = "baixa"
    INCONCLUSIVE = "inconclusiva"


@dataclass(frozen=True)
class MonitoringRequest:
    """Operator-provided monitoring configuration."""

    client_name: str
    unit: str
    problem_description: str
    duration_minutes: int
    collection_interval_seconds: float
    sip_target: str
    service_port: int
    expected_protocol: str
    external_target: str
    support_notes: str
    profile_id: str = "diagnostico_completo"
    softphone_monitor_enabled: bool = False
    softphone_process_name: str = ""
    softphone_expected_path: str = ""
    softphone_expected_pid: int | None = None


@dataclass(frozen=True)
class MonitoringSession:
    """Persisted monitoring session summary."""

    session_id: str
    request: MonitoringRequest
    status: str
    started_at: datetime
    expected_end_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class TargetDefinition:
    """A destination that should be tested during a monitoring session."""

    name: str
    kind: TargetKind
    host: str
    port: int | None = None
    protocol: str = "ICMP"
    enabled: bool = True


@dataclass(frozen=True)
class ProbeResult:
    """One collected network probe result."""

    target: TargetDefinition
    collected_at: datetime
    status: ProbeStatus
    latency_ms: float | None
    error: str | None
    details: dict[str, Any]


@dataclass(frozen=True)
class TargetMetricsSummary:
    """Running metrics calculated for one target."""

    target_name: str
    tests: int
    successes: int
    failures: int
    packet_loss_percent: float
    latency_current_ms: float | None
    latency_min_ms: float | None
    latency_avg_ms: float | None
    latency_max_ms: float | None
    jitter_ms: float | None
    consecutive_failures: int
    max_consecutive_failures: int
    availability_percent: float
    last_failure_at: datetime | None = None
    last_recovery_at: datetime | None = None
    interruption_count: int = 0
    current_interruption_seconds: float = 0.0
    longest_interruption_seconds: float = 0.0
    total_unavailable_seconds: float = 0.0
    mean_recovery_seconds: float = 0.0
    latency_p95_ms: float | None = None
    degraded_periods: int = 0


@dataclass(frozen=True)
class MonitoringSnapshot:
    """Latest full monitoring state displayed by the console."""

    session: MonitoringSession
    collected_at: datetime
    elapsed_seconds: int
    remaining_seconds: int
    gateway_host: str | None
    active_interface: str | None
    connection_type: str | None
    latest_results: list[ProbeResult]
    metrics: list[TargetMetricsSummary]
    customer_mark_count: int = 0
    latest_customer_mark_at: datetime | None = None
    timeline_events: list["EventRecord"] | None = None
    group_statuses: dict[str, "GroupStatus"] | None = None
    is_warmup: bool = False
    warmup_remaining_seconds: int = 0
    diagnostics: dict[str, Any] | None = None


@dataclass(frozen=True)
class CustomerMarkSignal:
    """Signal emitted by the floating customer button."""

    marked_at: datetime


@dataclass(frozen=True)
class StoredCustomerMark:
    """Customer mark persisted in SQLite."""

    mark_id: int
    session_id: str
    marked_at: datetime
    context_status: CustomerMarkContextStatus
    payload: dict[str, Any]


@dataclass(frozen=True)
class SessionBaseline:
    """Technical state captured near the beginning of a session."""

    session_id: str
    collected_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class TechnicalSnapshot:
    """Deep technical snapshot captured around a customer mark."""

    snapshot_id: int
    session_id: str
    mark_id: int
    collected_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class SnapshotDifference:
    """One verified difference between baseline and a technical snapshot."""

    difference_id: int
    session_id: str
    snapshot_id: int
    field_name: str
    baseline_value: Any
    snapshot_value: Any
    severity: str
    message: str


@dataclass(frozen=True)
class DiagnosticRecord:
    """Generic JSON diagnostic record stored in a specialized evidence table."""

    record_id: int
    session_id: str
    collected_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class MeasurementRecord:
    """Measurement loaded from SQLite."""

    measurement_id: int
    session_id: str
    target_name: str
    collected_at: datetime
    status: str
    latency_ms: float | None
    payload: dict[str, Any]
    is_warmup: bool = False


@dataclass(frozen=True)
class EventRecord:
    """Detected event loaded from SQLite."""

    event_id: int
    session_id: str
    occurred_at: datetime
    severity: EventSeverity
    event_type: str
    message: str
    payload: dict[str, Any]
    target_name: str | None = None
    technical_description: str | None = None
    duration_seconds: float | None = None
    origin: str = "automatic"


@dataclass(frozen=True)
class SystemInfoRecord:
    """System/network information captured at session start."""

    session_id: str
    collected_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class InterruptionRecord:
    """Persisted interruption interval for one target."""

    interruption_id: int
    session_id: str
    target_name: str
    event_type: str
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: float | None
    lost_tests: int
    max_consecutive_failures: int
    payload: dict[str, Any]


@dataclass(frozen=True)
class GroupStatus:
    """Operator-facing status for a service group."""

    name: str
    status: ProbeStatus
    latency_ms: float | None
    summary: str


@dataclass(frozen=True)
class AutomaticConclusion:
    """Rule-based final conclusion."""

    result: str
    likely_origin: str
    confidence: ConfidenceLevel
    evidences: list[str]
    confidence_reducers: list[str]
    recommendations: list[str]
