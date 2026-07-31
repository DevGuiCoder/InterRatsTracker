"""SQLite persistence for monitoring evidence."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from src.storage.models import (
    CustomerMarkContextStatus,
    DiagnosticRecord,
    EventRecord,
    EventSeverity,
    InterruptionRecord,
    MeasurementRecord,
    MonitoringRequest,
    MonitoringSession,
    ProbeResult,
    SessionBaseline,
    SnapshotDifference,
    StoredCustomerMark,
    SystemInfoRecord,
    TargetDefinition,
    TechnicalSnapshot,
)


class Database:
    """Small SQLite gateway with explicit schema ownership."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    @property
    def path(self) -> Path:
        """Return the database path."""
        return self._db_path

    def initialize(self) -> None:
        """Create database directories and the initial schema."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    client_name TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    problem_description TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    collection_interval_seconds REAL NOT NULL,
                    sip_target TEXT NOT NULL,
                    service_port INTEGER NOT NULL,
                    expected_protocol TEXT NOT NULL,
                    external_target TEXT NOT NULL,
                    support_notes TEXT NOT NULL,
                    profile_id TEXT NOT NULL DEFAULT 'diagnostico_completo',
                    softphone_monitor_enabled INTEGER NOT NULL DEFAULT 0,
                    softphone_process_name TEXT NOT NULL DEFAULT '',
                    softphone_expected_path TEXT NOT NULL DEFAULT '',
                    softphone_expected_pid INTEGER,
                    started_at TEXT NOT NULL,
                    expected_end_at TEXT NOT NULL,
                    finished_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS session_config (
                    session_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY (session_id, key),
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    host TEXT NOT NULL,
                    port INTEGER,
                    protocol TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    UNIQUE (session_id, name),
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    latency_ms REAL,
                    is_warmup INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    target_name TEXT,
                    technical_description TEXT,
                    duration_seconds REAL,
                    origin TEXT NOT NULL DEFAULT 'automatic',
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS customer_marks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    marked_at TEXT NOT NULL,
                    context_status TEXT NOT NULL DEFAULT 'pending_after_context',
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS system_info (
                    session_id TEXT PRIMARY KEY,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS session_baselines (
                    session_id TEXT PRIMARY KEY,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS technical_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    mark_id INTEGER NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id),
                    FOREIGN KEY (mark_id) REFERENCES customer_marks(id)
                );
                CREATE TABLE IF NOT EXISTS snapshot_differences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    snapshot_id INTEGER NOT NULL,
                    field_name TEXT NOT NULL,
                    baseline_value TEXT,
                    snapshot_value TEXT,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id),
                    FOREIGN KEY (snapshot_id) REFERENCES technical_snapshots(id)
                );
                CREATE TABLE IF NOT EXISTS interface_traffic (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS system_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS sip_options_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS sip_transport_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS udp_flow_tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS voice_quality_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS time_sync_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS wifi_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS route_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS public_ip_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS network_environment_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS interruptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_seconds REAL,
                    lost_tests INTEGER NOT NULL DEFAULT 0,
                    max_consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_measurements_session_time
                    ON measurements(session_id, collected_at);
                CREATE INDEX IF NOT EXISTS idx_targets_session
                    ON targets(session_id);
                CREATE INDEX IF NOT EXISTS idx_events_session_time
                    ON events(session_id, occurred_at);
                CREATE INDEX IF NOT EXISTS idx_marks_session_time
                    ON customer_marks(session_id, marked_at);
                CREATE INDEX IF NOT EXISTS idx_snapshots_session_mark
                    ON technical_snapshots(session_id, mark_id);
                CREATE INDEX IF NOT EXISTS idx_snapshot_differences_snapshot
                    ON snapshot_differences(snapshot_id);
                CREATE INDEX IF NOT EXISTS idx_interface_traffic_session_time
                    ON interface_traffic(session_id, collected_at);
                CREATE INDEX IF NOT EXISTS idx_system_metrics_session_time
                    ON system_metrics(session_id, collected_at);
                CREATE INDEX IF NOT EXISTS idx_voice_quality_session_time
                    ON voice_quality_results(session_id, collected_at);
                CREATE INDEX IF NOT EXISTS idx_interruptions_session_time
                    ON interruptions(session_id, started_at);
                """
            )
            self._migrate(conn)

    def create_session(self, session: MonitoringSession) -> None:
        """Persist a newly started session."""
        row = {
            "id": session.session_id,
            "status": session.status,
            "client_name": session.request.client_name,
            "unit": session.request.unit,
            "problem_description": session.request.problem_description,
            "duration_minutes": session.request.duration_minutes,
            "collection_interval_seconds": session.request.collection_interval_seconds,
            "sip_target": session.request.sip_target,
            "service_port": session.request.service_port,
            "expected_protocol": session.request.expected_protocol,
            "external_target": session.request.external_target,
            "support_notes": session.request.support_notes,
            "profile_id": session.request.profile_id,
            "softphone_monitor_enabled": 1 if session.request.softphone_monitor_enabled else 0,
            "softphone_process_name": session.request.softphone_process_name,
            "softphone_expected_path": session.request.softphone_expected_path,
            "softphone_expected_pid": session.request.softphone_expected_pid,
            "started_at": session.started_at.isoformat(),
            "expected_end_at": session.expected_end_at.isoformat(),
            "finished_at": session.finished_at.isoformat() if session.finished_at else None,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    id, status, client_name, unit, problem_description,
                    duration_minutes, collection_interval_seconds, sip_target,
                    service_port, expected_protocol, external_target, support_notes, profile_id,
                    softphone_monitor_enabled, softphone_process_name, softphone_expected_path,
                    softphone_expected_pid,
                    started_at, expected_end_at, finished_at
                )
                VALUES (
                    :id, :status, :client_name, :unit, :problem_description,
                    :duration_minutes, :collection_interval_seconds, :sip_target,
                    :service_port, :expected_protocol, :external_target, :support_notes, :profile_id,
                    :softphone_monitor_enabled, :softphone_process_name, :softphone_expected_path,
                    :softphone_expected_pid,
                    :started_at, :expected_end_at, :finished_at
                )
                """,
                row,
            )

    def update_session_status(self, session_id: str, status: str, finished_at: datetime | None) -> None:
        """Update session lifecycle status."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                   SET status = ?,
                       finished_at = ?,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                """,
                (status, finished_at.isoformat() if finished_at else None, session_id),
            )

    def get_incomplete_sessions(self) -> list[MonitoringSession]:
        """Load sessions that still require recovery or report generation."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                 FROM sessions
                 WHERE status NOT IN ('completed', 'archived')
                 ORDER BY started_at DESC
                """
            ).fetchall()
        return [self._row_to_session(dict(row)) for row in rows]

    def get_session(self, session_id: str) -> MonitoringSession | None:
        """Load one session by id."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._row_to_session(dict(row)) if row else None

    def store_session_config(self, session_id: str, config: dict[str, Any]) -> None:
        """Persist a JSON-serializable config snapshot for auditability."""
        values = [(session_id, key, json.dumps(value, ensure_ascii=True)) for key, value in config.items()]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO session_config (session_id, key, value)
                VALUES (?, ?, ?)
                """,
                values,
            )

    def store_targets(self, session_id: str, targets: list[TargetDefinition]) -> None:
        """Persist the target list used by a session."""
        values = [
            (
                session_id,
                target.name,
                target.kind.value,
                target.host,
                target.port,
                target.protocol,
                1 if target.enabled else 0,
            )
            for target in targets
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO targets (
                    session_id, name, kind, host, port, protocol, enabled
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

    def store_probe_results(
        self,
        session_id: str,
        results: list[ProbeResult],
        is_warmup: bool = False,
    ) -> None:
        """Persist a small batch of probe results."""
        values = [
            (
                session_id,
                result.target.name,
                result.collected_at.isoformat(),
                result.status.value,
                result.latency_ms,
                1 if is_warmup else 0,
                json.dumps(
                    {
                        "target": {
                            "kind": result.target.kind.value,
                            "host": result.target.host,
                            "port": result.target.port,
                            "protocol": result.target.protocol,
                        },
                        "error": result.error,
                        "details": result.details,
                        "is_warmup": is_warmup,
                        "diagnostic_use": not is_warmup,
                    },
                    ensure_ascii=True,
                    default=str,
                ),
            )
            for result in results
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO measurements (
                    session_id, target_name, collected_at, status, latency_ms, is_warmup, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

    def store_event(
        self,
        session_id: str,
        occurred_at: datetime,
        severity: EventSeverity,
        event_type: str,
        message: str,
        payload: dict[str, Any],
        target_name: str | None = None,
        technical_description: str | None = None,
        duration_seconds: float | None = None,
        origin: str = "automatic",
    ) -> int:
        """Persist a detected event."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (
                    session_id, occurred_at, severity, event_type, message, payload_json,
                    target_name, technical_description, duration_seconds, origin
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    occurred_at.isoformat(),
                    severity.value,
                    event_type,
                    message,
                    json.dumps(payload, ensure_ascii=True, default=str),
                    target_name,
                    technical_description,
                    duration_seconds,
                    origin,
                ),
            )
            return int(cursor.lastrowid)

    def store_interruption(
        self,
        session_id: str,
        target_name: str,
        event_type: str,
        started_at: datetime,
        ended_at: datetime | None,
        duration_seconds: float | None,
        lost_tests: int,
        max_consecutive_failures: int,
        payload: dict[str, Any],
    ) -> int:
        """Persist an interruption interval."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO interruptions (
                    session_id, target_name, event_type, started_at, ended_at,
                    duration_seconds, lost_tests, max_consecutive_failures, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    target_name,
                    event_type,
                    started_at.isoformat(),
                    ended_at.isoformat() if ended_at else None,
                    duration_seconds,
                    lost_tests,
                    max_consecutive_failures,
                    json.dumps(payload, ensure_ascii=True, default=str),
                ),
            )
            return int(cursor.lastrowid)

    def store_system_info(self, session_id: str, collected_at: datetime, payload: dict[str, Any]) -> None:
        """Persist system information captured at session start."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO system_info (session_id, collected_at, payload_json)
                VALUES (?, ?, ?)
                """,
                (session_id, collected_at.isoformat(), json.dumps(payload, ensure_ascii=True, default=str)),
            )

    def store_session_baseline(self, session_id: str, collected_at: datetime, payload: dict[str, Any]) -> None:
        """Persist the technical baseline for a session."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO session_baselines (session_id, collected_at, payload_json)
                VALUES (?, ?, ?)
                """,
                (session_id, collected_at.isoformat(), json.dumps(payload, ensure_ascii=True, default=str)),
            )

    def get_session_baseline(self, session_id: str) -> SessionBaseline | None:
        """Load the technical baseline for a session."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, collected_at, payload_json
                  FROM session_baselines
                 WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionBaseline(
            session_id=row["session_id"],
            collected_at=datetime.fromisoformat(row["collected_at"]),
            payload=json.loads(row["payload_json"]),
        )

    def store_technical_snapshot(
        self,
        session_id: str,
        mark_id: int,
        collected_at: datetime,
        payload: dict[str, Any],
    ) -> int:
        """Persist a deep technical snapshot captured for a customer mark."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO technical_snapshots (session_id, mark_id, collected_at, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    session_id,
                    mark_id,
                    collected_at.isoformat(),
                    json.dumps(payload, ensure_ascii=True, default=str),
                ),
            )
            return int(cursor.lastrowid)

    def store_snapshot_differences(
        self,
        session_id: str,
        snapshot_id: int,
        differences: list[dict[str, Any]],
    ) -> None:
        """Persist verified differences between baseline and snapshot."""
        values = [
            (
                session_id,
                snapshot_id,
                str(item.get("field_name", "")),
                json.dumps(item.get("baseline_value"), ensure_ascii=True, default=str),
                json.dumps(item.get("snapshot_value"), ensure_ascii=True, default=str),
                str(item.get("severity", "info")),
                str(item.get("message", "")),
            )
            for item in differences
        ]
        if not values:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO snapshot_differences (
                    session_id, snapshot_id, field_name, baseline_value,
                    snapshot_value, severity, message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

    def get_technical_snapshots(self, session_id: str) -> list[TechnicalSnapshot]:
        """Load technical snapshots for a session."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, mark_id, collected_at, payload_json
                  FROM technical_snapshots
                 WHERE session_id = ?
                 ORDER BY collected_at ASC, id ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            TechnicalSnapshot(
                snapshot_id=int(row["id"]),
                session_id=row["session_id"],
                mark_id=int(row["mark_id"]),
                collected_at=datetime.fromisoformat(row["collected_at"]),
                payload=json.loads(row["payload_json"]),
            )
            for row in rows
        ]

    def get_snapshot_differences(self, session_id: str) -> list[SnapshotDifference]:
        """Load snapshot differences for a session."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, snapshot_id, field_name, baseline_value,
                       snapshot_value, severity, message
                  FROM snapshot_differences
                 WHERE session_id = ?
                 ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            SnapshotDifference(
                difference_id=int(row["id"]),
                session_id=row["session_id"],
                snapshot_id=int(row["snapshot_id"]),
                field_name=row["field_name"],
                baseline_value=json.loads(row["baseline_value"]) if row["baseline_value"] else None,
                snapshot_value=json.loads(row["snapshot_value"]) if row["snapshot_value"] else None,
                severity=row["severity"],
                message=row["message"],
            )
            for row in rows
        ]

    def store_diagnostic_record(
        self,
        table_name: str,
        session_id: str,
        collected_at: datetime,
        payload: dict[str, Any],
    ) -> int:
        """Store a generic diagnostic payload in an allowed evidence table."""
        table = self._diagnostic_table(table_name)
        with self._connect() as conn:
            cursor = conn.execute(
                f"INSERT INTO {table} (session_id, collected_at, payload_json) VALUES (?, ?, ?)",
                (session_id, collected_at.isoformat(), json.dumps(payload, ensure_ascii=True, default=str)),
            )
            return int(cursor.lastrowid)

    def get_diagnostic_records(self, table_name: str, session_id: str) -> list[DiagnosticRecord]:
        """Load generic diagnostic payloads from an allowed evidence table."""
        table = self._diagnostic_table(table_name)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, session_id, collected_at, payload_json
                  FROM {table}
                 WHERE session_id = ?
                 ORDER BY collected_at ASC, id ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            DiagnosticRecord(
                record_id=int(row["id"]),
                session_id=row["session_id"],
                collected_at=datetime.fromisoformat(row["collected_at"]),
                payload=json.loads(row["payload_json"]),
            )
            for row in rows
        ]

    def create_customer_mark(
        self,
        session_id: str,
        marked_at: datetime,
        payload: dict[str, Any],
    ) -> int:
        """Persist a customer mark and return its database id."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO customer_marks (
                    session_id, marked_at, context_status, payload_json
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    session_id,
                    marked_at.isoformat(),
                    CustomerMarkContextStatus.PENDING_AFTER_CONTEXT.value,
                    json.dumps(payload, ensure_ascii=True, default=str),
                ),
            )
            return int(cursor.lastrowid)

    def update_customer_mark_context(
        self,
        mark_id: int,
        context_status: CustomerMarkContextStatus,
        payload: dict[str, Any],
    ) -> None:
        """Update customer mark context payload."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE customer_marks
                   SET context_status = ?,
                       payload_json = ?
                 WHERE id = ?
                """,
                (
                    context_status.value,
                    json.dumps(payload, ensure_ascii=True, default=str),
                    mark_id,
                ),
            )

    def get_customer_mark(self, mark_id: int) -> StoredCustomerMark | None:
        """Load one customer mark by id."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, session_id, marked_at, context_status, payload_json
                  FROM customer_marks
                 WHERE id = ?
                """,
                (mark_id,),
            ).fetchone()
        if row is None:
            return None
        return StoredCustomerMark(
            mark_id=int(row["id"]),
            session_id=row["session_id"],
            marked_at=datetime.fromisoformat(row["marked_at"]),
            context_status=CustomerMarkContextStatus(row["context_status"]),
            payload=json.loads(row["payload_json"]),
        )

    def get_measurements(self, session_id: str) -> list[MeasurementRecord]:
        """Load all measurements for a session."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, target_name, collected_at, status, latency_ms, is_warmup, payload_json
                  FROM measurements
                 WHERE session_id = ?
                 ORDER BY collected_at ASC, id ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            MeasurementRecord(
                measurement_id=int(row["id"]),
                session_id=row["session_id"],
                target_name=row["target_name"],
                collected_at=datetime.fromisoformat(row["collected_at"]),
                status=row["status"],
                latency_ms=float(row["latency_ms"]) if row["latency_ms"] is not None else None,
                payload=json.loads(row["payload_json"]),
                is_warmup=bool(row["is_warmup"]),
            )
            for row in rows
        ]

    def get_events(self, session_id: str) -> list[EventRecord]:
        """Load detected events for a session."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, occurred_at, severity, event_type, message, payload_json,
                       target_name, technical_description, duration_seconds, origin
                  FROM events
                 WHERE session_id = ?
                 ORDER BY occurred_at ASC, id ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            EventRecord(
                event_id=int(row["id"]),
                session_id=row["session_id"],
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
                severity=EventSeverity(row["severity"]),
                event_type=row["event_type"],
                message=row["message"],
                payload=json.loads(row["payload_json"]),
                target_name=row["target_name"],
                technical_description=row["technical_description"],
                duration_seconds=float(row["duration_seconds"]) if row["duration_seconds"] is not None else None,
                origin=row["origin"] or "automatic",
            )
            for row in rows
        ]

    def get_interruptions(self, session_id: str) -> list[InterruptionRecord]:
        """Load interruptions for a session."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, target_name, event_type, started_at, ended_at,
                       duration_seconds, lost_tests, max_consecutive_failures, payload_json
                  FROM interruptions
                 WHERE session_id = ?
                 ORDER BY started_at ASC, id ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            InterruptionRecord(
                interruption_id=int(row["id"]),
                session_id=row["session_id"],
                target_name=row["target_name"],
                event_type=row["event_type"],
                started_at=datetime.fromisoformat(row["started_at"]),
                ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
                duration_seconds=float(row["duration_seconds"]) if row["duration_seconds"] is not None else None,
                lost_tests=int(row["lost_tests"]),
                max_consecutive_failures=int(row["max_consecutive_failures"]),
                payload=json.loads(row["payload_json"]),
            )
            for row in rows
        ]

    def get_customer_marks(self, session_id: str) -> list[StoredCustomerMark]:
        """Load customer marks for a session."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, marked_at, context_status, payload_json
                  FROM customer_marks
                 WHERE session_id = ?
                 ORDER BY marked_at ASC, id ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            StoredCustomerMark(
                mark_id=int(row["id"]),
                session_id=row["session_id"],
                marked_at=datetime.fromisoformat(row["marked_at"]),
                context_status=CustomerMarkContextStatus(row["context_status"]),
                payload=json.loads(row["payload_json"]),
            )
            for row in rows
        ]

    def get_system_info(self, session_id: str) -> SystemInfoRecord | None:
        """Load system information for a session."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, collected_at, payload_json
                  FROM system_info
                 WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SystemInfoRecord(
            session_id=row["session_id"],
            collected_at=datetime.fromisoformat(row["collected_at"]),
            payload=json.loads(row["payload_json"]),
        )

    def checkpoint(self) -> None:
        """Flush WAL content into the main database file when possible."""
        with self._connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(FULL)")

    def session_stats(self, session_id: str) -> dict[str, Any]:
        """Return recovery-oriented session statistics."""
        with self._connect() as conn:
            measurement_count = conn.execute(
                "SELECT COUNT(*) FROM measurements WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            mark_count = conn.execute(
                "SELECT COUNT(*) FROM customer_marks WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            last_measurement = conn.execute(
                "SELECT collected_at, target_name, status FROM measurements WHERE session_id = ? ORDER BY collected_at DESC, id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return {
            "measurement_count": int(measurement_count),
            "mark_count": int(mark_count),
            "last_measurement_at": last_measurement["collected_at"] if last_measurement else None,
            "last_target_name": last_measurement["target_name"] if last_measurement else None,
            "last_status": last_measurement["status"] if last_measurement else None,
        }

    def delete_session(self, session_id: str) -> None:
        """Delete a session and all dependent diagnostic rows."""
        with self._connect() as conn:
            for table in _DIAGNOSTIC_TABLES:
                conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM measurements WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM events WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM snapshot_differences WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM technical_snapshots WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM customer_marks WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM interruptions WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM session_baselines WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM targets WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM session_config WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM system_info WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _diagnostic_table(table_name: str) -> str:
        if table_name not in _DIAGNOSTIC_TABLES:
            raise ValueError(f"Tabela diagnostica nao permitida: {table_name}")
        return table_name

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        event_columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
        additions = {
            "target_name": "ALTER TABLE events ADD COLUMN target_name TEXT",
            "technical_description": "ALTER TABLE events ADD COLUMN technical_description TEXT",
            "duration_seconds": "ALTER TABLE events ADD COLUMN duration_seconds REAL",
            "origin": "ALTER TABLE events ADD COLUMN origin TEXT NOT NULL DEFAULT 'automatic'",
        }
        for column, statement in additions.items():
            if column not in event_columns:
                conn.execute(statement)
        measurement_columns = {row["name"] for row in conn.execute("PRAGMA table_info(measurements)").fetchall()}
        if "is_warmup" not in measurement_columns:
            conn.execute("ALTER TABLE measurements ADD COLUMN is_warmup INTEGER NOT NULL DEFAULT 0")
        session_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        if "profile_id" not in session_columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN profile_id TEXT NOT NULL DEFAULT 'diagnostico_completo'")
        session_additions = {
            "softphone_monitor_enabled": "ALTER TABLE sessions ADD COLUMN softphone_monitor_enabled INTEGER NOT NULL DEFAULT 0",
            "softphone_process_name": "ALTER TABLE sessions ADD COLUMN softphone_process_name TEXT NOT NULL DEFAULT ''",
            "softphone_expected_path": "ALTER TABLE sessions ADD COLUMN softphone_expected_path TEXT NOT NULL DEFAULT ''",
            "softphone_expected_pid": "ALTER TABLE sessions ADD COLUMN softphone_expected_pid INTEGER",
        }
        session_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        for column, statement in session_additions.items():
            if column not in session_columns:
                conn.execute(statement)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_baselines (
                session_id TEXT PRIMARY KEY,
                collected_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS technical_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                mark_id INTEGER NOT NULL,
                collected_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                FOREIGN KEY (mark_id) REFERENCES customer_marks(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshot_differences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                snapshot_id INTEGER NOT NULL,
                field_name TEXT NOT NULL,
                baseline_value TEXT,
                snapshot_value TEXT,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                FOREIGN KEY (snapshot_id) REFERENCES technical_snapshots(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshots_session_mark ON technical_snapshots(session_id, mark_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshot_differences_snapshot ON snapshot_differences(snapshot_id)"
        )
        for table in _DIAGNOSTIC_TABLES:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
                """
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_session_time ON {table}(session_id, collected_at)"
            )
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', '8')"
        )

    @staticmethod
    def _row_to_session(row: dict[str, Any]) -> MonitoringSession:
        request = MonitoringRequest(
            client_name=row["client_name"],
            unit=row["unit"],
            problem_description=row["problem_description"],
            duration_minutes=int(row["duration_minutes"]),
            collection_interval_seconds=float(row["collection_interval_seconds"]),
            sip_target=row["sip_target"],
            service_port=int(row["service_port"]),
            expected_protocol=row["expected_protocol"],
            external_target=row["external_target"],
            support_notes=row["support_notes"],
            profile_id=row["profile_id"] if "profile_id" in row else "diagnostico_completo",
            softphone_monitor_enabled=bool(row["softphone_monitor_enabled"]) if "softphone_monitor_enabled" in row else False,
            softphone_process_name=row["softphone_process_name"] if "softphone_process_name" in row else "",
            softphone_expected_path=row["softphone_expected_path"] if "softphone_expected_path" in row else "",
            softphone_expected_pid=int(row["softphone_expected_pid"]) if "softphone_expected_pid" in row and row["softphone_expected_pid"] is not None else None,
        )
        return MonitoringSession(
            session_id=row["id"],
            request=request,
            status=row["status"],
            started_at=datetime.fromisoformat(row["started_at"]),
            expected_end_at=datetime.fromisoformat(row["expected_end_at"]),
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        )


_DIAGNOSTIC_TABLES = {
    "interface_traffic",
    "system_metrics",
    "sip_options_results",
    "sip_transport_results",
    "udp_flow_tests",
    "voice_quality_results",
    "time_sync_results",
    "wifi_metrics",
    "route_traces",
    "public_ip_history",
    "network_environment_events",
    "audio_devices",
    "audio_device_states",
    "audio_events",
    "audio_level_metrics",
    "microphone_tests",
    "output_tests",
    "audio_permissions",
    "audio_driver_information",
    "audio_snapshots",
    "softphone_processes",
    "softphone_metrics",
    "softphone_events",
    "windows_events",
    "power_audit",
    "marker_contexts",
    "marker_correlations",
    "domain_diagnostics",
    "softphone_config_snapshots",
}
