import subprocess
import sys

from mataklabat.supervisor import Supervisor, default_commands


class FakeProcess:
    def __init__(self, exits_after: int | None):
        self.polls = 0
        self.exits_after = exits_after
        self.terminated = False

    def poll(self):
        self.polls += 1
        if self.exits_after is not None and self.polls > self.exits_after:
            return 1
        return None

    def wait(self, timeout=None):
        if self.exits_after is None and not self.terminated:
            raise subprocess.TimeoutExpired("x", timeout)
        return 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_crashed_child_is_restarted_with_backoff():
    started = []

    def popen(cmd):
        started.append(cmd[0])
        return FakeProcess(exits_after=0 if cmd[0] == "crashy" and len(started) == 1 else None)

    clock = Clock()
    sup = Supervisor({"a": ["crashy"], "b": ["stable"]}, backoff_s=(2, 5), popen=popen, clock=clock)
    for child in sup.children:
        sup._start(child)
    assert sup.step() is True  # crashy exits
    crashy = sup.children[0]
    assert crashy.process is None and crashy.restart_at == 2
    clock.t = 1
    sup.step()
    assert started == ["crashy", "stable"]  # still waiting for backoff
    clock.t = 2
    sup.step()
    assert started == ["crashy", "stable", "crashy"] and crashy.process is not None


def test_gives_up_after_too_many_crashes():
    clock = Clock()
    sup = Supervisor({"a": ["boom"]}, backoff_s=(0,), max_crashes=2, popen=lambda cmd: FakeProcess(0), clock=clock)
    sup._start(sup.children[0])
    results = []
    for _ in range(6):
        clock.t += 1
        results.append(sup.step())
    # crash, restart, crash, restart, then the 3rd crash exceeds max_crashes=2
    assert results[:4] == [True] * 4 and results[4] is False


def test_stop_all_terminates_stuck_children():
    proc = FakeProcess(exits_after=None)
    sup = Supervisor({"a": ["x"]}, popen=lambda cmd: proc)
    sup._start(sup.children[0])
    import mataklabat.supervisor as s

    old, s.STOP_GRACE_S = s.STOP_GRACE_S, 0.01
    try:
        sup.stop_all()
    finally:
        s.STOP_GRACE_S = old
    assert proc.terminated


def test_default_commands():
    cmds = default_commands(no_llm=True, host="0.0.0.0", port=9000)
    assert cmds["monitor"] == [sys.executable, "-m", "mataklabat", "run", "--no-llm"]
    assert cmds["web"][-4:] == ["--host", "0.0.0.0", "--port", "9000"]


def test_real_processes_restart(tmp_path):
    marker = tmp_path / "runs.txt"
    script = f"open(r'{marker}', 'a').write('x'); raise SystemExit(3)"
    sup = Supervisor({"p": [sys.executable, "-c", script]}, backoff_s=(0,), max_crashes=2, poll_s=0.05)
    assert sup.run() == 1  # gives up after repeated crashes
    assert len(marker.read_text()) == 3
