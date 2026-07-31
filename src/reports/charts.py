"""Chart generation for monitoring reports."""

from __future__ import annotations

import base64
from pathlib import Path

from src.reports.customer_markers import (
    CUSTOMER_MARKER_COLOR,
    CUSTOMER_MARKER_EDGE_COLOR,
    CUSTOMER_MARKER_LINESTYLE,
    CUSTOMER_MARKER_ZORDER,
    is_customer_marker_event,
)
from src.storage.models import EventRecord, InterruptionRecord, MeasurementRecord, StoredCustomerMark

_EMPTY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lK3Q6wAAAABJRU5ErkJggg=="
)


def generate_charts(
    measurements: list[MeasurementRecord],
    output_dir: Path,
    events: list[EventRecord] | None = None,
    marks: list[StoredCustomerMark] | None = None,
    interruptions: list[InterruptionRecord] | None = None,
) -> dict[str, Path]:
    """Generate report charts with timeline markers."""
    events = events or []
    marks = marks or []
    interruptions = interruptions or []
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "latency": output_dir / "grafico_latencia.png",
        "loss": output_dir / "grafico_perda.png",
        "jitter": output_dir / "grafico_jitter.png",
        "availability": output_dir / "grafico_disponibilidade.png",
        "timeline": output_dir / "linha_tempo_eventos.png",
    }
    try:
        import matplotlib

        matplotlib.use("Agg")
        from matplotlib import pyplot as plt
    except Exception:
        for path in paths.values():
            path.write_bytes(_EMPTY_PNG)
        return paths

    grouped: dict[str, list[MeasurementRecord]] = {}
    for measurement in measurements:
        grouped.setdefault(measurement.target_name, []).append(measurement)

    _plot_latency(plt, grouped, paths["latency"], events, marks, interruptions)
    _plot_loss(plt, grouped, paths["loss"])
    _plot_jitter(plt, grouped, paths["jitter"])
    _plot_availability(plt, grouped, paths["availability"])
    _plot_timeline(plt, events, marks, paths["timeline"])
    for mark in marks:
        path = output_dir / f"marcacao_{mark.mark_id}_detalhe.png"
        paths[f"mark_{mark.mark_id}"] = path
        _plot_marker_window(plt, grouped, mark, path)
    return paths


