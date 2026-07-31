"""Read-only power configuration audit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psutil

from src.utils.windows_command import run_windows_command


@dataclass(frozen=True)
class PowerAuditItem:
    """One read-only power audit finding."""

    item: str
    classification: str
    current_value: str
    source: str
    related_device: str | None
    possible_impact: str
    related_event: str | None
    manual_guidance: str

    def to_dict(self) -> dict[str, object]:
        return {
            "item": self.item,
            "classification": self.classification,
            "current_value": self.current_value,
            "source": self.source,
            "related_device": self.related_device,
            "possible_impact": self.possible_impact,
            "related_event": self.related_event,
            "manual_guidance": self.manual_guidance,
        }


def collect_power_audit(active_interface: str | None = None, related_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Collect a conservative, read-only power audit."""
    collected_at = datetime.now(UTC)
    events = related_events or []
    items = [
        _active_plan(),
        _battery_state(),
        _usb_selective_suspend(events),
        _cpu_policy(),
        _sleep_policy(),
        _network_adapter_policy(active_interface),
    ]
    return {
        "available": True,
        "collected_at": collected_at.isoformat(),
        "items": [item.to_dict() for item in items],
    }


def _active_plan() -> PowerAuditItem:
    try:
        result = run_windows_command(["powercfg", "/GetActiveScheme"], timeout=5)
        value = " ".join(result.stdout.split()) or result.stderr.strip()
        classification = "INFORMACAO" if result.returncode == 0 else "NAO DISPONIVEL"
    except Exception as exc:
        value = str(exc)
        classification = "NAO DISPONIVEL"
    return PowerAuditItem(
        "Plano de energia ativo",
        classification,
        value or "nao disponivel",
        "powercfg /GetActiveScheme",
        None,
        "Planos economicos podem reduzir desempenho em alguns cenarios, mas nao comprovam falha isoladamente.",
        None,
        "Validar manualmente o plano quando houver travamentos ou economia agressiva.",
    )


def _battery_state() -> PowerAuditItem:
    battery = psutil.sensors_battery()
    if battery is None:
        value = "sem bateria detectada"
        classification = "NAO APLICAVEL"
    else:
        value = f"{battery.percent:.0f}% - {'carregando' if battery.power_plugged else 'na bateria'}"
        classification = "ATENCAO" if not battery.power_plugged and battery.percent <= 20 else "INFORMACAO"
    return PowerAuditItem(
        "Estado de bateria",
        classification,
        value,
        "psutil.sensors_battery",
        None,
        "Bateria baixa ou modo economico pode reduzir desempenho e afetar adaptadores.",
        None,
        "Conectar energia e repetir teste se houver suspeita de economia de bateria.",
    )


def _usb_selective_suspend(events: list[dict[str, Any]]) -> PowerAuditItem:
    related = _related_event(events, {"windows_usb_disconnected", "windows_audio_device_removed", "windows_bluetooth_disconnected"})
    return PowerAuditItem(
        "Suspensao seletiva de USB",
        "INFORMACAO",
        "nao alterado pela aplicacao",
        "auditoria somente leitura",
        "USB/headset quando aplicavel",
        "Pode contribuir para desconexoes intermitentes em alguns dispositivos USB, mas nao comprova causa sem evento correlacionado.",
        related,
        "Conferir manualmente no plano de energia se houver desconexoes USB proximas as marcacoes.",
    )


def _cpu_policy() -> PowerAuditItem:
    return PowerAuditItem(
        "Estado minimo/maximo da CPU",
        "INFORMACAO",
        "nao coletado detalhadamente",
        "auditoria somente leitura",
        None,
        "Limites agressivos de CPU podem afetar softphone em maquinas lentas.",
        None,
        "Validar opcoes avancadas do plano de energia quando houver CPU alta ou travamentos.",
    )


def _sleep_policy() -> PowerAuditItem:
    return PowerAuditItem(
        "Suspensao e hibernacao",
        "INFORMACAO",
        "verificar eventos de energia da sessao",
        "eventos Windows/powercfg",
        None,
        "Suspensao/retomada durante coleta pode interromper rede, USB, Bluetooth e audio.",
        None,
        "Comparar eventos windows_sleep/windows_resume com as marcacoes.",
    )


def _network_adapter_policy(active_interface: str | None) -> PowerAuditItem:
    return PowerAuditItem(
        "Gerenciamento de energia do adaptador de rede",
        "INFORMACAO" if active_interface else "NAO DISPONIVEL",
        "nao alterado pela aplicacao",
        "auditoria somente leitura",
        active_interface,
        "Economia de energia em adaptador ativo pode contribuir para instabilidade em alguns drivers.",
        None,
        "Conferir manualmente o adaptador ativo no Gerenciador de Dispositivos se houver quedas de rede.",
    )


def _related_event(events: list[dict[str, Any]], event_types: set[str]) -> str | None:
    for event in events:
        if event.get("normalized_type") in event_types:
            return str(event.get("summary") or event.get("normalized_type"))
    return None
