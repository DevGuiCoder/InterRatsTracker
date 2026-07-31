"""Audio inventory change detection."""

from __future__ import annotations

from datetime import UTC, datetime

from src.audio.audio_models import AudioDevice, AudioDirection, AudioEvent, AudioEventType, AudioInventory


class AudioEventMonitor:
    """Detect relevant audio changes between inventory snapshots."""

    def __init__(self) -> None:
        self._previous: AudioInventory | None = None

    def update(self, current: AudioInventory) -> list[AudioEvent]:
        """Return new audio events since the previous inventory."""
        if not current.available:
            return []
        if self._previous is None:
            self._previous = current
            return []
        events = _diff_inventory(self._previous, current)
        self._previous = current
        return events


def _diff_inventory(previous: AudioInventory, current: AudioInventory) -> list[AudioEvent]:
    events: list[AudioEvent] = []
    previous_by_id = {device.stable_id: device for device in previous.devices}
    current_by_id = {device.stable_id: device for device in current.devices}

    for stable_id, device in current_by_id.items():
        if stable_id not in previous_by_id:
            events.append(_device_event(device, True))
            continue
        previous_device = previous_by_id[stable_id]
        if previous_device.state != device.state:
            events.append(_state_event(previous_device, device))
        if previous_device.muted != device.muted and device.muted is not None:
            events.append(_mute_event(previous_device, device))
        if _volume_changed(previous_device.volume_percent, device.volume_percent):
            events.append(_volume_event(previous_device, device))

    for stable_id, device in previous_by_id.items():
        if stable_id not in current_by_id:
            events.append(_device_event(device, False))

    events.extend(_default_events(previous, current))
    return events


def _device_event(device: AudioDevice, connected: bool) -> AudioEvent:
    if device.direction == AudioDirection.INPUT:
        event_type = AudioEventType.AUDIO_INPUT_CONNECTED if connected else AudioEventType.AUDIO_INPUT_DISCONNECTED
    else:
        event_type = AudioEventType.AUDIO_OUTPUT_CONNECTED if connected else AudioEventType.AUDIO_OUTPUT_DISCONNECTED
    action = "conectado" if connected else "desconectado"
    return AudioEvent(
        occurred_at=datetime.now(UTC),
        event_type=event_type,
        severity="warning",
        message=f"{device.name} foi {action}.",
        device_id=device.stable_id,
        device_name=device.name,
        direction=device.direction,
        previous_state=None if connected else device.state.value,
        current_state=device.state.value if connected else "UNPLUGGED",
    )


def _state_event(previous: AudioDevice, current: AudioDevice) -> AudioEvent:
    return AudioEvent(
        occurred_at=datetime.now(UTC),
        event_type=AudioEventType.AUDIO_DRIVER_ERROR if current.pnp_error_code not in (None, 0) else _device_state_event_type(current),
        severity="critical" if current.pnp_error_code not in (None, 0) else "warning",
        message=f"{current.name} mudou de {previous.state.value} para {current.state.value}.",
        device_id=current.stable_id,
        device_name=current.name,
        direction=current.direction,
        previous_state=previous.state.value,
        current_state=current.state.value,
        payload={"pnp_error_code": current.pnp_error_code, "pnp_status": current.pnp_status},
    )


def _device_state_event_type(device: AudioDevice) -> AudioEventType:
    if device.direction == AudioDirection.INPUT:
        return AudioEventType.AUDIO_INPUT_DISCONNECTED
    return AudioEventType.AUDIO_OUTPUT_DISCONNECTED


def _mute_event(previous: AudioDevice, current: AudioDevice) -> AudioEvent:
    if current.direction == AudioDirection.INPUT:
        event_type = AudioEventType.MICROPHONE_MUTED if current.muted else AudioEventType.MICROPHONE_UNMUTED
    else:
        event_type = AudioEventType.OUTPUT_MUTED if current.muted else AudioEventType.OUTPUT_UNMUTED
    state = "ativado" if current.muted else "desativado"
    return AudioEvent(
        occurred_at=datetime.now(UTC),
        event_type=event_type,
        severity="warning",
        message=f"Mudo de {current.name} foi {state}.",
        device_id=current.stable_id,
        device_name=current.name,
        direction=current.direction,
        previous_state=str(previous.muted),
        current_state=str(current.muted),
    )


def _volume_event(previous: AudioDevice, current: AudioDevice) -> AudioEvent:
    return AudioEvent(
        occurred_at=datetime.now(UTC),
        event_type=AudioEventType.AUDIO_DEVICE_VOLUME_CHANGED,
        severity="info",
        message=f"Volume de {current.name} mudou.",
        device_id=current.stable_id,
        device_name=current.name,
        direction=current.direction,
        previous_state=str(previous.volume_percent),
        current_state=str(current.volume_percent),
    )


def _default_events(previous: AudioInventory, current: AudioInventory) -> list[AudioEvent]:
    mapping = [
        ("default_input_id", AudioEventType.DEFAULT_INPUT_CHANGED, AudioDirection.INPUT, "Entrada padrao mudou."),
        ("default_output_id", AudioEventType.DEFAULT_OUTPUT_CHANGED, AudioDirection.OUTPUT, "Saida padrao mudou."),
        ("communication_input_id", AudioEventType.COMMUNICATION_INPUT_CHANGED, AudioDirection.INPUT, "Entrada padrao para comunicacao mudou."),
        ("communication_output_id", AudioEventType.COMMUNICATION_OUTPUT_CHANGED, AudioDirection.OUTPUT, "Saida padrao para comunicacao mudou."),
    ]
    events = []
    for field_name, event_type, direction, message in mapping:
        old = getattr(previous, field_name)
        new = getattr(current, field_name)
        if old == new:
            continue
        events.append(
            AudioEvent(
                occurred_at=datetime.now(UTC),
                event_type=event_type,
                severity="warning",
                message=message,
                device_id=new,
                device_name=_device_name(current, new),
                direction=direction,
                previous_state=old,
                current_state=new,
            )
        )
    return events


def _volume_changed(previous: float | None, current: float | None) -> bool:
    if previous is None or current is None:
        return False
    return abs(previous - current) >= 5


def _device_name(inventory: AudioInventory, stable_id: str | None) -> str | None:
    if not stable_id:
        return None
    device = next((item for item in inventory.devices if item.stable_id == stable_id), None)
    return device.name if device else None
