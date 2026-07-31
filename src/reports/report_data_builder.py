"""Build presentation-ready report data from persisted records."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from src.analysis.domain_diagnostics import DomainDiagnostic, build_domain_diagnostics
from src.analysis.availability import percentile
from src.reports.audio_report_builder import AudioReportView, build_audio_report_view
from src.reports.customer_markers import (
    CUSTOMER_MARKER_EVENT_TYPE,
    CUSTOMER_MARKER_ORIGIN,
    CUSTOMER_MARKER_VISUAL_PRIORITY,
    correlation_label,
    customer_marker_anchor,
    customer_marker_replay_anchor,
    normalize_correlation_level,
)
from src.storage.models import (
    AutomaticConclusion,
    ConfidenceLevel,
    DiagnosticRecord,
    EventRecord,
    InterruptionRecord,
    MeasurementRecord,
    MonitoringSession,
    StoredCustomerMark,
    SystemInfoRecord,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DestinationMetricsView:
    """Presentation metrics for one monitored destination."""

    target_name: str
    short_name: str
    category: str
    probe: str
    final_status: str
    tests: int
    successes: int
    failures: int
    availability_percent: float
    failure_rate_percent: float
    latency_current_ms: float | None
    latency_min_ms: float | None
    latency_avg_ms: float | None
    latency_p95_ms: float | None
    latency_max_ms: float | None
    response_variation_ms: float | None
    jitter_label: str
    max_consecutive_failures: int
    last_failure_at: datetime | None
    ended_unavailable: bool


@dataclass(frozen=True)
class InterruptionReportView:
    """Presentation interruption, including open interruptions closed by session end."""

    target_name: str
    event_type: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: float | None
    lost_tests: int
    max_consecutive_failures: int
    no_recovery_observed: bool
    message: str


@dataclass(frozen=True)
class MarkerReportView:
    """Presentation correlation for one customer mark."""

    mark_id: int
    sequence_number: int
    marked_at: datetime
    relative_session_seconds: float
    anchor_id: str
    replay_anchor_id: str
    title: str
    description: str
    event_type: str
    event_origin: str
    is_customer_marker: bool
    visual_priority: str
    context_status: str
    context_start: datetime | None
    context_end: datetime | None
    immediate_snapshot_at: datetime | None
    technical_snapshot_status: str | None
    before_samples: int
    after_samples: int
    before_cycles: int
    after_cycles: int
    requested_before_seconds: float | None
    requested_after_seconds: float | None
    seconds_before: float | None
    seconds_after: float | None
    nearest_anomaly_seconds: float | None
    nearest_anomaly_target: str | None
    first_anomaly_after_seconds: float | None
    first_anomaly_after_target: str | None
    first_anomaly_before_seconds: float | None
    first_anomaly_before_target: str | None
    affected_monitors: list[str]
    nearby_events: list[dict[str, Any]]
    correlation_level: str
    correlation_label: str
    conclusion: str
    limitations: list[str]


@dataclass(frozen=True)
class CustomerMarkersSummaryView:
    """Summary cards and consistency metadata for customer markers."""

    total: int
    complete: int
    partial: int
    pending: int
    strong_correlations: int
    moderate_correlations: int
    weak_correlations: int
    no_anomaly: int
    insufficient: int
    anchors: list[str]


@dataclass(frozen=True)
class SipOptionsView:
    """Presentation row for SIP OPTIONS."""

    collected_at: datetime
    transport: str
    host: str
    port: int | None
    status: str
    sip_code: int | None
    sip_reason: str | None
    duration_ms: float | None
    interpretation: str


@dataclass(frozen=True)
class SipTransportView:
    """Presentation row for SIP transport checks."""

    transport: str
    port: int | None
    status: str
    duration_ms: float | None
    certificate: str
    observation: str


@dataclass(frozen=True)
class TrafficReportView:
    """Presentation traffic summary."""

    samples: int
    latest_interface: str | None
    mode: str | None
    counter_source: str | None
    latest_rate_available: bool
    upload_current_mbps: float | None
    download_current_mbps: float | None
    upload_peak_mbps: float | None
    download_peak_mbps: float | None
    collection_failures: int


@dataclass(frozen=True)
class SystemReportView:
    """Presentation system performance summary."""

    samples: int
    cpu_current_percent: float | None
    cpu_avg_percent: float | None
    cpu_p95_percent: float | None
    cpu_peak_percent: float | None
    memory_current_percent: float | None
    memory_avg_percent: float | None
    memory_peak_percent: float | None
    memory_available_mb: float | None
    disk_used_percent: float | None


@dataclass(frozen=True)
class WifiReportView:
    """Presentation Wi-Fi summary."""

    available: bool
    connected: bool | None
    ssid: str | None
    signal_percent: float | None
    radio_type: str | None
    channel: str | None
    receive_rate_mbps: float | None
    transmit_rate_mbps: float | None
    bssid_masked: str | None
    active_interface: str | None
    wifi_used_by_monitoring: bool | None
    note: str


@dataclass(frozen=True)
class RouteHopView:
    """Presentation row for one route hop."""

    hop: int
    address: str | None
    time_1_ms: float | None
    time_2_ms: float | None
    time_3_ms: float | None
    state: str


@dataclass(frozen=True)
class RouteReportView:
    """Presentation route summary."""

    available: bool
    reason: str
    duration_seconds: float | None
    hop_count: int
    timed_out_hops: int
    hops: list[RouteHopView]
    note: str | None


@dataclass(frozen=True)
class TimeSyncReportView:
    """Presentation Windows time synchronization summary."""

    local_time: str | None
    timezone: str | None
    synchronized: bool | None
    source: str | None
    last_successful_sync: str | None
    stratum: str | None
    offset: str | None
    service_active: bool | None
    observation: str


@dataclass(frozen=True)
class ExecutiveSummaryView:
    """Top report cards."""

    result_label: str
    likely_origin: str
    confidence: str
    marker_count: int
    interruption_count: int
    sip_tcp_availability: float | None


@dataclass(frozen=True)
class CorrelationReportView:
    """Final conclusion with consistency findings."""

    conclusion: AutomaticConclusion
    consistency_findings: list[str]


@dataclass(frozen=True)
class SoftphoneEventReportRow:
    """Presentation row for one softphone event."""

    occurred_at: datetime
    event_type: str
    severity: str
    message: str
    pid: int | None


@dataclass(frozen=True)
class SoftphoneReportView:
    """Softphone process report summary."""

    configured: bool
    found: bool
    process_name: str | None
    pid: int | None
    exe: str | None
    started_at: datetime | None
    cpu_percent: float | None
    rss_mb: float | None
    memory_percent: float | None
    thread_count: int | None
    handle_count: int | None
    instance_count: int
    event_count: int
    high_cpu_events: int
    high_memory_events: int
    not_responding_events: int
    events: list[SoftphoneEventReportRow]
    limitations: list[str]


@dataclass(frozen=True)
class WindowsEventReportRow:
    """Presentation row for a normalized Windows event."""

    occurred_at: datetime
    provider: str
    windows_event_id: int | None
    category: str
    device_name: str | None
    normalized_type: str
    summary: str
    relevance: str


@dataclass(frozen=True)
class PowerAuditReportRow:
    """Presentation row for one power audit item."""

    item: str
    classification: str
    current_value: str
    source: str
    related_device: str | None
    possible_impact: str
    related_event: str | None
    manual_guidance: str


@dataclass(frozen=True)
class SessionReportView:
    """Single source of truth for HTML, TXT and JSON report exports."""

    session: MonitoringSession
    executive: ExecutiveSummaryView
    destinations: list[DestinationMetricsView]
    interruptions: list[InterruptionReportView]
    markers: list[MarkerReportView]
    sip_options: list[SipOptionsView]
    sip_transports: list[SipTransportView]
    traffic: TrafficReportView
    system: SystemReportView
    wifi: WifiReportView
    routes: list[RouteReportView]
    time_sync: TimeSyncReportView
    audio: AudioReportView
    softphone: SoftphoneReportView
    windows_events: list[WindowsEventReportRow]
    power_audit: list[PowerAuditReportRow]
    domain_diagnostics: list[DomainDiagnostic]
    customer_markers_summary: CustomerMarkersSummaryView
    correlation: CorrelationReportView

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe representation."""
        return asdict(self)


