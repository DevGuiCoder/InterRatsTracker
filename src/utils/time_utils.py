"""Time formatting helpers."""

from __future__ import annotations

from datetime import datetime, timedelta


def format_duration(value: timedelta) -> str:
    """Format a timedelta as HH:MM:SS."""
    total_seconds = max(0, int(value.total_seconds()))
    return format_seconds(total_seconds)


def format_seconds(total_seconds: int) -> str:
    """Format seconds as HH:MM:SS."""
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def to_local(value: datetime) -> datetime:
    """Convert an aware or naive datetime to the local Windows timezone."""
    if value.tzinfo is None:
        return value.astimezone()
    return value.astimezone()


def format_datetime_local(value: datetime | None) -> str:
    """Format a datetime for operator-facing output in local time."""
    if value is None:
        return "nao registrado"
    return to_local(value).strftime("%Y-%m-%d %H:%M:%S %Z")


def format_datetime_local_ms(value: datetime | None) -> str:
    """Format a datetime in local time with milliseconds."""
    if value is None:
        return "nao registrado"
    local = to_local(value)
    return local.strftime("%Y-%m-%d %H:%M:%S.") + f"{local.microsecond // 1000:03d} " + local.strftime("%Z")
