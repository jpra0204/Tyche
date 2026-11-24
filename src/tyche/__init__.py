"""Tyche: an event-driven, agent-assisted trading framework.

Start with ``CLAUDE.md`` and ``docs/architecture/system-overview.md``.
"""

import logging
from importlib.metadata import version

__version__ = version("tyche")

# Until a command sends Tyche's logs to the workspace (``tyche.adapters.logs``), its
# records go nowhere, rather than to Python's last-resort handler on stderr.
logging.getLogger("tyche").addHandler(logging.NullHandler())

__all__ = ["__version__"]
