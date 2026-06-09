"""
Investigation manager — runs the OSINT agent in a background thread and
buffers every output event so SSE clients can reconnect at any time.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import traceback
import uuid
from datetime import datetime
from typing import Optional

from paw_agent.engine.pipeline import run_investigation as run_agent

# ── Step marker → (step_id, label, phase) ──────────────────────
_STEP_MARKERS: list[tuple[str, str, str, int]] = [
    ("[Step 0]",    "step0",     "Surname demographics",    1),
    ("[Step 0.5]",  "step0_5",   "Diplomas",                1),
    ("[Step 0.7]",  "step0_7",   "Business registries",     1),
    ("[Step 0.8]",  "step0_8",   "Directories",             1),
    ("[Step 0.9]",  "step0_9",   "Phone OSINT",             1),
    ("[Step 0.93]", "step0_93",  "Username pre-validation", 1),
    ("[Step 0.95]", "step0_95",  "Instagram",               1),
    ("[Step 0.95c]","step0_95c", "TikTok",                  1),
    ("[Step 0.95d]","step0_95d", "LinkedIn",                1),
    ("[Step 0.96]", "step0_96",  "Multi-platform",          1),
    ("[Step 1/4]",  "step1",     "Email generation",        2),
    ("[Step 2/4]",  "step2",     "SMTP validation",         2),
    ("[Step 2b]",   "step2b",    "GHunt",                   2),
    ("[Step 3/4]",  "step3",     "HIBP breach check",       2),
    ("[Step 4/4]",  "step4",     "Intelligence report",     2),
]


def _detect_step(line: str) -> dict | None:
    """Return a progress event if line contains a known step marker, else None."""
    for marker, step_id, label, phase in _STEP_MARKERS:
        if marker in line:
            return {
                "type":  "progress",
                "step":  step_id,
                "label": label,
                "phase": phase,
                "status": "running",
            }
    return None

_HISTORY_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "history")
)


def _save_history(target: dict, report: dict) -> None:
    """Persist a completed investigation to history/ as a JSON file."""
    try:
        os.makedirs(_HISTORY_DIR, exist_ok=True)
        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        fn    = "_".join(filter(None, [
            ts,
            target.get("firstname", ""),
            target.get("lastname", ""),
        ])).replace(" ", "_")
        path  = os.path.join(_HISTORY_DIR, f"{fn}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"target": target, "report": report, "saved_at": ts}, f,
                      ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass


class Investigation:
    def __init__(self, inv_id: str, target: dict):
        self.inv_id = inv_id
        self.target = target
        self.log: list[dict] = []   # all events, buffered forever
        self.done   = False
        self.report: dict = {}      # last completed report (for "Save as Case")
        self._lock = threading.Lock()
        self._confirm_event  = threading.Event()
        self._confirm_action = "stop"

    def _callback(self, line: str) -> None:
        with self._lock:
            self.log.append({"type": "log", "text": line})
            prog = _detect_step(line)
            if prog:
                self.log.append(prog)

    def _report_callback(self, report: dict) -> None:
        _save_history(self.target, report)
        with self._lock:
            self.report = report
            self.log.append({"type": "report", "data": report})

    def _event_callback(self, event: dict) -> None:
        with self._lock:
            self.log.append(event)

    def wait_for_confirmation(self) -> str:
        self._confirm_event.clear()
        self._confirm_event.wait(timeout=600)  # 10-min safety timeout
        return self._confirm_action

    def confirm(self, action: str) -> None:
        self._confirm_action = action
        self._confirm_event.set()

    def start(self) -> None:
        def _thread():
            try:
                asyncio.run(run_agent(
                    firstname         = self.target.get("firstname", ""),
                    lastname          = self.target.get("lastname", ""),
                    birth_year        = self.target.get("birth_year", ""),
                    keywords          = self.target.get("keywords", []),
                    cities            = self.target.get("cities", []),
                    phone             = self.target.get("phone", ""),
                    pseudo            = self.target.get("pseudo", ""),
                    modules           = self.target.get("modules", ["demographics", "diplomas", "email", "phone", "social_media"]),
                    callback          = self._callback,
                    report_callback   = self._report_callback,
                    event_callback    = self._event_callback,
                    confirmation_wait = self.wait_for_confirmation,
                ))
            except Exception as exc:
                tb = traceback.format_exc()
                with self._lock:
                    self.log.append({"type": "error", "text": f"{exc}\n{tb[-800:]}"})
            except BaseException as exc:
                tb = traceback.format_exc()
                with self._lock:
                    self.log.append({"type": "error", "text": f"{type(exc).__name__}: {exc}\n{tb[-800:]}"})
            finally:
                with self._lock:
                    self.log.append({"type": "done", "text": ""})
                    self.done = True

        threading.Thread(target=_thread, daemon=True).start()

    def stream_events(self, start_idx: int = 0):
        """
        Yield all buffered events from start_idx, then live events until done.
        Yields {"type": "ping"} every ~15 s of idle time to keep SSE alive.
        """
        idx       = start_idx
        last_ping = time.monotonic()

        while True:
            with self._lock:
                chunk   = list(self.log[idx:])
                is_done = self.done and (idx + len(chunk) >= len(self.log))

            for event in chunk:
                yield event
                idx += 1

            if is_done:
                break

            if not chunk:
                now = time.monotonic()
                if now - last_ping >= 15:
                    yield {"type": "ping"}
                    last_ping = now
                time.sleep(0.2)


# ── Global store ──────────────────────────────────────────────
_active: dict[str, Investigation] = {}


def start_investigation(target: dict) -> str:
    inv_id        = uuid.uuid4().hex[:8]
    inv           = Investigation(inv_id, target)
    _active[inv_id] = inv
    inv.start()
    return inv_id


def get_investigation(inv_id: str) -> Optional[Investigation]:
    return _active.get(inv_id)
