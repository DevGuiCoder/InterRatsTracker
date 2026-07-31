"""Domain-oriented diagnostic summaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class DestinationLike(Protocol):
    category: str
    failure_rate_percent: float
    ended_unavailable: bool
    max_consecutive_failures: int


@dataclass(frozen=True)
class DomainDiagnostic:
    """One domain-level diagnostic summary."""

    domain: str
    status: str
    evidence: str
    likely_impact: str
    next_validation: str

    def to_dict(self) -> dict[str, str]:
        return {
            "domain": self.domain,
            "status": self.status,
            "evidence": self.evidence,
            "likely_impact": self.likely_impact,
            "next_validation": self.next_validation,
        }


def build_domain_diagnostics(destinations: list[DestinationLike]) -> list[DomainDiagnostic]:
    """Build independent diagnostics for local network, internet, DNS and SIP."""
    return [
        _domain("rede local", [item for item in destinations if item.category == "gateway"], "Validar cabo, Wi-Fi, switch, roteador e gateway."),
        _domain("internet", [item for item in destinations if item.category == "internet"], "Validar provedor, modem, rota externa e saturacao."),
        _domain("dns", [item for item in destinations if item.category == "dns"], "Validar servidores DNS configurados e resolucao do dominio SIP."),
        _domain("sip", [item for item in destinations if item.category == "sip"], "Validar PABX/provedor SIP, firewall, NAT e transporte configurado."),
    ]


def _domain(name: str, items: list[DestinationLike], next_validation: str) -> DomainDiagnostic:
    if not items:
        return DomainDiagnostic(name, "N/D", "Sem medicoes para este dominio.", "Nao avaliado.", next_validation)
    worst_failure = max(item.failure_rate_percent for item in items)
    ended_unavailable = any(item.ended_unavailable for item in items)
    max_sequence = max(item.max_consecutive_failures for item in items)
    if ended_unavailable or worst_failure >= 20 or max_sequence >= 4:
        status = "CRITICO"
        impact = "Pode causar indisponibilidade, quedas ou falhas perceptiveis."
    elif worst_failure >= 10 or max_sequence >= 3:
        status = "ATENCAO"
        impact = "Pode causar intermitencia e deve ser correlacionado com horarios do cliente."
    else:
        status = "ESTAVEL"
        impact = "Sem anomalia relevante nas medicoes disponiveis."
    evidence = f"{len(items)} destino(s), maior taxa de falhas {worst_failure:.1f}%, maior sequencia {max_sequence}."
    return DomainDiagnostic(name, status, evidence, impact, next_validation)