def build_session_report_view(
    session: MonitoringSession,
    measurements: list[MeasurementRecord],
    events: list[EventRecord],
    marks: list[StoredCustomerMark],
    interruptions: list[InterruptionRecord],
    diagnostic_records: dict[str, list[DiagnosticRecord]],
    system_info: SystemInfoRecord | None = None,
) -> SessionReportView:
    """Build the report view used by every exporter."""
    official = [item for item in measurements if not item.is_warmup]
    destinations = build_destination_metrics(official)
    inferred_interruptions = build_interruption_views(session, destinations, interruptions)
    marker_views = build_marker_views(marks, session)
    customer_markers_summary = build_customer_markers_summary(marker_views)
    sip_options = build_sip_options_views(diagnostic_records.get("sip_options_results", []))
    sip_transports = build_sip_transport_views(diagnostic_records.get("sip_transport_results", []))
    traffic = build_traffic_view(diagnostic_records.get("interface_traffic", []))
    system = build_system_view(diagnostic_records.get("system_metrics", []))
    wifi = build_wifi_view(diagnostic_records.get("wifi_metrics", []), system_info)
    routes = build_route_views(diagnostic_records.get("route_traces", []))
    time_sync = build_time_sync_view(diagnostic_records.get("time_sync_results", []))
    audio = build_audio_report_view(
        diagnostic_records,
        level_monitoring_enabled=bool(diagnostic_records.get("audio_level_metrics")),
    )
    softphone = build_softphone_view(
        diagnostic_records.get("softphone_processes", []),
        diagnostic_records.get("softphone_metrics", []),
        diagnostic_records.get("softphone_events", []),
    )
    windows_events = build_windows_event_views(diagnostic_records.get("windows_events", []))
    power_audit = build_power_audit_views(diagnostic_records.get("power_audit", []))
    domain_diagnostics = build_domain_diagnostics(destinations)
    conclusion = build_report_conclusion(destinations, events, marker_views, sip_options, inferred_interruptions, audio, softphone)
    consistency = validate_report_consistency(conclusion, destinations, events, inferred_interruptions, audio, softphone, marker_views)
    for finding in consistency:
        LOGGER.error("Inconsistencia de relatorio detectada: %s", finding)
    if consistency and conclusion.likely_origin == "nenhuma instabilidade detectada":
        conclusion = _conclusion(
            "Foram detectadas anomalias tecnicas, mas a classificacao automatica original ficou inconsistente. O resultado foi invalidado para evitar conclusao incorreta de normalidade.",
            "anomalia tecnica detectada",
            ConfidenceLevel.MEDIUM,
            consistency,
            ["Revisar eventos criticos, destinos com falha e interrupcoes sem recuperacao observada."],
        )
    sip_tcp = _sip_tcp_destination(destinations)
    executive = ExecutiveSummaryView(
        result_label="INSTABILIDADE DETECTADA" if conclusion.likely_origin != "nenhuma instabilidade detectada" else "SEM ANOMALIA PRINCIPAL",
        likely_origin=conclusion.likely_origin.upper(),
        confidence=conclusion.confidence.value.upper(),
        marker_count=len(marks),
        interruption_count=len(inferred_interruptions),
        sip_tcp_availability=sip_tcp.availability_percent if sip_tcp else None,
    )
    return SessionReportView(
        session=session,
        executive=executive,
        destinations=destinations,
        interruptions=inferred_interruptions,
        markers=marker_views,
        sip_options=sip_options,
        sip_transports=sip_transports,
        traffic=traffic,
        system=system,
        wifi=wifi,
        routes=routes,
        time_sync=time_sync,
        audio=audio,
        softphone=softphone,
        windows_events=windows_events,
        power_audit=power_audit,
        domain_diagnostics=domain_diagnostics,
        customer_markers_summary=customer_markers_summary,
        correlation=CorrelationReportView(conclusion=conclusion, consistency_findings=consistency),
    )


