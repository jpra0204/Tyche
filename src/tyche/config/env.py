"""Secrets from the workspace's ``.env`` file, read with the standard library (ADR-0040).

The file holds secrets only (ADR-0010); everything else is in the TOML config. The
format is deliberately small, so that what is in the file is exactly what Tyche reads:

* One ``KEY=value`` per line. Blank lines and lines starting with ``#`` are ignored.
* The value is everything after the first ``=``, without surrounding spaces. It may be
  wrapped in matching single or double quotes, which are removed; nothing inside them
  is interpreted.
* No ``export``, no ``${VAR}`` expansion, no comment after a value, no key twice.
* Only the keys Tyche knows. A misspelt key is an error, not a secret silently unused.
* An empty value means the setting is not given.

A variable set in the process environment wins over the file. That is how Docker will
pass secrets in (Phase 2, PR 18), and it lets one command use another webhook.

Error messages name the file, the line and the key, never a value.
"""

import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import SecretStr

from tyche.config.loader import ConfigError

DISCORD_WEBHOOK_URL = "DISCORD_WEBHOOK_URL"

KNOWN_KEYS = (
    "TYCHE_HOME",
    DISCORD_WEBHOOK_URL,
    "IBKR_HOST",
    "IBKR_PORT",
    "IBKR_CLIENT_ID",
    "IBKR_ACCOUNT_ID",
)
"""Every key ``.env`` may hold. ``TYCHE_HOME`` is read from the process environment
before the workspace is known, so in the workspace's own file it is only a note. The
``IBKR_`` keys are read from Phase 2, PR 11; until then they are accepted and unused."""

SECRET_KEYS = frozenset({DISCORD_WEBHOOK_URL, "IBKR_ACCOUNT_ID"})
"""Keys whose values must never appear in a log, a message or a report."""

_KEY = re.compile(r"[A-Z][A-Z0-9_]*")

_WEBHOOK = re.compile(
    r"https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api(?:/v\d+)?/webhooks/\d+/[\w-]+"
)
"""A Discord channel webhook: ``https://discord.com/api/webhooks/<id>/<token>``."""


class EnvFileError(ConfigError):
    """The ``.env`` file or a secret in it is not valid. Never contains a secret."""


@dataclass(frozen=True, slots=True)
class Secrets:
    """The secrets Tyche uses, each hidden from ``repr`` and ``str``.

    Attributes:
        discord_webhook_url: The Discord channel's webhook, or ``None`` if not given.
        ibkr_account_id: The IBKR account id, or ``None``; used from Phase 2, PR 11.
    """

    discord_webhook_url: SecretStr | None = None
    ibkr_account_id: SecretStr | None = None

    def values(self) -> tuple[str, ...]:
        """Every secret given, for the log filter to hide. Longest first."""
        given = (self.discord_webhook_url, self.ibkr_account_id)
        found = {secret.get_secret_value() for secret in given if secret is not None}
        return tuple(sorted(found, key=lambda value: (-len(value), value)))


def parse_env(text: str, source: str = ".env") -> dict[str, str]:
    """The keys and values in ``.env`` ``text``, empty values left out.

    Raises:
        EnvFileError: A line is not ``KEY=value``, a key is unknown or given twice, or a
            value has an unmatched quote or a comment after it.
    """
    found: dict[str, str] = {}
    seen: set[str] = set()
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        where = f"{source}, line {number}"
        if "=" not in line:
            raise EnvFileError(f"{where}: expected KEY=value")
        key, value = (part.strip() for part in line.split("=", 1))
        if not _KEY.fullmatch(key):
            raise EnvFileError(
                f"{where}: {key!r} is not a key; keys are capital letters, digits and "
                "underscores (no `export`)"
            )
        if key not in KNOWN_KEYS:
            raise EnvFileError(f"{where}: unknown key {key}; known keys: {', '.join(KNOWN_KEYS)}")
        if key in seen:
            raise EnvFileError(f"{where}: {key} is given twice")
        seen.add(key)
        value = _unquote(value, where, key)
        if value:
            found[key] = value
    return found


def load_secrets(env_file: Path, environ: Mapping[str, str]) -> Secrets:
    """The secrets from ``env_file``, overridden by any set in ``environ``.

    A missing file means no secrets: everything that needs one says so when it is used.

    Raises:
        EnvFileError: The file cannot be read or parsed, or a secret is malformed.
    """
    try:
        text = env_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    except (OSError, UnicodeDecodeError) as error:
        raise EnvFileError(f"cannot read {env_file}: {error}") from error
    values = parse_env(text, str(env_file))
    for key in KNOWN_KEYS:
        if environ.get(key):
            values[key] = environ[key]
    webhook = values.get(DISCORD_WEBHOOK_URL)
    if webhook is not None and not _WEBHOOK.fullmatch(webhook):
        raise EnvFileError(
            f"{DISCORD_WEBHOOK_URL} is not a Discord webhook URL; it should look like "
            "https://discord.com/api/webhooks/<id>/<token> (value not shown)"
        )
    account = values.get("IBKR_ACCOUNT_ID")
    return Secrets(
        discord_webhook_url=SecretStr(webhook) if webhook is not None else None,
        ibkr_account_id=SecretStr(account) if account is not None else None,
    )


def readable_by_others(env_file: Path) -> bool:
    """True when ``env_file`` exists and its group or anyone else may read or change it.

    ``tyche init`` creates it readable by its owner only; a copy or an editor can change
    that.
    """
    try:
        mode = env_file.stat().st_mode
    except FileNotFoundError:
        return False
    return bool(mode & (stat.S_IRWXG | stat.S_IRWXO))


def _unquote(value: str, where: str, key: str) -> str:
    if value[:1] in {'"', "'"}:
        quote = value[0]
        if len(value) < 2 or not value.endswith(quote):
            raise EnvFileError(f"{where}: the value of {key} has an unmatched {quote}")
        return value[1:-1]
    if " #" in value or "\t#" in value:
        raise EnvFileError(
            f"{where}: the value of {key} has a comment after it; put comments on their "
            "own line, or quote the value if # is part of it"
        )
    return value
