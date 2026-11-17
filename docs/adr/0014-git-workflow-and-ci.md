# ADR-0014: Branch and pull request workflow with CI

- **Status:** Accepted (Pablo, 2026-11-16)
- **Date:** 2026-11-16

## Context

The brief asks for small, PR-sized steps with tests and clear commit messages, a review stop at the end of each phase, and CI with lint, types and tests. CI only protects `main` if changes arrive through pull requests.

## Decision

- **Every increment is a branch and a pull request.** Branches are named `phase-N/short-description`. Claude commits, pushes the branch and opens the PR.
- **Pablo merges.** Nothing reaches `main` without his review and his click.
- **CI runs on every PR and on `main`:** ruff lint, ruff format check, mypy (strict), import-linter contracts and pytest with coverage. `make check` runs the same commands locally.
- **A PR is not ready until its docs are updated**, including `STATUS.md` and `CHANGELOG.md` where relevant.
- **Commit messages** use a short imperative subject and a body that explains why.
- **Versioning** follows semantic versioning. While the version is below 1.0, each completed phase raises the minor version (Phase 1 ships 0.1.0).

## Alternatives considered

- **Local commits only, Pablo pushes.** Keeps everything on the machine until reviewed, but CI runs late and review happens without a diff view.
- **Commit straight to `main`.** Fastest, with no gate at all.

## Consequences

- Each PR is a natural unit to review and learn from.
- GitHub Actions is free for public repositories, so this fits the $0 constraint.
- Branch protection on `main` (require the CI check, require a PR) is a GitHub setting only Pablo can turn on. It is recommended and listed in `STATUS.md`.
