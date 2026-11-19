"""Where the workspace lives, where it may not, and what `tyche init` creates."""

import stat
from pathlib import Path

import pytest

from tyche.config import (
    DEFAULT_HOME,
    Workspace,
    WorkspaceError,
    check_location,
    init_workspace,
    resolve_home,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def user_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


class TestResolveHome:
    def test_explicit_path_wins(self, tmp_path: Path) -> None:
        chosen = tmp_path / "chosen"
        environ = {"TYCHE_HOME": str(tmp_path / "from-env")}

        assert resolve_home(chosen, environ) == chosen.resolve()

    def test_environment_variable_is_next(self, tmp_path: Path) -> None:
        assert (
            resolve_home(None, {"TYCHE_HOME": str(tmp_path / "ws")}) == (tmp_path / "ws").resolve()
        )

    def test_default_is_tyche_workspace_in_the_home_directory(self) -> None:
        assert resolve_home(None, {}) == Path(DEFAULT_HOME).expanduser().resolve()
        assert DEFAULT_HOME == "~/tyche-workspace"

    def test_tilde_is_expanded(self) -> None:
        assert (
            resolve_home(None, {"TYCHE_HOME": "~/elsewhere"}) == Path.home().resolve() / "elsewhere"
        )

    def test_relative_paths_become_absolute(self) -> None:
        assert resolve_home(Path("relative"), {}).is_absolute()

    @pytest.mark.parametrize("value", ["", "   "])
    def test_an_empty_environment_variable_is_an_error(self, value: str) -> None:
        with pytest.raises(WorkspaceError, match="TYCHE_HOME is set but empty"):
            resolve_home(None, {"TYCHE_HOME": value})


class TestCheckLocation:
    @pytest.mark.parametrize(
        ("folder", "reason"),
        [
            ("Public", "shares it on the local network"),
            ("Desktop", "sync it to iCloud"),
            ("Documents", "sync it to iCloud"),
        ],
    )
    def test_refuses_unsafe_home_folders(self, user_home: Path, folder: str, reason: str) -> None:
        with pytest.raises(WorkspaceError, match=rf"inside ~/{folder}, which .*{reason}"):
            check_location(user_home / folder / "tyche-workspace", user_home=user_home)
        with pytest.raises(WorkspaceError, match=rf"inside ~/{folder}"):
            check_location(user_home / folder, user_home=user_home)

    def test_refuses_the_home_directory_itself(self, user_home: Path) -> None:
        with pytest.raises(WorkspaceError, match="is your home directory"):
            check_location(user_home, user_home=user_home)

    def test_refuses_a_folder_inside_a_git_repository(
        self, tmp_path: Path, user_home: Path
    ) -> None:
        repo = tmp_path / "some-repo"
        (repo / ".git").mkdir(parents=True)

        with pytest.raises(WorkspaceError, match="inside the git repository"):
            check_location(repo / "nested" / "workspace", user_home=user_home)

    def test_refuses_a_folder_inside_the_tyche_repository(self, user_home: Path) -> None:
        with pytest.raises(WorkspaceError, match="inside the git repository"):
            check_location(REPO_ROOT / "workspace", user_home=user_home)

    def test_accepts_a_folder_of_its_own(self, user_home: Path) -> None:
        check_location(user_home / "tyche-workspace", user_home=user_home)

    def test_a_similarly_named_folder_is_not_confused_with_an_unsafe_one(
        self, user_home: Path
    ) -> None:
        check_location(user_home / "PublicNotes" / "ws", user_home=user_home)


class TestInitWorkspace:
    def test_creates_the_configuration_and_support_files(self, user_home: Path) -> None:
        root = user_home / "tyche-workspace"

        workspace = init_workspace(root, user_home=user_home)

        assert workspace == Workspace(root)
        created = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
        assert created == [
            ".env",
            ".gitignore",
            "README.md",
            "config/costs/US.toml",
            "config/markets/US.toml",
            "config/strategies/buy_and_hold.toml",
            "config/strategies/mean_reversion.toml",
            "config/strategies/trend_rotation.toml",
            "config/tyche.toml",
        ]

    def test_the_env_file_is_readable_by_its_owner_only(self, user_home: Path) -> None:
        workspace = init_workspace(user_home / "ws", user_home=user_home)

        mode = stat.S_IMODE(workspace.env_file.stat().st_mode)

        assert mode & (stat.S_IRWXG | stat.S_IRWXO) == 0

    def test_the_env_file_holds_no_values_yet(self, user_home: Path) -> None:
        workspace = init_workspace(user_home / "ws", user_home=user_home)
        assignments = [
            line
            for line in workspace.env_file.read_text().splitlines()
            if line and not line.startswith("#")
        ]

        secrets = [
            line
            for line in assignments
            if line.split("=", 1)[0] in {"DISCORD_WEBHOOK_URL", "IBKR_ACCOUNT_ID"}
        ]
        assert secrets == ["DISCORD_WEBHOOK_URL=", "IBKR_ACCOUNT_ID="]

    def test_gitignore_keeps_secrets_and_runtime_files_out(self, user_home: Path) -> None:
        workspace = init_workspace(user_home / "ws", user_home=user_home)
        ignored = set((workspace.root / ".gitignore").read_text().splitlines())

        assert {".env", "data/", "state/", "logs/", "KILL"} <= ignored

    def test_an_existing_empty_folder_is_used(self, user_home: Path) -> None:
        root = user_home / "ws"
        root.mkdir()

        init_workspace(root, user_home=user_home)

        assert (root / "config" / "tyche.toml").is_file()

    def test_never_overwrites_a_folder_with_contents(self, user_home: Path) -> None:
        root = user_home / "ws"
        root.mkdir()
        (root / "notes.txt").write_text("mine")

        with pytest.raises(WorkspaceError, match="is not empty"):
            init_workspace(root, user_home=user_home)

        assert sorted(p.name for p in root.iterdir()) == ["notes.txt"]

    def test_refuses_a_file_in_the_way(self, user_home: Path) -> None:
        (user_home / "ws").write_text("not a folder")

        with pytest.raises(WorkspaceError, match="is not a folder"):
            init_workspace(user_home / "ws", user_home=user_home)

    def test_checks_the_location_before_creating_anything(self, user_home: Path) -> None:
        target = user_home / "Documents" / "ws"

        with pytest.raises(WorkspaceError, match="inside ~/Documents"):
            init_workspace(target, user_home=user_home)

        assert not target.exists()


def test_the_packaged_env_template_matches_the_repository_example() -> None:
    packaged = REPO_ROOT / "src" / "tyche" / "config" / "templates" / "env.example"

    assert packaged.read_text() == (REPO_ROOT / ".env.example").read_text()
