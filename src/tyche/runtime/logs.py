"""Opening a command's logs in the workspace (ADR-0040)."""

import logging
from collections.abc import Mapping

from tyche.adapters.logs import configure_logging
from tyche.config import EnvFileError, Workspace, load_secrets

_log = logging.getLogger(__name__)


def open_logs(
    workspace: Workspace,
    command: str,
    *,
    environ: Mapping[str, str],
    code_version: str,
    **fields: object,
) -> str | None:
    """Send this process's logs to the workspace's daily file, and log the command.

    Never raises: a command must not fail because its logs cannot be written. Returns
    why logs are off, or ``None``. Only for a workspace that exists, so a mistyped
    ``--home`` creates no folder.

    The secrets in ``.env`` are hidden in every line. If ``.env`` cannot be read, the
    logs still hide anything shaped like a Discord webhook URL.
    """
    if not workspace.tyche_config.is_file():
        return "no workspace"
    try:
        secrets = load_secrets(workspace.env_file, environ).values()
    except EnvFileError:
        secrets = ()
    try:
        configure_logging(workspace.logs_dir, secrets=secrets)
    except OSError as error:
        return f"logs are off for this command: {error}"
    _log.info(
        "command started",
        extra={"fields": {"command": command, "version": code_version, **fields}},
    )
    return None
