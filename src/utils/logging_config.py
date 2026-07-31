"""Application logging setup."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(logs_dir: str) -> None:
    """Configure rotating logs for the initial application layer."""
    log_path = Path(logs_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    app_handler = RotatingFileHandler(
        log_path / "aplicacao.log",
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    app_handler.setFormatter(formatter)

    logging.basicConfig(level=logging.INFO, handlers=[app_handler], force=True)