def build_destination_metrics(measurements: list[MeasurementRecord]) -> list[DestinationMetricsView]:
    """Aggregate measurements per target with TCP semantics separated from packet loss."""
    grouped: dict[str, list[MeasurementRecord]] = {}
    for item in measurements:
        grouped.setdefault(item.target_name, []).append(item)
    rows: list[DestinationMetricsView] = []
    for target_name, values in sorted(grouped.items()):
        values = sorted(values, key=lambda item: item.collected_at)
        known = [item for item in values if item.status in {"online", "degraded", "offline"}]
        successes = sum(1 for item in known if item.status in {"online", "degraded"})
        failures = sum(1 for item in known if item.status == "offline")
        tests = len(known)
        latencies = [item.latency_ms for item in known if item.latency_ms is not None]
        final = known[-1] if known else values[-1]
        probe = _probe_for(final)
        category = _category_for(final)
        variation = _response_variation(latencies)
        rows.append(
            DestinationMetricsView(
                target_name=target_name,
                short_name=_short_name(target_name),
                category=category,
                probe=probe,
                final_status=final.status,
                tests=tests,
                successes=successes,
                failures=failures,
                availability_percent=(successes / tests) * 100 if tests else 0.0,
                failure_rate_percent=(failures / tests) * 100 if tests else 0.0,
                latency_current_ms=final.latency_ms,
                latency_min_ms=min(latencies) if latencies else None,
                latency_avg_ms=sum(latencies) / len(latencies) if latencies else None,
                latency_p95_ms=percentile(latencies, 95),
                latency_max_ms=max(latencies) if latencies else None,
                response_variation_ms=variation,
                jitter_label="Jitter estimado" if probe in {"ICMP", "UDP"} else "Variacao do tempo de resposta",
                max_consecutive_failures=_max_consecutive_failures(known),
                last_failure_at=next((item.collected_at for item in reversed(known) if item.status == "offline"), None),
                ended_unavailable=final.status == "offline",
            )
        )
    return rows


def build_interruption_views(
    session: MonitoringSession,
    destinations: list[DestinationMetricsView],
    stored_interruptions: list[InterruptionRecord],
) -> list[InterruptionReportView]:
    """Return stored interruptions plus open failures closed logically by session end."""
    views = []
    for item in stored_interruptions:
        status = str(item.payload.get("status") or ("OPEN" if item.ended_at is None else "RECOVERED"))
        views.append(
            InterruptionReportView(
                target_name=item.target_name,
                event_type=item.event_type,
                status=status,
                started_at=item.started_at,
                ended_at=item.ended_at,
                duration_seconds=item.duration_seconds,
                lost_tests=item.lost_tests,
                max_consecutive_failures=item.max_consecutive_failures,
                no_recovery_observed=status in {"OPEN", "CLOSED_BY_SESSION_END"},
                message=str(item.payload.get("message", "Interrupcao recuperada." if status == "RECOVERED" else "Interrupcao sem recuperacao observada.")),
            )
        )
    existing = {item.target_name for item in views}
    session_end = session.finished_at or session.expected_end_at
    for destination in destinations:
        if not destination.ended_unavailable or destination.target_name in existing or destination.last_failure_at is None:
            continue
        views.append(
            InterruptionReportView(
                target_name=destination.target_name,
                event_type="connection_unavailable" if destination.probe == "TCP" else "target_unavailable",
                status="CLOSED_BY_SESSION_END",
                started_at=destination.last_failure_at,
                ended_at=session_end,
                duration_seconds=max(0.0, (session_end - destination.last_failure_at).total_seconds()),
                lost_tests=destination.failures,
                max_consecutive_failures=destination.max_consecutive_failures,
                no_recovery_observed=True,
                message="Interrupcao ainda ativa no encerramento da coleta; recuperacao nao observada.",
            )
        )
    return sorted(views, key=lambda item: item.started_at)


