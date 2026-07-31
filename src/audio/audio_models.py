"""Audio diagnostic models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class AudioDirection(str, Enum):
    """Audio endpoint direction."""

    INPUT = "input"
    OUTPUT = "output"
    UNKNOWN = "unknown"


class AudioDeviceState(str, Enum):
    """Normalized Windows audio device state."""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    UNPLUGGED = "UNPLUGGED"
    NOT_PRESENT = "NOT_PRESENT"
    UNKNOWN = "UNKNOWN"
    MUTED = "MUTED"
    NO_SIGNAL = "NO_SIGNAL"
    DRIVER_ERROR = "DRIVER_ERROR"


class AudioEventType(str, Enum):
    """Audio event types persisted during a monitoring session."""

    AUDIO_INPUT_CONNECTED = "audio_input_connected"
    AUDIO_INPUT_DISCONNECTED = "audio_input_disconnected"
    AUDIO_OUTPUT_CONNECTED = "audio_output_connected"
    AUDIO_OUTPUT_DISCONNECTED = "audio_output_disconnected"
    DEFAULT_INPUT_CHANGED = "default_input_changed"
    DEFAULT_OUTPUT_CHANGED = "default_output_changed"
    COMMUNICATION_INPUT_CHANGED = "communication_input_changed"
    COMMUNICATION_OUTPUT_CHANGED = "communication_output_changed"
    MICROPHONE_MUTED = "microphone_muted"
    MICROPHONE_UNMUTED = "microphone_unmuted"
    OUTPUT_MUTED = "output_muted"
    OUTPUT_UNMUTED = "output_unmuted"
    MICROPHONE_SIGNAL_LOST = "microphone_signal_lost"
    MICROPHONE_SIGNAL_RESTORED = "microphone_signal_restored"
    AUDIO_DRIVER_ERROR = "audio_driver_error"
    BLUETOOTH_AUDIO_PROFILE_CHANGED = "bluetooth_audio_profile_changed"
    AUDIO_DEVICE_VOLUME_CHANGED = "audio_device_volume_changed"


class MicrophoneTestState(str, Enum):
    """Guided microphone test result."""

    FUNCTIONAL = "FUNCIONAL"
    NO_SIGNAL = "SEM SINAL"
    MUTED = "MUDO"
    VERY_LOW_LEVEL = "NIVEL MUITO BAIXO"
    SATURATION = "SATURACAO"
    DEVICE_UNAVAILABLE = "DISPOSITIVO INDISPONIVEL"
    EXCLUSIVE_USE = "DISPOSITIVO EM USO EXCLUSIVO"
    PERMISSION_BLOCKED = "PERMISSAO BLOQUEADA"
    DRIVER_ERROR = "ERRO DE DRIVER"
    INSUFFICIENT_DATA = "DADOS INSUFICIENTES"


@dataclass(frozen=True)
class AudioDevice:
    """One audio endpoint or related PnP device."""

    stable_id: str
    name: str
    direction: AudioDirection
    state: AudioDeviceState
    manufacturer: str | None = None
    device_type: str | None = None
    is_default: bool = False
    is_default_communications: bool = False
    volume_percent: float | None = None
    muted: bool | None = None
    channels: int | None = None
    sample_rate_hz: int | None = None
    bit_depth: int | None = None
    connection_type: str | None = None
    is_virtual: bool = False
    driver_version: str | None = None
    driver_date: str | None = None
    pnp_status: str | None = None
    pnp_error_code: int | None = None
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["direction"] = self.direction.value
        payload["state"] = self.state.value
        return payload


@dataclass(frozen=True)
class AudioInventory:
    """Audio inventory snapshot."""

    collected_at: datetime
    available: bool
    devices: list[AudioDevice]
    default_input_id: str | None = None
    default_output_id: str | None = None
    communication_input_id: str | None = None
    communication_output_id: str | None = None
    errors: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "collected_at": self.collected_at.isoformat(),
            "available": self.available,
            "devices": [device.to_dict() for device in self.devices],
            "default_input_id": self.default_input_id,
            "default_output_id": self.default_output_id,
            "communication_input_id": self.communication_input_id,
            "communication_output_id": self.communication_output_id,
            "errors": self.errors or [],
        }


@dataclass(frozen=True)
class AudioEvent:
    """Change event generated from inventory comparison."""

    occurred_at: datetime
    event_type: AudioEventType
    severity: str
    message: str
    device_id: str | None
    device_name: str | None
    direction: AudioDirection
    previous_state: str | None
    current_state: str | None
    origin: str = "audio_monitor"
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["occurred_at"] = self.occurred_at.isoformat()
        payload["event_type"] = self.event_type.value
        payload["direction"] = self.direction.value
        return payload


@dataclass(frozen=True)
class AudioLevelMetric:
    """Aggregated microphone level metric. No raw audio is persisted."""

    collected_at: datetime
    device_id: str | None
    rms: float | None
    peak: float | None
    signal_detected: bool | None
    continuous_silence_seconds: float
    saturation_seconds: float
    available: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["collected_at"] = self.collected_at.isoformat()
        return payload


@dataclass(frozen=True)
class MicrophoneTestResult:
    """Guided microphone test result. Raw audio is never saved."""

    started_at: datetime
    device_id: str | None
    device_name: str | None
    duration_seconds: float
    frames: int
    rms: float | None
    average_level: float | None
    peak: float | None
    silence_percent: float | None
    saturation: bool
    clipping: bool
    signal_detected: bool | None
    opened: bool
    state: MicrophoneTestState
    format_used: str | None
    error: str | None = None
    privacy_note: str = "Este teste mede apenas niveis tecnicos do microfone. O audio nao sera salvo."

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["started_at"] = self.started_at.isoformat()
        payload["state"] = self.state.value
        return payload


@dataclass(frozen=True)
class OutputTestResult:
    """Guided output test result."""

    started_at: datetime
    device_id: str | None
    device_name: str | None
    stream_accepted: bool
    user_confirmation: str | None
    left_channel_tested: bool
    right_channel_tested: bool
    volume_percent: float | None
    muted: bool | None
    result: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["started_at"] = self.started_at.isoformat()
        return payload


def state_label(state: AudioDeviceState | str | None) -> str:
    labels = {
        "ACTIVE": "ATIVO",
        "DISABLED": "DESATIVADO",
        "UNPLUGGED": "DESCONECTADO",
        "NOT_PRESENT": "NAO PRESENTE",
        "UNKNOWN": "DESCONHECIDO",
        "MUTED": "MUDO",
        "NO_SIGNAL": "SEM SINAL",
        "DRIVER_ERROR": "ERRO DE DRIVER",
    }
    return labels.get(str(state or "UNKNOWN"), "DESCONHECIDO")
