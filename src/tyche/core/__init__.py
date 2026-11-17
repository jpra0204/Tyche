"""The pure heart of Tyche.

Everything under ``tyche.core`` is plain, deterministic Python: no network, no disk,
no wall clock and no vendor library. The outside world is reached only through the
interfaces in ``tyche.core.ports``. CI enforces this with import-linter (see
``pyproject.toml`` and ADR-0004).
"""
