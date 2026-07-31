"""Centralized process snapshots based on psutil."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Iterable

import psutil


@dataclass(frozen=True)
class ProcessInfo:
    """Small immutable process snapshot used by monitors and reports."""

    pid: int
    name: str
    exe: str | None
    create_time: datetime | None
    cpu_percent: float | None
    rss_mb: float | None
    memory_percent: float | None
    thread_count: int | None
    handle_count: int | None
    read_bytes: int | None
    write_bytes: int | None
    not_responding: bool | None = None
    window_title: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "pid": self.pid,
            "name": self.name,
            "exe": self.exe,
            "create_time": self.create_time.isoformat() if self.create_time else None,
            "cpu_percent": self.cpu_percent,
            "rss_mb": self.rss_mb,
            "memory_percent": self.memory_percent,
            "thread_count": self.thread_count,
            "handle_count": self.handle_count,
            "read_bytes": self.read_bytes,
            "write_bytes": self.write_bytes,
            "not_responding": self.not_responding,
            "window_title": self.window_title,
        }


class ProcessSnapshotService:
    """Enumerate processes once and share the result through a short TTL cache."""

    def __init__(self, ttl_seconds: float = 1.0, max_processes: int = 4096) -> None:
        self._ttl_seconds = max(0.0, ttl_seconds)
        self._max_processes = max(1, max_processes)
        self._cached_at = 0.0
        self._cache: list[ProcessInfo] = []

    def snapshot(self, force_refresh: bool = False) -> list[ProcessInfo]:
        """Return a cached process list."""
        now = monotonic()
        if not force_refresh and self._cache and now - self._cached_at <= self._ttl_seconds:
            return self._cache
        self._cache = self._collect()
        self._cached_at = now
        return self._cache

    def find(
        self,
        process_name: str | None = None,
        expected_path: str | None = None,
        expected_pid: int | None = None,
    ) -> list[ProcessInfo]:
        """Return processes matching the requested identity."""
        matches = self.snapshot()
        if expected_pid is not None:
            matches = [process for process in matches if process.pid == expected_pid]
        if process_name:
            wanted_name = process_name.strip().lower()
            matches = [process for process in matches if process.name.lower() == wanted_name]
        if expected_path:
            wanted_path = expected_path.strip().lower()
            matches = [process for process in matches if (process.exe or "").lower() == wanted_path]
        return sorted(matches, key=lambda process: (process.create_time or datetime.min.replace(tzinfo=UTC), process.pid))

    def process_choices(self, limit: int = 30, visible_apps_only: bool = False) -> list[ProcessInfo]:
        """Return a compact list for operator selection."""
        processes = [process for process in self.snapshot() if process.name]
        if visible_apps_only:
            titles = _visible_window_titles()
            processes = [
                _with_window_title(process, titles.get(process.pid))
                for process in processes
                if process.pid in titles
            ]
        return sorted(processes, key=lambda process: process.name.lower())[: max(1, limit)]

    def _collect(self) -> list[ProcessInfo]:
        fields: Iterable[str] = (
            "pid",
            "name",
            "exe",
            "create_time",
            "cpu_percent",
            "memory_info",
            "memory_percent",
            "num_threads",
            "num_handles",
            "io_counters",
        )
        processes: list[ProcessInfo] = []
        for index, process in enumerate(psutil.process_iter(attrs=fields)):
            if index >= self._max_processes:
                break
            try:
                info = process.info
                memory_info = info.get("memory_info")
                io_counters = info.get("io_counters")
                create_time = info.get("create_time")
                processes.append(
                    ProcessInfo(
                        pid=int(info.get("pid") or process.pid),
                        name=str(info.get("name") or ""),
                        exe=info.get("exe"),
                        create_time=(
                            datetime.fromtimestamp(float(create_time), tz=UTC)
                            if create_time
                            else None
                        ),
                        cpu_percent=_optional_float(info.get("cpu_percent")),
                        rss_mb=(
                            float(memory_info.rss) / 1024 / 1024
                            if memory_info is not None and hasattr(memory_info, "rss")
                            else None
                        ),
                        memory_percent=_optional_float(info.get("memory_percent")),
                        thread_count=_optional_int(info.get("num_threads")),
                        handle_count=_optional_int(info.get("num_handles")),
                        read_bytes=(
                            int(io_counters.read_bytes)
                            if io_counters is not None and hasattr(io_counters, "read_bytes")
                            else None
                        ),
                        write_bytes=(
                            int(io_counters.write_bytes)
                            if io_counters is not None and hasattr(io_counters, "write_bytes")
                            else None
                        ),
                    )
                )
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        return processes


def _optional_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _with_window_title(process: ProcessInfo, window_title: str | None) -> ProcessInfo:
    return ProcessInfo(
        pid=process.pid,
        name=process.name,
        exe=process.exe,
        create_time=process.create_time,
        cpu_percent=process.cpu_percent,
        rss_mb=process.rss_mb,
        memory_percent=process.memory_percent,
        thread_count=process.thread_count,
        handle_count=process.handle_count,
        read_bytes=process.read_bytes,
        write_bytes=process.write_bytes,
        not_responding=process.not_responding,
        window_title=window_title,
    )


def _visible_window_titles() -> dict[int, str]:
    """Return PID -> first visible window title, best effort on Windows."""
    if not hasattr(ctypes, "windll"):
        return {}
    user32 = ctypes.windll.user32
    titles: dict[int, str] = {}

    enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd: int, lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not title:
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_id = int(pid.value)
        titles.setdefault(process_id, title[:160])
        return True

    user32.EnumWindows(enum_windows_proc(callback), 0)
    return titles
