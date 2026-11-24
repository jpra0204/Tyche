"""The Discord webhook notifier, against a fake transport (ADR-0040)."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from tyche.adapters.notifiers import MAX_CONTENT, DiscordWebhookNotifier, HttpResponse, content
from tyche.core.ports import Alert, AlertKind, NotifierError

WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/secret-token"
AT = datetime(2026, 11, 23, 21, 4, tzinfo=UTC)
ALERT = Alert(AlertKind.KILL_SWITCH, "Kill switch engaged", AT, ("Reason: stop",))
OK = HttpResponse(200, {}, b"{}")


class FakeTransport:
    """Answers each request with the next scripted response, and records it."""

    def __init__(self, *responses: HttpResponse | OSError) -> None:
        self._responses = list(responses)
        self.requests: list[tuple[str, dict[str, object], Mapping[str, str], float]] = []

    def __call__(
        self, url: str, body: bytes, headers: Mapping[str, str], timeout: float
    ) -> HttpResponse:
        self.requests.append((url, json.loads(body), headers, timeout))
        response = self._responses.pop(0)
        if isinstance(response, OSError):
            raise response
        return response


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


def notifier(transport: FakeTransport, clock: FakeTime | None = None) -> DiscordWebhookNotifier:
    time = clock or FakeTime()
    return DiscordWebhookNotifier(
        SecretStr(WEBHOOK),
        code_version="0.1.0",
        transport=transport,
        sleep=time.sleep,
        monotonic=time.monotonic,
    )


def too_many(retry_after: float) -> HttpResponse:
    body = json.dumps({"message": "You are being rate limited.", "retry_after": retry_after})
    return HttpResponse(429, {}, body.encode())


class TestRequest:
    def test_posts_the_alert_and_waits_for_discord_to_save_it(self) -> None:
        transport = FakeTransport(OK)
        notifier(transport).send(ALERT)
        [(url, body, headers, timeout)] = transport.requests
        assert url == f"{WEBHOOK}?wait=true"
        assert body == {"content": content(ALERT), "allowed_mentions": {"parse": []}}
        assert headers["Content-Type"] == "application/json"
        assert timeout == 10.0

    def test_names_itself_as_discord_asks(self) -> None:
        transport = FakeTransport(OK)
        notifier(transport).send(ALERT)
        user_agent = transport.requests[0][2]["User-Agent"]
        assert user_agent == "DiscordBot (https://github.com/jpra0204/Tyche, 0.1.0)"

    def test_a_no_content_answer_is_a_success(self) -> None:
        notifier(FakeTransport(HttpResponse(204, {}, b""))).send(ALERT)


class TestContent:
    def test_bold_title_then_time_then_lines(self) -> None:
        assert content(ALERT) == (
            "**Tyche: Kill switch engaged**\n2026-11-23 21:04 UTC\n- Reason: stop"
        )

    def test_escapes_markdown_outside_inline_code(self) -> None:
        alert = Alert(AlertKind.DATA_FAILURE, "a *b*", AT, ("missing_session, run `tyche_x`",))
        assert content(alert).splitlines()[2] == r"- missing\_session, run `tyche_x`"
        assert content(alert).splitlines()[0] == r"**Tyche: a \*b\***"

    def test_cut_to_discords_limit(self) -> None:
        alert = Alert(AlertKind.DATA_FAILURE, "many", AT, tuple("x" * 100 for _ in range(50)))
        text = content(alert)
        assert len(text) == MAX_CONTENT
        assert text.endswith("the full alert is in the logs)")


class TestRateLimits:
    def test_waits_as_long_as_a_429_says_then_tries_once_more(self) -> None:
        clock = FakeTime()
        transport = FakeTransport(too_many(1.5), OK)
        notifier(transport, clock).send(ALERT)
        assert clock.slept == [1.5]
        assert len(transport.requests) == 2

    def test_a_second_429_gives_up(self) -> None:
        transport = FakeTransport(too_many(1), too_many(1))
        with pytest.raises(NotifierError, match="HTTP 429: You are being rate limited"):
            notifier(transport).send(ALERT)

    def test_will_not_wait_longer_than_the_limit(self) -> None:
        clock = FakeTime()
        with pytest.raises(NotifierError, match="wait 120 s"):
            notifier(FakeTransport(too_many(120)), clock).send(ALERT)
        assert clock.slept == []

    def test_reads_the_retry_after_header_when_the_body_has_none(self) -> None:
        clock = FakeTime()
        transport = FakeTransport(HttpResponse(429, {"retry-after": "2"}, b""), OK)
        notifier(transport, clock).send(ALERT)
        assert clock.slept == [2.0]

    def test_an_empty_bucket_waits_for_its_reset_before_the_next_alert(self) -> None:
        clock = FakeTime()
        empty = HttpResponse(
            200, {"x-ratelimit-remaining": "0", "x-ratelimit-reset-after": "3.25"}, b"{}"
        )
        sender = notifier(FakeTransport(empty, OK), clock)
        sender.send(ALERT)
        assert clock.slept == []
        sender.send(ALERT)
        assert clock.slept == [3.25]

    def test_a_bucket_with_requests_left_does_not_wait(self) -> None:
        clock = FakeTime()
        left = HttpResponse(
            200, {"x-ratelimit-remaining": "4", "x-ratelimit-reset-after": "3"}, b"{}"
        )
        sender = notifier(FakeTransport(left, OK), clock)
        sender.send(ALERT)
        sender.send(ALERT)
        assert clock.slept == []


class TestFailures:
    @pytest.mark.parametrize("status", [401, 403, 404])
    def test_a_refused_webhook_is_never_used_again(self, status: int) -> None:
        transport = FakeTransport(HttpResponse(status, {}, b'{"message": "Unknown Webhook"}'))
        sender = notifier(transport)
        with pytest.raises(NotifierError, match=f"HTTP {status}"):
            sender.send(ALERT)
        with pytest.raises(NotifierError, match=r"update \.env"):
            sender.send(ALERT)
        assert len(transport.requests) == 1

    def test_another_error_says_what_discord_said(self) -> None:
        transport = FakeTransport(
            HttpResponse(400, {}, b'{"message": "Cannot send an empty message"}')
        )
        with pytest.raises(NotifierError, match="HTTP 400: Cannot send an empty message"):
            notifier(transport).send(ALERT)

    def test_an_error_body_that_is_not_json_is_shown_short(self) -> None:
        transport = FakeTransport(HttpResponse(502, {}, b"<html>" + b"x" * 500))
        with pytest.raises(NotifierError) as raised:
            notifier(transport).send(ALERT)
        assert len(str(raised.value)) < 250

    def test_an_unreachable_discord_is_a_notifier_error_without_the_url(self) -> None:
        transport = FakeTransport(TimeoutError("timed out"))
        with pytest.raises(NotifierError, match="cannot reach Discord: timed out") as raised:
            notifier(transport).send(ALERT)
        assert WEBHOOK not in str(raised.value)
        assert "secret-token" not in str(raised.value)
        assert raised.value.__cause__ is None
