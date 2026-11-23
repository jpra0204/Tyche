"""The KillSwitch port: whether Pablo has told Tyche to stop trading (ADR-0039)."""

from typing import Protocol

from tyche.core.domain import Kill


class KillSwitch(Protocol):
    """Read at every decision by the risk gate, so a switch engaged mid-run counts.

    Only reading belongs to the core. Engaging and releasing are Pablo's, through the
    ``tyche kill`` and ``tyche resume`` commands, or by hand.
    """

    def read(self) -> Kill | None:
        """The kill switch if it is engaged, or ``None``.

        Never raises. A switch that cannot be read fails closed: engaged, without
        flatten, with a reason saying what was wrong. Selling everything is never the
        answer to a flag nobody can read.
        """
        ...
