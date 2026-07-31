"""Service status classification rules."""

from __future__ import annotations

from dataclasses import replace

from src.storage.models import GroupStatus, ProbeResult, ProbeStatus


def classify_probe_results(results: list[ProbeResult]) -> list[ProbeResult]:
    """Normalize probe results that need cross-probe context."""
    sip_tcp_online = any("SIP " in item.target.name and " TCP" in item.target.name and item.status in {ProbeStatus.ONLINE, ProbeStatus.DEGRADED} for item in results)
    sip_dns_online = any("SIP " in item.target.name and " DNS" in item.target.name and item.status in {ProbeStatus.ONLINE, ProbeStatus.DEGRADED} for item in results)
    normalized: list[ProbeResult] = []
    for item in results:
        if (
            "SIP " in item.target.name
            and " Ping" in item.target.name
            and item.status == ProbeStatus.OFFLINE
            and (sip_tcp_online or sip_dns_online)
        ):
            normalized.append(
                replace(
                    item,
                    status=ProbeStatus.INCONCLUSIVE,
                    error="ICMP possivelmente bloqueado",
                    details={**item.details, "classification": "icmp_possibly_blocked"},
                )
            )
        else:
            normalized.append(item)
    return normalized


def group_statuses(results: list[ProbeResult]) -> dict[str, GroupStatus]:
    """Build operator-facing group statuses from latest probe results."""
    return {
        "rede_local": _group("Rede local", [item for item in results if item.target.kind.value == "gateway"]),
        "internet": _group("Internet", [item for item in results if item.target.kind.value in {"internet_ip", "custom"}]),
        "dns": _group("DNS", [item for item in results if item.target.kind.value == "dns" or " DNS" in item.target.name]),
        "sip": _sip_group(results),
        "voz": _voice_group(results),
    }


def _group(name: str, results: list[ProbeResult]) -> GroupStatus:
    if not results:
        return GroupStatus(name, ProbeStatus.UNKNOWN, None, "Sem dados")
    reliable = [item for item in results if item.status != ProbeStatus.INCONCLUSIVE]
    source = reliable or results
    if any(item.status == ProbeStatus.OFFLINE for item in source):
        return GroupStatus(name, ProbeStatus.OFFLINE, _best_latency(source), "Falha detectada")
    if any(item.status == ProbeStatus.DEGRADED for item in source):
        return GroupStatus(name, ProbeStatus.DEGRADED, _best_latency(source), "Degradado")
    if all(item.status == ProbeStatus.INCONCLUSIVE for item in results):
        return GroupStatus(name, ProbeStatus.INCONCLUSIVE, None, "Dados inconclusivos")
    return GroupStatus(name, ProbeStatus.ONLINE, _best_latency(source), "Operacional")


def _sip_group(results: list[ProbeResult]) -> GroupStatus:
    sip_results = [item for item in results if "SIP " in item.target.name]
    tcp_results = [item for item in sip_results if " TCP" in item.target.name]
    if tcp_results:
        return _group("Servico SIP", tcp_results)
    return _group("Servico SIP", sip_results)


def _voice_group(results: list[ProbeResult]) -> GroupStatus:
    if any(item.status == ProbeStatus.DEGRADED for item in results):
        return GroupStatus("Qualidade de voz", ProbeStatus.DEGRADED, _best_latency(results), "Latencia/jitter/perda elevada")
    if any(item.status == ProbeStatus.OFFLINE for item in results):
        return GroupStatus("Qualidade de voz", ProbeStatus.DEGRADED, _best_latency(results), "Quedas podem afetar voz")
    return GroupStatus("Qualidade de voz", ProbeStatus.ONLINE, _best_latency(results), "Sem anomalia atual")


def _best_latency(results: list[ProbeResult]) -> float | None:
    values = [item.latency_ms for item in results if item.latency_ms is not None]
    return min(values) if values else None
