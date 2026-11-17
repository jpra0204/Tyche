"""Loading and validating configuration from the workspace.

Planned (Phase 1 onward): reads TOML and ``.env`` from ``TYCHE_HOME``, builds typed
settings and refuses to start on any invalid value (ADR-0010). The typed models
themselves live next to the code they configure.
"""
