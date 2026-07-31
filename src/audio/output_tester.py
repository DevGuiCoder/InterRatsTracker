"""Guided output playback test."""

from __future__ import annotations

from datetime import UTC, datetime
from math import pi, sin

from src.audio.audio_models import OutputTestResult


def run_output_test(
    device_id: str | None = None,
    user_confirmation: str | None = None,
    channel: str = "stereo",
    duration_seconds: float = 0.7,
    sample_rate: int = 44_100,
    volume: float = 0.12,
) -> OutputTestResult:
    """Play a short safe tone when explicitly requested by the operator."""
    started = datetime.now(UTC)
    device_index = _device_index(device_id)
    try:
        import numpy as np
        import sounddevice as sd
    except Exception as exc:
        return OutputTestResult(
            started_at=started,
            device_id=device_id,
            device_name=_device_name(device_id),
            stream_accepted=False,
            user_confirmation=user_confirmation,
            left_channel_tested=channel in {"left", "stereo"},
            right_channel_tested=channel in {"right", "stereo"},
            volume_percent=None,
            muted=None,
            result="DISPOSITIVO INDISPONIVEL",
            error=f"Dependencia de audio indisponivel: {exc}",
        )
    frames = int(duration_seconds * sample_rate)
    t = np.arange(frames) / sample_rate
    tone = (np.sin(2 * pi * 880 * t) * volume).astype("float32")
    stereo = np.zeros((frames, 2), dtype="float32")
    if channel in {"left", "stereo"}:
        stereo[:, 0] = tone
    if channel in {"right", "stereo"}:
        stereo[:, 1] = tone
    try:
        sd.play(stereo, samplerate=sample_rate, device=device_index)
        sd.wait()
        accepted = True
        error = None
    except Exception as exc:
        accepted = False
        error = str(exc)
    return OutputTestResult(
        started_at=started,
        device_id=device_id,
        device_name=_device_name(device_id),
        stream_accepted=accepted,
        user_confirmation=user_confirmation,
        left_channel_tested=channel in {"left", "stereo"},
        right_channel_tested=channel in {"right", "stereo"},
        volume_percent=None,
        muted=None,
        result=_result_label(accepted, user_confirmation),
        error=error,
    )


def _result_label(accepted: bool, user_confirmation: str | None) -> str:
    if not accepted:
        return "FALHA TECNICA NA REPRODUCAO"
    if not user_confirmation:
        return "FLUXO ACEITO, AGUARDANDO CONFIRMACAO DO USUARIO"
    if user_confirmation == "OUVI CORRETAMENTE":
        return "REPRODUCAO CONFIRMADA PELO USUARIO"
    return "REPRODUCAO ACEITA PELO WINDOWS, MAS USUARIO RELATOU PROBLEMA"


def _device_index(device_id: str | None) -> int | None:
    if not device_id or not device_id.startswith("sounddevice:"):
        return None
    try:
        return int(device_id.split(":", 2)[1])
    except (IndexError, ValueError):
        return None


def _device_name(device_id: str | None) -> str | None:
    if not device_id:
        return None
    if device_id.startswith("sounddevice:"):
        parts = device_id.split(":", 2)
        return parts[2] if len(parts) >= 3 else device_id
    return device_id
