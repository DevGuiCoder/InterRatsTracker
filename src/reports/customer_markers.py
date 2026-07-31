"""Shared customer-marker presentation and identification helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CUSTOMER_MARKER_EVENT_TYPE = "customer_marker"
LEGACY_CUSTOMER_MARK_EVENT_TYPE = "customer_mark"
CUSTOMER_MARKER_ORIGIN = "customer"
CUSTOMER_MARKER_SOURCE = "floating_button"
CUSTOMER_MARKER_VISUAL_PRIORITY = "highest"

CUSTOMER_MARKER_COLOR = "#ff7a00"
CUSTOMER_MARKER_EDGE_COLOR = "#b45309"
CUSTOMER_MARKER_FILL_COLOR = "#fff3e6"
CUSTOMER_MARKER_TEXT_COLOR = "#7c2d12"
CUSTOMER_MARKER_LINESTYLE = "--"
CUSTOMER_MARKER_ZORDER = 100


@dataclass(frozen=True)
class CustomerMarkerTheme:
    """Single source for marker colors used by HTML and charts."""

    color: str = CUSTOMER_MARKER_COLOR
    edge_color: str = CUSTOMER_MARKER_EDGE_COLOR
    fill_color: str = CUSTOMER_MARKER_FILL_COLOR
    text_color: str = CUSTOMER_MARKER_TEXT_COLOR
    linestyle: str = CUSTOMER_MARKER_LINESTYLE
    zorder: int = CUSTOMER_MARKER_ZORDER


CUSTOMER_MARKER_THEME = CustomerMarkerTheme()


def customer_marker_css_variables() -> str:
    """Return CSS variables for customer marker styling."""
    return (
        f"--customer-marker-color: {CUSTOMER_MARKER_COLOR};"
        f"--customer-marker-edge-color: {CUSTOMER_MARKER_EDGE_COLOR};"
        f"--customer-marker-fill-color: {CUSTOMER_MARKER_FILL_COLOR};"
        f"--customer-marker-text-color: {CUSTOMER_MARKER_TEXT_COLOR};"
    )


def customer_marker_anchor(sequence_number: int) -> str:
    """Return a stable anchor id for a marker card."""
    return f"customer-marker-{sequence_number}"


def customer_marker_replay_anchor(sequence_number: int) -> str:
    """Return a stable anchor id for the incident replay section."""
    return f"customer-marker-{sequence_number}-replay"


def is_customer_marker_event(value: object) -> bool:
    """Identify customer markers from structured fields, with narrow legacy support."""
    payload = _payload_for(value)
    event_type = str(getattr(value, "event_type", payload.get("event_type") or "") or "")
    origin = str(getattr(value, "origin", payload.get("event_origin") or payload.get("origin") or "") or "")
    severity = getattr(value, "severity", None)
    severity_value = str(getattr(severity, "value", severity) or "")
    return (
        payload.get("is_customer_marker") is True
        or event_type == CUSTOMER_MARKER_EVENT_TYPE
        or (
            event_type == LEGACY_CUSTOMER_MARK_EVENT_TYPE
            and (origin in {"manual", CUSTOMER_MARKER_ORIGIN, ""} or severity_value == "user_marker")
        )
    )


def normalize_correlation_level(value: object) -> str:
    """Normalize correlation labels without relying on sentence text."""
    normalized = str(value or "").strip().lower()
    normalized = normalized.replace("ç", "c").replace("ã", "a").replace("á", "a").replace("é", "e")
    if "forte" in normalized or normalized == "strong":
        return "strong"
    if "moderada" in normalized or "moderado" in normalized or normalized == "moderate":
        return "moderate"
    if "fraca" in normalized or "fraco" in normalized or normalized == "weak":
        return "weak"
    if "sem anomalia" in normalized or normalized in {"none", "no_anomaly"}:
        return "none"
    if "insuficiente" in normalized or normalized == "insufficient":
        return "insufficient"
    return "unknown"


def correlation_label(level: str) -> str:
    """Return operator-facing label for a normalized correlation level."""
    return {
        "strong": "correlacao forte",
        "moderate": "correlacao moderada",
        "weak": "correlacao fraca",
        "none": "sem anomalia proxima",
        "insufficient": "dados insuficientes",
    }.get(level, "correlacao nao classificada")


def _payload_for(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    payload = getattr(value, "payload", None)
    return payload if isinstance(payload, dict) else {}
