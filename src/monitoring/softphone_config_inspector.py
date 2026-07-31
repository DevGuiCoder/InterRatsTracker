"""Safe softphone configuration inspection interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


SENSITIVE_KEYS = {"password", "passwd", "secret", "token", "authorization", "auth", "key", "nonce"}


class SoftphoneConfigInspector(Protocol):
    """Safe softphone config inspector contract."""

    def supports(self, application: str) -> bool:
        ...

    def locate_config(self) -> str | None:
        ...

    def read_allowed_fields(self) -> dict[str, object]:
        ...

    def redact_sensitive_data(self, payload: dict[str, object]) -> dict[str, object]:
        ...

    def validate(self, payload: dict[str, object]) -> list[str]:
        ...


@dataclass(frozen=True)
class UnsupportedSoftphoneConfigInspector:
    """Default safe inspector for unsupported softphones."""

    application: str

    def inspect(self) -> dict[str, object]:
        return {
            "available": False,
            "application": self.application,
            "message": "Inspecao automatica de configuracao nao disponivel para este softphone.",
            "allowed_fields": {},
            "warnings": [],
        }


def redact_sensitive_data(payload: dict[str, object]) -> dict[str, object]:
    """Return payload with sensitive-looking keys redacted recursively."""
    redacted: dict[str, object] = {}
    for key, value in payload.items():
        if any(token in key.lower() for token in SENSITIVE_KEYS):
            redacted[key] = "[removido]"
        elif isinstance(value, dict):
            redacted[key] = redact_sensitive_data(value)
        elif isinstance(value, list):
            redacted[key] = [redact_sensitive_data(item) if isinstance(item, dict) else item for item in value]
        else:
            redacted[key] = value
    return redacted
