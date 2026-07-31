"""Cautious audio evidence classification."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.audio.audio_models import AudioEvent, AudioEventType, AudioInventory, MicrophoneTestResult, MicrophoneTestState


def classify_audio_context(
    inventory: AudioInventory | None,
    recent_events: list[AudioEvent],
    microphone_test: MicrophoneTestResult | None = None,
    marked_at: datetime | None = None,
) -> dict[str, Any]:
    """Build cautious audio conclusion for report correlation."""
    evidences: list[str] = []
    recommendations: list[str] = []
    likely_origin = "audio sem anomalia detectada"
    confidence = "baixa"

    nearby_events = _nearby_events(recent_events, marked_at)
    if any(event.event_type in {AudioEventType.AUDIO_INPUT_DISCONNECTED, AudioEventType.AUDIO_OUTPUT_DISCONNECTED} for event in nearby_events):
        likely_origin = "dispositivo de audio desconectado"
        confidence = "media"
        evidences.append("Houve desconexao de dispositivo de audio proxima da ocorrencia.")
        recommendations.append("Validar cabo USB/P2, Bluetooth, energia e driver do headset.")
    elif any(event.event_type in {AudioEventType.DEFAULT_INPUT_CHANGED, AudioEventType.DEFAULT_OUTPUT_CHANGED, AudioEventType.COMMUNICATION_INPUT_CHANGED, AudioEventType.COMMUNICATION_OUTPUT_CHANGED} for event in nearby_events):
        likely_origin = "dispositivo padrao alterado"
        confidence = "media"
        evidences.append("Houve troca de dispositivo padrao ou de comunicacao proxima da ocorrencia.")
        recommendations.append("Conferir dispositivos padrao de comunicacao no Windows e no softphone.")

    if microphone_test:
        if microphone_test.state == MicrophoneTestState.NO_SIGNAL:
            likely_origin = "microfone sem sinal"
            confidence = "media"
            evidences.append("Teste guiado abriu o microfone, mas nao detectou sinal suficiente.")
        elif microphone_test.state == MicrophoneTestState.MUTED:
            likely_origin = "microfone no mudo"
            confidence = "alta"
            evidences.append("Microfone estava no mudo durante o teste guiado.")
        elif microphone_test.state == MicrophoneTestState.FUNCTIONAL:
            evidences.append("Teste guiado de microfone detectou sinal tecnico.")

    driver_errors = []
    if inventory:
        driver_errors = [device for device in inventory.devices if device.pnp_error_code not in (None, 0)]
    if driver_errors:
        likely_origin = "erro de driver de audio"
        confidence = "media"
        evidences.append(f"{len(driver_errors)} dispositivo(s) de audio com codigo de erro do Windows.")

    return {
        "likely_origin": likely_origin,
        "confidence": confidence,
        "evidences": evidences or ["Nao foram detectadas alteracoes relevantes de audio no intervalo analisado."],
        "recommendations": recommendations,
        "limitations": [
            "O modulo nao grava chamadas, nao transcreve fala e nao comprova defeito fisico sem validacao externa.",
            "Silencio durante monitoramento continuo nao e classificado automaticamente como defeito.",
        ],
    }


def _nearby_events(events: list[AudioEvent], marked_at: datetime | None) -> list[AudioEvent]:
    if marked_at is None:
        return events
    return [
        event for event in events
        if abs((event.occurred_at - marked_at).total_seconds()) <= 60
    ]
