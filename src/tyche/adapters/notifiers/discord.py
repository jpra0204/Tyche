"""Alerts to a Discord channel through its webhook (ADR-0040, brief §9).

One HTTP POST per alert, with the standard library's ``urllib``: a few messages a day
need no HTTP client library. What Discord's documentation says, checked 2026-11-23 on
docs.discord.com (``resources/webhook``, ``topics/rate-limits``, ``reference``):

* A message's ``content`` holds up to 2,000 characters. Longer alerts are cut.
* ``?wait=true`` makes Discord confirm that the message was saved, so a message that
  was not saved is an error instead of a silent ``204``.
* Rate limits are not to be hard-coded. Each response says, in ``X-RateLimit-*``
  headers, how many requests are left and when the bucket resets; a ``429`` says how
  many seconds to wait in ``retry_after``. Tyche waits that long, up to a limit, and
  tries once more.
* A webhook that answers ``404`` must not be used again: repeated attempts are
  restricted. A ``401``, ``403`` or ``404`` retires this notifier for the rest of the
  process.
* Every request carries a ``User-Agent`` of the form ``DiscordBot (url, version)``;
  without one, requests may be blocked.

``allowed_mentions`` is empty, so no text in an alert (a kill switch's reason, a data
issue) can ping ``@everyone``. The webhook URL is the secret: it is never in an error
message, and the log filter hides it as a second line of defence.
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr

from tyche.core.ports import Alert, NotifierError

PROJECT_URL = "https://github.com/jpra0204/Tyche"
"""Named in the User-Agent Discord asks for. The repository is public."""

MAX_CONTENT = 2000
"""Characters in a message's ``content`` (Discord's documented limit)."""

DEFAULT_TIMEOUT = 10.0
"""Seconds to wait for Discord before giving up on one request."""

DEFAULT_MAX_WAIT = 30.0
"""The longest Tyche waits for a rate limit before giving up on an alert."""

_CUT = "\n… (cut to fit Discord's limit; the full alert is in the logs)"

_MARKDOWN = str.maketrans({"*": r"\*", "_": r"\_", "~": r"\~", "|": r"\|"})


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """What came back: the status, the headers with lower-case names, the body."""

    status: int
    headers: Mapping[str, str]
    body: bytes


type Transport = Callable[[str, bytes, Mapping[str, str], float], HttpResponse]
"""POSTs a body to a URL with headers and a timeout. Raises ``OSError`` if unreachable."""


def urllib_post(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> HttpResponse:
    """The real transport. An HTTP error status is a response, not an exception."""
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(response.status, _lower(response.headers.items()), response.read())
    except urllib.error.HTTPError as error:
        with error:
            return HttpResponse(error.code, _lower(error.headers.items()), error.read())


class DiscordWebhookNotifier:
    """A ``Notifier`` that posts each alert to one Discord channel.

    Args:
        webhook_url: The channel's webhook, from ``DISCORD_WEBHOOK_URL``.
        code_version: Tyche's version, for the User-Agent.
        transport: Sends one request; tests pass a fake.
        sleep: Waits a number of seconds; tests pass a fake.
        monotonic: A clock for rate-limit waits only, never for trading time.
        timeout: Seconds for one request.
        max_wait: The longest rate-limit wait before the alert is given up.
    """

    def __init__(
        self,
        webhook_url: SecretStr,
        *,
        code_version: str,
        transport: Transport = urllib_post,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        timeout: float = DEFAULT_TIMEOUT,
        max_wait: float = DEFAULT_MAX_WAIT,
    ) -> None:
        self._url = webhook_url
        self._headers = {
            "Content-Type": "application/json",
            "User-Agent": f"DiscordBot ({PROJECT_URL}, {code_version})",
        }
        self._transport = transport
        self._sleep = sleep
        self._monotonic = monotonic
        self._timeout = timeout
        self._max_wait = max_wait
        self._not_before: float | None = None
        self._retired: str | None = None

    def send(self, alert: Alert) -> None:
        if self._retired is not None:
            raise NotifierError(self._retired)
        body = json.dumps(payload(alert)).encode("utf-8")
        self._wait_for_bucket()
        response = self._post(body)
        if response.status == 429:
            self._wait(_retry_after(response), "a rate limit")
            response = self._post(body)
        if 200 <= response.status < 300:
            return
        if response.status in {401, 403, 404}:
            self._retired = (
                f"Discord refused the webhook (HTTP {response.status}): it was deleted or "
                "DISCORD_WEBHOOK_URL is wrong. Make a new webhook and update .env; no more "
                "alerts are sent until Tyche restarts"
            )
            raise NotifierError(self._retired)
        raise NotifierError(f"Discord answered HTTP {response.status}: {_message(response)}")

    def _post(self, body: bytes) -> HttpResponse:
        url = f"{self._url.get_secret_value()}?wait=true"
        try:
            response = self._transport(url, body, self._headers, self._timeout)
        except OSError as error:  # URLError, TimeoutError, connection errors
            reason = getattr(error, "reason", error)
            raise NotifierError(f"cannot reach Discord: {reason}") from None
        self._remember_bucket(response.headers)
        return response

    def _remember_bucket(self, headers: Mapping[str, str]) -> None:
        if headers.get("x-ratelimit-remaining") != "0":
            self._not_before = None
            return
        reset_after = _seconds(headers.get("x-ratelimit-reset-after"))
        if reset_after is not None:
            self._not_before = self._monotonic() + reset_after

    def _wait_for_bucket(self) -> None:
        if self._not_before is None:
            return
        self._wait(self._not_before - self._monotonic(), "the rate limit's reset")
        self._not_before = None

    def _wait(self, seconds: float | None, what: str) -> None:
        if seconds is None:
            raise NotifierError(f"Discord asked Tyche to wait for {what} without saying how long")
        if seconds > self._max_wait:
            raise NotifierError(
                f"Discord asked Tyche to wait {seconds:.0f} s for {what}, more than "
                f"{self._max_wait:.0f} s; alert not sent"
            )
        if seconds > 0:
            self._sleep(seconds)


def payload(alert: Alert) -> dict[str, Any]:
    """The JSON body for ``alert``: plain text, nobody mentioned."""
    return {"content": content(alert), "allowed_mentions": {"parse": []}}


def content(alert: Alert) -> str:
    """The message text: the title in bold, the time in UTC, then each line.

    Markdown characters in the alert's own text are escaped, so a symbol such as
    ``missing_session`` shows as written. Cut to Discord's limit if needed.
    """
    lines = [
        f"**Tyche: {_escape(alert.title)}**",
        f"{alert.at:%Y-%m-%d %H:%M} UTC",
        *(f"- {_escape(line)}" for line in alert.lines),
    ]
    text = "\n".join(lines)
    if len(text) > MAX_CONTENT:
        text = text[: MAX_CONTENT - len(_CUT)] + _CUT
    return text


def _escape(text: str) -> str:
    """Escape Discord markdown outside inline code (text between backticks)."""
    parts = text.split("`")
    return "`".join(
        part if index % 2 else part.translate(_MARKDOWN) for index, part in enumerate(parts)
    )


def _retry_after(response: HttpResponse) -> float | None:
    try:
        value = json.loads(response.body).get("retry_after")
    except ValueError, AttributeError:
        value = None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return _seconds(response.headers.get("retry-after"))


def _seconds(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value >= 0 else None


def _message(response: HttpResponse) -> str:
    """Discord's own error message, short, or the start of the body."""
    try:
        message = json.loads(response.body).get("message")
    except ValueError, AttributeError:
        message = None
    text = message if isinstance(message, str) else response.body.decode("utf-8", "replace")
    return text.strip()[:200] or "no message"


def _lower(items: Any) -> dict[str, str]:
    return {str(name).lower(): str(value) for name, value in items}
