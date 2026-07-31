"""Session lifecycle orchestration."""

from __future__ import annotations

import logging
import queue
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.monitoring.runner import MonitoringRunner
from src.monitoring.system_monitor import collect_system_info
from src.monitoring.technical_snapshot import collect_session_baseline
from src.reports.exporters import generate_report_package
from src.storage.database import Database
from src.storage.models import (
    CustomerMarkSignal,
    EventSeverity,
    MonitoringRequest,
    MonitoringSession,
    MonitoringSnapshot,
    SessionStatus,
)
from src.utils.config_loader import AppConfig
from src.utils.validators import validate_monitoring_request

LOGGER = logging.getLogger(__name__)


class SessionController:
    """Coordinates monitoring sessions without binding to any UI."""

    def __init__(self, database: Database, app_config: AppConfig) -> None:
        self._database = database
        self._config = app_config

    def start_session(self, request: MonitoringRequest) -> MonitoringSession:
        """Validate, create and persist a new monitoring session."""
        validate_monitoring_request(request)
        started_at = datetime.now(UTC)
        session = MonitoringSession(
            session_id=str(uuid4()),
            request=request,
            status=SessionStatus.RUNNING.value,
            started_at=started_at,
            expected_end_at=started_at + timedelta(minutes=request.duration_minutes),
            finished_at=None,
        )
        self._database.create_session(session)
        self._database.store_session_config(session.session_id, asdict(self._config))
        self._database.store_system_info(session.session_id, started_at, collect_system_info())
        self._database.store_session_baseline(
            session.session_id,
            started_at,
            collect_session_baseline(
                request.sip_target,
                public_ip_providers=self._config.monitoring.public_ip_providers or [],
            ),
        )
        self._database.store_event(
            session_id=session.session_id,
            occurred_at=started_at,
            severity=EventSeverity.INFO,
            event_type="monitoring_started",
            message="Monitoramento iniciado.",
            payload={"client_name": request.client_name, "duration_minutes": request.duration_minutes},
        )
        LOGGER.info("Monitoring session started", extra={"session_id": session.session_id})
        return session

    async def run_monitoring(
        self,
        session: MonitoringSession,
        on_snapshot: Callable[[MonitoringSnapshot], None] | None = None,
        mark_queue: queue.Queue[CustomerMarkSignal] | None = None,
    ) -> MonitoringSnapshot:
        """Run monitoring probes, process customer marks and complete the session."""
        runner = MonitoringRunner(database=self._database, app_config=self._config)
        snapshot = await runner.run(session, on_snapshot=on_snapshot, mark_queue=mark_queue)
        self.finish_session(session.session_id)
        return snapshot

    def finish_session(self, session_id: str, interrupted: bool = False) -> None:
        """Mark a session as completed or unexpectedly interrupted."""
        status = SessionStatus.INTERRUPTED if interrupted else SessionStatus.COMPLETED
        finished_at = datetime.now(UTC)
        self._database.update_session_status(
            session_id=session_id,
            status=status.value,
            finished_at=finished_at,
        )
        self._database.store_event(
            session_id=session_id,
            occurred_at=finished_at,
            severity=EventSeverity.WARNING if interrupted else EventSeverity.INFO,
            event_type="session_interrupted" if interrupted else "monitoring_finished",
            message="Sessao interrompida." if interrupted else "Monitoramento finalizado.",
            payload={"status": status.value},
        )
        LOGGER.info("Monitoring session finished", extra={"session_id": session_id, "status": status.value})

    def list_incomplete_sessions(self) -> list[MonitoringSession]:
        """Return sessions that did not reach a normal completion state."""
        return self._database.get_incomplete_sessions()

    def session_recovery_stats(self, session_id: str) -> dict[str, object]:
        """Return details for interrupted session recovery UI."""
        return self._database.session_stats(session_id)

    def generate_report_for_session(self, session_id: str, interrupted: bool = False) -> str:
        """Generate evidence package for a persisted session."""
        if interrupted:
            self._database.update_session_status(
                session_id=session_id,
                status=SessionStatus.INTERRUPTED.value,
                finished_at=datetime.now(UTC),
            )
        session = self._database.get_session(session_id)
        if session is None:
            raise ValueError("Sessao nao encontrada.")
        zip_path = generate_report_package(
            database=self._database,
            session=session,
            reports_dir=self._config.paths.reports_dir,
            interrupted=interrupted,
            exclude_warmup_from_summary=self._config.monitoring.exclude_warmup_from_summary,
        )
        return str(zip_path)

    def record_close_attempt(self, session_id: str, source: str) -> None:
        """Record an accidental close attempt while monitoring is active."""
        self._database.store_event(
            session_id=session_id,
            occurred_at=datetime.now(UTC),
            severity=EventSeverity.WARNING,
            event_type="close_attempt",
            message=f"Tentativa de encerramento interceptada: {source}.",
            payload={"source": source},
            origin="manual",
        )

    def archive_session(self, session_id: str) -> None:
        """Archive an incomplete session without deleting evidence."""
        self._database.update_session_status(
            session_id=session_id,
            status=SessionStatus.ARCHIVED.value,
            finished_at=datetime.now(UTC),
        )

    def delete_session(self, session_id: str) -> None:
        """Delete a session after explicit UI confirmation."""
        self._database.delete_session(session_id)
