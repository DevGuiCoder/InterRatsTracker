"""Monitoring loop orchestration for probes and customer marks."""

from __future__ import annotations

import asyncio
import queue
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any

from src.audio.audio_event_monitor import AudioEventMonitor
from src.audio.audio_level_monitor import AudioLevelMonitor
from src.audio.device_enumerator import collect_audio_inventory, inventory_summary
from src.audio.permission_checker import check_microphone_permissions
from src.analysis.event_detector import EventDetector
from src.analysis.metrics import MetricsAggregator
from src.analysis.status_classifier import classify_probe_results, group_statuses
from src.analysis.voice_quality import classify_voice_quality
from src.monitoring.dns_monitor import resolve_once
from src.monitoring.network_environment import collect_network_environment
from src.monitoring.power_audit import collect_power_audit
from src.monitoring.ping_monitor import ping_once
from src.monitoring.public_ip_monitor import collect_public_ip
from src.monitoring.process_snapshot import ProcessSnapshotService
from src.monitoring.route_trace import collect_route_trace
from src.monitoring.sip_target_monitor import probe_sip_target
from src.monitoring.sip_options_monitor import sip_options_once, test_sip_transport
from src.monitoring.softphone_monitor import SoftphoneMonitor, SoftphoneMonitorConfig
from src.monitoring.softphone_config_inspector import UnsupportedSoftphoneConfigInspector
from src.monitoring.system_performance_monitor import collect_system_metrics
from src.monitoring.technical_snapshot import collect_technical_snapshot, compare_snapshot_to_baseline
from src.monitoring.time_sync_monitor import collect_time_sync
from src.monitoring.traffic_monitor import TrafficSampler
from src.monitoring.udp_flow_monitor import run_udp_flow_test
from src.monitoring.wifi_monitor import collect_wifi_info
from src.monitoring.windows_event_collector import WindowsEventCollector
from src.reports.customer_markers import (
    CUSTOMER_MARKER_EVENT_TYPE,
    CUSTOMER_MARKER_ORIGIN,
    CUSTOMER_MARKER_SOURCE,
    CUSTOMER_MARKER_VISUAL_PRIORITY,
)
from src.storage.database import Database
from src.storage.models import (
    CustomerMarkContextStatus,
    CustomerMarkSignal,
    EventRecord,
    EventSeverity,
    MonitoringSession,
    MonitoringSnapshot,
    ProbeResult,
    ProbeStatus,
    TargetDefinition,
    TargetKind,
)
from src.utils.config_loader import AppConfig
from src.utils.networking import detect_active_interface, is_ip_address
from src.utils.profile_loader import get_profile

SnapshotCallback = Callable[[MonitoringSnapshot], None]


@dataclass
class _PendingCustomerMark:
    mark_id: int
    marked_at: datetime
    payload: dict[str, Any]


@dataclass
class _SnapshotJob:
    mark_id: int
    marked_at: datetime
    latest_results: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    group_statuses: dict[str, Any]


