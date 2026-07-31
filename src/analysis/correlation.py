"""Basic correlation of monitoring results."""

from __future__ import annotations

from src.storage.models import AutomaticConclusion, ConfidenceLevel, EventRecord, MeasurementRecord


def correlate_results(measurements: list[MeasurementRecord], events: list[EventRecord]) -> list[str]:
    """Return cautious diagnostic notes based on collected evidence."""
    conclusion = build_conclusion(measurements, events)
    return [
        conclusion.result,
        f"Origem provavel: {conclusion.likely_origin}.",
        f"Confianca: {conclusion.confidence.value.upper()}.",
        *[f"Evidencia: {item}" for item in conclusion.evidences],
        *[f"Redutor de confianca: {item}" for item in conclusion.confidence_reducers],
        *[f"Recomendacao: {item}" for item in conclusion.recommendations],
    ]


def build_conclusion(measurements: list[MeasurementRecord], events: list[EventRecord]) -> AutomaticConclusion:
    """Build a rule-based conclusion with confidence and evidence."""
    measurements = [item for item in measurements if not item.is_warmup]
    status_by_group = _failure_rate_by_group(measurements)
    target_stats = _failure_stats_by_target(measurements)

    sip_tcp = next(
        (stats for target, stats in target_stats.items() if _is_sip_tcp(target, stats["probe"])),
        None,
    )
    if sip_tcp and (
        sip_tcp["failure_rate"] >= 10
        or sip_tcp["max_consecutive"] >= 3
        or sip_tcp["ended_unavailable"]
    ):
        evidences = [
            (
                f"{sip_tcp['target_name']}: {sip_tcp['failures']} falhas em {sip_tcp['tests']} testes "
                f"({sip_tcp['failure_rate']:.1f}% de falhas de conexao TCP)."
            ),
            f"Maior sequencia de falhas consecutivas: {sip_tcp['max_consecutive']}.",
        ]
        if sip_tcp["ended_unavailable"]:
            evidences.append("A coleta terminou sem recuperacao observada da conexao TCP SIP.")
        return _conclusion(
            "Foi detectada instabilidade especifica na comunicacao TCP com o servico SIP.",
            "SERVICO SIP / COMUNICACAO TCP",
            ConfidenceLevel.HIGH if sip_tcp["max_consecutive"] >= 4 else ConfidenceLevel.MEDIUM,
            evidences,
            measurements,
            extra_reducers=[
                "Falhas TCP nao comprovam, isoladamente, perda RTP ou degradacao real de audio."
            ],
        )

    critical_events = [event for event in events if event.severity.value == "critical"]
    if critical_events:
        return _conclusion(
            "Foram detectados eventos criticos durante a sessao.",
            "anomalia tecnica detectada",
            ConfidenceLevel.MEDIUM,
            [f"{event.event_type}: {event.message}" for event in critical_events[:5]],
            measurements,
        )

    gateway_loss = status_by_group.get("gateway", 0.0)
    internet_loss = status_by_group.get("internet_ip", 0.0)
    sip_loss = status_by_group.get("sip", 0.0)
    dns_loss = status_by_group.get("dns", 0.0)

    if gateway_loss > 20 and internet_loss > 20 and sip_loss > 20:
        return _conclusion(
            "Ha indicios de instabilidade na rede local, no Wi-Fi, no cabo, no switch ou no roteador.",
            "rede local",
            ConfidenceLevel.HIGH,
            ["Gateway, internet e SIP falharam no periodo monitorado."],
            measurements,
        )
    if gateway_loss <= 10 and internet_loss > 20 and sip_loss > 20:
        return _conclusion(
            "Ha indicios de instabilidade na conexao externa ou no provedor de internet.",
            "provedor de internet",
            ConfidenceLevel.MEDIUM,
            ["Gateway permaneceu majoritariamente disponivel enquanto internet e SIP falharam."],
            measurements,
        )
    if dns_loss > 20 and internet_loss <= 10:
        return _conclusion(
            "Ha indicios de falha ou lentidao no servico de DNS.",
            "DNS",
            ConfidenceLevel.MEDIUM,
            ["Destinos por IP responderam melhor que testes por dominio."],
            measurements,
        )
    if gateway_loss <= 10 and internet_loss <= 10 and dns_loss <= 10 and sip_loss > 20:
        return _conclusion(
            "Ha indicios de indisponibilidade, bloqueio ou falha especifica na comunicacao com o servico de telefonia.",
            "servidor ou servico SIP",
            ConfidenceLevel.MEDIUM,
            ["Gateway, internet e DNS ficaram majoritariamente disponiveis enquanto SIP falhou."],
            measurements,
        )

    quality_events = {event.event_type for event in events}
    if any(name in quality_events for name in {"packet_loss_warning", "jitter_warning", "target_degraded"}):
        return _conclusion(
            "A conexao permaneceu disponivel, porem apresentou variacoes que podem afetar a qualidade de chamadas.",
            "qualidade inadequada para voz",
            ConfidenceLevel.MEDIUM,
            ["Foram registrados eventos de perda, jitter ou degradacao de latencia."],
            measurements,
        )
    relevant_failures = [
        stats for stats in target_stats.values()
        if stats["failure_rate"] >= 10 or stats["max_consecutive"] >= 3 or stats["ended_unavailable"]
    ]
    if relevant_failures:
        first = relevant_failures[0]
        return _conclusion(
            "Foram detectadas falhas relevantes em pelo menos um destino monitorado.",
            "anomalia tecnica detectada",
            ConfidenceLevel.MEDIUM,
            [
                (
                    f"{first['target_name']}: {first['failures']} falhas em {first['tests']} testes "
                    f"({first['failure_rate']:.1f}%)."
                )
            ],
            measurements,
        )
    if measurements:
        return _conclusion(
            "Nao foram detectadas anomalias nos destinos monitorados durante esta sessao.",
            "nenhuma instabilidade detectada",
            ConfidenceLevel.LOW,
            ["As medicoes disponiveis nao ultrapassaram os limites configurados."],
            measurements,
            extra_reducers=[
                "Esse resultado nao descarta problemas especificos de equipamento, credenciais, codec, RTP, aplicacao ou telefonia que nao sejam observaveis pelos testes atuais."
            ],
        )
    return _conclusion(
        "Dados insuficientes para uma conclusao automatica.",
        "dados insuficientes",
        ConfidenceLevel.INCONCLUSIVE,
        [],
        measurements,
    )