def build_marker_views(marks: list[StoredCustomerMark], session: MonitoringSession | None = None) -> list[MarkerReportView]:
    """Summarize before/after context by cycles and nearest anomalies."""
    views: list[MarkerReportView] = []
    for index, mark in enumerate(sorted(marks, key=lambda item: (item.marked_at, item.mark_id)), start=1):
        before = [item for item in mark.payload.get("before", []) if not item.get("is_warmup")]
        after = [item for item in mark.payload.get("after", []) if not item.get("is_warmup")]
        first_after = _nearest_anomaly(after, mark.marked_at, after=True)
        first_before = _nearest_anomaly(before, mark.marked_at, after=False)
        sequence_number = _optional_int(mark.payload.get("sequence_number")) or index
        classification = mark.payload.get("classification")
        correlation_level = normalize_correlation_level(classification)
        limitations: list[str] = []
        if not mark.payload.get("after_context_complete"):
            limitations.append("Contexto posterior parcial ou limitado pelo fim da sessao.")
        if before:
            first_before_time = datetime.fromisoformat(before[0]["collected_at"])
            limitations.append(f"Contexto anterior cobriu {max(0.0, (mark.marked_at - first_before_time).total_seconds()):.0f}s.")
        views.append(
            MarkerReportView(
                mark_id=mark.mark_id,
                sequence_number=sequence_number,
                marked_at=mark.marked_at,
                relative_session_seconds=_relative_session_seconds(mark.marked_at, session),
                anchor_id=customer_marker_anchor(sequence_number),
                replay_anchor_id=customer_marker_replay_anchor(sequence_number),
                title=f"OCORRENCIA REGISTRADA PELO CLIENTE #{sequence_number}",
                description=str(
                    mark.payload.get("customer_description")
                    or mark.payload.get("description")
                    or "Ocorrencia registrada pelo cliente pelo botao flutuante."
                ),
                event_type=str(mark.payload.get("event_type") or CUSTOMER_MARKER_EVENT_TYPE),
                event_origin=str(mark.payload.get("event_origin") or CUSTOMER_MARKER_ORIGIN),
                is_customer_marker=bool(mark.payload.get("is_customer_marker", True)),
                visual_priority=str(mark.payload.get("visual_priority") or CUSTOMER_MARKER_VISUAL_PRIORITY),
                context_status=mark.context_status.value,
                context_start=_optional_datetime(mark.payload.get("context_start")),
                context_end=_optional_datetime(mark.payload.get("context_end")),
                immediate_snapshot_at=_optional_datetime(mark.payload.get("immediate_snapshot_at")),
                technical_snapshot_status=_optional_str(mark.payload.get("technical_snapshot_status")),
                before_samples=len(before),
                after_samples=len(after),
                before_cycles=len({item.get("collected_at") for item in before}),
                after_cycles=len({item.get("collected_at") for item in after}),
                requested_before_seconds=_optional_float(mark.payload.get("context_before_seconds")),
                requested_after_seconds=_optional_float(mark.payload.get("context_after_seconds")),
                seconds_before=_context_seconds(before),
                seconds_after=_context_seconds(after),
                nearest_anomaly_seconds=_optional_float(mark.payload.get("nearest_anomaly_seconds")),
                nearest_anomaly_target=_optional_str(mark.payload.get("nearest_anomaly_target")),
                first_anomaly_after_seconds=first_after[0],
                first_anomaly_after_target=first_after[1],
                first_anomaly_before_seconds=first_before[0],
                first_anomaly_before_target=first_before[1],
                affected_monitors=_string_list(mark.payload.get("affected_monitors")),
                nearby_events=_dict_list(mark.payload.get("nearby_events")),
                correlation_level=correlation_level,
                correlation_label=correlation_label(correlation_level),
                conclusion=_marker_conclusion(mark, first_after),
                limitations=limitations,
            )
        )
    return views


def build_customer_markers_summary(markers: list[MarkerReportView]) -> CustomerMarkersSummaryView:
    """Aggregate customer marker counts for report cards and JSON."""
    return CustomerMarkersSummaryView(
        total=len(markers),
        complete=sum(1 for item in markers if item.context_status == "complete"),
        partial=sum(1 for item in markers if item.context_status == "partial"),
        pending=sum(1 for item in markers if item.context_status == "pending_after_context"),
        strong_correlations=sum(1 for item in markers if item.correlation_level == "strong"),
        moderate_correlations=sum(1 for item in markers if item.correlation_level == "moderate"),
        weak_correlations=sum(1 for item in markers if item.correlation_level == "weak"),
        no_anomaly=sum(1 for item in markers if item.correlation_level == "none"),
        insufficient=sum(1 for item in markers if item.correlation_level == "insufficient"),
        anchors=[item.anchor_id for item in markers],
    )


def build_sip_options_views(records: list[DiagnosticRecord]) -> list[SipOptionsView]:
    """Build safe SIP OPTIONS rows without exposing challenge internals."""
    rows: list[SipOptionsView] = []
    for record in records:
        payload = record.payload
        code = _optional_int(payload.get("sip_code"))
        rows.append(
            SipOptionsView(
                collected_at=record.collected_at,
                transport=str(payload.get("transport") or "N/D"),
                host=str(payload.get("host") or "N/D"),
                port=int(payload["port"]) if payload.get("port") is not None else None,
                status=str(payload.get("status") or "N/D"),
                sip_code=code,
                sip_reason=str(payload.get("sip_reason") or ""),
                duration_ms=float(payload["duration_ms"]) if payload.get("duration_ms") is not None else None,
                interpretation=_sip_options_interpretation(code),
            )
        )
    return rows


def build_sip_transport_views(records: list[DiagnosticRecord]) -> list[SipTransportView]:
    """Build SIP transport rows."""
    rows: list[SipTransportView] = []
    for record in records:
        for item in record.payload.get("results", []):
            rows.append(
                SipTransportView(
                    transport=str(item.get("transport") or "N/D"),
                    port=int(item["port"]) if item.get("port") is not None else None,
                    status=str(item.get("status") or "N/D"),
                    duration_ms=float(item["duration_ms"]) if item.get("duration_ms") is not None else None,
                    certificate="validado" if item.get("certificate") else "N/D",
                    observation=_transport_observation(item),
                )
            )
    return rows


