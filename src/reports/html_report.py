"""HTML report generation."""

from __future__ import annotations

from html import escape
from pathlib import Path

from src.reports.customer_markers import customer_marker_css_variables, is_customer_marker_event
from src.reports.report_data_builder import (
    DestinationMetricsView,
    InterruptionReportView,
    MarkerReportView,
    SessionReportView,
    SystemReportView,
    TimeSyncReportView,
    TrafficReportView,
    WifiReportView,
)
from src.storage.models import (
    EventRecord,
    InterruptionRecord,
    MeasurementRecord,
    MonitoringSession,
    SessionBaseline,
    SnapshotDifference,
    StoredCustomerMark,
    SystemInfoRecord,
    TechnicalSnapshot,
)
from src.utils.time_utils import format_datetime_local, format_datetime_local_ms


def write_html_report(
    output_path: Path,
    session: MonitoringSession,
    measurements: list[MeasurementRecord],
    raw_measurement_count: int,
    warmup_measurement_count: int,
    events: list[EventRecord],
    marks: list[StoredCustomerMark],
    baseline: SessionBaseline | None,
    technical_snapshots: list[TechnicalSnapshot],
    snapshot_differences: list[SnapshotDifference],
    diagnostic_records: dict[str, list[object]],
    interruptions: list[InterruptionRecord],
    system_info: SystemInfoRecord | None,
    report_view: SessionReportView,
    interrupted: bool,
) -> None:
    """Write a self-contained HTML report."""
    metric_rows = _metric_rows(report_view.destinations)
    rendered = _render_with_jinja(
        session=session,
        metric_rows=metric_rows,
        executive_html=_executive_html(report_view),
        raw_measurement_count=raw_measurement_count,
        official_measurement_count=len(measurements),
        warmup_measurement_count=warmup_measurement_count,
        events_html=_events_table(events),
        marks_html=_marks_html(report_view.markers),
        baseline_html=_baseline_html(baseline),
        technical_snapshots_html=_technical_snapshots_html(technical_snapshots, snapshot_differences),
        diagnostics_html=_diagnostics_html(diagnostic_records, report_view),
        audio_html=_audio_html(report_view),
        marker_images=_marker_images(marks),
        interruptions_html=_interruptions_table(report_view.interruptions),
        system_info_html=_system_table(system_info),
        correlation_html=_correlation_html(report_view),
        interrupted=interrupted,
        format_datetime_local=format_datetime_local,
    )
    if rendered is not None:
        output_path.write_text(rendered, encoding="utf-8")
        return
    output_path.write_text(
        f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>Relatorio Vigos - {escape(session.request.client_name)}</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 32px; color: #172033; }}
    h1, h2 {{ color: #0B3157; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #D0D7DE; padding: 8px; font-size: 13px; text-align: left; }}
    th {{ background: #EAF2F8; }}
    .critical {{ color: #B42318; font-weight: 700; }}
    .warning {{ color: #9A6700; font-weight: 700; }}
    :root {{ {customer_marker_css_variables()} }}
    .mark {{ border-left: 4px solid var(--customer-marker-color); padding: 8px 12px; background: var(--customer-marker-fill-color); margin: 10px 0; }}
    .customer-marker-summary {{ border: 1px solid var(--customer-marker-edge-color); background: var(--customer-marker-fill-color); padding: 12px; margin: 12px 0 20px; }}
    .customer-occurrence-card {{ border: 2px solid var(--customer-marker-color); border-left-width: 8px; background: var(--customer-marker-fill-color); padding: 14px; margin: 14px 0; page-break-inside: avoid; }}
    .customer-occurrence-card h3 {{ margin: 6px 0 8px; color: var(--customer-marker-text-color); }}
    .customer-marker-badge {{ display: inline-block; border: 1px solid var(--customer-marker-edge-color); color: var(--customer-marker-text-color); background: #fff; padding: 3px 7px; font-size: 12px; font-weight: 700; }}
    .customer-marker-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 8px 12px; }}
    .customer-marker-row {{ background: var(--customer-marker-fill-color); color: var(--customer-marker-text-color); font-weight: 700; }}
    .incident-replay {{ border-top: 2px solid var(--customer-marker-color); margin-top: 18px; padding-top: 10px; page-break-inside: avoid; }}
    @media print {{ .customer-occurrence-card, .incident-replay {{ break-inside: avoid; }} a {{ color: inherit; text-decoration: none; }} }}
    img {{ max-width: 100%; border: 1px solid #D0D7DE; margin-bottom: 16px; }}
    code {{ background: #F6F8FA; padding: 2px 4px; }}
  </style>
</head>
<body>
  <h1>Vigos Network Stability Monitor</h1>
  <p><strong>Status:</strong> {escape("monitoramento interrompido inesperadamente" if interrupted else session.status)}</p>
  <h2>Identificacao</h2>
  <p><strong>Cliente:</strong> {escape(session.request.client_name)}</p>
  <p><strong>Unidade:</strong> {escape(session.request.unit or "nao informada")}</p>
  <p><strong>Perfil:</strong> {escape(session.request.profile_id)}</p>
  <p><strong>Problema relatado:</strong> {escape(session.request.problem_description)}</p>
  <p><strong>Inicio:</strong> {format_datetime_local(session.started_at)}<br>
     <strong>Fim:</strong> {format_datetime_local(session.finished_at)}</p>
  <p><strong>Medicoes usadas no diagnostico:</strong> {len(measurements)} de {raw_measurement_count}
     <br><strong>Medicoes de aquecimento:</strong> {warmup_measurement_count}</p>
  <h2>Resumo executivo</h2>
  {_executive_html(report_view)}
  <h2>Maquina e rede</h2>
  {_system_table(system_info)}
  <h2>Metricas oficiais por destino</h2>
  <table><thead><tr><th>Destino</th><th>Categoria</th><th>Teste</th><th>Estado final</th><th>Testes</th><th>Sucessos</th><th>Falhas</th><th>Disponibilidade</th><th>Taxa de falhas</th><th>Atual</th><th>Media</th><th>P95</th><th>Pico</th><th>Variacao</th><th>Maior sequencia</th></tr></thead>
  <tbody>{metric_rows}</tbody></table>
  <h2>Marcacoes do cliente</h2>
  {_marks_html(report_view.markers)}
  <h2>Baseline inicial</h2>
  {_baseline_html(baseline)}
  <h2>Snapshots tecnicos das marcacoes</h2>
  {_technical_snapshots_html(technical_snapshots, snapshot_differences)}
  <h2>Diagnosticos adicionais</h2>
  {_diagnostics_html(diagnostic_records, report_view)}
  <h2>Diagnostico de audio</h2>
  {_audio_html(report_view)}
  <h2>Eventos criticos e avisos</h2>
  {_events_table(events)}
  <h2>Interrupcoes detectadas</h2>
  {_interruptions_table(report_view.interruptions)}
  <h2>Correlacao</h2>
  {_correlation_html(report_view)}
  <h2>Graficos</h2>
  <img src="grafico_latencia.png" alt="Grafico de latencia">
  <img src="grafico_perda.png" alt="Grafico de perda">
  <img src="grafico_jitter.png" alt="Grafico de jitter">
  <img src="grafico_disponibilidade.png" alt="Grafico de disponibilidade">
  <img src="linha_tempo_eventos.png" alt="Linha do tempo de eventos">
  <img src="grafico_trafego.png" alt="Grafico de trafego">
  <img src="grafico_sistema.png" alt="Grafico de sistema">
  <img src="grafico_wifi.png" alt="Grafico de Wi-Fi">
  <img src="grafico_qualidade_voz.png" alt="Grafico de qualidade de voz">
  {_marker_images(marks)}
</body>
</html>
""",
        encoding="utf-8",
    )


def _executive_html(report_view: SessionReportView) -> str:
    conclusion = report_view.correlation.conclusion
    table = "<table><tbody>" + _payload_rows(
        {
            "Resultado": report_view.executive.result_label,
            "Origem provavel": report_view.executive.likely_origin,
            "Confianca": report_view.executive.confidence,
            "Disponibilidade SIP TCP": _percent(report_view.executive.sip_tcp_availability),
            "Interrupcoes": report_view.executive.interruption_count,
            "Marcacoes": report_view.executive.marker_count,
            "Conclusao": conclusion.result,
        }
    ) + "</tbody></table>"
    return table + _customer_marker_summary_html(report_view.markers)


def _metric_rows(destinations: list[DestinationMetricsView]) -> str:
    rows = []
    for item in destinations:
        css = "critical" if item.failure_rate_percent >= 10 or item.ended_unavailable else ""
        rows.append(
            f"<tr class='{css}'>"
            f"<td>{escape(item.target_name)}</td><td>{escape(item.category)}</td><td>{escape(item.probe)}</td>"
            f"<td>{escape(item.final_status)}</td><td>{item.tests}</td><td>{item.successes}</td><td>{item.failures}</td>"
            f"<td>{_percent(item.availability_percent)}</td><td>{_percent(item.failure_rate_percent)}</td>"
            f"<td>{_ms(item.latency_current_ms)}</td><td>{_ms(item.latency_avg_ms)}</td><td>{_ms(item.latency_p95_ms)}</td>"
            f"<td>{_ms(item.latency_max_ms)}</td><td>{escape(item.jitter_label)}: {_ms(item.response_variation_ms)}</td>"
            f"<td>{item.max_consecutive_failures}</td>"
            "</tr>"
        )
    return "".join(rows) or "<tr><td colspan='15'>Sem medicoes.</td></tr>"


def _system_table(system_info: SystemInfoRecord | None) -> str:
    if not system_info:
        return "<p>Informacoes de sistema indisponiveis.</p>"
    payload = system_info.payload
    wifi = payload.get("wifi") if isinstance(payload.get("wifi"), dict) else {}
    rows = _payload_rows(
        {
            "Computador": payload.get("computer_name"),
            "Usuario": payload.get("current_user"),
            "Windows": payload.get("windows_version"),
            "Python": payload.get("python_version"),
            "Capturado em": payload.get("captured_local_time"),
            "Interface ativa": payload.get("active_interface"),
            "IP local": payload.get("local_ip"),
            "Gateway": payload.get("gateway"),
            "Tipo de conexao": payload.get("connection_type"),
            "Rota padrao detectada": _enabled(payload.get("default_route")),
            "Metrica da rota padrao": payload.get("default_route_metric"),
            "Interface ativa ligada": _enabled(payload.get("interface_up")),
            "MAC": payload.get("mac_address"),
            "Wi-Fi SSID": wifi.get("ssid") if isinstance(wifi, dict) else None,
            "Wi-Fi sinal": _percent(wifi.get("signal_percent")) if isinstance(wifi, dict) else None,
        }
    )
    return f"<table><tbody>{rows}</tbody></table>"


def _marks_html(marks: list[MarkerReportView]) -> str:
    if not marks:
        return "<p>Nenhuma marcacao do cliente.</p>"
    blocks = []
    for mark in marks:
        limitations = "; ".join(mark.limitations) if mark.limitations else "Sem limitacoes relevantes."
        affected = "; ".join(mark.affected_monitors) if mark.affected_monitors else "Nenhum destino afetado identificado."
        nearby_count = len(mark.nearby_events)
        blocks.append(
            f"<article id='{escape(mark.anchor_id)}' class='customer-occurrence-card'>"
            "<span class='customer-marker-badge'>CLIENTE</span>"
            f"<h3>{escape(mark.title)}</h3>"
            f"<p><strong>Horario do clique:</strong> {format_datetime_local_ms(mark.marked_at)} "
            f"({mark.relative_session_seconds:.0f}s apos o inicio da sessao)</p>"
            f"<p><strong>Descricao vinculada:</strong> {escape(mark.description)}</p>"
            "<div class='customer-marker-grid'>"
            f"<div><strong>Origem</strong><br>{escape(mark.event_origin)}</div>"
            f"<div><strong>Tipo estruturado</strong><br>{escape(mark.event_type)}</div>"
            f"<div><strong>Status do contexto</strong><br>{escape(mark.context_status)}</div>"
            f"<div><strong>Prioridade visual</strong><br>{escape(mark.visual_priority)}</div>"
            f"<div><strong>Correlacao</strong><br>{escape(mark.correlation_label)}</div>"
            f"<div><strong>Anomalia mais proxima</strong><br>{_anomaly_text(mark.nearest_anomaly_seconds, mark.nearest_anomaly_target)}</div>"
            f"<div><strong>Amostras antes/depois</strong><br>{mark.before_samples}/{mark.after_samples}</div>"
            f"<div><strong>Janela coletada antes/depois</strong><br>{_seconds(mark.seconds_before)} / {_seconds(mark.seconds_after)}</div>"
            f"<div><strong>Janela solicitada antes/depois</strong><br>{_seconds(mark.requested_before_seconds)} / {_seconds(mark.requested_after_seconds)}</div>"
            f"<div><strong>Eventos proximos</strong><br>{nearby_count}</div>"
            "</div>"
            f"<p><strong>Destinos afetados:</strong> {escape(affected)}</p>"
            f"<p><strong>Conclusao:</strong> {escape(mark.conclusion)}</p>"
            f"<p><strong>Limitacoes:</strong> {escape(limitations)}</p>"
            f"<p><a href='#{escape(mark.replay_anchor_id)}'>Ver reproducao da ocorrencia #{mark.sequence_number}</a></p>"
            "</article>"
            f"<section id='{escape(mark.replay_anchor_id)}' class='incident-replay'>"
            f"<h3>REPRODUCAO DA OCORRENCIA #{mark.sequence_number}</h3>"
            f"<p><strong>Ancora da ocorrencia:</strong> <a href='#{escape(mark.anchor_id)}'>{escape(mark.anchor_id)}</a></p>"
            "<table><tbody>"
            + _payload_rows(
                {
                    "Contexto solicitado": f"{_seconds(mark.requested_before_seconds)} antes / {_seconds(mark.requested_after_seconds)} depois",
                    "Contexto coletado": f"{_seconds(mark.seconds_before)} antes / {_seconds(mark.seconds_after)} depois",
                    "Captura imediata": format_datetime_local_ms(mark.immediate_snapshot_at),
                    "Enriquecimento tecnico": mark.technical_snapshot_status or "nao registrado",
                    "Primeira anomalia antes": _anomaly_text(mark.first_anomaly_before_seconds, mark.first_anomaly_before_target),
                    "Primeira anomalia depois": _anomaly_text(mark.first_anomaly_after_seconds, mark.first_anomaly_after_target),
                }
            )
            + "</tbody></table>"
            + _nearby_events_table(mark.nearby_events)
            + "</section>"
        )
    return "".join(blocks)


def _events_table(events: list[EventRecord]) -> str:
    if not events:
        return "<p>Nenhum evento automatico registrado.</p>"
    rows = []
    for event in events:
        if is_customer_marker_event(event):
            css = "customer-marker-row"
        else:
            css = "critical" if event.severity.value == "critical" else "warning" if event.severity.value == "warning" else ""
        severity = "CLIENTE" if is_customer_marker_event(event) else event.severity.value
        rows.append(
            f"<tr class='{css}'><td>{format_datetime_local_ms(event.occurred_at)}</td>"
            f"<td>{escape(severity)}</td><td>{escape(event.event_type)}</td>"
            f"<td>{escape(event.message)}</td></tr>"
        )
    return "<table><thead><tr><th>Horario</th><th>Severidade</th><th>Tipo</th><th>Mensagem</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def _baseline_html(baseline: SessionBaseline | None) -> str:
    if baseline is None:
        return "<p>Baseline tecnico indisponivel.</p>"
    rows = _payload_rows(
        {
            "Coletado em": format_datetime_local_ms(baseline.collected_at),
            "Interface": _nested(baseline.payload, "network.active_interface"),
            "Tipo": _nested(baseline.payload, "network.connection_type"),
            "IP local": _nested(baseline.payload, "network.local_ip"),
            "Gateway": _nested(baseline.payload, "network.gateway"),
            "DNS": ", ".join(_nested(baseline.payload, "network.dns_servers") or []),
            "SSID": _nested(baseline.payload, "wifi.ssid"),
            "Sinal Wi-Fi": _percent(_nested(baseline.payload, "wifi.signal_percent")),
            "Proxy": _enabled(_nested(baseline.payload, "network.proxy.enabled")),
            "IPs SIP": ", ".join(_nested(baseline.payload, "sip.resolved_ips") or []),
        }
    )
    return f"<table><tbody>{rows}</tbody></table>"


def _technical_snapshots_html(
    snapshots: list[TechnicalSnapshot],
    differences: list[SnapshotDifference],
) -> str:
    if not snapshots:
        return "<p>Nenhum snapshot tecnico registrado.</p>"
    by_snapshot: dict[int, list[SnapshotDifference]] = {}
    for difference in differences:
        by_snapshot.setdefault(difference.snapshot_id, []).append(difference)
    blocks = []
    for snapshot in snapshots:
        payload = snapshot.payload
        rows = _payload_rows(
            {
                "Marcacao": snapshot.mark_id,
                "Coletado em": format_datetime_local_ms(snapshot.collected_at),
                "Clique registrado em": _nested(payload, "triggered_at"),
                "Enriquecimento iniciado em": _nested(payload, "enrichment_started_at"),
                "Enriquecimento finalizado em": _nested(payload, "enrichment_finished_at"),
                "Duracao do enriquecimento": _seconds(_nested(payload, "duration_seconds")),
                "Interface": _nested(payload, "network.active_interface"),
                "Tipo": _nested(payload, "network.connection_type"),
                "IP local": _nested(payload, "network.local_ip"),
                "Gateway": _nested(payload, "network.gateway"),
                "DNS": ", ".join(_nested(payload, "network.dns_servers") or []),
                "SSID": _nested(payload, "wifi.ssid"),
                "Sinal Wi-Fi": _percent(_nested(payload, "wifi.signal_percent")),
                "Proxy": _enabled(_nested(payload, "network.proxy.enabled")),
                "IPs SIP": ", ".join(_nested(payload, "sip.resolved_ips") or []),
                "Falhas parciais": "; ".join(payload.get("partial_failures", [])),
            }
        )
        diff_rows = "".join(
            "<li>"
            f"{escape(item.message)} "
            f"({escape(item.field_name)}: {escape(_display_value(item.baseline_value))} -> {escape(_display_value(item.snapshot_value))})"
            "</li>"
            for item in by_snapshot.get(snapshot.snapshot_id, [])
        )
        diff_html = f"<ul>{diff_rows}</ul>" if diff_rows else "<p>Nenhuma alteracao comprovada em relacao ao baseline.</p>"
        blocks.append(
            "<div class='mark'>"
            f"<strong>Snapshot tecnico #{snapshot.snapshot_id}</strong>"
            f"<table><tbody>{rows}</tbody></table>"
            f"<strong>Alteracoes detectadas</strong>{diff_html}"
            "</div>"
        )
    return "".join(blocks)


def _diagnostics_html(records_by_table: dict[str, list[object]], report_view: SessionReportView) -> str:
    sections = [
        ("Diagnostico por dominio", "domain_diagnostics", lambda records: _domain_diagnostics_summary_view(report_view)),
        ("Trafego de upload/download", "interface_traffic", lambda records: _traffic_summary_view(report_view.traffic)),
        ("CPU, memoria e disco", "system_metrics", lambda records: _system_metrics_summary_view(report_view.system)),
        ("SIP OPTIONS", "sip_options_results", lambda records: _sip_options_summary(report_view)),
        ("Transportes SIP UDP/TCP/TLS", "sip_transport_results", lambda records: _sip_transport_summary(report_view)),
        ("Teste UDP avancado", "udp_flow_tests", _udp_flow_summary),
        ("Qualidade estimada para voz", "voice_quality_results", _voice_quality_summary),
        ("Data, hora e sincronizacao", "time_sync_results", lambda records: _time_sync_summary_view(report_view.time_sync)),
        ("Wi-Fi", "wifi_metrics", lambda records: _wifi_summary_view(report_view.wifi)),
        ("Rotas", "route_traces", lambda records: _route_summary_view(report_view)),
        ("IP publico, IPv4/IPv6 e CGNAT", "public_ip_history", _public_ip_summary),
        ("VPN, proxy e adaptadores", "network_environment_events", _network_environment_summary),
        ("Processo do softphone", "softphone_metrics", lambda records: _softphone_summary_view(report_view)),
        ("Eventos do Windows", "windows_events", lambda records: _windows_events_summary_view(report_view)),
        ("Auditoria de energia", "power_audit", lambda records: _power_audit_summary_view(report_view)),
    ]
    blocks = []
    for title, table, renderer in sections:
        records = records_by_table.get(table, [])
        blocks.append(f"<h3>{escape(title)}</h3>{renderer(records)}")
    blocks.append(
        "<p><strong>Limitacoes:</strong> dados indisponiveis ou bloqueados pelo Windows/rede sao apresentados como "
        "nao disponiveis. Traceroute e respostas UDP sao evidencias complementares e nao comprovam causa isoladamente.</p>"
    )
    return "".join(blocks)


def _audio_html(report_view: SessionReportView) -> str:
    audio = report_view.audio
    summary = "<table><tbody>" + _payload_rows(
        {
            "Disponivel": _enabled(audio.available),
            "Entrada padrao": audio.default_input,
            "Entrada de comunicacao": audio.communication_input,
            "Saida padrao": audio.default_output,
            "Saida de comunicacao": audio.communication_output,
            "Dispositivos": audio.device_count,
            "Entradas": audio.input_count,
            "Saidas": audio.output_count,
            "Dispositivos virtuais": audio.virtual_device_count,
            "Erros de driver": audio.driver_error_count,
            "Alteracoes na sessao": audio.event_count,
            "Monitoramento de nivel": _enabled(audio.level_monitoring_enabled),
            "Permissoes": audio.permission_summary,
        }
    ) + "</tbody></table>"
    input_rows = _audio_device_rows([item for item in audio.devices if item.direction == "input"], include_test=False)
    output_rows = _audio_device_rows([item for item in audio.devices if item.direction == "output"], include_test=True)
    events = _audio_event_rows(audio.events)
    mic_tests = _audio_test_rows(audio.microphone_tests)
    output_tests = _audio_test_rows(audio.output_tests)
    driver_rows = _audio_driver_rows(audio.devices)
    limitations = "".join(f"<li>{escape(item)}</li>" for item in audio.limitations)
    return "".join(
        [
            "<h3>Resumo</h3>",
            summary,
            "<h3>Dispositivos de entrada</h3>",
            "<table><thead><tr><th>Dispositivo</th><th>Estado</th><th>Padrao</th><th>Comunicacao</th><th>Volume</th><th>Mudo</th><th>Sinal</th></tr></thead><tbody>",
            input_rows,
            "</tbody></table>",
            "<h3>Dispositivos de saida</h3>",
            "<table><thead><tr><th>Dispositivo</th><th>Estado</th><th>Padrao</th><th>Comunicacao</th><th>Volume</th><th>Teste</th></tr></thead><tbody>",
            output_rows,
            "</tbody></table>",
            "<h3>Eventos de audio</h3>",
            "<table><thead><tr><th>Horario</th><th>Evento</th><th>Dispositivo</th><th>Estado anterior</th><th>Estado atual</th></tr></thead><tbody>",
            events,
            "</tbody></table>",
            "<h3>Teste de microfone</h3>",
            mic_tests,
            "<h3>Teste de reproducao</h3>",
            output_tests,
            "<h3>Drivers</h3>",
            "<table><thead><tr><th>Dispositivo</th><th>Versao</th><th>Data</th><th>Status</th><th>Codigo</th><th>Interpretacao</th></tr></thead><tbody>",
            driver_rows,
            "</tbody></table>",
            f"<h3>Limitacoes</h3><ul>{limitations}</ul>",
        ]
    )


def _audio_device_rows(devices: list[object], include_test: bool) -> str:
    if not devices:
        colspan = 6 if include_test else 7
        return f"<tr><td colspan='{colspan}'>Nenhum dispositivo registrado.</td></tr>"
    rows = []
    for item in devices:
        if include_test:
            rows.append(
                f"<tr><td>{escape(item.name)}</td><td>{escape(item.state)}</td><td>{_enabled(item.is_default)}</td>"
                f"<td>{_enabled(item.is_default_communications)}</td><td>{_percent(item.volume_percent)}</td><td>N/D</td></tr>"
            )
        else:
            rows.append(
                f"<tr><td>{escape(item.name)}</td><td>{escape(item.state)}</td><td>{_enabled(item.is_default)}</td>"
                f"<td>{_enabled(item.is_default_communications)}</td><td>{_percent(item.volume_percent)}</td>"
                f"<td>{_enabled(item.muted)}</td><td>{escape(item.signal)}</td></tr>"
            )
    return "".join(rows)


def _audio_event_rows(events: list[object]) -> str:
    if not events:
        return "<tr><td colspan='5'>Nenhum evento de audio registrado.</td></tr>"
    return "".join(
        f"<tr><td>{format_datetime_local_ms(item.occurred_at)}</td><td>{escape(item.event_type)}</td>"
        f"<td>{escape(item.device_name or 'N/D')}</td><td>{escape(item.previous_state or 'N/D')}</td>"
        f"<td>{escape(item.current_state or 'N/D')}</td></tr>"
        for item in events
    )


def _audio_test_rows(tests: list[dict[str, object]]) -> str:
    if not tests:
        return "<p>Nenhum teste guiado registrado.</p>"
    blocks = []
    for item in tests:
        blocks.append(
            "<table><tbody>"
            + _payload_rows(
                {
                    "Horario": item.get("started_at"),
                    "Dispositivo": item.get("device_name") or item.get("device_id"),
                    "Duracao": _seconds(_to_float(item.get("duration_seconds"))),
                    "Sinal": _enabled(item.get("signal_detected")),
                    "Media/RMS": item.get("rms") or item.get("average_level"),
                    "Pico": item.get("peak"),
                    "Silencio": _percent(item.get("silence_percent")),
                    "Saturacao": _enabled(item.get("saturation")),
                    "Fluxo aceito": _enabled(item.get("stream_accepted")),
                    "Confirmacao do usuario": item.get("user_confirmation"),
                    "Resultado": item.get("state") or item.get("result"),
                    "Limitacao": item.get("privacy_note") or item.get("error"),
                }
            )
            + "</tbody></table>"
        )
    return "".join(blocks)


def _audio_driver_rows(devices: list[object]) -> str:
    driver_devices = [item for item in devices if item.driver_version or item.pnp_status or item.pnp_error_code is not None]
    if not driver_devices:
        return "<tr><td colspan='6'>Nenhuma informacao de driver registrada.</td></tr>"
    return "".join(
        f"<tr><td>{escape(item.name)}</td><td>{escape(item.driver_version or 'N/D')}</td><td>{escape(item.driver_date or 'N/D')}</td>"
        f"<td>{escape(item.pnp_status or 'N/D')}</td><td>{item.pnp_error_code if item.pnp_error_code is not None else 'N/D'}</td>"
        f"<td>{escape(item.pnp_error_interpretation or 'N/D')}</td></tr>"
        for item in driver_devices
    )


def _traffic_summary_view(traffic: TrafficReportView) -> str:
    if traffic.samples == 0:
        return "<p>Nao disponivel.</p>"
    return "<table><tbody>" + _payload_rows(
        {
            "Amostras": traffic.samples,
            "Interface": traffic.latest_interface,
            "Modo": traffic.mode,
            "Origem do contador": traffic.counter_source,
            "Taxa atual disponivel": "sim" if traffic.latest_rate_available else "nao, primeira amostra ou troca de interface",
            "Upload atual": _mbps(traffic.upload_current_mbps),
            "Download atual": _mbps(traffic.download_current_mbps),
            "Pico upload": _mbps(traffic.upload_peak_mbps),
            "Pico download": _mbps(traffic.download_peak_mbps),
            "Falhas de coleta": traffic.collection_failures,
        }
    ) + "</tbody></table>"


def _system_metrics_summary_view(system: SystemReportView) -> str:
    if system.samples == 0:
        return "<p>Nao disponivel.</p>"
    return "<table><tbody>" + _payload_rows(
        {
            "Amostras": system.samples,
            "CPU atual": _percent(system.cpu_current_percent),
            "CPU media": _percent(system.cpu_avg_percent),
            "CPU P95": _percent(system.cpu_p95_percent),
            "CPU pico": _percent(system.cpu_peak_percent),
            "Memoria atual": _percent(system.memory_current_percent),
            "Memoria media": _percent(system.memory_avg_percent),
            "Memoria pico": _percent(system.memory_peak_percent),
            "Memoria disponivel": f"{system.memory_available_mb:.0f} MB" if system.memory_available_mb is not None else None,
            "Espaco em disco utilizado": _percent(system.disk_used_percent),
        }
    ) + "</tbody></table>"


def _wifi_summary_view(wifi: WifiReportView) -> str:
    if not wifi.available:
        return f"<p>{escape(wifi.note)}</p>"
    return "<table><tbody>" + _payload_rows(
        {
            "Wi-Fi disponivel": _enabled(wifi.available),
            "Wi-Fi conectado": _enabled(wifi.connected),
            "SSID": wifi.ssid,
            "Sinal": _percent(wifi.signal_percent),
            "Radio": wifi.radio_type,
            "Canal": wifi.channel,
            "Recepcao": _mbps(wifi.receive_rate_mbps),
            "Transmissao": _mbps(wifi.transmit_rate_mbps),
            "BSSID": wifi.bssid_masked,
            "Interface padrao": wifi.active_interface,
            "Wi-Fi utilizado pelo monitoramento": _enabled(wifi.wifi_used_by_monitoring),
            "Observacao": wifi.note,
        }
    ) + "</tbody></table>"


def _time_sync_summary_view(time_sync: TimeSyncReportView) -> str:
    return "<table><tbody>" + _payload_rows(
        {
            "Hora local": time_sync.local_time,
            "Fuso": time_sync.timezone,
            "Sincronizado": _enabled(time_sync.synchronized),
            "Servico ativo": _enabled(time_sync.service_active),
            "Origem": time_sync.source,
            "Ultima sincronizacao": time_sync.last_successful_sync,
            "Camada": time_sync.stratum,
            "Offset": time_sync.offset,
            "Observacao": time_sync.observation,
        }
    ) + "</tbody></table>"


def _softphone_summary_view(report_view: SessionReportView) -> str:
    softphone = report_view.softphone
    if not softphone.configured:
        return "<p>Monitoramento do softphone nao configurado para esta sessao.</p>"
    rows = _payload_rows(
        {
            "Encontrado": _enabled(softphone.found),
            "Processo": softphone.process_name,
            "PID": softphone.pid,
            "Caminho": softphone.exe,
            "Inicio do processo": format_datetime_local_ms(softphone.started_at),
            "CPU": _percent(softphone.cpu_percent),
            "Memoria RSS": f"{softphone.rss_mb:.1f} MB" if softphone.rss_mb is not None else None,
            "Memoria percentual": _percent(softphone.memory_percent),
            "Threads": softphone.thread_count,
            "Handles": softphone.handle_count,
            "Instancias": softphone.instance_count,
            "Eventos": softphone.event_count,
            "CPU alta": softphone.high_cpu_events,
            "Memoria alta": softphone.high_memory_events,
            "Nao respondendo": softphone.not_responding_events,
        }
    )
    event_rows = "".join(
        f"<tr><td>{format_datetime_local_ms(event.occurred_at)}</td><td>{escape(event.severity)}</td>"
        f"<td>{escape(event.event_type)}</td><td>{event.pid or 'N/D'}</td><td>{escape(event.message)}</td></tr>"
        for event in softphone.events
    )
    events = (
        "<p>Nenhum evento do softphone registrado.</p>"
        if not event_rows
        else "<table><thead><tr><th>Horario</th><th>Severidade</th><th>Evento</th><th>PID</th><th>Mensagem</th></tr></thead><tbody>"
        + event_rows
        + "</tbody></table>"
    )
    limitations = "".join(f"<li>{escape(item)}</li>" for item in softphone.limitations)
    return f"<table><tbody>{rows}</tbody></table><h4>Eventos do softphone</h4>{events}<h4>Limitacoes</h4><ul>{limitations}</ul>"


def _windows_events_summary_view(report_view: SessionReportView) -> str:
    if not report_view.windows_events:
        return "<p>Nenhum evento relevante do Windows registrado ou fonte indisponivel.</p>"
    rows = "".join(
        f"<tr><td>{format_datetime_local_ms(event.occurred_at)}</td><td>{escape(event.provider)}</td>"
        f"<td>{event.windows_event_id or 'N/D'}</td><td>{escape(event.category)}</td>"
        f"<td>{escape(event.normalized_type)}</td><td>{escape(event.device_name or 'N/D')}</td>"
        f"<td>{escape(event.relevance)}</td><td>{escape(event.summary)}</td></tr>"
        for event in report_view.windows_events
    )
    return (
        "<table><thead><tr><th>Horario</th><th>Provider</th><th>ID</th><th>Categoria</th>"
        "<th>Evento</th><th>Dispositivo</th><th>Relevancia</th><th>Resumo</th></tr></thead><tbody>"
        + rows
        + "</tbody></table>"
    )


def _power_audit_summary_view(report_view: SessionReportView) -> str:
    if not report_view.power_audit:
        return "<p>Auditoria de energia nao disponivel.</p>"
    rows = "".join(
        f"<tr><td>{escape(item.item)}</td><td>{escape(item.classification)}</td>"
        f"<td>{escape(item.current_value)}</td><td>{escape(item.related_device or 'N/D')}</td>"
        f"<td>{escape(item.possible_impact)}</td><td>{escape(item.related_event or 'N/D')}</td>"
        f"<td>{escape(item.manual_guidance)}</td></tr>"
        for item in report_view.power_audit
    )
    return (
        "<table><thead><tr><th>Item</th><th>Classificacao</th><th>Valor atual</th>"
        "<th>Dispositivo</th><th>Possivel impacto</th><th>Evento relacionado</th><th>Orientacao</th></tr></thead><tbody>"
        + rows
        + "</tbody></table>"
    )


def _domain_diagnostics_summary_view(report_view: SessionReportView) -> str:
    if not report_view.domain_diagnostics:
        return "<p>Diagnostico por dominio indisponivel.</p>"
    rows = "".join(
        f"<tr><td>{escape(item.domain)}</td><td>{escape(item.status)}</td><td>{escape(item.evidence)}</td>"
        f"<td>{escape(item.likely_impact)}</td><td>{escape(item.next_validation)}</td></tr>"
        for item in report_view.domain_diagnostics
    )
    return (
        "<table><thead><tr><th>Dominio</th><th>Status</th><th>Evidencia</th><th>Impacto provavel</th>"
        "<th>Proxima validacao</th></tr></thead><tbody>"
        + rows
        + "</tbody></table>"
    )


def _route_summary_view(report_view: SessionReportView) -> str:
    if not report_view.routes:
        return "<p>Nao disponivel.</p>"
    details = []
    rows = "".join(
        _route_row(item, details)
        for item in report_view.routes
    )
    return (
        "<table><thead><tr><th>Motivo</th><th>Disponivel</th><th>Duracao</th><th>Saltos</th>"
        "<th>Saltos sem resposta</th><th>Observacao</th></tr></thead><tbody>"
        + rows + "</tbody></table>"
        + "".join(details)
    )


def _route_row(item: object, details: list[str]) -> str:
    if getattr(item, "hops", None):
        hop_rows = "".join(
            f"<tr><td>{hop.hop}</td><td>{escape(hop.address or 'N/D')}</td><td>{_ms(hop.time_1_ms)}</td>"
            f"<td>{_ms(hop.time_2_ms)}</td><td>{_ms(hop.time_3_ms)}</td><td>{escape(hop.state)}</td></tr>"
            for hop in item.hops
        )
        details.append(
            "<details><summary>Exibir detalhes tecnicos da rota</summary>"
            "<table><thead><tr><th>Salto</th><th>Endereco</th><th>Tempo 1</th><th>Tempo 2</th><th>Tempo 3</th><th>Estado</th></tr></thead><tbody>"
            + hop_rows + "</tbody></table></details>"
        )
    return (
        f"<tr><td>{escape(item.reason)}</td><td>{_enabled(item.available)}</td><td>{_seconds(item.duration_seconds)}</td>"
        f"<td>{item.hop_count}</td><td>{item.timed_out_hops}</td><td>{escape(item.note or 'nao informado')}</td></tr>"
    )


def _traffic_summary(records: list[object]) -> str:
    available = [item for item in records if item.payload.get("available")]
    if not available:
        return "<p>Nao disponivel.</p>"
    latest = available[-1].payload
    rated = [item for item in available if item.payload.get("rate_available", True)]
    peak_upload = max((item.payload.get("upload_peak_mbps") or 0 for item in rated), default=0)
    peak_download = max((item.payload.get("download_peak_mbps") or 0 for item in rated), default=0)
    return "<table><tbody>" + _payload_rows(
        {
            "Amostras": len(available),
            "Interface": latest.get("interface"),
            "Modo": latest.get("mode"),
            "Taxa atual disponivel": "sim" if latest.get("rate_available", True) else "nao, primeira amostra ou troca de interface",
            "Upload atual": _mbps(latest.get("upload_mbps")),
            "Download atual": _mbps(latest.get("download_mbps")),
            "Pico upload": f"{peak_upload:.1f} Mbps",
            "Pico download": f"{peak_download:.1f} Mbps",
        }
    ) + "</tbody></table>"


def _system_metrics_summary(records: list[object]) -> str:
    available = [item for item in records if item.payload.get("available")]
    if not available:
        return "<p>Nao disponivel.</p>"
    latest = available[-1].payload
    return "<table><tbody>" + _payload_rows(
        {
            "Amostras": len(available),
            "CPU atual": _percent(latest.get("cpu_percent")),
            "Memoria atual": _percent(latest.get("memory_used_percent")),
            "Disco atual": _percent(latest.get("disk_used_percent")),
        }
    ) + "</tbody></table>"


def _sip_options_summary(report_view: SessionReportView) -> str:
    if not report_view.sip_options:
        return "<p>Nao disponivel.</p>"
    rows = "".join(
        f"<tr><td>{format_datetime_local_ms(item.collected_at)}</td><td>{escape(item.transport)}</td>"
        f"<td>{escape(item.host)}</td><td>{item.port or 'N/D'}</td><td>{escape(item.status)}</td>"
        f"<td>{item.sip_code or 'N/D'}</td><td>{escape(item.sip_reason or 'N/D')}</td>"
        f"<td>{_ms(item.duration_ms)}</td><td>{escape(item.interpretation)}</td></tr>"
        for item in report_view.sip_options
    )
    return (
        "<table><thead><tr><th>Coleta</th><th>Transporte</th><th>Host</th><th>Porta</th><th>Status</th>"
        "<th>Codigo SIP</th><th>Motivo</th><th>Duracao</th><th>Interpretacao</th></tr></thead><tbody>"
        + rows + "</tbody></table>"
    )


def _sip_transport_summary(report_view: SessionReportView) -> str:
    if not report_view.sip_transports:
        return "<p>Nao disponivel.</p>"
    rows = "".join(
        f"<tr><td>{escape(item.transport)}</td><td>{item.port or 'N/D'}</td><td>{escape(item.status)}</td>"
        f"<td>{_ms(item.duration_ms)}</td><td>{escape(item.certificate)}</td><td>{escape(item.observation)}</td></tr>"
        for item in report_view.sip_transports
    )
    return (
        "<table><thead><tr><th>Transporte</th><th>Porta</th><th>Status</th><th>Duracao</th>"
        "<th>Certificado</th><th>Observacao</th></tr></thead><tbody>" + rows + "</tbody></table>"
    )


def _udp_flow_summary(records: list[object]) -> str:
    latest = _latest(records)
    if not latest:
        return "<p>Nao disponivel.</p>"
    payload = latest.payload
    return "<table><tbody>" + _payload_rows(
        {
            "Ultima coleta": format_datetime_local_ms(latest.collected_at),
            "Status": payload.get("status"),
            "Pacotes enviados": payload.get("packets_sent"),
            "Pacotes recebidos": payload.get("packets_received"),
            "Perda UDP": _percent(payload.get("packet_loss_percent")),
            "Jitter UDP": _ms(payload.get("jitter_ms")),
            "Mensagem": payload.get("message") or payload.get("error"),
        }
    ) + "</tbody></table>"


def _voice_quality_summary(records: list[object]) -> str:
    latest = _latest(records)
    if not latest:
        return "<p>Nao disponivel.</p>"
    payload = latest.payload
    reasons = payload.get("reasons")
    if isinstance(reasons, list):
        reasons = "; ".join(str(item) for item in reasons)
    return "<table><tbody>" + _payload_rows(
        {
            "Ultima coleta": format_datetime_local_ms(latest.collected_at),
            "Estado": payload.get("state"),
            "Pontuacao": payload.get("score"),
            "Motivos": reasons,
            "Nota": payload.get("note"),
        }
    ) + "</tbody></table>"


def _time_sync_summary(records: list[object]) -> str:
    latest = _latest(records)
    if not latest:
        return "<p>Nao disponivel.</p>"
    payload = latest.payload
    windows_time = payload.get("windows_time") if isinstance(payload.get("windows_time"), dict) else {}
    return "<table><tbody>" + _payload_rows(
        {
            "Hora local": payload.get("local_time"),
            "Fuso": payload.get("timezone"),
            "Windows Time disponivel": _enabled(windows_time.get("available") if isinstance(windows_time, dict) else None),
            "Origem": windows_time.get("source") if isinstance(windows_time, dict) else None,
            "Ultima sincronizacao": windows_time.get("last_successful_sync") if isinstance(windows_time, dict) else None,
        }
    ) + "</tbody></table>"


def _wifi_summary(records: list[object]) -> str:
    latest = _latest(records)
    if not latest or not latest.payload.get("available"):
        return "<p>Nao disponivel ou sem interface Wi-Fi ativa.</p>"
    payload = latest.payload
    return "<table><tbody>" + _payload_rows(
        {
            "SSID": payload.get("ssid"),
            "Estado": payload.get("state"),
            "Conectado": _enabled(payload.get("connected")),
            "Sinal": _percent(payload.get("signal_percent")),
            "Radio": payload.get("radio_type"),
            "Canal": payload.get("channel"),
            "Recepcao": _mbps(payload.get("receive_rate_mbps")),
            "Transmissao": _mbps(payload.get("transmit_rate_mbps")),
            "BSSID": payload.get("bssid_masked"),
        }
    ) + "</tbody></table>"


def _route_summary(records: list[object]) -> str:
    latest = _latest(records)
    if not latest:
        return "<p>Nao disponivel.</p>"
    payload = latest.payload
    hops = payload.get("hops") if isinstance(payload.get("hops"), list) else []
    timed_out = sum(1 for hop in hops if isinstance(hop, dict) and hop.get("timeout"))
    return "<table><tbody>" + _payload_rows(
        {
            "Disponivel": _enabled(payload.get("available")),
            "Duracao": _seconds(payload.get("duration_seconds")),
            "Saltos": len(hops),
            "Saltos sem resposta": timed_out,
            "Observacao": payload.get("note"),
        }
    ) + "</tbody></table>"


def _public_ip_summary(records: list[object]) -> str:
    latest = _latest(records)
    if not latest:
        return "<p>Nao disponivel.</p>"
    payload = latest.payload
    attempts = payload.get("attempts") if isinstance(payload.get("attempts"), list) else []
    ok = sum(1 for item in attempts if isinstance(item, dict) and item.get("status") == "ok")
    return "<table><tbody>" + _payload_rows(
        {
            "IPv4 publico": payload.get("ipv4"),
            "IPv6 publico": payload.get("ipv6"),
            "Provedores consultados": len(attempts),
            "Consultas bem-sucedidas": ok,
            "Possivel CGNAT": _enabled(payload.get("possible_cgnat")),
            "Observacao": payload.get("note"),
        }
    ) + "</tbody></table>"


def _network_environment_summary(records: list[object]) -> str:
    latest = _latest(records)
    if not latest:
        return "<p>Nao disponivel.</p>"
    payload = latest.payload
    virtual = payload.get("virtual_adapters") if isinstance(payload.get("virtual_adapters"), list) else []
    proxy = payload.get("proxy") if isinstance(payload.get("proxy"), dict) else {}
    return "<table><tbody>" + _payload_rows(
        {
            "VPN detectada": _enabled(payload.get("vpn_detected")),
            "Adaptadores virtuais": "; ".join(str(item) for item in virtual) if virtual else "nenhum",
            "Proxy WinHTTP": _enabled(proxy.get("enabled") if isinstance(proxy, dict) else None),
        }
    ) + "</tbody></table>"


def _interruptions_table(interruptions: list[InterruptionReportView]) -> str:
    if not interruptions:
        return "<p>Nenhuma interrupcao detectada.</p>"
    rows = []
    for item in interruptions:
        css = "critical" if item.no_recovery_observed else ""
        rows.append(
            f"<tr class='{css}'><td>{escape(item.target_name)}</td><td>{escape(item.status)}</td>"
            f"<td>{format_datetime_local(item.started_at)}</td>"
            f"<td>{format_datetime_local(item.ended_at)}</td><td>{_seconds(item.duration_seconds)}</td>"
            f"<td>{item.lost_tests}</td><td>{item.max_consecutive_failures}</td><td>{escape(item.message)}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Destino</th><th>Status</th><th>Inicio</th><th>Fim</th><th>Duracao</th>"
        "<th>Testes perdidos</th><th>Maior sequencia</th><th>Observacao</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _correlation_html(report_view: SessionReportView) -> str:
    conclusion = report_view.correlation.conclusion
    rows = _payload_rows(
        {
            "Conclusao": conclusion.result,
            "Origem provavel": conclusion.likely_origin,
            "Confianca": conclusion.confidence.value.upper(),
        }
    )
    evidence = "".join(f"<li>{escape(item)}</li>" for item in conclusion.evidences) or "<li>Nenhuma evidencia especifica.</li>"
    consistency = "".join(f"<li>{escape(item)}</li>" for item in report_view.correlation.consistency_findings) or "<li>Nenhuma contradicao interna detectada.</li>"
    recommendations = "".join(f"<li>{escape(item)}</li>" for item in conclusion.recommendations) or "<li>Sem recomendacoes automaticas.</li>"
    return (
        f"<table><tbody>{rows}</tbody></table>"
        f"<h3>Evidencias</h3><ul>{evidence}</ul>"
        f"<h3>Consistencia</h3><ul>{consistency}</ul>"
        f"<h3>Recomendacoes</h3><ul>{recommendations}</ul>"
    )


def _marker_images(marks: list[StoredCustomerMark]) -> str:
    return "".join(
        f'<img src="marcacao_{mark.mark_id}_detalhe.png" alt="Contexto da ocorrencia registrada pelo cliente {index}">'
        for index, mark in enumerate(marks, start=1)
    )


def _customer_marker_summary_html(markers: list[MarkerReportView]) -> str:
    if not markers:
        return "<div class='customer-marker-summary'><strong>Ocorrencias do cliente:</strong> nenhuma registrada.</div>"
    links = " ".join(
        f"<a href='#{escape(marker.anchor_id)}'>#{marker.sequence_number}</a>"
        for marker in markers
    )
    return (
        "<div class='customer-marker-summary'>"
        f"<strong>Ocorrencias registradas pelo cliente:</strong> {len(markers)} "
        f"| Correlacoes fortes: {sum(1 for item in markers if item.correlation_level == 'strong')} "
        f"| Acessos rapidos: {links}"
        "</div>"
    )


def _nearby_events_table(events: list[dict[str, object]]) -> str:
    if not events:
        return "<p>Nenhum evento automatico no contexto da marcacao.</p>"
    rows = "".join(
        f"<tr><td>{escape(str(event.get('occurred_at') or 'nao disponivel'))}</td>"
        f"<td>{escape(str(event.get('severity') or 'info'))}</td>"
        f"<td>{escape(str(event.get('event_type') or 'evento'))}</td>"
        f"<td>{escape(str(event.get('target_name') or 'N/D'))}</td>"
        f"<td>{escape(str(event.get('message') or ''))}</td></tr>"
        for event in events[:30]
    )
    return (
        "<table><thead><tr><th>Horario</th><th>Severidade</th><th>Tipo</th><th>Destino</th><th>Mensagem</th></tr></thead><tbody>"
        + rows
        + "</tbody></table>"
    )


def _ms(value: float | None) -> str:
    return "n/d" if value is None else f"{value:.0f} ms"


def _seconds(value: float | None) -> str:
    return "n/d" if value is None else f"{value:.1f} s"


def _percent(value: object) -> str:
    if value is None:
        return "nao disponivel"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return f"{value}%"


def _mbps(value: object) -> str:
    if value is None:
        return "nao disponivel"
    try:
        return f"{float(value):.1f} Mbps"
    except (TypeError, ValueError):
        return str(value)


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _anomaly_text(seconds: float | None, target: str | None) -> str:
    if seconds is None or not target:
        return "nao detectada"
    return f"aproximadamente {seconds:.0f}s em {escape(target)}"


def _latest(records: list[object]) -> object | None:
    return records[-1] if records else None


def _payload_rows(payload: dict[str, object]) -> str:
    return "".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(_display_value(value))}</td></tr>"
        for key, value in payload.items()
    )


def _display_value(value: object) -> str:
    if value in (None, ""):
        return "nao disponivel"
    if isinstance(value, dict):
        available = value.get("available")
        status = value.get("status")
        if available is not None or status is not None:
            parts = []
            if available is not None:
                parts.append(f"disponivel={_enabled(available)}")
            if status is not None:
                parts.append(f"status={status}")
            return ", ".join(parts)
        return f"dados estruturados com {len(value)} campos"
    if isinstance(value, list):
        if not value:
            return "nenhum"
        if all(not isinstance(item, (dict, list, tuple, set)) for item in value):
            return "; ".join(str(item) for item in value)
        return f"{len(value)} itens estruturados"
    return str(value)


def _nested(payload: dict[str, object], path: str) -> object:
    current: object = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _enabled(value: object) -> str:
    if value is True:
        return "detectado"
    if value is False:
        return "nao detectado"
    return "nao disponivel"


def _render_with_jinja(**context: object) -> str | None:
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except Exception:
        return None
    template_dir = Path(__file__).resolve().parent / "templates"
    template_path = template_dir / "report.html.j2"
    if not template_path.exists():
        return None
    environment = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "xml"]),
    )
    return environment.get_template("report.html.j2").render(**context)
