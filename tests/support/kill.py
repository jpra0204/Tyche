"""A kill switch a test can script: engaged from one decision, released at another."""

from datetime import UTC, datetime

from tyche.core.domain import Kill

ENGAGED_AT = datetime(2024, 1, 5, 22, 0, tzinfo=UTC)


def kill(*, flatten: bool = False, reason: str = "stop now") -> Kill:
    return Kill(reason, flatten=flatten, engaged_at=ENGAGED_AT)


class ScriptedKillSwitch:
    """Engaged from the ``first``-th decision (1-based) until before the ``until``-th.

    The risk gate reads the switch once per decision, so counting reads counts decisions.
    """

    def __init__(self, engaged: Kill, *, first: int = 1, until: int | None = None) -> None:
        self._engaged = engaged
        self._first = first
        self._until = until
        self.reads = 0

    def read(self) -> Kill | None:
        self.reads += 1
        if self.reads < self._first:
            return None
        if self._until is not None and self.reads >= self._until:
            return None
        return self._engaged