def build_traffic_view(records: list[DiagnosticRecord]) -> TrafficReportView:
    """Build traffic presentation summary without turning missing rates into zero."""
    available = [item for item in records if item.payload.get("available")]
    latest = available[-1].payload if available else {}
    rated = [item for item in available if item.payload.get("rate_available", True)]
    return TrafficReportView(
        samples=len(available),
        latest_interface=_optional_str(latest.get("interface")),
        mode=_optional_str(latest.get("mode")),
        counter_source=_optional_str(latest.get("counter_source")),
        latest_rate_available=bool(latest.get("rate_available", False)),
        upload_current_mbps=_optional_float(latest.get("upload_mbps")),
        download_current_mbps=_optional_float(latest.get("download_mbps")),
        upload_peak_mbps=max((_optional_float(item.payload.get("upload_peak_mbps")) or 0.0 for item in rated), default=None),
        download_peak_mbps=max((_optional_float(item.payload.get("download_peak_mbps")) or 0.0 for item in rated), default=None),
        collection_failures=len(records) - len(available),
    )


def build_system_view(records: list[DiagnosticRecord]) -> SystemReportView:
    """Build CPU, memory and storage presentation summary."""
    available = [item for item in records if item.payload.get("available")]
    latest = available[-1].payload if available else {}
    cpu = [_optional_float(item.payload.get("cpu_percent")) for item in available]
    memory = [_optional_float(item.payload.get("memory_used_percent")) for item in available]
    cpu_values = [item for item in cpu if item is not None]
    memory_values = [item for item in memory if item is not None]
    return SystemReportView(
        samples=len(available),
        cpu_current_percent=_optional_float(latest.get("cpu_percent")),
        cpu_avg_percent=sum(cpu_values) / len(cpu_values) if cpu_values else None,
        cpu_p95_percent=percentile(cpu_values, 95),
        cpu_peak_percent=max(cpu_values) if cpu_values else None,
        memory_current_percent=_optional_float(latest.get("memory_used_percent")),
        memory_avg_percent=sum(memory_values) / len(memory_values) if memory_values else None,
        memory_peak_percent=max(memory_values) if memory_values else None,
        memory_available_mb=_optional_float(latest.get("memory_available_mb")),
        disk_used_percent=_optional_float(latest.get("disk_used_percent")),
    )


def build_wifi_view(records: list[DiagnosticRecord], system_info: SystemInfoRecord | None) -> WifiReportView:
    """Build Wi-Fi presentation summary and distinguish Wi-Fi from default route."""
    latest_record = records[-1] if records else None
    payload = latest_record.payload if latest_record else {}
    active_interface = _optional_str((system_info.payload if system_info else {}).get("active_interface"))
    wifi_used = _wifi_matches_interface(payload, active_interface) if payload.get("available") else None
    note = "Wi-Fi indisponivel ou nao coletado."
    if payload.get("available") and wifi_used is True:
        note = "O adaptador Wi-Fi estava disponivel e aparenta ser a rota utilizada pelo monitoramento."
    elif payload.get("available") and wifi_used is False:
        note = "O adaptador Wi-Fi estava disponivel, porem a rota padrao utilizada pelo monitoramento aparenta ser outra interface."
    return WifiReportView(
        available=bool(payload.get("available", False)),
        connected=payload.get("connected") if isinstance(payload.get("connected"), bool) else None,
        ssid=_optional_str(payload.get("ssid")),
        signal_percent=_optional_float(payload.get("signal_percent")),
        radio_type=_optional_str(payload.get("radio_type")),
        channel=_optional_str(payload.get("channel")),
        receive_rate_mbps=_optional_float(payload.get("receive_rate_mbps")),
        transmit_rate_mbps=_optional_float(payload.get("transmit_rate_mbps")),
        bssid_masked=_optional_str(payload.get("bssid_masked")),
        active_interface=active_interface,
        wifi_used_by_monitoring=wifi_used,
        note=note,
    )


def build_route_views(records: list[DiagnosticRecord]) -> list[RouteReportView]:
    """Build route summaries."""
    rows: list[RouteReportView] = []
    for record in records:
        payload = record.payload
        hops = payload.get("hops") if isinstance(payload.get("hops"), list) else []
        rows.append(
            RouteReportView(
                available=bool(payload.get("available", False)),
                reason=_optional_str(payload.get("reason")) or "coleta complementar",
                duration_seconds=_optional_float(payload.get("duration_seconds")),
                hop_count=len(hops),
                timed_out_hops=sum(1 for hop in hops if isinstance(hop, dict) and hop.get("timeout")),
                hops=[
                    RouteHopView(
                        hop=int(hop.get("hop", 0)),
                        address=_optional_str(hop.get("address")),
                        time_1_ms=_optional_float(hop.get("time_1_ms")),
                        time_2_ms=_optional_float(hop.get("time_2_ms")),
                        time_3_ms=_optional_float(hop.get("time_3_ms")),
                        state="sem resposta" if hop.get("timeout") else "respondido",
                    )
                    for hop in hops
                    if isinstance(hop, dict)
                ],
                note=_optional_str(payload.get("note")),
            )
        )
    return rows


def build_time_sync_view(records: list[DiagnosticRecord]) -> TimeSyncReportView:
    """Build Windows time synchronization summary."""
    latest = records[-1].payload if records else {}
    windows_time = latest.get("windows_time") if isinstance(latest.get("windows_time"), dict) else {}
    available = windows_time.get("available") if isinstance(windows_time, dict) else None
    return TimeSyncReportView(
        local_time=_optional_str(latest.get("local_time")),
        timezone=_optional_str(latest.get("timezone")),
        synchronized=available if isinstance(available, bool) else None,
        source=_optional_str(windows_time.get("source")) if isinstance(windows_time, dict) else None,
        last_successful_sync=_optional_str(windows_time.get("last_successful_sync")) if isinstance(windows_time, dict) else None,
        stratum=_optional_str(windows_time.get("stratum")) if isinstance(windows_time, dict) else None,
        offset=_optional_str(windows_time.get("offset")) if isinstance(windows_time, dict) else None,
        service_active=windows_time.get("service_active") if isinstance(windows_time.get("service_active"), bool) else None,
        observation="Windows Time respondeu ao diagnostico." if available else "Nao foi possivel confirmar sincronizacao pelo w32tm.",
    )