def _failure_rate_by_group(measurements: list[MeasurementRecord]) -> dict[str, float]:
    grouped: dict[str, list[MeasurementRecord]] = {}
    for measurement in measurements:
        kind = str(measurement.payload.get("target", {}).get("kind", "unknown"))
        grouped.setdefault(kind, []).append(measurement)
    rates: dict[str, float] = {}
    for kind, values in grouped.items():
        failures = sum(1 for item in values if item.status == "offline")
        rates[kind] = (failures / len(values)) * 100 if values else 0.0
    return rates


def _failure_stats_by_target(measurements: list[MeasurementRecord]) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[MeasurementRecord]] = {}
    for measurement in measurements:
        grouped.setdefault(measurement.target_name, []).append(measurement)
    stats: dict[str, dict[str, object]] = {}
    for target, values in grouped.items():
        values = sorted(values, key=lambda item: item.collected_at)
        tests = len(values)
        failures = sum(1 for item in values if item.status == "offline")
        stats[target] = {
            "target_name": target,
            "tests": tests,
            "failures": failures,
            "failure_rate": (failures / tests) * 100 if tests else 0.0,
            "max_consecutive": _max_consecutive_failures(values),
            "ended_unavailable": bool(values and values[-1].status == "offline"),
            "probe": _probe_for(values[-1]) if values else "ICMP",
        }
    return stats


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


def _probe_for(item: MeasurementRecord) -> str:
    protocol = str(item.payload.get("target", {}).get("protocol") or "").upper()
    probe = str(item.payload.get("details", {}).get("probe") or "").upper()
    name = item.target_name.upper()
    if " TCP" in name or protocol == "TCP" or probe == "TCP":
        return "TCP"
    if " TLS" in name or protocol == "TLS" or probe == "TLS":
        return "TLS"
    if " DNS" in name or protocol == "DNS" or probe == "DNS":
        return "DNS"
    if protocol == "UDP" or probe == "UDP":
        return "UDP"
    return "ICMP"


def _is_sip_tcp(target_name: str, probe: object) -> bool:
    return "SIP " in target_name.upper() and str(probe).upper() == "TCP"


def _conclusion(
    result: str,
    origin: str,
    confidence: ConfidenceLevel,
    evidences: list[str],
    measurements: list[MeasurementRecord],
    extra_reducers: list[str] | None = None,
) -> AutomaticConclusion:
    reducers = list(extra_reducers or [])
    if len(measurements) < 10:
        confidence = ConfidenceLevel.LOW if confidence != ConfidenceLevel.INCONCLUSIVE else confidence
        reducers.append("Poucas medicoes foram coletadas.")
    recommendations = [
        "Comparar os horarios dos eventos com relatos do cliente.",
        "Validar gateway, cabos, Wi-Fi e regras de firewall quando houver falha local.",
        "Usar o resultado como indicio tecnico, nao como conclusao absoluta.",
    ]
    return AutomaticConclusion(
        result=result,
        likely_origin=origin,
        confidence=confidence,
        evidences=evidences,
        confidence_reducers=reducers,
        recommendations=recommendations,
    )
