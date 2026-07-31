"""CSV, JSON, TXT and ZIP report exports."""

from __future__ import annotations

import csv
import json
import shutil
import zipfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from src.reports.charts import generate_charts, generate_diagnostic_charts
from src.reports.html_report import write_html_report
from src.reports.report_data_builder import SessionReportView, build_session_report_view
from src.storage.database import Database
from src.storage.models import MeasurementRecord, MonitoringSession
from src.utils.time_utils import format_datetime_local, format_datetime_local_ms


def generate_report_package(
    database: Database,
    session: MonitoringSession,
    reports_dir: str,
    interrupted: bool = False,
    exclude_warmup_from_summary: bool = True,
) -> Path:
    """Generate all report files and return the ZIP path."""
    output_dir = _session_output_dir(Path(reports_dir), session)
    output_dir.mkdir(parents=True, exist_ok=True)

    measurements = database.get_measurements(session.session_id)
    official_measurements = (
        _official_measurements(measurements)
        if exclude_warmup_from_summary
        else measurements
    )
    events = database.get_events(session.session_id)
    marks = database.get_customer_marks(session.session_id)
    baseline = database.get_session_baseline(session.session_id)
    technical_snapshots = database.get_technical_snapshots(session.session_id)
    snapshot_differences = database.get_snapshot_differences(session.session_id)
    diagnostic_records = {
        table: database.get_diagnostic_records(table, session.session_id)
        for table in _DIAGNOSTIC_TABLES
    }
    interruptions = database.get_interruptions(session.session_id)
    system_info = database.get_system_info(session.session_id)
    report_view = build_session_report_view(
        session,
        official_measurements,
        events,
        marks,
        interruptions,
        diagnostic_records,
        system_info,
    )
    database.store_diagnostic_record(
        "domain_diagnostics",
        session.session_id,
        datetime.now(UTC),
        {"items": [item.to_dict() for item in report_view.domain_diagnostics]},
    )
    generate_charts(official_measurements, output_dir, events=events, marks=marks, interruptions=interruptions)
    generate_diagnostic_charts(diagnostic_records, output_dir)
    _write_summary(
        output_dir / "resumo.txt",
        session,
        measurements,
        official_measurements,
        events,
        marks,
        technical_snapshots,
        report_view,
        interrupted,
    )
    _write_ticket_summary(output_dir / "resumo_chamado.txt", session, report_view)
    _write_events(output_dir / "eventos.txt", events)
    _write_metrics_csv(output_dir / "metricas.csv", measurements)
    _write_metrics_json(
        output_dir / "metricas.json",
        measurements,
        events,
        marks,
        interruptions,
        baseline,
        technical_snapshots,
        snapshot_differences,
        diagnostic_records,
        report_view,
    )
    _write_network_config(output_dir / "configuracao_rede.txt", system_info.payload if system_info else {})
    write_html_report(
        output_path=output_dir / "relatorio.html",
        session=session,
        measurements=official_measurements,
        raw_measurement_count=len(measurements),
        warmup_measurement_count=sum(1 for item in measurements if item.is_warmup),
        events=events,
        marks=marks,
        baseline=baseline,
        technical_snapshots=technical_snapshots,
        snapshot_differences=snapshot_differences,
        diagnostic_records=diagnostic_records,
        interruptions=interruptions,
        system_info=system_info,
        report_view=report_view,
        interrupted=interrupted,
    )
    if database.path.exists():
        database.checkpoint()
        shutil.copy2(database.path, output_dir / "banco_monitoramento.db")

    zip_path = output_dir.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in output_dir.iterdir():
            if file_path.is_file():
                archive.write(file_path, arcname=file_path.name)
    return zip_path


def _session_output_dir(base_dir: Path, session: MonitoringSession) -> Path:
    safe_client = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in session.request.client_name.strip()
    ).strip("_") or "Cliente"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return base_dir / f"Diagnostico_{safe_client}_{stamp}"


