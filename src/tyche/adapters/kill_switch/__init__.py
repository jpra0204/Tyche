"""Kill switch adapters: the ``KILL`` flag file in the workspace (ADR-0039).

Available now: ``FlagFileKillSwitch``, which reads the flag for the risk gate, and
``engage`` and ``release``, which ``tyche kill`` and ``tyche resume`` use to write and
remove it.

Later: a Discord ``/kill`` command, which will write the same file.
"""

from tyche.adapters.kill_switch.flag_file import FlagFileKillSwitch, engage, release

__all__ = ["FlagFileKillSwitch", "engage", "release"]
