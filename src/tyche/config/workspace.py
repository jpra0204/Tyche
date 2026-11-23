"""The workspace: the private folder that holds the user's config, data and state.

The code repository is public; everything specific to the user lives here instead
(ADR-0008). This module knows where the workspace is, what is inside it, and how to
create a new one.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

DEFAULT_HOME = "~/tyche-workspace"
HOME_ENV_VAR = "TYCHE_HOME"

# Folders under the user's home directory that must never hold the workspace.
_UNSAFE_HOME_FOLDERS = {
    "Public": "macOS shares it on the local network when File Sharing is on",
    "Desktop": "macOS can sync it to iCloud",
    "Documents": "macOS can sync it to iCloud",
}

# Template file in the package -> where `tyche init` writes it in the workspace.
_TEMPLATES = {
    "tyche.toml": "config/tyche.toml",
    "markets/US.toml": "config/markets/US.toml",
    "costs/US.toml": "config/costs/US.toml",
    "strategies/buy_and_hold.toml": "config/strategies/buy_and_hold.toml",
    "strategies/mean_reversion.toml": "config/strategies/mean_reversion.toml",
    "strategies/trend_rotation.toml": "config/strategies/trend_rotation.toml",
    "sweeps/trend_rotation.toml": "config/sweeps/trend_rotation.toml",
    "env.example": ".env",
    "gitignore": ".gitignore",
    "README.md": "README.md",
}


class WorkspaceError(Exception):
    """The workspace cannot be found, used or created where it was asked to be."""


@dataclass(frozen=True, slots=True)
class Workspace:
    """Paths inside a workspace. Creating this object touches nothing on disk."""

    root: Path

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def tyche_config(self) -> Path:
        return self.config_dir / "tyche.toml"

    @property
    def markets_dir(self) -> Path:
        return self.config_dir / "markets"

    @property
    def costs_dir(self) -> Path:
        return self.config_dir / "costs"

    @property
    def strategies_dir(self) -> Path:
        """One file per strategy instance: its plugin and parameters (ADR-0022)."""
        return self.config_dir / "strategies"

    @property
    def sweeps_dir(self) -> Path:
        """One file per parameter sweep: a strategy and the values to try (ADR-0030)."""
        return self.config_dir / "sweeps"

    @property
    def env_file(self) -> Path:
        return self.root / ".env"

    @property
    def data_dir(self) -> Path:
        """Market data. Gitignored: it is large and can be fetched again."""
        return self.root / "data"

    @property
    def reports_dir(self) -> Path:
        """Backtest records and reports. Committed: each says which code and config made it."""
        return self.root / "reports"

    def relative(self, path: Path) -> str:
        """``path`` relative to the workspace root, for messages."""
        return path.relative_to(self.root).as_posix()


def resolve_home(explicit: Path | None, environ: Mapping[str, str]) -> Path:
    """Decide where the workspace is, as an absolute path.

    In order: ``explicit`` (the ``--home`` option), then the ``TYCHE_HOME`` environment
    variable, then ``~/tyche-workspace``. A ``~`` is expanded.
    """
    if explicit is not None:
        raw = str(explicit)
    elif HOME_ENV_VAR in environ:
        raw = environ[HOME_ENV_VAR]
        if not raw.strip():
            raise WorkspaceError(f"{HOME_ENV_VAR} is set but empty; unset it or give a path")
    else:
        raw = DEFAULT_HOME
    return Path(raw).expanduser().resolve()


def check_location(root: Path, *, user_home: Path) -> None:
    """Refuse places where a private workspace could leak or end up committed.

    Raises ``WorkspaceError`` if ``root`` is the home directory itself, is inside
    ``~/Public``, ``~/Desktop`` or ``~/Documents``, or is inside an existing git
    repository (such as the Tyche code repository).
    """
    root = root.resolve()
    user_home = user_home.resolve()
    if root == user_home:
        raise WorkspaceError(f"{root} is your home directory; use a folder of its own")
    for folder, reason in _UNSAFE_HOME_FOLDERS.items():
        unsafe = user_home / folder
        if root == unsafe or unsafe in root.parents:
            raise WorkspaceError(
                f"{root} is inside ~/{folder}, which {reason}; choose another place"
            )
    for ancestor in root.parents:
        if (ancestor / ".git").exists():
            raise WorkspaceError(
                f"{root} is inside the git repository at {ancestor}; private files could be "
                "committed there by mistake, so choose a folder outside it"
            )


def init_workspace(root: Path, *, user_home: Path) -> Workspace:
    """Create a new workspace at ``root`` from the templates shipped with Tyche.

    ``root`` may already exist only as an empty folder. Nothing is overwritten.
    The ``.env`` file is created readable by its owner only.
    """
    check_location(root, user_home=user_home)
    if root.exists():
        if not root.is_dir():
            raise WorkspaceError(f"{root} exists and is not a folder")
        if any(root.iterdir()):
            raise WorkspaceError(
                f"{root} is not empty; tyche init only creates a new workspace and never "
                "overwrites one"
            )

    workspace = Workspace(root)
    templates = files("tyche.config") / "templates"
    for template, destination in _TEMPLATES.items():
        target = root / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        if destination == ".env":
            # Create it private before anything is written to it.
            target.touch(mode=0o600, exist_ok=False)
        target.write_text(
            templates.joinpath(*template.split("/")).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    return workspace
