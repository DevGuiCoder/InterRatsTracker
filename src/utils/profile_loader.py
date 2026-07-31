"""Monitoring profile loading."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MonitoringProfile:
    """Operator-selectable monitoring profile."""

    profile_id: str
    name: str
    description: str
    recommended_interval_seconds: float
    enabled_monitors: list[str]
    priority_metrics: list[str]
    mark_tests: list[str]
    highlight_report_sections: list[str]
    threshold_overrides: dict[str, Any]


def load_profiles(path: Path | None = None) -> list[MonitoringProfile]:
    """Load monitoring profiles from JSON files."""
    base_dir = path or _profiles_dir()
    profiles: list[MonitoringProfile] = []
    for file_path in sorted(base_dir.glob("*.json")):
        with file_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        profiles.append(
            MonitoringProfile(
                profile_id=raw["id"],
                name=raw["name"],
                description=raw.get("description", ""),
                recommended_interval_seconds=float(raw.get("recommended_interval_seconds", 2.0)),
                enabled_monitors=list(raw.get("enabled_monitors", [])),
                priority_metrics=list(raw.get("priority_metrics", [])),
                mark_tests=list(raw.get("mark_tests", [])),
                highlight_report_sections=list(raw.get("highlight_report_sections", [])),
                threshold_overrides=dict(raw.get("threshold_overrides", {})),
            )
        )
    return profiles


def get_profile(profile_id: str, path: Path | None = None) -> MonitoringProfile | None:
    """Return one profile by id."""
    normalized = profile_id.strip().lower()
    for profile in load_profiles(path):
        if profile.profile_id == normalized:
            return profile
    return None


def _profiles_dir() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "src" / "config" / "profiles"
    return Path(__file__).resolve().parents[1] / "config" / "profiles"
