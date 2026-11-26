"""Running ``tyche`` from the page: one command at a time, as a subprocess (ADR-0046).

A run started from the page is the CLI itself. The page names a command and its options
with a typed request (``tyche.api.models``); ``arguments`` turns that into the command's
argument list, never a shell string, so a form can ask only for what the command offers,
and the command makes every check it makes in the terminal (the holdout, the config,
the cache). Its two output streams are read line by line as it prints them and kept
with the run, so the page can show them while it runs and after it ends.

One run at a time: ``Runner.start`` refuses a second while the first is running. The
last run is kept in memory until the next one starts; what it wrote (``reports/``, the
cache) is in the workspace, as after a run in the terminal.
"""

import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import IO, Literal

from tyche.api.models import (
    BacktestRequest,
    FetchRequest,
    ReportRequest,
    RunLine,
    RunView,
)
from tyche.config import Workspace
from tyche.core.ports import Clock

TYCHE: tuple[str, ...] = (sys.executable, "-m", "tyche")
"""The command a run starts: this Python's ``tyche``, the same code as the console."""


class RunBusyError(Exception):
    """A run was asked for while another is still running."""


class RunStartError(Exception):
    """The command could not be started at all."""


def arguments(request: FetchRequest | BacktestRequest | ReportRequest) -> list[str]:
    """The command's arguments for ``request``, as typed in a terminal after ``tyche``.

    ``--home`` is not among them: the runner adds it, for the console's workspace.
    """
    match request:
        case FetchRequest():
            args = ["data", "fetch"]
            if request.every_candidate:
                args.append("--all")
            args.extend(request.symbols)
            if request.exchange is not None:
                args.extend(["--exchange", request.exchange])
            if request.asset_class is not None:
                args.extend(["--asset-class", request.asset_class])
            if request.first is not None:
                args.extend(["--from", request.first.isoformat()])
            if request.last is not None:
                args.extend(["--to", request.last.isoformat()])
            return args
        case BacktestRequest():
            args = ["backtest", "--from", request.first.isoformat()]
            if request.last is not None:
                args.extend(["--to", request.last.isoformat()])
            args.extend(["--risk-profile", request.risk_profile])
            return args
        case ReportRequest():
            return ["report", request.run_id]


@dataclass
class _Run:
    number: int
    command: Literal["data_fetch", "backtest", "report"]
    argv: list[str]
    started_at: datetime
    process: subprocess.Popen[str]
    clock: Clock
    lines: list[RunLine] = field(default_factory=list)
    finished_at: datetime | None = None
    exit_code: int | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    done: threading.Event = field(default_factory=threading.Event)

    def follow(self) -> None:
        """Read both streams on their own threads, then wait for the process to end."""
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        readers = [
            threading.Thread(target=self._read, args=(self.process.stdout, "out"), daemon=True),
            threading.Thread(target=self._read, args=(self.process.stderr, "err"), daemon=True),
        ]
        for reader in readers:
            reader.start()
        threading.Thread(target=self._wait, args=(readers,), daemon=True).start()

    def _read(self, stream: IO[str], name: Literal["out", "err"]) -> None:
        for text in stream:
            with self.lock:
                self.lines.append(RunLine(stream=name, text=text.rstrip("\r\n")))
        stream.close()

    def _wait(self, readers: Sequence[threading.Thread]) -> None:
        for reader in readers:
            reader.join()
        code = self.process.wait()
        with self.lock:
            self.exit_code = code
            self.finished_at = self.clock.now()
        self.done.set()

    @property
    def running(self) -> bool:
        with self.lock:
            return self.exit_code is None

    def view(self) -> RunView:
        with self.lock:
            code = self.exit_code
            return RunView(
                number=self.number,
                command=self.command,
                argv=self.argv,
                started_at=self.started_at,
                finished_at=self.finished_at,
                exit_code=code,
                state="running" if code is None else "succeeded" if code == 0 else "failed",
                lines=list(self.lines),
            )


class Runner:
    """Starts ``tyche`` commands for one workspace, one at a time.

    Args:
        workspace: Every command runs with ``--home`` set to it.
        environ: The environment each command gets, as the terminal would give it.
        clock: When each run starts and ends.
        program: What to start; tests pass a stand-in. Everything else uses ``TYCHE``.
    """

    def __init__(
        self,
        workspace: Workspace,
        environ: Mapping[str, str],
        clock: Clock,
        program: Sequence[str] = TYCHE,
    ) -> None:
        self._workspace = workspace
        # Output as it is printed, not when a buffer fills.
        self._environ = {**environ, "PYTHONUNBUFFERED": "1"}
        self._clock = clock
        self._program = list(program)
        self._lock = threading.Lock()
        self._current: _Run | None = None
        self._count = 0

    def start(self, request: FetchRequest | BacktestRequest | ReportRequest) -> RunView:
        """Start the command ``request`` names.

        Raises:
            RunBusyError: Another run is still running.
            RunStartError: The command could not be started.
        """
        args = arguments(request)
        with self._lock:
            current = self._current
            if current is not None and current.running:
                raise RunBusyError(
                    f"run {current.number} ({' '.join(current.argv)}) is still running; "
                    "wait for it to end"
                )
            root = str(self._workspace.root)
            try:
                process = subprocess.Popen(
                    [*self._program, *args, "--home", root],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    cwd=root,
                    env=self._environ,
                )
            except OSError as error:
                raise RunStartError(f"could not start tyche: {error}") from error
            self._count += 1
            run = _Run(
                number=self._count,
                command=request.command,
                argv=["tyche", *args],
                started_at=self._clock.now(),
                process=process,
                clock=self._clock,
            )
            self._current = run
            run.follow()
        return run.view()

    def current(self) -> RunView | None:
        """The run going now, or the last one, or ``None`` before the first."""
        with self._lock:
            run = self._current
        return run.view() if run is not None else None

    def wait(self, timeout: float | None = None) -> RunView | None:
        """Wait for the current run to end (for tests, and for a clean shutdown)."""
        with self._lock:
            run = self._current
        if run is None:
            return None
        run.done.wait(timeout)
        return run.view()
