# ADR-0008: Public code repository, private workspace

- **Status:** Accepted (Pablo, 2026-11-16)
- **Date:** 2026-11-16

## Context

The GitHub repository `jpra0204/Tyche` is public. The brief asks for versioned strategy config, proposal files and backtest reports saved with their config. Kept in this repository, those would publish the real strategy parameters, risk profiles, capital and review history.

Separately, Tyche will run in Docker and must move to another machine without code changes, so code and user state have to be separable anyway.

## Decision

**The repository holds the framework only**: source, tests, docs, built-in example strategies and example config.

**Everything specific to Pablo lives in a workspace folder**, located by the `TYCHE_HOME` environment variable (default `~/tyche-workspace`). The workspace is its own **private git repository**, so config, proposals and reports stay versioned. Its layout is in the [system overview](../architecture/system-overview.md#7-where-state-lives).

Within the workspace:

- **Committed:** `config/`, `strategies/`, `research/`, `proposals/`, `reports/`.
- **Gitignored:** `.env`, `data/`, `state/`, `logs/`.

A `tyche init` command (Phase 1) will create a workspace from the example config shipped in the package. Docker mounts the workspace as a volume.

Every run records the framework's code version and a hash of the config it used, so a result can be reproduced from the two repositories together.

## Alternatives considered

- **Make the repository private.** Simplest, with everything in one place. It closes the door on Tyche as a shareable product and leaves secrets one mistake away from the code.
- **Everything public.** Fully transparent, and it publishes position sizing and capital.

## Consequences

- Nothing private can be committed to the public repository by accident, because nothing private lives in it. `.gitignore` also blocks `.env`, databases and Parquet files as a second line of defence.
- Reproducing a result needs two things, a code version and a workspace commit. Reports will print both.
- The workspace should not be created under `~/Public`, where this repository currently sits: macOS shares that folder on the local network when File Sharing is turned on.
- The repository has no licence file, so by default all rights are reserved. Choosing a licence is an open decision in `STATUS.md`.
