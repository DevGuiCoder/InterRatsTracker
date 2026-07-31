"""Technical baseline and snapshot collection."""

from __future__ import annotations

import re
import socket
from datetime import UTC, datetime
from typing import Any

from src.audio.device_enumerator import collect_audio_inventory, inventory_summary
from src.monitoring.wifi_monitor import collect_wifi_info
from src.monitoring.route_trace import collect_route_trace, compare_routes
from src.monitoring.public_ip_monitor import collect_public_ip
from src.monitoring.time_sync_monitor import collect_time_sync
from src.monitoring.network_environment import collect_network_environment
from src.storage.models import ProbeResult, TargetMetricsSummary
from src.utils.networking import detect_active_interface
from src.utils.windows_command import run_windows_command


def collect_session_baseline(
    sip_target: str,
    include_route: bool = True,
    public_ip_providers: list[str] | None = None,
) -> dict[str, Any]:
    """Collect the initial technical state for later comparison."""
    payload = collect_technical_snapshot(
        sip_target=sip_target,
        latest_results=[],
        metric_summaries=[],
        group_status_payload={},
        reason="session_start",
    )
    if include_route:
        payload["route"] = collect_route_trace(sip_target, timeout_seconds=15.0, reason="baseline")
    payload["network"]["public_ip"] = collect_public_ip(public_ip_providers or [])
    payload["time_sync"] = collect_time_sync()
    payload["network_environment"] = collect_network_environment()
    return payload


