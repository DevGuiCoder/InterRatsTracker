"""Configuration loading with typed defaults."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AppIdentityConfig:
    """Application identity settings."""

    name: str
    version: str


@dataclass(frozen=True)
class PathConfig:
    """Filesystem path settings."""

    data_dir: str
    logs_dir: str
    reports_dir: str


@dataclass(frozen=True)
class MonitoringConfig:
    """Default monitoring choices used by the operator console."""

    default_duration_minutes: int
    default_interval_seconds: float
    default_sip_target: str
    default_sip_port: int
    default_protocol: str
    default_external_target: str
    external_ip_targets: list[str]
    domain_targets: list[str]
    marker_context_before_seconds: int = 120
    marker_context_after_seconds: int = 120
    marker_debounce_seconds: float = 5.0
    marker_pre_context_seconds: int = 120
    marker_post_context_seconds: int = 120
    marker_click_cooldown_seconds: float = 5.0
    marker_correlation_strong_seconds: int = 15
    marker_correlation_moderate_seconds: int = 45
    marker_correlation_weak_seconds: int = 120
    warmup_seconds: int = 10
    minimum_samples_for_jitter: int = 5
    minimum_samples_for_alerts: int = 5
    monitor_start_stagger_ms: int = 250
    jitter_window_samples: int = 30
    max_concurrent_checks: int = 3
    exclude_warmup_from_summary: bool = True
    store_warmup_measurements: bool = True
    snapshot_queue_size: int = 20
    snapshot_timeout_seconds: float = 10.0
    sip_options_enabled: bool = True
    sip_options_interval_seconds: float = 30.0
    sip_options_timeout_seconds: float = 3.0
    sip_transports: list[str] | None = None
    route_trace_cooldown_seconds: int = 300
    public_ip_interval_seconds: int = 300
    public_ip_providers: list[str] | None = None
    udp_flow_test: dict[str, Any] | None = None
    system_alert_min_duration_seconds: int = 5
    audio_monitoring_enabled: bool = True
    audio_poll_interval_seconds: float = 2.0
    audio_level_monitoring_enabled: bool = False
    audio_level_window_seconds: float = 0.25
    audio_level_poll_interval_seconds: float = 5.0
    microphone_test_duration_seconds: float = 5.0
    softphone_monitor_enabled: bool = True
    softphone_poll_interval_seconds: float = 2.0
    softphone_high_cpu_percent: float = 85.0
    softphone_high_cpu_min_duration_seconds: float = 5.0
    softphone_high_memory_mb: float = 1024.0
    softphone_high_memory_min_duration_seconds: float = 5.0
    softphone_not_responding_min_duration_seconds: float = 3.0
    windows_events_enabled: bool = True
    windows_events_poll_interval_seconds: float = 30.0
    power_audit_enabled: bool = True
    power_audit_interval_seconds: float = 300.0


@dataclass(frozen=True)
class ThresholdConfig:
    """Event threshold defaults."""

    latency_warning_ms: int
    latency_critical_ms: int
    packet_loss_warning_percent: float
    packet_loss_critical_percent: float
    jitter_warning_ms: int
    jitter_critical_ms: int


@dataclass(frozen=True)
class AppConfig:
    """Full application configuration."""

    app: AppIdentityConfig
    paths: PathConfig
    monitoring: MonitoringConfig
    thresholds: ThresholdConfig


def load_config(path: Path | None = None) -> AppConfig:
    """Load application configuration from JSON."""
    config_path = path or _default_config_path()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return parse_config(raw)


def parse_config(raw: dict[str, Any]) -> AppConfig:
    """Parse a raw config dictionary into typed dataclasses."""
    return AppConfig(
        app=AppIdentityConfig(**raw["app"]),
        paths=PathConfig(**raw["paths"]),
        monitoring=MonitoringConfig(**raw["monitoring"]),
        thresholds=ThresholdConfig(**raw["thresholds"]),
    )


def _default_config_path() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "src" / "config" / "default_config.json"
    return Path(__file__).resolve().parents[1] / "config" / "default_config.json"