class MonitoringRunner:
    """Runs network probes for one monitoring session."""

    def __init__(self, database: Database, app_config: AppConfig) -> None:
        self._database = database
        self._config = app_config

    async def run(
        self,
        session: MonitoringSession,
        on_snapshot: SnapshotCallback | None = None,
        mark_queue: queue.Queue[CustomerMarkSignal] | None = None,
    ) -> MonitoringSnapshot:
        """Run probes until the configured session end time."""
        interface = detect_active_interface()
        targets = self._build_targets(session, interface.gateway)
        self._database.store_targets(session.session_id, targets)
        profile = get_profile(session.request.profile_id)
        enabled_monitors = set(profile.enabled_monitors if profile else [])
        audio_enabled = self._config.monitoring.audio_monitoring_enabled and "audio" in enabled_monitors
        audio_monitor = AudioEventMonitor()
        audio_level_monitor = AudioLevelMonitor()
        process_snapshot_service = ProcessSnapshotService()
        softphone_monitor = self._build_softphone_monitor(session, process_snapshot_service)
        windows_event_collector = WindowsEventCollector() if self._config.monitoring.windows_events_enabled else None
        if softphone_monitor:
            self._database.store_diagnostic_record(
                "softphone_processes",
                session.session_id,
                datetime.now(UTC),
                {
                    "configured": True,
                    "process_name": session.request.softphone_process_name,
                    "expected_path": session.request.softphone_expected_path,
                    "expected_pid": session.request.softphone_expected_pid,
                },
            )
            config_snapshot = UnsupportedSoftphoneConfigInspector(
                session.request.softphone_process_name or "softphone"
            ).inspect()
            self._database.store_diagnostic_record(
                "softphone_config_snapshots",
                session.session_id,
                datetime.now(UTC),
                config_snapshot,
            )
        if audio_enabled:
            initial_audio = collect_audio_inventory()
            audio_monitor.update(initial_audio)
            self._database.store_diagnostic_record("audio_devices", session.session_id, initial_audio.collected_at, initial_audio.to_dict())
            self._database.store_diagnostic_record(
                "audio_driver_information",
                session.session_id,
                initial_audio.collected_at,
                {
                    "drivers": [
                        device.to_dict()
                        for device in initial_audio.devices
                        if device.driver_version or device.pnp_status or device.pnp_error_code is not None
                    ]
                },
            )
            permissions = check_microphone_permissions()
            self._database.store_diagnostic_record("audio_permissions", session.session_id, initial_audio.collected_at, permissions)

        aggregator = MetricsAggregator(
            jitter_window_size=self._config.monitoring.jitter_window_samples,
            minimum_samples_for_jitter=self._config.monitoring.minimum_samples_for_jitter,
        )
        event_detector = EventDetector(self._config.thresholds)
        latest_snapshot: MonitoringSnapshot | None = None
        recent_results: deque[ProbeResult] = deque(maxlen=self._recent_result_limit(session))
        pending_marks: list[_PendingCustomerMark] = []
        mark_count = 0
        latest_mark_at: datetime | None = None
        last_interface = interface
        recent_events: deque[EventRecord] = deque(maxlen=12)
        last_resolved_ips: dict[str, set[str]] = {}
        warmup_until = session.started_at + timedelta(seconds=self._config.monitoring.warmup_seconds)
        official_started_event_recorded = self._config.monitoring.warmup_seconds <= 0
        baseline = self._database.get_session_baseline(session.session_id)
        traffic_sampler = TrafficSampler()
        timers: dict[str, float] = {}
        latest_diagnostics: dict[str, Any] = {}
        snapshot_queue: asyncio.Queue[_SnapshotJob | None] = asyncio.Queue(
            maxsize=max(1, self._config.monitoring.snapshot_queue_size)
        )
        snapshot_worker = asyncio.create_task(
            self._snapshot_worker(session, snapshot_queue, baseline.payload if baseline else None, recent_events)
        )

        try:
            while datetime.now(UTC) < session.expected_end_at:
                cycle_started = perf_counter()
                current_interface = detect_active_interface()
                now = datetime.now(UTC)
                is_warmup = now < warmup_until
                warmup_remaining = max(0, int((warmup_until - now).total_seconds()))
                if current_interface != last_interface and not is_warmup:
                    self._store_timeline_event(
                        recent_events,
                        session_id=session.session_id,
                        occurred_at=datetime.now(UTC),
                        severity=EventSeverity.WARNING,
                        event_type="interface_changed",
                        message="Interface, gateway ou IP local mudou durante o monitoramento.",
                        payload={
                            "previous": last_interface.__dict__,
                            "current": current_interface.__dict__,
                        },
                        target_name="interface",
                        technical_description="Mudanca detectada na rota ativa local.",
                    )
                    last_interface = current_interface
                elif current_interface != last_interface:
                    last_interface = current_interface

                results = classify_probe_results(await self._probe_targets(targets))
                if is_warmup:
                    results = self._mark_warmup_results(results, warmup_remaining)
                else:
                    if not official_started_event_recorded:
                        self._store_timeline_event(
                            recent_events,
                            session_id=session.session_id,
                            occurred_at=now,
                            severity=EventSeverity.INFO,
                            event_type="official_monitoring_started",
                            message="Monitoramento oficial iniciado apos aquecimento.",
                            payload={"warmup_seconds": self._config.monitoring.warmup_seconds},
                        )
                        official_started_event_recorded = True
                    results = self._apply_thresholds(results)
                    aggregator.add_results(results)

                metric_summaries = aggregator.summaries()
                if not is_warmup or self._config.monitoring.store_warmup_measurements:
                    self._database.store_probe_results(session.session_id, results, is_warmup=is_warmup)
                recent_results.extend(results)

                if not is_warmup:
                    self._detect_dns_ip_changes(session.session_id, results, last_resolved_ips, recent_events)
                    for interruption in aggregator.drain_closed_interruptions():
                        self._database.store_interruption(
                            session_id=session.session_id,
                            target_name=interruption.target_name,
                            event_type="target_interruption",
                            started_at=interruption.started_at,
                            ended_at=interruption.ended_at,
                            duration_seconds=interruption.duration_seconds,
                            lost_tests=interruption.lost_tests,
                            max_consecutive_failures=interruption.max_consecutive_failures,
                            payload={"source": "metrics_aggregator"},
                        )

                    alert_results, alert_summaries = self._alert_ready_inputs(results, metric_summaries)
                    for event in event_detector.detect(alert_results, alert_summaries):
                        self._store_timeline_event(
                            recent_events,
                            session_id=session.session_id,
                            occurred_at=event.occurred_at,
                            severity=event.severity,
                            event_type=event.event_type,
                            message=event.message,
                            payload=event.payload,
                            target_name=event.target_name,
                            technical_description=event.technical_description,
                            duration_seconds=event.duration_seconds,
                            origin=event.origin,
                        )

                current_group_statuses = self._snapshot_group_statuses(results, is_warmup, warmup_remaining)
                latest_diagnostics = await self._collect_cycle_diagnostics(
                    session,
                    enabled_monitors,
                    traffic_sampler,
                    audio_monitor,
                    audio_level_monitor,
                    softphone_monitor,
                    windows_event_collector,
                    timers,
                    current_interface.interface_name,
                    metric_summaries,
                    is_warmup,
                    recent_events,
                )
                new_marks = self._drain_mark_queue(mark_queue)
                for mark in new_marks:
                    pending = self._create_customer_mark(session, mark, recent_results, recent_events, mark_count + 1)
                    pending_marks.append(pending)
                    self._enqueue_snapshot(
                        snapshot_queue,
                        session,
                        pending,
                        results,
                        metric_summaries,
                        current_group_statuses,
                        recent_events,
                    )
                    mark_count += 1
                    latest_mark_at = mark.marked_at

                self._complete_pending_marks(pending_marks, recent_results, recent_events)

                now = datetime.now(UTC)
                snapshot = MonitoringSnapshot(
                    session=session,
                    collected_at=now,
                    elapsed_seconds=int((now - session.started_at).total_seconds()),
                    remaining_seconds=max(0, int((session.expected_end_at - now).total_seconds())),
                    gateway_host=current_interface.gateway,
                    active_interface=current_interface.interface_name,
                    connection_type=current_interface.connection_type,
                    latest_results=results,
                    metrics=metric_summaries,
                    customer_mark_count=mark_count,
                    latest_customer_mark_at=latest_mark_at,
                    group_statuses=current_group_statuses,
                    timeline_events=list(recent_events),
                    is_warmup=is_warmup,
                    warmup_remaining_seconds=warmup_remaining,
                    diagnostics=latest_diagnostics,
                )
                latest_snapshot = snapshot
                if on_snapshot:
                    on_snapshot(snapshot)

                elapsed = perf_counter() - cycle_started
                sleep_for = max(0.0, session.request.collection_interval_seconds - elapsed)
                if sleep_for:
                    await asyncio.sleep(sleep_for)

            final_marks = self._drain_mark_queue(mark_queue)
            current_group_statuses = (latest_snapshot.group_statuses if latest_snapshot else group_statuses([])) or {}
            metric_summaries = latest_snapshot.metrics if latest_snapshot else []
            results = latest_snapshot.latest_results if latest_snapshot else []
            for mark in final_marks:
                pending = self._create_customer_mark(session, mark, recent_results, recent_events, mark_count + 1)
                pending_marks.append(pending)
                self._enqueue_snapshot(
                    snapshot_queue,
                    session,
                    pending,
                    results,
                    metric_summaries,
                    current_group_statuses,
                    recent_events,
                )
                mark_count += 1
                latest_mark_at = mark.marked_at
            await snapshot_queue.join()
        finally:
            if "route" in enabled_monitors:
                final_route = await asyncio.to_thread(collect_route_trace, session.request.sip_target, 15.0, "final_da_sessao")
                self._database.store_diagnostic_record("route_traces", session.session_id, datetime.now(UTC), final_route)
            await self._stop_snapshot_worker(snapshot_queue, snapshot_worker)

        if latest_snapshot is None:
            now = datetime.now(UTC)
            latest_snapshot = MonitoringSnapshot(
                session=session,
                collected_at=now,
                elapsed_seconds=int((now - session.started_at).total_seconds()),
                remaining_seconds=0,
                gateway_host=last_interface.gateway,
                active_interface=last_interface.interface_name,
                connection_type=last_interface.connection_type,
                latest_results=[],
                metrics=[],
                customer_mark_count=mark_count,
                latest_customer_mark_at=latest_mark_at,
                group_statuses=group_statuses([]),
                timeline_events=list(recent_events),
                is_warmup=False,
                warmup_remaining_seconds=0,
                diagnostics=latest_diagnostics,
            )
        elif final_marks:
            latest_snapshot = replace(
                latest_snapshot,
                customer_mark_count=mark_count,
                latest_customer_mark_at=latest_mark_at,
            )
        self._complete_pending_marks(pending_marks, recent_results, recent_events, force_partial=True)
        return latest_snapshot

    def _build_targets(self, session: MonitoringSession, gateway: str | None) -> list[TargetDefinition]:
        targets: list[TargetDefinition] = []
        if gateway:
            self._add_target(
                targets,
                TargetDefinition(
                    name="Gateway local",
                    kind=TargetKind.GATEWAY,
                    host=gateway,
                    protocol="ICMP",
                )
            )

        for host in self._unique_values(self._config.monitoring.external_ip_targets):
            self._add_target(
                targets,
                TargetDefinition(
                    name=f"Internet IP {host}",
                    kind=TargetKind.INTERNET_IP,
                    host=host,
                    protocol="ICMP",
                )
            )

        if session.request.external_target:
            self._add_target(
                targets,
                TargetDefinition(
                    name=f"Destino adicional {session.request.external_target}",
                    kind=TargetKind.CUSTOM,
                    host=session.request.external_target,
                    protocol="ICMP",
                )
            )

        for domain in self._unique_values(self._config.monitoring.domain_targets):
            if not is_ip_address(domain):
                self._add_target(
                    targets,
                    TargetDefinition(
                        name=f"DNS {domain}",
                        kind=TargetKind.DNS,
                        host=domain,
                        protocol="DNS",
                    )
                )

        sip_protocol = session.request.expected_protocol.upper()
        self._add_target(
            targets,
            TargetDefinition(
                name=f"SIP {session.request.sip_target}:{session.request.service_port}",
                kind=TargetKind.SIP,
                host=session.request.sip_target,
                port=session.request.service_port,
                protocol=sip_protocol,
            )
        )
        return targets

    @staticmethod
    def _add_target(targets: list[TargetDefinition], target: TargetDefinition) -> None:
        protocol = target.protocol.strip().upper()
        if protocol == "ICMP":
            key = ("ICMP", target.host.strip().lower(), target.port)
            existing = {
                ("ICMP", item.host.strip().lower(), item.port)
                for item in targets
                if item.protocol.strip().upper() == "ICMP"
            }
        else:
            key = (target.kind.value, target.host.strip().lower(), target.port, protocol)
            existing = {
                (item.kind.value, item.host.strip().lower(), item.port, item.protocol.strip().upper())
                for item in targets
                if item.protocol.strip().upper() != "ICMP"
            }
        if key not in existing:
            targets.append(target)

    async def _probe_targets(self, targets: list[TargetDefinition]) -> list[ProbeResult]:
        enabled_targets = [target for target in targets if target.enabled]
        semaphore = asyncio.Semaphore(max(1, self._config.monitoring.max_concurrent_checks))

        async def run(index: int, target: TargetDefinition) -> list[ProbeResult]:
            stagger = max(0, self._config.monitoring.monitor_start_stagger_ms) / 1000
            if stagger:
                await asyncio.sleep(index * stagger)
            async with semaphore:
                return await self._probe_target(target)

        nested = await asyncio.gather(
            *(run(index, target) for index, target in enumerate(enabled_targets))
        )
        return [result for group in nested for result in group]

    async def _probe_target(self, target: TargetDefinition) -> list[ProbeResult]:
        if target.kind == TargetKind.DNS:
            return [await resolve_once(target)]
        if target.kind == TargetKind.SIP:
            return await probe_sip_target(target)
        return [await ping_once(target)]

    def _detect_dns_ip_changes(
        self,
        session_id: str,
        results: list[ProbeResult],
        last_resolved_ips: dict[str, set[str]],
        recent_events: deque[EventRecord],
    ) -> None:
        for result in results:
            resolved = result.details.get("resolved_ips")
            if not isinstance(resolved, list):
                continue
            current = {str(item) for item in resolved}
            previous = last_resolved_ips.get(result.target.name)
            last_resolved_ips[result.target.name] = current
            if previous is not None and previous != current:
                self._store_timeline_event(
                    recent_events,
                    session_id=session_id,
                    occurred_at=result.collected_at,
                    severity=EventSeverity.WARNING,
                    event_type="destination_ip_changed",
                    message=f"{result.target.name} mudou os IPs resolvidos.",
                    payload={"previous": sorted(previous), "current": sorted(current)},
                    target_name=result.target.name,
                    technical_description="Alteracao observada no resultado de resolucao DNS.",
                )

    def _apply_thresholds(self, results: list[ProbeResult]) -> list[ProbeResult]:
        normalized: list[ProbeResult] = []
        for result in results:
            if (
                result.status == ProbeStatus.ONLINE
                and result.latency_ms is not None
                and result.latency_ms >= self._config.thresholds.latency_warning_ms
            ):
                normalized.append(
                    replace(
                        result,
                        status=ProbeStatus.DEGRADED,
                        details={
                            **result.details,
                            "threshold": "latency_warning",
                            "latency_warning_ms": self._config.thresholds.latency_warning_ms,
                        },
                    )
                )
            else:
                normalized.append(result)
        return normalized

    def _mark_warmup_results(
        self,
        results: list[ProbeResult],
        warmup_remaining_seconds: int,
    ) -> list[ProbeResult]:
        return [
            replace(
                result,
                details={
                    **result.details,
                    "is_warmup": True,
                    "warmup_remaining_seconds": warmup_remaining_seconds,
                    "diagnostic_use": False,
                },
            )
            for result in results
        ]

    def _alert_ready_inputs(
        self,
        results: list[ProbeResult],
        summaries: list[Any],
    ) -> tuple[list[ProbeResult], list[Any]]:
        minimum = max(1, self._config.monitoring.minimum_samples_for_alerts)
        counts = {summary.target_name: summary.tests for summary in summaries}
        return (
            [result for result in results if counts.get(result.target.name, 0) >= minimum],
            [summary for summary in summaries if summary.tests >= minimum],
        )

    def _build_softphone_monitor(
        self,
        session: MonitoringSession,
        process_snapshot_service: ProcessSnapshotService,
    ) -> SoftphoneMonitor | None:
        if not (
            self._config.monitoring.softphone_monitor_enabled
            and session.request.softphone_monitor_enabled
        ):
            return None
        config = SoftphoneMonitorConfig(
            enabled=True,
            process_name=session.request.softphone_process_name or None,
            expected_path=session.request.softphone_expected_path or None,
            expected_pid=session.request.softphone_expected_pid,
            high_cpu_percent=self._config.monitoring.softphone_high_cpu_percent,
            high_cpu_min_duration_seconds=self._config.monitoring.softphone_high_cpu_min_duration_seconds,
            high_memory_mb=self._config.monitoring.softphone_high_memory_mb,
            high_memory_min_duration_seconds=self._config.monitoring.softphone_high_memory_min_duration_seconds,
            not_responding_min_duration_seconds=self._config.monitoring.softphone_not_responding_min_duration_seconds,
        )
        return SoftphoneMonitor(config, process_snapshot_service)

    async def _collect_cycle_diagnostics(
        self,
        session: MonitoringSession,
        enabled_monitors: set[str],
        traffic_sampler: TrafficSampler,
        audio_monitor: AudioEventMonitor,
        audio_level_monitor: AudioLevelMonitor,
        softphone_monitor: SoftphoneMonitor | None,
        windows_event_collector: WindowsEventCollector | None,
        timers: dict[str, float],
        active_interface: str | None,
        metric_summaries: list[Any],
        is_warmup: bool,
        recent_events: deque[EventRecord],
    ) -> dict[str, Any]:
        diagnostics: dict[str, Any] = {}
        now = datetime.now(UTC)
        if "traffic" in enabled_monitors:
            traffic = traffic_sampler.sample(active_interface)
            diagnostics["traffic"] = traffic
            if not is_warmup:
                self._database.store_diagnostic_record("interface_traffic", session.session_id, now, traffic)
        if "system" in enabled_monitors:
            system = collect_system_metrics()
            diagnostics["system"] = system
            if not is_warmup:
                self._database.store_diagnostic_record("system_metrics", session.session_id, now, system)
        if not is_warmup and windows_event_collector and self._timer_ready(
            timers,
            "windows_events",
            max(self._config.monitoring.windows_events_poll_interval_seconds, 5.0),
        ):
            windows_events = windows_event_collector.collect_since(session.started_at, now)
            diagnostics["windows_events"] = windows_events
            self._database.store_diagnostic_record("windows_events", session.session_id, now, windows_events)
            for event in windows_events.get("events", []) if windows_events.get("available") else []:
                self._store_timeline_event(
                    recent_events,
                    session_id=session.session_id,
                    occurred_at=_optional_event_datetime(event.get("occurred_at")) or now,
                    severity=EventSeverity.WARNING if event.get("relevance") in {"alta", "media"} else EventSeverity.INFO,
                    event_type=str(event.get("normalized_type") or "windows_event"),
                    message=str(event.get("summary") or "Evento do Windows registrado."),
                    payload=event,
                    target_name=str(event.get("category") or "windows"),
                    origin="windows_event_log",
                )
        if not is_warmup and self._config.monitoring.power_audit_enabled and self._timer_ready(
            timers,
            "power_audit",
            max(self._config.monitoring.power_audit_interval_seconds, 60.0),
        ):
            related_windows_events = (diagnostics.get("windows_events") or {}).get("events", [])
            power = collect_power_audit(active_interface, related_windows_events)
            diagnostics["power_audit"] = power
            self._database.store_diagnostic_record("power_audit", session.session_id, now, power)
        if softphone_monitor and self._timer_ready(
            timers,
            "softphone",
            max(self._config.monitoring.softphone_poll_interval_seconds, 1.0),
        ):
            softphone = softphone_monitor.update(now)
            metric_payload = softphone.to_metric_payload()
            diagnostics["softphone"] = metric_payload
            if not is_warmup:
                self._database.store_diagnostic_record("softphone_metrics", session.session_id, now, metric_payload)
                for event in softphone.events:
                    self._database.store_diagnostic_record("softphone_events", session.session_id, now, _serialize_softphone_event(event))
                    self._store_timeline_event(
                        recent_events,
                        session_id=session.session_id,
                        occurred_at=event["occurred_at"],
                        severity=_event_severity(str(event["severity"])),
                        event_type=str(event["event_type"]),
                        message=str(event["message"]),
                        payload=_serialize_softphone_event(event),
                        target_name=session.request.softphone_process_name or "softphone",
                        origin="softphone_monitor",
                    )
        if "wifi" in enabled_monitors:
            wifi = collect_wifi_info()
            diagnostics["wifi"] = wifi
            if not is_warmup:
                self._database.store_diagnostic_record("wifi_metrics", session.session_id, now, wifi)

        traffic_payload = diagnostics.get("traffic")
        wifi_payload = diagnostics.get("wifi")
        quality = classify_voice_quality(metric_summaries, traffic_payload, wifi_payload)
        diagnostics["voice_quality"] = quality
        if not is_warmup:
            self._database.store_diagnostic_record("voice_quality_results", session.session_id, now, quality)

        if not is_warmup and self._config.monitoring.sip_options_enabled and "sip_options" in enabled_monitors and self._timer_ready(
            timers,
            "sip_options",
            self._config.monitoring.sip_options_interval_seconds,
        ):
            options = await sip_options_once(
                session.request.sip_target,
                session.request.service_port,
                session.request.expected_protocol if session.request.expected_protocol.upper() in {"UDP", "TCP", "TLS"} else "UDP",
                timeout_seconds=self._config.monitoring.sip_options_timeout_seconds,
            )
            diagnostics["sip_options"] = options
            self._database.store_diagnostic_record("sip_options_results", session.session_id, now, options)

        if not is_warmup and "sip_transport" in enabled_monitors and self._timer_ready(timers, "sip_transport", 60):
            transports = []
            for transport in self._config.monitoring.sip_transports or ["UDP", "TCP"]:
                transports.append(
                    await test_sip_transport(
                        session.request.sip_target,
                        session.request.service_port,
                        transport,
                        timeout_seconds=self._config.monitoring.sip_options_timeout_seconds,
                    )
                )
            diagnostics["sip_transport"] = transports
            self._database.store_diagnostic_record(
                "sip_transport_results",
                session.session_id,
                now,
                {"results": transports, "general_status": self._sip_general_status(transports)},
            )

        if not is_warmup and "time_sync" in enabled_monitors and self._timer_ready(timers, "time_sync", 300):
            time_sync = collect_time_sync()
            diagnostics["time_sync"] = time_sync
            self._database.store_diagnostic_record("time_sync_results", session.session_id, now, time_sync)

        if not is_warmup and "public_ip" in enabled_monitors and self._timer_ready(
            timers,
            "public_ip",
            self._config.monitoring.public_ip_interval_seconds,
        ):
            public_ip = await asyncio.to_thread(
                collect_public_ip,
                self._config.monitoring.public_ip_providers or [],
            )
            diagnostics["public_ip"] = public_ip
            self._database.store_diagnostic_record("public_ip_history", session.session_id, now, public_ip)

        if not is_warmup and "network_environment" in enabled_monitors and self._timer_ready(timers, "network_environment", 120):
            environment = collect_network_environment()
            diagnostics["network_environment"] = environment
            self._database.store_diagnostic_record("network_environment_events", session.session_id, now, environment)
        if self._config.monitoring.audio_monitoring_enabled and "audio" in enabled_monitors and self._timer_ready(
            timers,
            "audio",
            max(self._config.monitoring.audio_poll_interval_seconds, 1.0),
        ):
            inventory = collect_audio_inventory(include_driver_info=False)
            diagnostics["audio"] = inventory_summary(inventory)
            if not is_warmup:
                self._database.store_diagnostic_record("audio_device_states", session.session_id, inventory.collected_at, inventory.to_dict())
                for audio_event in audio_monitor.update(inventory):
                    self._database.store_diagnostic_record("audio_events", session.session_id, audio_event.occurred_at, audio_event.to_dict())
                    self._store_timeline_event(
                        recent_events,
                        session_id=session.session_id,
                        occurred_at=audio_event.occurred_at,
                        severity=EventSeverity(audio_event.severity) if audio_event.severity in EventSeverity._value2member_map_ else EventSeverity.INFO,
                        event_type=audio_event.event_type.value,
                        message=audio_event.message,
                        payload=audio_event.to_dict(),
                        target_name=audio_event.device_name,
                        origin="audio_monitor",
                    )
            if self._config.monitoring.audio_level_monitoring_enabled and self._timer_ready(
                timers,
                "audio_level",
                max(self._config.monitoring.audio_level_poll_interval_seconds, 1.0),
            ):
                level = audio_level_monitor.sample(
                    inventory.default_input_id,
                    window_seconds=max(self._config.monitoring.audio_level_window_seconds, 0.1),
                )
                diagnostics["audio_level"] = level.to_dict()
                if not is_warmup:
                    self._database.store_diagnostic_record("audio_level_metrics", session.session_id, level.collected_at, level.to_dict())
        return diagnostics

    @staticmethod
    def _timer_ready(timers: dict[str, float], key: str, interval_seconds: float) -> bool:
        now = perf_counter()
        previous = timers.get(key)
        if previous is not None and now - previous < interval_seconds:
            return False
        timers[key] = now
        return True

    @staticmethod
    def _sip_general_status(results: list[dict[str, Any]]) -> str:
        statuses = {str(item.get("status")) for item in results}
        if "online" in statuses:
            return "online"
        if "degraded" in statuses:
            return "degraded"
        if statuses and statuses <= {"inconclusive"}:
            return "inconclusive"
        if "offline" in statuses:
            return "offline"
        return "unknown"

    def _enqueue_snapshot(
        self,
        snapshot_queue: asyncio.Queue[_SnapshotJob | None],
        session: MonitoringSession,
        pending: _PendingCustomerMark,
        results: list[ProbeResult],
        metrics: list[Any],
        group_status_payload: dict[str, Any],
        recent_events: deque[EventRecord],
    ) -> None:
        job = _SnapshotJob(
            mark_id=pending.mark_id,
            marked_at=pending.marked_at,
            latest_results=[self._serialize_result(result) for result in results],
            metrics=[self._serialize_metric(summary) for summary in metrics],
            group_statuses=self._serialize_group_statuses(group_status_payload),
        )
        try:
            snapshot_queue.put_nowait(job)
        except asyncio.QueueFull:
            payload = {
                **pending.payload,
                "technical_snapshot_status": "skipped_queue_full",
                "technical_snapshot_error": "Fila de snapshot tecnico cheia.",
            }
            pending.payload.update(payload)
            self._database.update_customer_mark_context(
                pending.mark_id,
                CustomerMarkContextStatus.PENDING_AFTER_CONTEXT,
                payload,
            )
            self._store_timeline_event(
                recent_events,
                session_id=session.session_id,
                occurred_at=datetime.now(UTC),
                severity=EventSeverity.WARNING,
                event_type="technical_snapshot_skipped",
                message="Snapshot tecnico ignorado porque a fila estava cheia.",
                payload={"mark_id": pending.mark_id},
                target_name="snapshot",
            )

    async def _snapshot_worker(
        self,
        session: MonitoringSession,
        snapshot_queue: asyncio.Queue[_SnapshotJob | None],
        baseline_payload: dict[str, Any] | None,
        recent_events: deque[EventRecord],
    ) -> None:
        while True:
            job = await snapshot_queue.get()
            try:
                if job is None:
                    return
                await self._process_snapshot_job(session, job, baseline_payload, recent_events)
            finally:
                snapshot_queue.task_done()

    async def _process_snapshot_job(
        self,
        session: MonitoringSession,
        job: _SnapshotJob,
        baseline_payload: dict[str, Any] | None,
        recent_events: deque[EventRecord],
    ) -> None:
        try:
            enrichment_started_at = datetime.now(UTC)
            payload = await asyncio.wait_for(
                asyncio.to_thread(
                    collect_technical_snapshot,
                    session.request.sip_target,
                    job.latest_results,
                    job.metrics,
                    job.group_statuses,
                    "customer_mark",
                ),
                timeout=self._config.monitoring.snapshot_timeout_seconds,
            )
            enrichment_finished_at = datetime.now(UTC)
            payload["mark_id"] = job.mark_id
            payload["marked_at"] = job.marked_at.isoformat()
            payload["triggered_at"] = job.marked_at.isoformat()
            payload["enrichment_started_at"] = enrichment_started_at.isoformat()
            payload["enrichment_finished_at"] = enrichment_finished_at.isoformat()
            payload["duration_seconds"] = max(0.0, (enrichment_finished_at - enrichment_started_at).total_seconds())
            await self._run_mark_tests(session, payload)
            self._database.store_diagnostic_record(
                "audio_snapshots",
                session.session_id,
                enrichment_finished_at,
                {
                    "mark_id": job.mark_id,
                    "phase": "enrichment",
                    "triggered_at": job.marked_at.isoformat(),
                    "audio": payload.get("audio"),
                },
            )
            differences = compare_snapshot_to_baseline(baseline_payload, payload)
            payload["baseline_differences"] = differences
            snapshot_id = self._database.store_technical_snapshot(
                session.session_id,
                job.mark_id,
                datetime.now(UTC),
                payload,
            )
            self._database.store_snapshot_differences(session.session_id, snapshot_id, differences)
            self._merge_snapshot_into_mark(job.mark_id, snapshot_id, "complete", differences, None)
            self._store_timeline_event(
                recent_events,
                session_id=session.session_id,
                occurred_at=datetime.now(UTC),
                severity=EventSeverity.INFO,
                event_type="technical_snapshot_created",
                message="Snapshot tecnico da marcacao criado.",
                payload={"mark_id": job.mark_id, "snapshot_id": snapshot_id, "differences": len(differences)},
                target_name="snapshot",
            )
        except Exception as exc:
            self._merge_snapshot_into_mark(job.mark_id, None, "partial_failed", [], str(exc))
            self._store_timeline_event(
                recent_events,
                session_id=session.session_id,
                occurred_at=datetime.now(UTC),
                severity=EventSeverity.WARNING,
                event_type="technical_snapshot_partial_failed",
                message="Snapshot tecnico da marcacao falhou parcialmente.",
                payload={"mark_id": job.mark_id, "error": str(exc)},
                target_name="snapshot",
            )

    async def _run_mark_tests(self, session: MonitoringSession, payload: dict[str, Any]) -> None:
        profile = get_profile(session.request.profile_id)
        mark_tests = set(profile.mark_tests if profile else [])
        failures = payload.setdefault("partial_failures", [])
        now = datetime.now(UTC)
        if self._config.monitoring.sip_options_enabled and "sip_options" in mark_tests:
            try:
                options = await sip_options_once(
                    session.request.sip_target,
                    session.request.service_port,
                    session.request.expected_protocol if session.request.expected_protocol.upper() in {"UDP", "TCP", "TLS"} else "UDP",
                    timeout_seconds=self._config.monitoring.sip_options_timeout_seconds,
                )
                payload["sip_options"] = options
                self._database.store_diagnostic_record("sip_options_results", session.session_id, now, options)
            except Exception as exc:
                failures.append(f"sip_options: {exc}")
        if "sip_transport" in mark_tests:
            try:
                transports = [
                    await test_sip_transport(
                        session.request.sip_target,
                        session.request.service_port,
                        transport,
                        timeout_seconds=self._config.monitoring.sip_options_timeout_seconds,
                    )
                    for transport in (self._config.monitoring.sip_transports or ["UDP", "TCP"])
                ]
                transport_payload = {"results": transports, "general_status": self._sip_general_status(transports)}
                payload["sip_transport"] = transport_payload
                self._database.store_diagnostic_record("sip_transport_results", session.session_id, now, transport_payload)
            except Exception as exc:
                failures.append(f"sip_transport: {exc}")
        if "route_trace" in mark_tests:
            try:
                route = await asyncio.to_thread(collect_route_trace, session.request.sip_target, 20.0, "marcacao")
                payload["route"] = route
                self._database.store_diagnostic_record("route_traces", session.session_id, now, route)
            except Exception as exc:
                failures.append(f"route_trace: {exc}")
        if "public_ip" in mark_tests:
            try:
                public_ip = await asyncio.to_thread(
                    collect_public_ip,
                    self._config.monitoring.public_ip_providers or [],
                )
                payload["network"]["public_ip"] = public_ip
                self._database.store_diagnostic_record("public_ip_history", session.session_id, now, public_ip)
            except Exception as exc:
                failures.append(f"public_ip: {exc}")
        if "time_sync" in mark_tests:
            try:
                time_sync = collect_time_sync()
                payload["time_sync"] = time_sync
                self._database.store_diagnostic_record("time_sync_results", session.session_id, now, time_sync)
            except Exception as exc:
                failures.append(f"time_sync: {exc}")
        if "udp_flow" in mark_tests:
            try:
                udp_config = dict(self._config.monitoring.udp_flow_test or {})
                if not udp_config.get("enabled"):
                    udp_config = {}
                udp = await run_udp_flow_test(udp_config)
                payload["udp_flow"] = udp
                self._database.store_diagnostic_record("udp_flow_tests", session.session_id, now, udp)
            except Exception as exc:
                failures.append(f"udp_flow: {exc}")

    async def _stop_snapshot_worker(
        self,
        snapshot_queue: asyncio.Queue[_SnapshotJob | None],
        snapshot_worker: asyncio.Task[None],
    ) -> None:
        await snapshot_queue.put(None)
        await snapshot_worker

    def _merge_snapshot_into_mark(
        self,
        mark_id: int,
        snapshot_id: int | None,
        status: str,
        differences: list[dict[str, Any]],
        error: str | None,
    ) -> None:
        stored = self._database.get_customer_mark(mark_id)
        if stored is None:
            return
        payload = {
            **stored.payload,
            "technical_snapshot_status": status,
            "technical_snapshot_id": snapshot_id,
            "baseline_differences_count": len(differences),
            "baseline_differences": differences,
        }
        if error:
            payload["technical_snapshot_error"] = error
        self._database.update_customer_mark_context(mark_id, stored.context_status, payload)

    @staticmethod
    def _snapshot_mark_fields(payload: dict[str, Any]) -> dict[str, Any]:
        keys = {
            "technical_snapshot_status",
            "technical_snapshot_id",
            "technical_snapshot_error",
            "baseline_differences_count",
            "baseline_differences",
        }
        return {key: payload[key] for key in keys if key in payload}

    @staticmethod
    def _snapshot_group_statuses(
        results: list[ProbeResult],
        is_warmup: bool,
        warmup_remaining_seconds: int,
    ) -> dict[str, Any]:
        if not is_warmup:
            return group_statuses(results)
        summary = (
            f"Aquecendo, {warmup_remaining_seconds}s restantes"
            if warmup_remaining_seconds
            else "Aquecendo"
        )
        return {
            "rede_local": replace(group_statuses([])["rede_local"], status=ProbeStatus.WARMING_UP, summary=summary),
            "internet": replace(group_statuses([])["internet"], status=ProbeStatus.WARMING_UP, summary=summary),
            "dns": replace(group_statuses([])["dns"], status=ProbeStatus.WARMING_UP, summary=summary),
            "sip": replace(group_statuses([])["sip"], status=ProbeStatus.WARMING_UP, summary=summary),
            "voz": replace(group_statuses([])["voz"], status=ProbeStatus.WARMING_UP, summary=summary),
        }

    @staticmethod
    def _serialize_metric(summary: Any) -> dict[str, Any]:
        return {
            "target_name": summary.target_name,
            "tests": summary.tests,
            "successes": summary.successes,
            "failures": summary.failures,
            "packet_loss_percent": summary.packet_loss_percent,
            "latency_current_ms": summary.latency_current_ms,
            "latency_avg_ms": summary.latency_avg_ms,
            "latency_p95_ms": summary.latency_p95_ms,
            "latency_max_ms": summary.latency_max_ms,
            "jitter_ms": summary.jitter_ms,
            "consecutive_failures": summary.consecutive_failures,
            "availability_percent": summary.availability_percent,
        }

    @staticmethod
    def _serialize_group_statuses(group_status_payload: dict[str, Any]) -> dict[str, Any]:
        return {
            key: {
                "name": value.name,
                "status": value.status.value,
                "latency_ms": value.latency_ms,
                "summary": value.summary,
            }
            for key, value in group_status_payload.items()
        }

    def _drain_mark_queue(
        self,
        mark_queue: queue.Queue[CustomerMarkSignal] | None,
    ) -> list[CustomerMarkSignal]:
        if mark_queue is None:
            return []
        marks: list[CustomerMarkSignal] = []
        while True:
            try:
                marks.append(mark_queue.get_nowait())
            except queue.Empty:
                return marks

    def _create_customer_mark(
        self,
        session: MonitoringSession,
        mark: CustomerMarkSignal,
        recent_results: deque[ProbeResult],
        recent_events: deque[EventRecord],
        sequence_number: int = 1,
    ) -> _PendingCustomerMark:
        immediate_snapshot_at = datetime.now(UTC)
        interface = detect_active_interface()
        audio_inventory = collect_audio_inventory(include_driver_info=False)
        before_context = self._context_window(
            recent_results,
            start=mark.marked_at - timedelta(seconds=self._config.monitoring.marker_context_before_seconds),
            end=mark.marked_at,
        )
        payload = {
            "marked_at": mark.marked_at.isoformat(),
            "marker_id": None,
            "sequence_number": sequence_number,
            "event_type": CUSTOMER_MARKER_EVENT_TYPE,
            "event_origin": CUSTOMER_MARKER_ORIGIN,
            "source": CUSTOMER_MARKER_SOURCE,
            "is_customer_marker": True,
            "visual_priority": CUSTOMER_MARKER_VISUAL_PRIORITY,
            "display_label": "OCORRENCIA REGISTRADA PELO CLIENTE",
            "customer_description": session.request.problem_description,
            "context_start": (mark.marked_at - timedelta(seconds=self._config.monitoring.marker_context_before_seconds)).isoformat(),
            "context_end": (mark.marked_at + timedelta(seconds=self._config.monitoring.marker_context_after_seconds)).isoformat(),
            "context_before_seconds": self._config.monitoring.marker_context_before_seconds,
            "context_after_seconds": self._config.monitoring.marker_context_after_seconds,
            "before": before_context,
            "at_click_latest": self._latest_by_target(before_context),
            "triggered_at": mark.marked_at.isoformat(),
            "immediate_snapshot_at": immediate_snapshot_at.isoformat(),
            "immediate": {
                "captured_at": immediate_snapshot_at.isoformat(),
                "latest_results": self._latest_by_target(before_context),
                "interface": {
                    "name": interface.interface_name,
                    "type": interface.connection_type,
                    "ipv4": interface.local_ip,
                    "gateway": interface.gateway,
                    "is_default_route": interface.is_default_route,
                    "is_up": interface.is_up,
                },
                "audio": inventory_summary(audio_inventory),
            },
            "after": [],
            "after_context_complete": False,
            "technical_snapshot_status": "pending",
            "classification": "dados_insuficientes",
            "conclusion": "Analise da marcacao pendente.",
        }
        mark_id = self._database.create_customer_mark(session.session_id, mark.marked_at, payload)
        payload["marker_id"] = mark_id
        self._database.update_customer_mark_context(mark_id, CustomerMarkContextStatus.PENDING_AFTER_CONTEXT, payload)
        self._database.store_diagnostic_record(
            "audio_snapshots",
            session.session_id,
            immediate_snapshot_at,
            {
                "mark_id": mark_id,
                "phase": "immediate",
                "triggered_at": mark.marked_at.isoformat(),
                "audio": payload["immediate"].get("audio"),
            },
        )
        self._store_timeline_event(
            recent_events,
            session_id=session.session_id,
            occurred_at=mark.marked_at,
            severity=EventSeverity.USER_MARKER,
            event_type=CUSTOMER_MARKER_EVENT_TYPE,
            message="Ocorrencia registrada pelo cliente pelo botao flutuante.",
            payload={
                "mark_id": mark_id,
                "marked_at": mark.marked_at.isoformat(),
                "sequence_number": sequence_number,
                "event_type": CUSTOMER_MARKER_EVENT_TYPE,
                "event_origin": CUSTOMER_MARKER_ORIGIN,
                "source": CUSTOMER_MARKER_SOURCE,
                "is_customer_marker": True,
                "visual_priority": CUSTOMER_MARKER_VISUAL_PRIORITY,
                "display_label": "OCORRENCIA REGISTRADA PELO CLIENTE",
            },
            origin=CUSTOMER_MARKER_ORIGIN,
        )
        return _PendingCustomerMark(mark_id=mark_id, marked_at=mark.marked_at, payload=payload)

    def _complete_pending_marks(
        self,
        pending_marks: list[_PendingCustomerMark],
        recent_results: deque[ProbeResult],
        recent_events: deque[EventRecord],
        force_partial: bool = False,
    ) -> None:
        remaining: list[_PendingCustomerMark] = []
        now = datetime.now(UTC)
        for mark in pending_marks:
            after_seconds = self._config.monitoring.marker_context_after_seconds
            ready = now >= mark.marked_at + timedelta(seconds=after_seconds)
            if not ready and not force_partial:
                remaining.append(mark)
                continue
            after_context = self._context_window(
                recent_results,
                start=mark.marked_at,
                end=mark.marked_at + timedelta(seconds=after_seconds),
            )
            payload = {
                **mark.payload,
                "after": after_context,
                "nearby_events": self._event_context_window(
                    recent_events,
                    start=mark.marked_at - timedelta(seconds=self._config.monitoring.marker_context_before_seconds),
                    end=mark.marked_at + timedelta(seconds=after_seconds),
                ),
                "after_context_complete": ready,
            }
            stored = self._database.get_customer_mark(mark.mark_id)
            if stored is not None:
                payload.update(self._snapshot_mark_fields(stored.payload))
            payload.update(self._classify_marker_payload(payload))
            self._database.update_customer_mark_context(
                mark_id=mark.mark_id,
                context_status=(
                    CustomerMarkContextStatus.COMPLETE
                    if ready
                    else CustomerMarkContextStatus.PARTIAL
                ),
                payload=payload,
            )
            if stored is not None:
                self._database.store_diagnostic_record(
                    "marker_contexts",
                    stored.session_id,
                    now,
                    _marker_context_record(mark.mark_id, payload),
                )
                self._database.store_diagnostic_record(
                    "marker_correlations",
                    stored.session_id,
                    now,
                    _marker_correlation_record(mark.mark_id, payload),
                )
        pending_marks[:] = remaining

    def _context_window(
        self,
        results: deque[ProbeResult],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        return [
            self._serialize_result(result)
            for result in results
            if start <= result.collected_at <= end
        ]

    def _latest_by_target(self, serialized_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for result in serialized_results:
            latest[result["target_name"]] = result
        return latest

    def _event_context_window(
        self,
        events: deque[EventRecord],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        return [
            {
                "event_id": event.event_id,
                "occurred_at": event.occurred_at.isoformat(),
                "severity": event.severity.value,
                "event_type": event.event_type,
                "message": event.message,
                "target_name": event.target_name,
            }
            for event in events
            if start <= event.occurred_at <= end
        ]

    @staticmethod
    def _serialize_result(result: ProbeResult) -> dict[str, Any]:
        return {
            "target_name": result.target.name,
            "target_kind": result.target.kind.value,
            "host": result.target.host,
            "port": result.target.port,
            "protocol": result.target.protocol,
            "collected_at": result.collected_at.isoformat(),
            "status": result.status.value,
            "latency_ms": result.latency_ms,
            "error": result.error,
            "is_warmup": bool(result.details.get("is_warmup")),
            "details": result.details,
        }

    @staticmethod
    def _recent_result_limit(session: MonitoringSession) -> int:
        cycles_for_context = int(150 / max(session.request.collection_interval_seconds, 1))
        return max(200, cycles_for_context * 12)

    def _classify_marker_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        samples = [
            sample
            for sample in list(payload.get("before", [])) + list(payload.get("after", []))
            if not sample.get("is_warmup")
        ]
        if not samples:
            return {
                "classification": "DADOS INSUFICIENTES",
                "conclusion": "Nao ha amostras oficiais suficientes para correlacionar a ocorrencia marcada.",
            }
        anomalies = [
            sample
            for sample in samples
            if sample.get("status") in {"offline", "degraded"}
        ]
        if not anomalies:
            return {
                "classification": "SEM ANOMALIA DETECTADA",
                "conclusion": (
                    "Nao foram encontradas anomalias nos destinos monitorados durante o intervalo analisado. "
                    "Isso nao descarta problemas especificos de audio, equipamento, RTP ou aplicacao."
                ),
            }
        marked_at = datetime.fromisoformat(str(payload["marked_at"]))
        nearest = min(
            anomalies,
            key=lambda sample: abs((datetime.fromisoformat(str(sample["collected_at"])) - marked_at).total_seconds()),
        )
        nearest_seconds = abs((datetime.fromisoformat(str(nearest["collected_at"])) - marked_at).total_seconds())
        if nearest_seconds <= self._config.monitoring.marker_correlation_strong_seconds:
            classification = "CORRELACAO FORTE"
        elif nearest_seconds <= self._config.monitoring.marker_correlation_moderate_seconds:
            classification = "CORRELACAO MODERADA"
        elif nearest_seconds <= self._config.monitoring.marker_correlation_weak_seconds:
            classification = "CORRELACAO FRACA"
        else:
            classification = "DADOS INSUFICIENTES"
        targets = sorted({str(sample.get("target_name")) for sample in anomalies})
        return {
            "classification": classification,
            "nearest_anomaly_seconds": nearest_seconds,
            "nearest_anomaly_target": str(nearest.get("target_name")),
            "affected_monitors": targets,
            "max_severity": "critical" if any(sample.get("status") == "offline" for sample in anomalies) else "warning",
            "conclusion": (
                f"{classification}: ocorrencia marcada com anomalias proximas ao clique "
                f"({nearest_seconds:.0f}s): "
                + ", ".join(targets[:5])
                + "."
            ),
        }

    def _store_timeline_event(
        self,
        recent_events: deque[EventRecord],
        session_id: str,
        occurred_at: datetime,
        severity: EventSeverity,
        event_type: str,
        message: str,
        payload: dict[str, Any],
        target_name: str | None = None,
        technical_description: str | None = None,
        duration_seconds: float | None = None,
        origin: str = "automatic",
    ) -> int:
        event_id = self._database.store_event(
            session_id=session_id,
            occurred_at=occurred_at,
            severity=severity,
            event_type=event_type,
            message=message,
            payload=payload,
            target_name=target_name,
            technical_description=technical_description,
            duration_seconds=duration_seconds,
            origin=origin,
        )
        recent_events.append(
            EventRecord(
                event_id=event_id,
                session_id=session_id,
                occurred_at=occurred_at,
                severity=severity,
                event_type=event_type,
                message=message,
                payload=payload,
                target_name=target_name,
                technical_description=technical_description,
                duration_seconds=duration_seconds,
                origin=origin,
            )
        )
        return event_id

    @staticmethod
    def _unique_values(values: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for value in values:
            cleaned = value.strip()
            if cleaned and cleaned not in seen:
                unique.append(cleaned)
                seen.add(cleaned)
        return unique


def _event_severity(value: str) -> EventSeverity:
    if value in EventSeverity._value2member_map_:
        return EventSeverity(value)
    return EventSeverity.INFO


def _serialize_softphone_event(event: dict[str, object]) -> dict[str, object]:
    return {
        **event,
        "occurred_at": event["occurred_at"].isoformat()
        if isinstance(event.get("occurred_at"), datetime)
        else event.get("occurred_at"),
    }


def _marker_context_record(mark_id: int, payload: dict[str, Any]) -> dict[str, object]:
    return {
        "mark_id": mark_id,
        "marked_at": payload.get("marked_at"),
        "context_start": payload.get("context_start"),
        "context_end": payload.get("context_end"),
        "requested_before_seconds": payload.get("context_before_seconds"),
        "requested_after_seconds": payload.get("context_after_seconds"),
        "before_samples": len(payload.get("before", [])),
        "after_samples": len(payload.get("after", [])),
        "after_context_complete": payload.get("after_context_complete"),
        "nearby_event_count": len(payload.get("nearby_events", [])),
    }


def _marker_correlation_record(mark_id: int, payload: dict[str, Any]) -> dict[str, object]:
    return {
        "mark_id": mark_id,
        "classification": payload.get("classification"),
        "conclusion": payload.get("conclusion"),
        "nearest_anomaly_seconds": payload.get("nearest_anomaly_seconds"),
        "nearest_anomaly_target": payload.get("nearest_anomaly_target"),
        "affected_monitors": payload.get("affected_monitors", []),
        "max_severity": payload.get("max_severity"),
    }


def _optional_event_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
