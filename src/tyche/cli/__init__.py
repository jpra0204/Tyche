"""The ``tyche`` command-line interface.

Phase 0 ships only ``tyche --version`` so that packaging, the entry point and CI can be
tested end to end. Real commands (backtest, kill switch, agents, ...) arrive with the
phases that implement them.
"""

import argparse
from collections.abc import Sequence

from tyche import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tyche",
        description="Tyche: an event-driven, agent-assisted trading framework.",
    )
    parser.add_argument("--version", action="version", version=f"tyche {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
