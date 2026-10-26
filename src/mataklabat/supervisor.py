"""`python -m mataklabat up`: run monitor and web together and restart them on crash (Spec §12)."""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger(__name__)

BACKOFF_S = (1, 2, 5, 10, 30)
MAX_CRASHES = 5
CRASH_WINDOW_S = 300.0
STOP_GRACE_S = 8.0


@dataclass
class Child:
    name: str
    command: list[str]
    process: subprocess.Popen | None = None
    restart_at: float | None = None
    crashes: deque = field(default_factory=deque)


class Supervisor:
    def __init__(
        self,
        commands: dict[str, list[str]],
        backoff_s: tuple[float, ...] = BACKOFF_S,
        max_crashes: int = MAX_CRASHES,
        crash_window_s: float = CRASH_WINDOW_S,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
        poll_s: float = 0.5,
    ):
        self.children = [Child(name, cmd) for name, cmd in commands.items()]
        self.backoff_s = backoff_s
        self.max_crashes = max_crashes
        self.crash_window_s = crash_window_s
        self._popen = popen
        self._clock = clock
        self.poll_s = poll_s

    def _start(self, child: Child) -> None:
        log.info("Menjalankan %s.", child.name)
        child.process = self._popen(child.command)
        child.restart_at = None

    def step(self) -> bool:
        """Check every child once. Returns False when the supervisor should give up."""
        now = self._clock()
        for child in self.children:
            if child.process is None:
                if child.restart_at is not None and now >= child.restart_at:
                    self._start(child)
                continue
            code = child.process.poll()
            if code is None:
                continue
            child.process = None
            child.crashes.append(now)
            while child.crashes and now - child.crashes[0] > self.crash_window_s:
                child.crashes.popleft()
            if len(child.crashes) > self.max_crashes:
                log.error(
                    "%s berhenti %d kali dalam %.0f menit. Supervisor berhenti; cek log di data/runtime/logs.",
                    child.name, len(child.crashes), self.crash_window_s / 60,
                )
                return False
            delay = self.backoff_s[min(len(child.crashes) - 1, len(self.backoff_s) - 1)]
            child.restart_at = now + delay
            log.warning("%s berhenti (kode %s), dinyalakan ulang dalam %.0f dtk.", child.name, code, delay)
        return True

    def run(self) -> int:
        for child in self.children:
            self._start(child)
        try:
            while self.step():
                time.sleep(self.poll_s)
            return 1
        except KeyboardInterrupt:
            log.info("Ctrl+C diterima, menghentikan semua proses…")
            return 0
        finally:
            self.stop_all()

    def stop_all(self) -> None:
        # On Ctrl+C the children receive it too and stop on their own; give them time first.
        deadline = time.monotonic() + STOP_GRACE_S
        for child in self.children:
            proc = child.process
            if proc is None:
                continue
            try:
                proc.wait(max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except KeyboardInterrupt:
                proc.kill()
        log.info("Semua proses berhenti.")


def default_commands(no_llm: bool = False, host: str | None = None, port: int | None = None) -> dict[str, list[str]]:
    base = [sys.executable, "-m", "mataklabat"]
    monitor = base + ["run"] + (["--no-llm"] if no_llm else [])
    web = base + ["web"] + (["--host", host] if host else []) + (["--port", str(port)] if port else [])
    return {"monitor": monitor, "web": web}
