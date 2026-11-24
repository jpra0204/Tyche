"""Reading secrets from ``.env`` with the standard library (ADR-0040)."""

from pathlib import Path

import pytest

from tyche.config import EnvFileError, Secrets, load_secrets, parse_env, readable_by_others

WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/abc-DEF_123"
OTHER_WEBHOOK = "https://discord.com/api/webhooks/987654321098765432/zzz"


class TestParse:
    def test_reads_keys_and_values_and_skips_comments_and_blank_lines(self) -> None:
        text = f"# a comment\n\nDISCORD_WEBHOOK_URL={WEBHOOK}\n  IBKR_HOST = 127.0.0.1  \n"
        assert parse_env(text) == {"DISCORD_WEBHOOK_URL": WEBHOOK, "IBKR_HOST": "127.0.0.1"}

    def test_an_empty_value_is_not_given(self) -> None:
        assert parse_env("DISCORD_WEBHOOK_URL=\nIBKR_PORT=''\n") == {}

    @pytest.mark.parametrize("quote", ['"', "'"])
    def test_removes_matching_quotes_and_interprets_nothing_inside(self, quote: str) -> None:
        text = f"IBKR_ACCOUNT_ID={quote}a #b ${{HOME}}{quote}"
        assert parse_env(text) == {"IBKR_ACCOUNT_ID": "a #b ${HOME}"}

    def test_the_value_is_everything_after_the_first_equals(self) -> None:
        assert parse_env("IBKR_ACCOUNT_ID=a=b") == {"IBKR_ACCOUNT_ID": "a=b"}

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("DISCORD_WEBHOOK_URL", "line 1: expected KEY=value"),
            ("export IBKR_HOST=x", "is not a key"),
            ("ibkr_host=x", "is not a key"),
            ("DISCORD_WEBHOOK=x", "unknown key DISCORD_WEBHOOK"),
            ("IBKR_HOST=a\nIBKR_HOST=b", "line 2: IBKR_HOST is given twice"),
            ("IBKR_ACCOUNT_ID='abc", "unmatched '"),
            ('IBKR_ACCOUNT_ID="', 'unmatched "'),
            ("IBKR_ACCOUNT_ID=abc # mine", "comment after it"),
        ],
    )
    def test_refuses_anything_else(self, text: str, message: str) -> None:
        with pytest.raises(EnvFileError, match=message):
            parse_env(text)

    def test_an_error_never_shows_a_value(self) -> None:
        with pytest.raises(EnvFileError) as raised:
            parse_env("IBKR_ACCOUNT_ID='U1234567 # private")
        assert "U1234567" not in str(raised.value)


class TestLoad:
    def test_reads_the_file(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text(f"DISCORD_WEBHOOK_URL={WEBHOOK}\nIBKR_ACCOUNT_ID=DU111\n")
        secrets = load_secrets(env, {})
        assert secrets.discord_webhook_url is not None
        assert secrets.discord_webhook_url.get_secret_value() == WEBHOOK
        assert secrets.ibkr_account_id is not None
        assert secrets.ibkr_account_id.get_secret_value() == "DU111"

    def test_a_missing_file_means_no_secrets(self, tmp_path: Path) -> None:
        assert load_secrets(tmp_path / ".env", {}) == Secrets()

    def test_the_environment_wins_over_the_file(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text(f"DISCORD_WEBHOOK_URL={WEBHOOK}\n")
        secrets = load_secrets(env, {"DISCORD_WEBHOOK_URL": OTHER_WEBHOOK})
        assert secrets.discord_webhook_url is not None
        assert secrets.discord_webhook_url.get_secret_value() == OTHER_WEBHOOK

    def test_an_empty_environment_variable_does_not_hide_the_file(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text(f"DISCORD_WEBHOOK_URL={WEBHOOK}\n")
        secrets = load_secrets(env, {"DISCORD_WEBHOOK_URL": ""})
        assert secrets.discord_webhook_url is not None

    def test_the_environment_alone_is_enough(self, tmp_path: Path) -> None:
        secrets = load_secrets(tmp_path / ".env", {"DISCORD_WEBHOOK_URL": WEBHOOK})
        assert secrets.discord_webhook_url is not None

    @pytest.mark.parametrize(
        "url",
        [
            "http://discord.com/api/webhooks/1/abc",  # not https
            "https://discord.com.evil.example/api/webhooks/1/abc",
            "https://discord.com/api/webhooks/abc/def",  # the id is a number
            f"{WEBHOOK} trailing",
        ],
    )
    def test_refuses_what_is_not_a_discord_webhook_without_showing_it(
        self, tmp_path: Path, url: str
    ) -> None:
        env = tmp_path / ".env"
        env.write_text(f'DISCORD_WEBHOOK_URL="{url}"\n')
        with pytest.raises(EnvFileError, match="not a Discord webhook URL") as raised:
            load_secrets(env, {})
        assert url not in str(raised.value)

    @pytest.mark.parametrize(
        "url",
        [
            WEBHOOK,
            "https://discordapp.com/api/webhooks/1/abc",
            "https://ptb.discord.com/api/v10/webhooks/1/abc",
        ],
    )
    def test_accepts_the_webhook_forms_discord_gives(self, tmp_path: Path, url: str) -> None:
        assert load_secrets(tmp_path / ".env", {"DISCORD_WEBHOOK_URL": url}).values() == (url,)

    def test_the_new_workspace_template_is_valid(self) -> None:
        template = Path(__file__).parents[2] / "src/tyche/config/templates/env.example"
        assert load_secrets(template, {}) == Secrets()


class TestSecrets:
    def test_never_print(self, tmp_path: Path) -> None:
        secrets = load_secrets(tmp_path / ".env", {"DISCORD_WEBHOOK_URL": WEBHOOK})
        assert WEBHOOK not in repr(secrets)
        assert WEBHOOK not in str(secrets)

    def test_values_lists_each_secret_once_longest_first(self, tmp_path: Path) -> None:
        environ = {"DISCORD_WEBHOOK_URL": WEBHOOK, "IBKR_ACCOUNT_ID": "DU111"}
        assert load_secrets(tmp_path / ".env", environ).values() == (WEBHOOK, "DU111")


class TestReadableByOthers:
    def test_a_private_file_is_not(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.touch(mode=0o600)
        env.chmod(0o600)
        assert not readable_by_others(env)

    def test_a_group_readable_file_is(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.touch()
        env.chmod(0o640)
        assert readable_by_others(env)

    def test_a_missing_file_is_not(self, tmp_path: Path) -> None:
        assert not readable_by_others(tmp_path / ".env")
