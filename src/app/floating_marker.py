"""Floating customer marker button."""

from __future__ import annotations

import logging
import queue
import threading
from datetime import UTC, datetime
from time import monotonic

from src.storage.models import CustomerMarkSignal

LOGGER = logging.getLogger(__name__)


class FloatingMarkerWindow:
    """Small always-on-top customer button that emits mark signals."""

    def __init__(self, mark_queue: queue.Queue[CustomerMarkSignal], debounce_seconds: float = 3.0) -> None:
        self._mark_queue = mark_queue
        self._debounce_seconds = debounce_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._failed = threading.Event()

    def start(self) -> bool:
        """Start the floating button thread."""
        self._thread = threading.Thread(target=self._run, name="floating-marker", daemon=True)
        self._thread.start()
        started = self._started.wait(timeout=3)
        return started and not self._failed.is_set()

    def stop(self) -> None:
        """Request the window to close and wait briefly for the UI thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def _run(self) -> None:
        try:
            import tkinter as tk
        except ImportError:
            LOGGER.exception("Tkinter is not available")
            self._failed.set()
            self._started.set()
            return

        try:
            root = tk.Tk()
            root.title("InterRats Tracker - Marcador")
            root.attributes("-topmost", True)
            root.resizable(False, False)
            root.protocol("WM_DELETE_WINDOW", lambda: None)
            root.bind("<Alt-F4>", lambda _event: "break")
            root.configure(bg="#101820")

            button = tk.Button(
                root,
                text="MARCAR INSTABILIDADE",
                command=lambda: self._handle_click(button, root),
                bg="#0B5CAD",
                fg="white",
                activebackground="#084A8C",
                activeforeground="white",
                font=("Segoe UI", 10, "bold"),
                relief="flat",
                padx=16,
                pady=10,
                cursor="hand2",
            )
            button.pack(fill="both", expand=True, padx=2, pady=2)

            drag_state = {"x": 0, "y": 0}

            def begin_drag(event: object) -> None:
                drag_state["x"] = getattr(event, "x", 0)
                drag_state["y"] = getattr(event, "y", 0)

            def drag(event: object) -> None:
                x = root.winfo_pointerx() - drag_state["x"]
                y = root.winfo_pointery() - drag_state["y"]
                root.geometry(f"+{x}+{y}")

            button.bind("<ButtonPress-1>", begin_drag)
            button.bind("<B1-Motion>", drag)

            root.update_idletasks()
            width = max(root.winfo_width(), 220)
            height = max(root.winfo_height(), 54)
            screen_width = root.winfo_screenwidth()
            screen_height = root.winfo_screenheight()
            x = max(0, screen_width - width - 24)
            y = max(0, screen_height - height - 72)
            root.geometry(f"{width}x{height}+{x}+{y}")

            self._started.set()
            self._poll_stop(root)
            root.mainloop()
        except Exception:
            LOGGER.exception("Floating marker window failed")
            self._failed.set()
            self._started.set()

    def _handle_click(self, button: object, root: object) -> None:
        now_monotonic = monotonic()
        last_click = getattr(self, "_last_click_monotonic", 0.0)
        if now_monotonic - last_click < self._debounce_seconds:
            return
        self._last_click_monotonic = now_monotonic
        try:
            self._mark_queue.put_nowait(CustomerMarkSignal(marked_at=datetime.now(UTC)))
        except queue.Full:
            LOGGER.warning("Customer mark queue is full; mark ignored")
            return

        button.configure(text="EVENTO REGISTRADO", state="disabled", bg="#1F7A4D")

        def reset() -> None:
            button.configure(text="MARCAR INSTABILIDADE", state="normal", bg="#0B5CAD")

        root.after(int(self._debounce_seconds * 1000), reset)

    def _poll_stop(self, root: object) -> None:
        if self._stop_event.is_set():
            root.destroy()
            return
        root.after(200, lambda: self._poll_stop(root))