def build_softphone_view(
    process_records: list[DiagnosticRecord],
    metric_records: list[DiagnosticRecord],
    event_records: list[DiagnosticRecord],
) -> SoftphoneReportView:
    """Build softphone process presentation summary."""
    latest_metric = metric_records[-1].payload if metric_records else {}
    selected = latest_metric.get("selected") if isinstance(latest_metric.get("selected"), dict) else {}
    process_name = _optional_str(selected.get("name")) or _optional_str(latest_metric.get("process_name"))
    events = [
        SoftphoneEventReportRow(
            occurred_at=_optional_datetime(record.payload.get("occurred_at")) or record.collected_at,
            event_type=str(record.payload.get("event_type") or "softphone_event"),
            severity=str(record.payload.get("severity") or "info"),
            message=str(record.payload.get("message") or ""),
            pid=_optional_int(((record.payload.get("payload") or {}).get("process") or {}).get("pid"))
            if isinstance(record.payload.get("payload"), dict)
            else None,
        )
        for record in event_records
    ]
    return SoftphoneReportView(
        configured=bool(process_records or latest_metric.get("configured")),
        found=bool(latest_metric.get("found", False)),
        process_name=process_name,
        pid=_optional_int(selected.get("pid")),
        exe=_optional_str(selected.get("exe")),
        started_at=_optional_datetime(selected.get("create_time")),
        cpu_percent=_optional_float(selected.get("cpu_percent")),
        rss_mb=_optional_float(selected.get("rss_mb")),
        memory_percent=_optional_float(selected.get("memory_percent")),
        thread_count=_optional_int(selected.get("thread_count")),
        handle_count=_optional_int(selected.get("handle_count")),
        instance_count=_optional_int(latest_metric.get("instance_count")) or 0,
        event_count=len(events),
        high_cpu_events=sum(1 for event in events if event.event_type == "softphone_cpu_high"),
        high_memory_events=sum(1 for event in events if event.event_type == "softphone_memory_high"),
        not_responding_events=sum(1 for event in events if event.event_type == "softphone_not_responding"),
        events=events,
        limitations=[
            "CPU alta do processo nao comprova travamento por si so; e necessario correlacionar duracao, sintomas e outros eventos.",
            "Estado 'nao respondendo' so e apresentado quando houver metodo confiavel de coleta.",
            "Caminho do executavel pode ficar indisponivel quando o Windows negar acesso ao processo.",
        ],
    )


def build_windows_event_views(records: list[DiagnosticRecord]) -> list[WindowsEventReportRow]:
    """Build normalized Windows event rows."""
    rows: list[WindowsEventReportRow] = []
    for record in records:
        events = record.payload.get("events") if isinstance(record.payload.get("events"), list) else []
        for event in events:
            if not isinstance(event, dict):
                continue
            rows.append(
                WindowsEventReportRow(
                    occurred_at=_optional_datetime(event.get("occurred_at")) or record.collected_at,
                    provider=str(event.get("provider") or "N/D"),
                    windows_event_id=_optional_int(event.get("windows_event_id")),
                    category=str(event.get("category") or "system"),
                    device_name=_optional_str(event.get("device_name")),
                    normalized_type=str(event.get("normalized_type") or "windows_event"),
                    summary=str(event.get("summary") or "Evento do Windows registrado."),
                    relevance=str(event.get("relevance") or "baixa"),
                )
            )
    return sorted(rows, key=lambda item: item.occurred_at)


def build_power_audit_views(records: list[DiagnosticRecord]) -> list[PowerAuditReportRow]:
    """Build latest power audit rows."""
    latest = records[-1].payload if records else {}
    items = latest.get("items") if isinstance(latest.get("items"), list) else []
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rows.append(
            PowerAuditReportRow(
                item=str(item.get("item") or "N/D"),
                classification=str(item.get("classification") or "NAO DISPONIVEL"),
                current_value=str(item.get("current_value") or "nao disponivel"),
                source=str(item.get("source") or "N/D"),
                related_device=_optional_str(item.get("related_device")),
                possible_impact=str(item.get("possible_impact") or "N/D"),
                related_event=_optional_str(item.get("related_event")),
                manual_guidance=str(item.get("manual_guidance") or "N/D"),
            )
        )
    return rows


