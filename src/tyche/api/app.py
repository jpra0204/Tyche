"""The console's server: the API under ``/api``, the built React app everywhere else.

``create_app`` builds it for one workspace and one launch's token; ``serve`` runs it
with uvicorn on ``127.0.0.1``. Routes are thin: each reads through ``tyche.runtime`` or
``tyche.config`` and answers with a model from ``tyche.api.models``.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import APIRouter, Body, Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse, HTMLResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tyche import __version__
from tyche.adapters.clocks import SystemClock
from tyche.api.backtests import RecordNotFoundError, list_backtests, report_html
from tyche.api.data import read_data
from tyche.api.models import (
    BacktestSummary,
    DataView,
    PaperView,
    RunId,
    RunRequest,
    RunView,
    StatusView,
)
from tyche.api.paper import read_paper
from tyche.api.runs import TYCHE, RunBusyError, Runner, RunStartError
from tyche.api.security import LOCAL_HOSTS, TOKEN_HEADER, same_token
from tyche.api.status import read_status
from tyche.config import Workspace
from tyche.core.ports import Clock
from tyche.core.risk import DEFAULT_RISK_PROFILE

HOST = "127.0.0.1"
"""The only address the console listens on (ADR-0046)."""

DEFAULT_PORT = 8765


def default_app_dir() -> Path:
    """Where ``make ui`` puts the built app: ``ui/dist`` in this checkout."""
    return Path(__file__).resolve().parents[3] / "ui" / "dist"


def create_app(
    workspace: Workspace,
    token: str,
    *,
    environ: Mapping[str, str],
    app_dir: Path | None = None,
    clock: Clock | None = None,
    program: Sequence[str] = TYCHE,
) -> FastAPI:
    """The console for ``workspace``, locked with ``token``.

    Args:
        workspace: The workspace every route reads.
        token: This launch's token; every ``/api`` call must carry it in ``X-Tyche-Token``.
        environ: The process environment, for secrets set there (whether, never what).
        app_dir: The built React app to serve, or ``None`` to serve the API alone.
        clock: When runs start and end. Defaults to the system clock.
        program: The ``tyche`` a run starts; tests pass a stand-in.
    """
    runner = Runner(workspace, environ, clock or SystemClock(), program)

    def require_token(
        given: Annotated[str | None, Header(alias=TOKEN_HEADER)] = None,
    ) -> None:
        if not same_token(given, token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or wrong console token")

    app = FastAPI(
        title="Tyche console",
        version=__version__,
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(LOCAL_HOSTS))
    app.state.runner = runner  # for tests, to wait for a run to end

    api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    @api.get("/status", operation_id="getStatus")
    def get_status(
        risk_profile: Annotated[str, Query()] = DEFAULT_RISK_PROFILE,
    ) -> StatusView:
        """The workspace, its config, which secrets are set, what stops trading, and the
        account as the latest checkpoint saved it."""
        return read_status(workspace, risk_profile, environ)

    @api.get("/data", operation_id="getData")
    def get_data() -> DataView:
        """What ``tyche data fetch`` can fetch: the exchanges, and what ``--all`` fetches."""
        return read_data(workspace)

    @api.get("/paper", operation_id="getPaper")
    def get_paper() -> PaperView:
        """The last paper cycle's reconciliations, and the latest alerts from the logs."""
        return read_paper(workspace)

    @api.get("/backtests", operation_id="listBacktests")
    def get_backtests() -> list[BacktestSummary]:
        """Every recorded backtest in the workspace, newest first."""
        return list_backtests(workspace)

    @api.get(
        "/backtests/{run_id}/report",
        operation_id="getBacktestReport",
        response_class=HTMLResponse,
    )
    def get_backtest_report(run_id: RunId) -> HTMLResponse:
        """A backtest's ``report.html``, for the page to show in a sandboxed frame."""
        try:
            html = report_html(workspace, run_id)
        except RecordNotFoundError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
        # Opened by itself, it could run nothing: reports have no script, and this says so.
        return HTMLResponse(html, headers={"Content-Security-Policy": "sandbox"})

    @api.post("/runs", operation_id="startRun", status_code=status.HTTP_201_CREATED)
    def start_run(request: Annotated[RunRequest, Body()]) -> RunView:
        """Start a ``tyche`` command; refused while another is running."""
        try:
            return runner.start(request)
        except RunBusyError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        except RunStartError as error:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(error)) from error

    @api.get("/runs/current", operation_id="getCurrentRun")
    def get_current_run() -> RunView | None:
        """The run going now, or the last one since the console started, with its output."""
        return runner.current()

    app.include_router(api)

    if app_dir is not None:
        root = app_dir.resolve()
        index = root / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        def page(path: str) -> FileResponse:
            """A built file if it exists, else the app's page: its router takes over."""
            if path.startswith("api/"):
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            target = (root / path).resolve()
            if path and target.is_file() and target.is_relative_to(root):
                return FileResponse(target)
            return FileResponse(index)

    return app


def serve(app: FastAPI, port: int = DEFAULT_PORT) -> None:
    """Run ``app`` on ``127.0.0.1:port`` until interrupted."""
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