def _write_summary(
    path: Path,
    session: MonitoringSession,
    measurements: list[MeasurementRecord],
    official_measurements: list[MeasurementRecord],
    events: list[object],
    marks: list[object],
    technical_snapshots: list[object],
    report_view: SessionReportView,
    interrupted: bool,
) -> None:
    conclusion = report_view.correlation.conclusion
    lines = [
        "Vigos Network Stability Monitor",
        f"Cliente: {session.request.client_name}",
        f"Unidade: {session.request.unit or 'nao informada'}",
        f"Perfil: {session.request.profile_id}",
        f"Problema: {session.request.problem_description}",
        f"Status: {'monitoramento interrompido inesperadamente' if interrupted else session.status}",
        f"Inicio: {format_datetime_local(session.started_at)}",
        f"Fim: {format_datetime_local(session.finished_at)}",
        f"Medicoes brutas: {len(measurements)}",
        f"Medicoes usadas no diagnostico: {len(official_measurements)}",
        f"Medicoes de aquecimento: {sum(1 for item in measurements if item.is_warmup)}",
        f"Eventos: {len(events)}",
        f"Marcacoes do cliente: {len(marks)}",
        f"Snapshots tecnicos: {len(technical_snapshots)}",
        "",
        "Resumo executivo:",
        f"- Resultado: {report_view.executive.result_label}",
        f"- Origem provavel: {report_view.executive.likely_origin}",
        f"- Confianca: {report_view.executive.confidence}",
        f"- Interrupcoes identificadas: {report_view.executive.interruption_count}",
        f"- Marcacoes do cliente: {report_view.executive.marker_count}",
        f"- Disponibilidade SIP TCP: {_percent(report_view.executive.sip_tcp_availability)}",
        f"- Ocorrencias registradas pelo cliente: {report_view.customer_markers_summary.total}",
        f"- Correlacoes fortes com marcacao: {report_view.customer_markers_summary.strong_correlations}",
        "",
        "Audio:",
        f"- Entrada padrao: {report_view.audio.default_input or 'nao disponivel'}",
        f"- Entrada de comunicacao: {report_view.audio.communication_input or 'nao disponivel'}",
        f"- Saida padrao: {report_view.audio.default_output or 'nao disponivel'}",
        f"- Saida de comunicacao: {report_view.audio.communication_output or 'nao disponivel'}",
        f"- Dispositivos encontrados: {report_view.audio.device_count}",
        f"- Alteracoes de audio na sessao: {report_view.audio.event_count}",
        f"- Erros de driver: {report_view.audio.driver_error_count}",
        f"- Monitoramento de nivel habilitado: {'sim' if report_view.audio.level_monitoring_enabled else 'nao'}",
        "",
        "Softphone:",
        f"- Configurado: {'sim' if report_view.softphone.configured else 'nao'}",
        f"- Processo: {report_view.softphone.process_name or 'nao disponivel'}",
        f"- PID: {report_view.softphone.pid or 'nao disponivel'}",
        f"- Encontrado no fim da coleta: {'sim' if report_view.softphone.found else 'nao'}",
        f"- Eventos do softphone: {report_view.softphone.event_count}",
        f"- CPU alta: {report_view.softphone.high_cpu_events}",
        f"- Memoria alta: {report_view.softphone.high_memory_events}",
        f"- Nao respondendo: {report_view.softphone.not_responding_events}",
        "",
        "Diagnostico por dominio:",
        *[
            f"- {item.domain}: {item.status} ({item.evidence})"
            for item in report_view.domain_diagnostics
        ],
        "",
        "Eventos do Windows:",
        *(
            [
                f"- {format_datetime_local_ms(item.occurred_at)} {item.normalized_type}: {item.summary}"
                for item in report_view.windows_events[:8]
            ]
            or ["- Nenhum evento relevante registrado ou fonte indisponivel."]
        ),
        "",
        "Auditoria de energia:",
        *(
            [
                f"- {item.item}: {item.classification} - {item.current_value}"
                for item in report_view.power_audit
            ]
            or ["- Auditoria de energia indisponivel."]
        ),
        "",
        "Conclusao automatica:",
        f"- {conclusion.result}",
        f"- Origem provavel: {conclusion.likely_origin}",
        f"- Confianca: {conclusion.confidence.value.upper()}",
        "",
        "Evidencias:",
        *[f"- {item}" for item in conclusion.evidences],
        "",
        "Consistencia:",
        *([f"- {item}" for item in report_view.correlation.consistency_findings] or ["- Nenhuma contradicao interna detectada."]),
        "",
        "Metricas oficiais por destino:",
        *[
            (
                f"- {item.target_name}: {item.tests} testes, {item.successes} sucessos, "
                f"{item.failures} falhas, disponibilidade {_percent(item.availability_percent)}, "
                f"taxa de falhas {_percent(item.failure_rate_percent)}, maior sequencia {item.max_consecutive_failures}, "
                f"estado final {item.final_status}"
            )
            for item in report_view.destinations
        ],
        "",
        "Interrupcoes:",
        *(
            [
                (
                    f"- {item.target_name}: {item.status}, inicio {format_datetime_local_ms(item.started_at)}, "
                    f"fim {format_datetime_local_ms(item.ended_at)}, duracao {_seconds(item.duration_seconds)}, "
                    f"testes perdidos {item.lost_tests}, maior sequencia {item.max_consecutive_failures}"
                )
                for item in report_view.interruptions
            ]
            or ["- Nenhuma interrupcao detectada."]
        ),
        "",
        "Marcacoes do cliente:",
        *(_customer_marker_txt_blocks(report_view) or ["- Nenhuma marcacao registrada."]),
        "",
        "Recomendacoes:",
        *[f"- {item}" for item in conclusion.recommendations],
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_ticket_summary(path: Path, session: MonitoringSession, report_view: SessionReportView) -> None:
    conclusion = report_view.correlation.conclusion
    stable_areas = _stable_areas(report_view)
    nearby_events = [
        f"- {item.event_type}: {item.message}"
        for item in report_view.softphone.events[:3]
    ]
    nearby_events.extend(
        f"- {item.event_type}: {item.message}"
        for item in report_view.audio.events[:3]
    )
    nearby_events.extend(
        f"- {item.normalized_type}: {item.summary}"
        for item in report_view.windows_events[:3]
    )
    limitations = []
    limitations.extend(report_view.audio.limitations[:2])
    limitations.extend(report_view.softphone.limitations[:2])
    lines = [
        f"Cliente: {session.request.client_name}",
        f"Unidade: {session.request.unit or 'nao informada'}",
        f"Problema relatado: {session.request.problem_description}",
        f"Inicio: {format_datetime_local(session.started_at)}",
        f"Fim: {format_datetime_local(session.finished_at)}",
        f"Marcacoes: {report_view.executive.marker_count}",
        "",
        f"Resultado geral: {report_view.executive.result_label}",
        "",
        f"Dominio mais provavel: {conclusion.likely_origin}",
        "",
        f"Confianca: {conclusion.confidence.value.upper()}",
        "",
        "Evidencias principais:",
        *([f"- {item}" for item in conclusion.evidences[:6]] or ["- Nenhuma evidencia especifica registrada."]),
        "",
        "Areas que permaneceram estaveis:",
        *stable_areas,
        "",
        "Diagnostico por dominio:",
        *[f"- {item.domain}: {item.status} - {item.evidence}" for item in report_view.domain_diagnostics],
        "",
        "Eventos proximos a marcacao:",
        *(nearby_events or ["- Nenhum evento especifico de softphone/audio registrado."]),
        "",
        "Ocorrencias registradas pelo cliente:",
        *(_customer_marker_ticket_blocks(report_view) or ["- Nenhuma ocorrencia registrada pelo cliente durante a coleta."]),
        "",
        "Limitacoes:",
        *([f"- {item}" for item in limitations] or ["- A conclusao automatica depende das evidencias coletadas nesta sessao."]),
        "",
        "Proxima validacao recomendada:",
        *([f"- {item}" for item in conclusion.recommendations[:3]] or ["- Repetir coleta se o sintoma nao ocorreu durante a janela monitorada."]),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _customer_marker_txt_blocks(report_view: SessionReportView) -> list[str]:
    lines: list[str] = []
    for marker in report_view.markers:
        affected = "; ".join(marker.affected_monitors) if marker.affected_monitors else "nenhum destino afetado identificado"
        lines.extend(
            [
                "------------------------------------------------------------",
                f"OCORRENCIA REGISTRADA PELO CLIENTE #{marker.sequence_number}",
                f"- ID interno: {marker.mark_id}",
                f"- Ancora no HTML/JSON: {marker.anchor_id}",
                f"- Horario do clique: {format_datetime_local_ms(marker.marked_at)}",
                f"- Segundo relativo na sessao: {marker.relative_session_seconds:.0f}s",
                f"- Origem estruturada: {marker.event_origin}",
                f"- Tipo estruturado: {marker.event_type}",
                f"- Prioridade visual: {marker.visual_priority}",
                f"- Descricao vinculada: {marker.description}",
                f"- Status do contexto: {marker.context_status}",
                f"- Janela solicitada antes/depois: {_seconds(marker.requested_before_seconds)} / {_seconds(marker.requested_after_seconds)}",
                f"- Janela coletada antes/depois: {_seconds(marker.seconds_before)} / {_seconds(marker.seconds_after)}",
                f"- Amostras antes/depois: {marker.before_samples}/{marker.after_samples}",
                f"- Correlacao: {marker.correlation_label}",
                f"- Anomalia mais proxima: {_anomaly_txt(marker.nearest_anomaly_seconds, marker.nearest_anomaly_target)}",
                f"- Destinos afetados: {affected}",
                f"- Eventos automaticos no contexto: {len(marker.nearby_events)}",
                f"- Conclusao: {marker.conclusion}",
                f"- Limitacoes: {'; '.join(marker.limitations) if marker.limitations else 'sem limitacoes relevantes'}",
            ]
        )
    if lines:
        lines.append("------------------------------------------------------------")
    return lines


def _customer_marker_ticket_blocks(report_view: SessionReportView) -> list[str]:
    lines: list[str] = []
    for marker in report_view.markers:
        affected = "; ".join(marker.affected_monitors) if marker.affected_monitors else "sem destino afetado identificado"
        lines.extend(
            [
                f"- OCORRENCIA #{marker.sequence_number}: clique em {format_datetime_local_ms(marker.marked_at)} ({marker.relative_session_seconds:.0f}s apos o inicio).",
                f"  Correlacao: {marker.correlation_label}; anomalia mais proxima: {_anomaly_txt(marker.nearest_anomaly_seconds, marker.nearest_anomaly_target)}.",
                f"  Contexto: {_seconds(marker.seconds_before)} antes / {_seconds(marker.seconds_after)} depois; destinos afetados: {affected}.",
            ]
        )
    return lines


def _anomaly_txt(seconds: float | None, target: str | None) -> str:
    if seconds is None or not target:
        return "nao detectada"
    return f"{seconds:.0f}s em {target}"


def _write_events(path: Path, events: list[object]) -> None:
    lines = []
    for event in events:
        lines.append(
            f"{format_datetime_local_ms(event.occurred_at)} [{event.severity.value}] "
            f"{event.event_type}: {event.message}"
        )
    path.write_text("\n".join(lines) if lines else "Nenhum evento registrado.", encoding="utf-8")


def _write_metrics_csv(path: Path, measurements: list[MeasurementRecord]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["collected_at", "target_name", "status", "latency_ms", "is_warmup", "diagnostic_use", "error", "kind", "host"])
        for item in measurements:
            target = item.payload.get("target", {})
            writer.writerow(
                [
                    item.collected_at.isoformat(),
                    item.target_name,
                    item.status,
                    item.latency_ms,
                    item.is_warmup,
                    not item.is_warmup,
                    item.payload.get("error"),
                    target.get("kind"),
                    target.get("host"),
                ]
            )


def _write_metrics_json(
    path: Path,
    measurements: list[MeasurementRecord],
    events: list[object],
    marks: list[object],
    interruptions: list[object],
    baseline: object | None,
    technical_snapshots: list[object],
    snapshot_differences: list[object],
    diagnostic_records: dict[str, list[object]],
    report_view: SessionReportView,
) -> None:
    payload = {
        "measurements": [_record_dict(item) for item in measurements],
        "events": [_record_dict(item) for item in events],
        "customer_marks": [_record_dict(item) for item in marks],
        "interruptions": [_record_dict(item) for item in interruptions],
        "session_baseline": _record_dict(baseline) if baseline else None,
        "technical_snapshots": [_record_dict(item) for item in technical_snapshots],
        "snapshot_differences": [_record_dict(item) for item in snapshot_differences],
        "diagnostics": {
            table: [_safe_diagnostic_record(table, item) for item in records]
            for table, records in diagnostic_records.items()
        },
        "report_view": report_view.to_dict(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, default=str), encoding="utf-8")


def _write_network_config(path: Path, payload: dict[str, object]) -> None:
    lines = []
    for key, value in payload.items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            for nested_key, nested_value in value.items():
                if isinstance(nested_value, (dict, list)):
                    lines.append(f"  {nested_key}: dados estruturados")
                else:
                    lines.append(f"  {nested_key}: {nested_value if nested_value not in (None, '') else 'nao disponivel'}")
        elif isinstance(value, list):
            lines.append(f"{key}: {'; '.join(str(item) for item in value) if value else 'nenhum'}")
        else:
            lines.append(f"{key}: {value if value not in (None, '') else 'nao disponivel'}")
    path.write_text("\n".join(lines) if lines else "Informacoes de rede indisponiveis.", encoding="utf-8")


def _record_dict(value: object) -> dict[str, object]:
    try:
        return asdict(value)
    except TypeError:
        return dict(value.__dict__)


def _safe_diagnostic_record(table: str, value: object) -> dict[str, object]:
    record = _record_dict(value)
    if table == "sip_options_results" and isinstance(record.get("payload"), dict):
        record["payload"] = _sanitize_sensitive(record["payload"])
    return record


def _sanitize_sensitive(value: object) -> object:
    sensitive = {"nonce", "opaque", "authorization", "proxy-authorization", "call-id", "branch", "challenge"}
    if isinstance(value, dict):
        sanitized = {}
        for key, nested in value.items():
            if str(key).lower() in sensitive:
                sanitized[key] = "[removido]"
            else:
                sanitized[key] = _sanitize_sensitive(nested)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_sensitive(item) for item in value]
    return value


def _percent(value: float | None) -> str:
    return "nao disponivel" if value is None else f"{value:.1f}%"


def _seconds(value: float | None) -> str:
    return "nao disponivel" if value is None else f"{value:.1f}s"


def _stable_areas(report_view: SessionReportView) -> list[str]:
    rows = []
    for category, label in {
        "gateway": "Gateway/rede local",
        "internet": "Internet por IP",
        "dns": "DNS",
        "sip": "Servico SIP",
    }.items():
        matches = [item for item in report_view.destinations if item.category == category]
        if matches and all(item.failure_rate_percent <= 10 and not item.ended_unavailable for item in matches):
            rows.append(f"- {label}")
    return rows or ["- Nao foi possivel confirmar areas estaveis com os dados disponiveis."]


def _official_measurements(measurements: list[MeasurementRecord]) -> list[MeasurementRecord]:
    return [item for item in measurements if not item.is_warmup]


_DIAGNOSTIC_TABLES = [
    "interface_traffic",
    "system_metrics",
    "sip_options_results",
    "sip_transport_results",
    "udp_flow_tests",
    "voice_quality_results",
    "time_sync_results",
    "wifi_metrics",
    "route_traces",
    "public_ip_history",
    "network_environment_events",
    "audio_devices",
    "audio_device_states",
    "audio_events",
    "audio_level_metrics",
    "microphone_tests",
    "output_tests",
    "audio_permissions",
    "audio_driver_information",
    "audio_snapshots",
    "softphone_processes",
    "softphone_metrics",
    "softphone_events",
    "windows_events",
    "power_audit",
    "marker_contexts",
    "marker_correlations",
    "domain_diagnostics",
    "softphone_config_snapshots",
]
