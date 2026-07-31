"""Guided microphone level test. Raw audio is not persisted."""

from __future__ import annotations

from datetime import UTC, datetime

from src.audio.audio_models import MicrophoneTestResult, MicrophoneTestState


def run_microphone_test(
    device_id: str | None = None,
    duration_seconds: float = 5.0,
    sample_rate: int = 16_000,
    silence_threshold: float = 0.01,
    low_level_threshold: float = 0.03,
    saturation_threshold: float = 0.98,
) -> MicrophoneTestResult:
    """Capture a short explicit test and return aggregate levels only."""
    started = datetime.now(UTC)
    try:
        import numpy as np
        import sounddevice as sd
    except Exception as exc:
        return _failed(started, device_id, MicrophoneTestState.DEVICE_UNAVAILABLE, f"Dependencia de audio indisponivel: {exc}", duration_seconds)

    device_index = _device_index(device_id)
    frames = int(duration_seconds * sample_rate)
    try:
        recording = sd.rec(frames, samplerate=sample_rate, channels=1, dtype="float32", device=device_index)
        sd.wait()
    except Exception as exc:
        message = str(exc)
        state = MicrophoneTestState.PERMISSION_BLOCKED if "permission" in message.lower() else MicrophoneTestState.DEVICE_UNAVAILABLE
        if "exclusive" in message.lower() or "busy" in message.lower():
            state = MicrophoneTestState.EXCLUSIVE_USE
        return _failed(started, device_id, state, message, duration_seconds)

    samples = np.asarray(recording, dtype="float32").reshape(-1)
    if samples.size == 0:
        return _failed(started, device_id, MicrophoneTestState.INSUFFICIENT_DATA, "Nenhum frame capturado.", duration_seconds)
    absolute = np.abs(samples)
    rms = float(np.sqrt(np.mean(samples * samples)))
    average = float(np.mean(absolute))
    peak = float(np.max(absolute))
    silence_percent = float(np.mean(absolute < silence_threshold) * 100)
    clipping = bool(np.any(absolute >= 1.0))
    saturation = bool(peak >= saturation_threshold)
    signal = rms >= silence_threshold
    if saturation or clipping:
        state = MicrophoneTestState.SATURATION
    elif not signal:
        state = MicrophoneTestState.NO_SIGNAL
    elif rms < low_level_threshold:
        state = MicrophoneTestState.VERY_LOW_LEVEL
    else:
        state = MicrophoneTestState.FUNCTIONAL
    return MicrophoneTestResult(
        started_at=started,
        device_id=device_id,
        device_name=_device_name(device_id),
        duration_seconds=duration_seconds,
        frames=int(samples.size),
        rms=rms,
        average_level=average,
        peak=peak,
        silence_percent=silence_percent,
        saturation=saturation,
        clipping=clipping,
        signal_detected=signal,
        opened=True,
        state=state,
        format_used=f"float32 mono {sample_rate}Hz",
    )


def _failed(
    started: datetime,
    device_id: str | None,
    state: MicrophoneTestState,
    error: str,
    duration_seconds: float,
) -> MicrophoneTestResult:
    return MicrophoneTestResult(
        started_at=started,
        device_id=device_id,
        device_name=_device_name(device_id),
        duration_seconds=duration_seconds,
        frames=0,
        rms=None,
        average_level=None,
        peak=None,
        silence_percent=None,
        saturation=False,
        clipping=False,
        signal_detected=None,
        opened=False,
        state=state,
        format_used=None,
        error=error,
    )


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
