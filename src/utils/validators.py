"""Input validation helpers."""

from __future__ import annotations

from src.storage.models import MonitoringRequest


def parse_positive_int(raw: str, field_name: str) -> int:
    """Parse a positive integer from operator input."""
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{field_name} deve ser um numero inteiro positivo.") from exc
    if value <= 0:
        raise ValueError(f"{field_name} deve ser maior que zero.")
    return value


def parse_positive_float(raw: str, field_name: str) -> float:
    """Parse a positive float from operator input."""
    try:
        value = float(raw.replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"{field_name} deve ser um numero positivo.") from exc
    if value <= 0:
        raise ValueError(f"{field_name} deve ser maior que zero.")
    return value


def validate_monitoring_request(request: MonitoringRequest) -> None:
    """Validate the minimum safe fields for a monitoring run."""
    if not _text(request.client_name):
        raise ValueError("Nome do cliente e obrigatorio.")
    if not _text(request.problem_description):
        raise ValueError("Descricao do problema e obrigatoria.")
    if request.duration_minutes <= 0:
        raise ValueError("Duracao deve ser maior que zero.")
    if request.collection_interval_seconds <= 0:
        raise ValueError("Intervalo de coleta deve ser maior que zero.")
    if not _text(request.sip_target):
        raise ValueError("Destino SIP e obrigatorio.")
    if not 1 <= request.service_port <= 65535:
        raise ValueError("Porta do servico deve estar entre 1 e 65535.")
    if not _text(request.expected_protocol):
        raise ValueError("Protocolo esperado e obrigatorio.")
    if not _text(request.profile_id):
        raise ValueError("Perfil de monitoramento e obrigatorio.")


def _text(value: object) -> str:
    return str(value or "").strip()
