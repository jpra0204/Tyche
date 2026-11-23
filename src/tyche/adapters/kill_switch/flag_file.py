"""The kill switch as a file: ``KILL`` at the workspace root (ADR-0039).

The file being there is what engages the switch. What is in it only says why, when,
and whether to flatten::

    engaged_at = 2026-11-23T21:04:00Z
    reason = "market chaos, stopping until I have looked"
    flatten = false

So the switch still works when the command does not: ``touch KILL`` engages it with no
flatten, and deleting the file releases a kill switch (but not the drawdown halt, which
only ``tyche resume`` lifts). A file that cannot be read, or says anything unexpected,
engages the switch without flatten: a flag nobody can read must stop new orders, and
must never sell everything.
"""

import json
import tomllib
from datetime import datetime
from pathlib import Path

from tyche.core.domain import Kill

_BY_HAND = "the KILL file is there with nothing in it (engaged by hand)"


class FlagFileKillSwitch:
    """A ``KillSwitch`` that reads the flag file every time it is asked.

    Args:
        path: The flag file: ``Workspace.kill_file``.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> Kill | None:
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError) as error:
            return Kill(f"the KILL file is there but cannot be read ({error}); kept engaged")
        return parse(text)


def parse(text: str) -> Kill:
    """The kill switch a flag file's ``text`` describes. Always engaged.

    Empty text is a switch engaged by hand. Anything that is not exactly the three
    known keys with the right types engages it without flatten, with a reason saying
    what was wrong.
    """
    if not text.strip():
        return Kill(_BY_HAND)
    try:
        values = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        return _unreadable(f"it is not valid TOML ({error})")
    unknown = sorted(set(values) - {"engaged_at", "reason", "flatten"})
    if unknown:
        return _unreadable(f"it has unknown keys: {', '.join(unknown)}")
    reason = values.get("reason", _BY_HAND)
    flatten = values.get("flatten", False)
    engaged_at = values.get("engaged_at")
    if not isinstance(reason, str) or not reason.strip():
        return _unreadable("its reason is not a text")
    if not isinstance(flatten, bool):
        return _unreadable("its flatten is not true or false")
    if engaged_at is not None and not isinstance(engaged_at, datetime):
        return _unreadable("its engaged_at is not a date and time")
    try:
        return Kill(reason, flatten=flatten, engaged_at=engaged_at)
    except ValueError as error:
        return _unreadable(str(error))


def engage(path: Path, kill: Kill) -> None:
    """Write the flag file for ``kill``, replacing any already there.

    Written to a temporary file in the same folder, then renamed over the flag, so a
    reader never sees half a file.
    """
    lines = []
    if kill.engaged_at is not None:
        lines.append(f"engaged_at = {kill.engaged_at.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    # A JSON string with ASCII escapes is a valid TOML basic string.
    lines.append(f"reason = {json.dumps(kill.reason)}")
    lines.append(f"flatten = {'true' if kill.flatten else 'false'}")
    text = "\n".join(lines) + "\n"
    if parse(text) != _second_precision(kill):
        raise ValueError(f"the kill switch {kill!r} would not read back as written")
    temporary = path.with_name(f".{path.name}.writing")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def release(path: Path) -> bool:
    """Remove the flag file. True if it was there."""
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def _unreadable(what: str) -> Kill:
    return Kill(f"the KILL file is there but {what}; engaged without flatten")


def _second_precision(kill: Kill) -> Kill:
    if kill.engaged_at is None:
        return kill
    return Kill(kill.reason, kill.flatten, kill.engaged_at.replace(microsecond=0))
