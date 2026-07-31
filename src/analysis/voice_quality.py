"""Estimated voice quality classification."""

from __future__ import annotations

from typing import Any

from src.storage.models import TargetMetricsSummary


def classify_voice_quality(
    summaries: list[TargetMetricsSummary],
    traffic_payload: dict[str, Any] | None = None,
    wifi_payload: dict[str, Any] | None = None,
    udp_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify voice quality from available technical metrics without exact MOS claims."""
    voice_summaries = [summary for summary in summaries if _usable_for_voice_quality(summary)]
    if not summaries and not udp_payload and not wifi_payload and not traffic_payload:
        return {
            "state": "DADOS INSUFICIENTES PARA AVALIACAO RTP",
            "reasons": ["Sem metricas ICMP/UDP/Wi-Fi/trafego suficientes."],
            "note": "Falhas TCP nao sao perda RTP e nao permitem inferir qualidade real de audio isoladamente.",
        }
    reasons: list[str] = []
    score = 0
    max_jitter = _max_value(voice_summaries, "jitter_ms")
    max_loss = _max_value(voice_summaries, "packet_loss_percent")
    max_p95 = _max_value(voice_summaries, "latency_p95_ms")
    max_consecutive = max((item.consecutive_failures for item in voice_summaries), default=0)
    if max_jitter is not None and max_jitter >= 60:
        score += 3
        reasons.append(f"jitter critico ({max_jitter:.0f} ms)")
    elif max_jitter is not None and max_jitter >= 30:
        score += 2
        reasons.append(f"jitter elevado ({max_jitter:.0f} ms)")
    if max_loss is not None and max_loss >= 3:
        score += 3
        reasons.append(f"perda critica ({max_loss:.1f}%)")
    elif max_loss is not None and max_loss >= 1:
        score += 2
        reasons.append(f"perda em atencao ({max_loss:.1f}%)")
    if max_p95 is not None and max_p95 >= 300:
        score += 2
        reasons.append(f"P95 de latencia alto ({max_p95:.0f} ms)")
    elif max_p95 is not None and max_p95 >= 150:
        score += 1
        reasons.append(f"P95 de latencia em atencao ({max_p95:.0f} ms)")
    if max_consecutive >= 4:
        score += 2
        reasons.append(f"{max_consecutive} falhas consecutivas")
    if traffic_payload and (traffic_payload.get("upload_mbps") or 0) >= 10:
        score += 1
        reasons.append("pico de upload proximo da coleta")
    signal = (wifi_payload or {}).get("signal_percent")
    if isinstance(signal, int) and signal < 45:
        score += 1
        reasons.append(f"sinal Wi-Fi baixo ({signal}%)")
    if udp_payload and udp_payload.get("packet_loss_percent") is not None:
        udp_loss = float(udp_payload["packet_loss_percent"])
        if udp_loss >= 3:
            score += 3
            reasons.append(f"perda UDP elevada ({udp_loss:.1f}%)")
    if not voice_summaries and udp_payload and udp_payload.get("packet_loss_percent") is None:
        reasons.append("teste UDP sem retorno; mede envio, mas nao confirma perda RTP")
    if summaries and not voice_summaries:
        reasons.append("testes TCP/DNS ignorados para qualidade de voz direta")
    if score >= 7:
        state = "CRITICA"
    elif score >= 5:
        state = "DEGRADADA"
    elif score >= 3:
        state = "ATENCAO"
    elif score >= 1:
        state = "BOA"
    else:
        state = "EXCELENTE"
        reasons.append("metricas disponiveis dentro dos limites configurados")
    return {
        "state": state,
        "score": score,
        "reasons": reasons,
        "note": "Estimativa tecnica baseada nas metricas ICMP/UDP/Wi-Fi/trafego disponiveis. Nao representa analise de uma chamada RTP real.",
    }


def _max_value(summaries: list[TargetMetricsSummary], field_name: str) -> float | None:
    values = [getattr(item, field_name) for item in summaries if getattr(item, field_name) is not None]
    return max(values) if values else None


def _usable_for_voice_quality(summary: TargetMetricsSummary) -> bool:
    name = summary.target_name.upper()
    if " TCP" in name or " TLS" in name or " DNS" in name:
        return False
    return True