def generate_diagnostic_charts(records_by_table: dict[str, list[object]], output_dir: Path) -> dict[str, Path]:
    """Generate charts for optional diagnostic records."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "traffic": output_dir / "grafico_trafego.png",
        "system": output_dir / "grafico_sistema.png",
        "wifi": output_dir / "grafico_wifi.png",
        "voice": output_dir / "grafico_qualidade_voz.png",
    }
    try:
        import matplotlib

        matplotlib.use("Agg")
        from matplotlib import pyplot as plt
    except Exception:
        for path in paths.values():
            path.write_bytes(_EMPTY_PNG)
        return paths
    _plot_traffic(plt, records_by_table.get("interface_traffic", []), paths["traffic"])
    _plot_system(plt, records_by_table.get("system_metrics", []), paths["system"])
    _plot_wifi_signal(plt, records_by_table.get("wifi_metrics", []), paths["wifi"])
    _plot_voice_quality(plt, records_by_table.get("voice_quality_results", []), paths["voice"])
    return paths


def _plot_traffic(plt: object, records: list[object], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4))
    usable = [
        item for item in records
        if item.payload.get("available")
        and item.payload.get("rate_available", True)
        and item.payload.get("upload_mbps") is not None
        and item.payload.get("download_mbps") is not None
    ]
    if usable:
        x = [item.collected_at for item in usable]
        upload = [item.payload.get("upload_mbps") for item in usable]
        download = [item.payload.get("download_mbps") for item in usable]
        ax.plot(x, upload, label="Upload Mbps")
        ax.plot(x, download, label="Download Mbps")
        ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "Sem dados de trafego", ha="center", va="center")
    ax.set_title("Upload e download")
    ax.set_ylabel("Mbps")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _plot_system(plt: object, records: list[object], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4))
    x = [item.collected_at for item in records if item.payload.get("available")]
    cpu = [item.payload.get("cpu_percent") or 0 for item in records if item.payload.get("available")]
    memory = [item.payload.get("memory_used_percent") or 0 for item in records if item.payload.get("available")]
    disk = [item.payload.get("disk_used_percent") or 0 for item in records if item.payload.get("available")]
    if x:
        ax.plot(x, cpu, label="CPU %")
        ax.plot(x, memory, label="Memoria %")
        ax.plot(x, disk, label="Disco %")
        ax.set_ylim(0, 100)
        ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "Sem dados de sistema", ha="center", va="center")
    ax.set_title("CPU, memoria e disco")
    ax.set_ylabel("%")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _plot_wifi_signal(plt: object, records: list[object], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4))
    filtered = [item for item in records if item.payload.get("signal_percent") is not None]
    if filtered:
        ax.plot([item.collected_at for item in filtered], [item.payload.get("signal_percent") for item in filtered], label="Sinal Wi-Fi")
        ax.set_ylim(0, 100)
        ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "Sem dados Wi-Fi", ha="center", va="center")
    ax.set_title("Sinal Wi-Fi")
    ax.set_ylabel("%")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _plot_voice_quality(plt: object, records: list[object], path: Path) -> None:
    score_by_state = {
        "EXCELENTE": 5,
        "BOA": 4,
        "ATENCAO": 3,
        "DEGRADADA": 2,
        "CRITICA": 1,
        "DADOS INSUFICIENTES": 0,
        "DADOS INSUFICIENTES PARA AVALIACAO RTP": 0,
    }
    fig, ax = plt.subplots(figsize=(10, 4))
    x = [item.collected_at for item in records]
    y = [score_by_state.get(str(item.payload.get("state")), 0) for item in records]
    if x:
        ax.step(x, y, where="post")
        ax.set_yticks(list(score_by_state.values()), list(score_by_state.keys()))
    else:
        ax.text(0.5, 0.5, "Sem classificacao de voz", ha="center", va="center")
    ax.set_title("Qualidade estimada para voz")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _plot_latency(
    plt: object,
    grouped: dict[str, list[MeasurementRecord]],
    path: Path,
    events: list[EventRecord],
    marks: list[StoredCustomerMark],
    interruptions: list[InterruptionRecord],
) -> None:
    fig, ax = plt.subplots(figsize=(10, 4))
    for target, values in grouped.items():
        x = [item.collected_at for item in values if item.latency_ms is not None]
        y = [item.latency_ms for item in values if item.latency_ms is not None]
        if x:
            ax.plot(x, y, label=target, linewidth=1.4)
    ax.set_title("Latencia por destino")
    ax.set_ylabel("ms")
    ax.grid(True, alpha=0.3)
    if grouped:
        ax.legend(fontsize=7)
    _add_markers(ax, events, marks, interruptions)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _plot_loss(plt: object, grouped: dict[str, list[MeasurementRecord]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4))
    targets = list(grouped)
    loss_values = []
    for values in grouped.values():
        failures = sum(1 for item in values if item.status == "offline")
        loss_values.append((failures / len(values)) * 100 if values else 0)
    ax.bar(targets, loss_values, color="#B42318")
    ax.set_title("Falhas/perda por destino")
    ax.set_ylabel("%")
    ax.tick_params(axis="x", labelrotation=30)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _plot_jitter(plt: object, grouped: dict[str, list[MeasurementRecord]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4))
    targets = []
    jitter_values = []
    for target, values in grouped.items():
        if _is_connection_style_target(target):
            continue
        latencies = [item.latency_ms for item in values if item.latency_ms is not None]
        if len(latencies) < 2:
            continue
        deltas = [abs(current - previous) for previous, current in zip(latencies, latencies[1:], strict=False)]
        targets.append(target)
        jitter_values.append(sum(deltas) / len(deltas))
    ax.bar(targets, jitter_values, color="#0B5CAD")
    ax.set_title("Jitter estimado por destino ICMP/UDP")
    ax.set_ylabel("ms")
    ax.tick_params(axis="x", labelrotation=30)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _plot_availability(plt: object, grouped: dict[str, list[MeasurementRecord]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4))
    targets = list(grouped)
    values = []
    for records in grouped.values():
        known = [item for item in records if item.status in {"online", "degraded", "offline"}]
        successes = sum(1 for item in known if item.status in {"online", "degraded"})
        values.append((successes / len(known)) * 100 if known else 0)
    ax.bar(targets, values, color="#1F7A4D")
    ax.set_title("Disponibilidade por destino")
    ax.set_ylabel("%")
    ax.set_ylim(0, 100)
    ax.tick_params(axis="x", labelrotation=30)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _plot_timeline(plt: object, events: list[EventRecord], marks: list[StoredCustomerMark], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 3))
    timeline = sorted([(event.occurred_at, event.severity.value, event.event_type, is_customer_marker_event(event)) for event in events])
    if not timeline and not marks:
        ax.text(0.5, 0.5, "Sem eventos", ha="center", va="center")
        ax.set_axis_off()
    else:
        for index, (timestamp, severity, event_type, customer_marker) in enumerate(timeline[:80]):
            color = CUSTOMER_MARKER_COLOR if customer_marker else {"critical": "#B42318", "warning": "#9A6700", "recovery": "#1F7A4D", "user_marker": CUSTOMER_MARKER_COLOR}.get(severity, "#57606A")
            ax.scatter(timestamp, index % 8, color=color, s=30)
            if severity in {"critical", "user_marker"} or customer_marker:
                label = "Cliente" if customer_marker else event_type[:18]
                ax.text(timestamp, (index % 8) + 0.2, label, fontsize=7, rotation=30, color=color)
        for sequence, mark in enumerate(_sorted_marks(marks), start=1):
            ax.axvline(
                mark.marked_at,
                color=CUSTOMER_MARKER_COLOR,
                linestyle=CUSTOMER_MARKER_LINESTYLE,
                linewidth=2.4,
                alpha=0.95,
                zorder=CUSTOMER_MARKER_ZORDER,
            )
            ax.text(mark.marked_at, 7.2, f"Cliente #{sequence}", fontsize=7, rotation=30, color=CUSTOMER_MARKER_EDGE_COLOR)
        ax.set_title("Linha do tempo de eventos")
        ax.set_yticks([])
        ax.grid(True, axis="x", alpha=0.3)
        fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _plot_marker_window(plt: object, grouped: dict[str, list[MeasurementRecord]], mark: StoredCustomerMark, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4))
    before = int(mark.payload.get("context_before_seconds", 60))
    after = int(mark.payload.get("context_after_seconds", 60))
    start = mark.marked_at.timestamp() - before
    end = mark.marked_at.timestamp() + after
    for target, values in grouped.items():
        filtered = [
            item
            for item in values
            if item.latency_ms is not None and start <= item.collected_at.timestamp() <= end
        ]
        if filtered:
            ax.plot([item.collected_at for item in filtered], [item.latency_ms for item in filtered], label=target)
    ax.axvline(
        mark.marked_at,
        color=CUSTOMER_MARKER_COLOR,
        linestyle=CUSTOMER_MARKER_LINESTYLE,
        linewidth=2.8,
        label="Ocorrencia registrada pelo cliente",
        zorder=CUSTOMER_MARKER_ZORDER,
    )
    ax.set_title(f"Contexto da ocorrencia do cliente {mark.mark_id}")
    ax.set_ylabel("ms")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _add_markers(
    ax: object,
    events: list[EventRecord],
    marks: list[StoredCustomerMark],
    interruptions: list[InterruptionRecord],
) -> None:
    shown = set()
    for mark in _sorted_marks(marks)[:20]:
        label = "Ocorrencia do cliente" if "mark" not in shown else None
        ax.axvline(
            mark.marked_at,
            color=CUSTOMER_MARKER_COLOR,
            linestyle=CUSTOMER_MARKER_LINESTYLE,
            linewidth=2.4,
            alpha=0.95,
            label=label,
            zorder=CUSTOMER_MARKER_ZORDER,
        )
        shown.add("mark")
    priority = [event for event in events if event.severity.value in {"critical", "recovery"}][:30]
    for event in priority:
        color = "#B42318" if event.severity.value == "critical" else "#1F7A4D"
        label = event.severity.value if event.severity.value not in shown else None
        ax.axvline(event.occurred_at, color=color, linestyle="--", linewidth=1, alpha=0.5, label=label)
        shown.add(event.severity.value)
    for interruption in interruptions[:20]:
        if interruption.ended_at:
            ax.axvspan(interruption.started_at, interruption.ended_at, color="#B42318", alpha=0.08)


def _is_connection_style_target(target_name: str) -> bool:
    upper = target_name.upper()
    return " TCP" in upper or " TLS" in upper or " DNS" in upper


def _sorted_marks(marks: list[StoredCustomerMark]) -> list[StoredCustomerMark]:
    return sorted(marks, key=lambda item: (item.marked_at, item.mark_id))
