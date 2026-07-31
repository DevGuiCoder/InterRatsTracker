"""Optional microphone level sampling without storing raw audio."""

from __future__ import annotations

from datetime import UTC, datetime

from src.audio.audio_models import AudioLevelMetric
from src.audio.microphone_tester import run_microphone_test


class AudioLevelMonitor:
    """Low-frequency aggregate microphone level sampler."""

    def __init__(self, silence_threshold: float = 0.01, saturation_threshold: float = 0.98) -> None:
        self._silence_threshold = silence_threshold
        self._saturation_threshold = saturation_threshold
        self._continuous_silence_seconds = 0.0
        self._saturation_seconds = 0.0

    def sample(self, device_id: str | None, window_seconds: float = 0.25) -> AudioLevelMetric:
        """Collect one short aggregate level sample when enabled by config."""
        result = run_microphone_test(
            device_id=device_id,
            duration_seconds=window_seconds,
            silence_threshold=self._silence_threshold,
            saturation_threshold=self._saturation_threshold,
        )
        if not result.opened:
            return AudioLevelMetric(
                collected_at=datetime.now(UTC),
                device_id=device_id,
                rms=None,
                peak=None,
                signal_detected=None,
                continuous_silence_seconds=self._continuous_silence_seconds,
                saturation_seconds=self._saturation_seconds,
                available=False,
                error=result.error,
            )
        if result.signal_detected:
            self._continuous_silence_seconds = 0.0
        else:
            self._continuous_silence_seconds += window_seconds
        if result.saturation or result.clipping:
            self._saturation_seconds += window_seconds
        else:
            self._saturation_seconds = 0.0
        return AudioLevelMetric(
            collected_at=datetime.now(UTC),
            device_id=device_id,
            rms=result.rms,
            peak=result.peak,
            signal_detected=result.signal_detected,
            continuous_silence_seconds=self._continuous_silence_seconds,
            saturation_seconds=self._saturation_seconds,
            available=True,
        )
