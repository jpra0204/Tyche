# ADR-0016: Typer for the command-line interface

- **Status:** Accepted (Pablo, 2026-11-17)
- **Date:** 2026-11-17

## Context

Phase 0 shipped a one-option CLI on the standard library's `argparse`. Tyche will grow many commands: `init`, `config check`, `backtest`, `data fetch`, the kill switch, risk-profile switching, agent runs and proposal approvals. Most take typed options (paths, dates, profile names). Pablo chose the framework at the start of PR 4.

## Decision

The `tyche` command is built with **Typer** (MIT licence, 0.29.1 at the time of writing), which sits on Click.

- Commands are plain functions with type-annotated parameters. Typer builds the options, help text and type conversion from the annotations.
- Related commands are grouped as sub-applications: `tyche config check`, later `tyche risk ...`, `tyche proposal ...`.
- **Commands stay thin.** A command parses its options, calls one function outside `tyche.cli`, and turns the result or the error into text and an exit code. Logic never lives in the CLI, so it can be tested without it.
- **Tracebacks never show local variables** (`pretty_exceptions_show_locals=False`). Typer shows them by default, and a local variable can hold a secret.
- Errors are printed to standard error as `Error: <message>` with exit code 1.

## Alternatives considered

- **argparse.** No dependency, but every typed option and sub-command needs hand-written parsing and help text, and that code grows with every command.
- **Click directly.** What Typer is built on. More decorators, and types declared twice: once in the decorator and once in the function.

## Consequences

- Adds Typer and its dependencies: Click (BSD-3-Clause), Rich (MIT), Shellingham (ISC). All are free.
- Help output is formatted by Rich. Error output is plain text.
- Shell completion is turned off (`add_completion=False`) to keep the command surface small. It can be turned on later.
- Tests drive commands through `typer.testing.CliRunner`, which captures standard output and standard error separately.
