"""Application entry point."""

from __future__ import annotations

import sys

from src.app.signature import show_signature


def main() -> int:
    """Start the console application."""
    show_signature()

    from pathlib import Path

    from src.app.console_ui import ConsoleUI
    from src.app.session_controller import SessionController
    from src.storage.database import Database
    from src.utils.config_loader import load_config
    from src.utils.logging_config import configure_logging

    app_config = load_config()
    configure_logging(app_config.paths.logs_dir)

    db_path = Path(app_config.paths.data_dir) / "monitoramento.db"
    database = Database(db_path)
    database.initialize()

    controller = SessionController(database=database, app_config=app_config)
    ui = ConsoleUI(controller=controller, app_config=app_config)
    return ui.run()


if __name__ == "__main__":
    sys.exit(main())