def collect_technical_snapshot(
    sip_target: str,
    latest_results: list[dict[str, Any]] | list[ProbeResult],
    metric_summaries: list[dict[str, Any]] | list[TargetMetricsSummary],
    group_status_payload: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    """Collect a best-effort technical snapshot without sensitive content."""
    captured_at = datetime.now(UTC)
    partial_failures: list[str] = []
    interface = detect_active_interface()
    wifi = collect_wifi_info()
    dns_servers = _dns_servers(partial_failures)
    proxy = _proxy_state(partial_failures)
    sip_resolution = _resolve_sip_target(sip_target, partial_failures)
    audio_inventory = collect_audio_inventory(include_driver_info=False)
    return {
        "captured_at": captured_at.isoformat(),
        "reason": reason,
        "partial_failures": partial_failures,
        "network": {
            "active_interface": interface.interface_name,
            "connection_type": interface.connection_type,
            "local_ip": interface.local_ip,
            "gateway": interface.gateway,
            "dns_servers": dns_servers,
            "proxy": proxy,
            "public_ip": {
                "ipv4": None,
                "ipv6": None,
                "status": "not_collected_in_phase_1",
            },
        },
        "wifi": wifi,
        "sip": {
            "target": sip_target,
            **sip_resolution,
        },
        "audio": inventory_summary(audio_inventory),
        "monitoring": {
            "latest_results": [_result_payload(item) for item in latest_results],
            "metrics": [_metric_payload(item) for item in metric_summaries],
            "group_statuses": group_status_payload,
        },
        "route": {
            "status": "not_collected_in_phase_1",
            "note": "Traceroute sera coletado em fase propria para evitar testes pesados em todos os eventos.",
        },
    }


def compare_snapshot_to_baseline(
    baseline: dict[str, Any] | None,
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return verified differences between an initial baseline and a snapshot."""
    if not baseline:
        return []
    differences: list[dict[str, Any]] = []
    _compare_path(differences, baseline, snapshot, "network.active_interface", "Interface ativa mudou.")
    _compare_path(differences, baseline, snapshot, "network.connection_type", "Tipo de conexao mudou.")
    _compare_path(differences, baseline, snapshot, "network.local_ip", "Endereco IP local mudou.")
    _compare_path(differences, baseline, snapshot, "network.gateway", "Gateway padrao mudou.")
    _compare_path(differences, baseline, snapshot, "network.dns_servers", "Servidores DNS mudaram.")
    _compare_path(differences, baseline, snapshot, "network.proxy.enabled", "Estado do proxy do sistema mudou.")
    _compare_path(differences, baseline, snapshot, "network.public_ip.ipv4", "Endereco IPv4 publico mudou.")
    _compare_path(differences, baseline, snapshot, "network.public_ip.ipv6", "Endereco IPv6 publico mudou.")
    _compare_path(differences, baseline, snapshot, "wifi.ssid", "SSID do Wi-Fi mudou.")
    _compare_path(differences, baseline, snapshot, "sip.resolved_ips", "IPs resolvidos do servidor SIP mudaram.")
    _compare_wifi_signal(differences, baseline, snapshot)
    for route_difference in compare_routes(baseline.get("route"), snapshot.get("route", {})):
        differences.append(
            {
                "field_name": route_difference.get("field_name", "route"),
                "baseline_value": "rota inicial",
                "snapshot_value": "rota da marcacao",
                "severity": "info",
                "message": route_difference.get("message", "Rota mudou."),
            }
        )
    return differences


def _compare_path(
    differences: list[dict[str, Any]],
    baseline: dict[str, Any],
    snapshot: dict[str, Any],
    field_name: str,
    message: str,
) -> None:
    baseline_value = _get_path(baseline, field_name)
    snapshot_value = _get_path(snapshot, field_name)
    if baseline_value in (None, [], {}) or snapshot_value in (None, [], {}):
        return
    if baseline_value == snapshot_value:
        return
    differences.append(
        {
            "field_name": field_name,
            "baseline_value": baseline_value,
            "snapshot_value": snapshot_value,
            "severity": "warning",
            "message": message,
        }
    )


def _compare_wifi_signal(
    differences: list[dict[str, Any]],
    baseline: dict[str, Any],
    snapshot: dict[str, Any],
) -> None:
    baseline_signal = _get_path(baseline, "wifi.signal_percent")
    snapshot_signal = _get_path(snapshot, "wifi.signal_percent")
    if not isinstance(baseline_signal, int) or not isinstance(snapshot_signal, int):
        return
    if baseline_signal - snapshot_signal < 25:
        return
    differences.append(
        {
            "field_name": "wifi.signal_percent",
            "baseline_value": baseline_signal,
            "snapshot_value": snapshot_signal,
            "severity": "warning",
            "message": "Sinal Wi-Fi caiu de forma relevante em relacao ao inicio da sessao.",
        }
    )


def _get_path(payload: dict[str, Any], field_name: str) -> Any:
    current: Any = payload
    for part in field_name.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _result_payload(item: dict[str, Any] | ProbeResult) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    return {
        "target_name": item.target.name,
        "target_kind": item.target.kind.value,
        "host": item.target.host,
        "port": item.target.port,
        "protocol": item.target.protocol,
        "collected_at": item.collected_at.isoformat(),
        "status": item.status.value,
        "latency_ms": item.latency_ms,
        "error": item.error,
        "is_warmup": bool(item.details.get("is_warmup")),
    }


def _metric_payload(item: dict[str, Any] | TargetMetricsSummary) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    return {
        "target_name": item.target_name,
        "tests": item.tests,
        "successes": item.successes,
        "failures": item.failures,
        "packet_loss_percent": item.packet_loss_percent,
        "latency_current_ms": item.latency_current_ms,
        "latency_avg_ms": item.latency_avg_ms,
        "latency_p95_ms": item.latency_p95_ms,
        "latency_max_ms": item.latency_max_ms,
        "jitter_ms": item.jitter_ms,
        "consecutive_failures": item.consecutive_failures,
        "availability_percent": item.availability_percent,
    }


def _dns_servers(partial_failures: list[str]) -> list[str]:
    try:
        completed = run_windows_command(["ipconfig", "/all"], timeout=5)
    except Exception as exc:
        partial_failures.append(f"dns_servers: {exc}")
        return []
    servers: list[str] = []
    capture_continuation = False
    for raw_line in completed.stdout.splitlines():
        line = raw_line.rstrip()
        if "DNS Servers" in line or "Servidores DNS" in line:
            capture_continuation = True
            value = line.split(":", 1)[-1].strip()
            if value:
                servers.extend(_ip_tokens(value))
            continue
        if capture_continuation and line.startswith(" "):
            servers.extend(_ip_tokens(line.strip()))
            continue
        capture_continuation = False
    return _unique(servers)


def _proxy_state(partial_failures: list[str]) -> dict[str, Any]:
    try:
        completed = run_windows_command(["netsh", "winhttp", "show", "proxy"], timeout=5)
    except Exception as exc:
        partial_failures.append(f"proxy: {exc}")
        return {"enabled": None, "source": "winhttp", "details": "unavailable"}
    output = completed.stdout.strip()
    direct_tokens = ("Direct access", "Acesso direto", "sem proxy")
    enabled = not any(token.lower() in output.lower() for token in direct_tokens)
    return {
        "enabled": enabled,
        "source": "winhttp",
        "details": _compact_text(output),
    }


def _resolve_sip_target(sip_target: str, partial_failures: list[str]) -> dict[str, Any]:
    try:
        results = socket.getaddrinfo(sip_target, None)
    except OSError as exc:
        partial_failures.append(f"sip_resolution: {exc}")
        return {"resolved_ips": [], "resolution_error": str(exc)}
    resolved = sorted({item[4][0] for item in results if item[4]})
    return {"resolved_ips": resolved, "resolution_error": None}


def _ip_tokens(value: str) -> list[str]:
    return re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b|[0-9a-fA-F:]{3,}", value)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value not in seen:
            unique.append(value)
            seen.add(value)
    return unique


def _compact_text(value: str, limit: int = 500) -> str:
    return " ".join(value.split())[:limit]