def build_report_conclusion(
    destinations: list[DestinationMetricsView],
    events: list[EventRecord],
    markers: list[MarkerReportView],
    sip_options: list[SipOptionsView],
    interruptions: list[InterruptionReportView],
    audio: AudioReportView | None = None,
    softphone: SoftphoneReportView | None = None,
) -> AutomaticConclusion:
    """Build a final conclusion using all presentation evidence."""
    sip_tcp = _sip_tcp_destination(destinations)
    gateway_stable = _stable_category(destinations, "gateway")
    internet_stable = _stable_category(destinations, "internet")
    dns_stable = _stable_category(destinations, "dns")
    if sip_tcp and (
        sip_tcp.failure_rate_percent >= 10
        or sip_tcp.max_consecutive_failures >= 3
        or sip_tcp.ended_unavailable
    ):
        marker_text = _marker_evidence(markers, sip_tcp.target_name)
        options_text = _sip_options_evidence(sip_options)
        evidences = [
            f"{sip_tcp.target_name}: {sip_tcp.failures} falhas em {sip_tcp.tests} testes ({sip_tcp.failure_rate_percent:.1f}% de falhas).",
            f"Maior sequencia de falhas consecutivas: {sip_tcp.max_consecutive_failures}.",
            f"Disponibilidade da conexao TCP SIP: {sip_tcp.availability_percent:.1f}%.",
        ]
        if gateway_stable and internet_stable and dns_stable:
            evidences.append("Gateway, internet por IP e DNS permaneceram majoritariamente disponiveis.")
        if sip_tcp.ended_unavailable:
            evidences.append("A sessao terminou sem recuperacao observada da conexao TCP SIP.")
        if marker_text:
            evidences.append(marker_text)
        if options_text:
            evidences.append(options_text)
        confidence = ConfidenceLevel.HIGH if sip_tcp.max_consecutive_failures >= 4 and gateway_stable and internet_stable else ConfidenceLevel.MEDIUM
        return _conclusion(
            "Foi detectada instabilidade especifica na comunicacao TCP com o servico SIP. O comportamento e compativel com falha intermitente, bloqueio temporario ou indisponibilidade especifica do servico ou transporte SIP.",
            "SERVICO SIP / COMUNICACAO TCP",
            confidence,
            evidences,
            [
                "Validar disponibilidade do transporte TCP no servidor SIP, firewall, NAT, regras de seguranca e logs da plataforma.",
                "Nao interpretar essas falhas TCP, isoladamente, como perda RTP ou degradacao real de audio.",
            ],
        )
    critical_events = [event for event in events if event.severity.value == "critical"]
    if critical_events:
        return _conclusion(
            "Foram detectados eventos criticos durante a sessao.",
            "anomalia tecnica detectada",
            ConfidenceLevel.MEDIUM,
            [f"{event.event_type}: {event.message}" for event in critical_events[:5]],
            ["Comparar os eventos criticos com as marcacoes do cliente."],
        )
    if softphone and softphone.event_count:
        evidences = [f"{item.event_type}: {item.message}" for item in softphone.events[:5]]
        if gateway_stable and internet_stable and dns_stable:
            evidences.append("Rede local, internet por IP e DNS permaneceram majoritariamente disponiveis.")
        confidence = ConfidenceLevel.MEDIUM if softphone.not_responding_events or softphone.high_memory_events else ConfidenceLevel.LOW
        return _conclusion(
            "Foram detectados eventos relevantes no processo do softphone durante a sessao. O comportamento pode indicar instabilidade local da aplicacao ou pressao de recursos do computador.",
            "aplicacao de telefonia / desempenho local",
            confidence,
            evidences,
            [
                "Comparar os horarios dos eventos do softphone com as marcacoes do cliente.",
                "Nao concluir travamento apenas por CPU alta sem duracao, ausencia de resposta ou sintoma correlacionado.",
            ],
        )
    if audio and audio.event_count:
        evidences = [
            f"{item.event_type}: {item.message}"
            for item in audio.events[:5]
        ]
        return _conclusion(
            "Foram detectadas alteracoes relevantes em dispositivos de audio durante a sessao.",
            "dispositivo de audio / configuracao local",
            ConfidenceLevel.MEDIUM,
            evidences,
            [
                "Conferir headset, dispositivo padrao de comunicacao, volume, mudo, USB/Bluetooth e driver.",
                "Nao concluir defeito fisico sem validacao local do dispositivo.",
            ],
        )
    if destinations:
        return _conclusion(
            "Nao foram detectadas anomalias nos destinos monitorados durante esta sessao.",
            "nenhuma instabilidade detectada",
            ConfidenceLevel.LOW,
            ["As medicoes disponiveis nao ultrapassaram os limites configurados."],
            ["Esse resultado nao descarta problemas especificos de equipamento, codec, RTP ou aplicacao."],
        )
    return _conclusion(
        "Dados insuficientes para uma conclusao automatica.",
        "dados insuficientes",
        ConfidenceLevel.INCONCLUSIVE,
        [],
        ["Coletar uma nova sessao com duracao suficiente."],
    )


def validate_report_consistency(
    conclusion: AutomaticConclusion,
    destinations: list[DestinationMetricsView],
    events: list[EventRecord],
    interruptions: list[InterruptionReportView],
    audio: AudioReportView | None = None,
    softphone: SoftphoneReportView | None = None,
    markers: list[MarkerReportView] | None = None,
) -> list[str]:
    """Find contradictions that must not pass silently into exports."""
    findings: list[str] = []
    says_no_anomaly = conclusion.likely_origin == "nenhuma instabilidade detectada"
    if says_no_anomaly and any(event.severity.value == "critical" for event in events):
        findings.append("Conclusao sem anomalia contradiz eventos criticos.")
    if says_no_anomaly and any(item.failure_rate_percent >= 10 for item in destinations):
        findings.append("Conclusao sem anomalia contradiz destino com taxa de falhas relevante.")
    if says_no_anomaly and any(item.max_consecutive_failures >= 3 for item in destinations):
        findings.append("Conclusao sem anomalia contradiz tres ou mais falhas consecutivas.")
    if says_no_anomaly and any(item.no_recovery_observed for item in interruptions):
        findings.append("Conclusao sem anomalia contradiz interrupcao sem recuperacao observada.")
    if says_no_anomaly and audio and audio.event_count:
        findings.append("Conclusao sem anomalia contradiz eventos de audio registrados.")
    if says_no_anomaly and softphone and softphone.event_count:
        findings.append("Conclusao sem anomalia contradiz eventos de softphone registrados.")
    markers = markers or []
    anchors = [item.anchor_id for item in markers]
    if len(set(anchors)) != len(anchors):
        findings.append("Marcacoes do cliente possuem identificadores de ancora duplicados.")
    expected_sequences = list(range(1, len(markers) + 1))
    actual_sequences = [item.sequence_number for item in markers]
    if actual_sequences != expected_sequences:
        findings.append("Sequencia das marcacoes do cliente esta inconsistente.")
    if any(not item.is_customer_marker for item in markers):
        findings.append("Marcacao persistida sem identificador estruturado de ocorrencia do cliente.")
    return findings


def _conclusion(
    result: str,
    origin: str,
    confidence: ConfidenceLevel,
    evidences: list[str],
    recommendations: list[str],
) -> AutomaticConclusion:
    return AutomaticConclusion(
        result=result,
        likely_origin=origin,
        confidence=confidence,
        evidences=evidences,
        confidence_reducers=[],
        recommendations=recommendations,
    )


def _probe_for(item: MeasurementRecord) -> str:
    protocol = str(item.payload.get("target", {}).get("protocol") or "").upper()
    probe = str(item.payload.get("details", {}).get("probe") or "").upper()
    name = item.target_name.upper()
    if " TCP" in name or protocol == "TCP" or probe == "TCP":
        return "TCP"
    if " DNS" in name or protocol == "DNS" or probe == "DNS":
        return "DNS"
    if protocol == "TLS" or probe == "TLS":
        return "TLS"
    if protocol == "UDP" or probe == "UDP":
        return "UDP"
    return "ICMP"


def _category_for(item: MeasurementRecord) -> str:
    kind = str(item.payload.get("target", {}).get("kind", "unknown"))
    if "SIP " in item.target_name:
        return "sip"
    if kind in {"internet_ip", "custom"}:
        return "internet"
    return kind


def _short_name(name: str) -> str:
    if name == "Gateway local":
        return "Gateway"
    return name.replace("SIP ", "SIP ").replace(":5060", "")


def _response_variation(latencies: list[float]) -> float | None:
    if len(latencies) < 2:
        return None
    deltas = [abs(current - previous) for previous, current in zip(latencies, latencies[1:], strict=False)]
    return sum(deltas) / len(deltas)


def _max_consecutive_failures(values: list[MeasurementRecord]) -> int:
    current = 0
    maximum = 0
    for item in values:
        if item.status == "offline":
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _sip_tcp_destination(destinations: list[DestinationMetricsView]) -> DestinationMetricsView | None:
    for destination in destinations:
        if destination.category == "sip" and destination.probe == "TCP":
            return destination
    return None


def _stable_category(destinations: list[DestinationMetricsView], category: str) -> bool:
    matches = [item for item in destinations if item.category == category]
    return bool(matches) and all(item.failure_rate_percent <= 10 and not item.ended_unavailable for item in matches)


def _nearest_anomaly(samples: list[dict[str, Any]], marked_at: datetime, after: bool) -> tuple[float | None, str | None]:
    anomalies = [
        item for item in samples
        if item.get("status") in {"offline", "degraded"}
    ]
    if not anomalies:
        return None, None
    anomalies.sort(key=lambda item: abs((datetime.fromisoformat(item["collected_at"]) - marked_at).total_seconds()))
    first = anomalies[0]
    seconds = (datetime.fromisoformat(first["collected_at"]) - marked_at).total_seconds()
    if not after:
        seconds = abs(seconds)
    return abs(seconds), str(first.get("target_name"))


def _context_seconds(samples: list[dict[str, Any]]) -> float | None:
    if len(samples) < 2:
        return None
    times = [datetime.fromisoformat(item["collected_at"]) for item in samples]
    return max(0.0, (max(times) - min(times)).total_seconds())


def _marker_conclusion(mark: StoredCustomerMark, first_after: tuple[float | None, str | None]) -> str:
    seconds, target = first_after
    if seconds is None or target is None:
        return str(mark.payload.get("conclusion", "Sem anomalia proxima confirmada."))
    return f"A primeira anomalia detectada apos a marcacao ocorreu aproximadamente {seconds:.0f} segundos depois e afetou {target}."


def _marker_evidence(markers: list[MarkerReportView], target_name: str) -> str | None:
    for marker in markers:
        if marker.first_anomaly_after_target == target_name and marker.first_anomaly_after_seconds is not None:
            return (
                f"Primeira falha correlacionada ocorreu aproximadamente "
                f"{marker.first_anomaly_after_seconds:.0f} segundos apos a marcacao do cliente."
            )
    return None


def _sip_options_evidence(options: list[SipOptionsView]) -> str | None:
    for option in options:
        if option.sip_code in {200, 401, 403, 404}:
            return f"SIP OPTIONS recebeu {option.sip_code} {option.sip_reason}, comprovando resposta valida do servico SIP."
    return None


def _sip_options_interpretation(code: object) -> str:
    code = _optional_int(code)
    if code in {200, 401, 403, 404}:
        if code == 401:
            return "O servico SIP respondeu e solicitou autenticacao."
        return "O servico SIP respondeu com uma resposta SIP valida."
    if code in {408, 503}:
        return "O servico SIP respondeu indicando indisponibilidade ou timeout."
    return "Resultado inconclusivo ou sem resposta SIP valida."


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _relative_session_seconds(marked_at: datetime, session: MonitoringSession | None) -> float:
    if session is None:
        return 0.0
    return max(0.0, (marked_at - session.started_at).total_seconds())


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item not in (None, "")]


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _wifi_matches_interface(payload: dict[str, Any], active_interface: str | None) -> bool | None:
    if not active_interface:
        return None
    if not payload.get("available"):
        return None
    lowered = active_interface.lower()
    return "wi-fi" in lowered or "wireless" in lowered or "wlan" in lowered


def _transport_observation(item: dict[str, Any]) -> str:
    transport = str(item.get("transport") or "").upper()
    status = str(item.get("status") or "")
    if transport == "UDP" and status == "inconclusive":
        return "Ausencia de resposta UDP nao comprova bloqueio."
    if status == "online":
        return "Conexao estabelecida ou resposta valida observada."
    if status == "offline":
        return "Falha de conexao ou handshake."
    return "Evidencia inconclusiva."
