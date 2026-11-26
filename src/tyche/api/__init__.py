"""The console's HTTP API: a second front door beside the CLI (ADR-0046).

``tyche ui`` serves it, with the built React app (``ui/dist``), on ``127.0.0.1`` only.
Every call under ``/api`` must carry the token made for that launch. The API reads what
the CLI reads (the workspace, its config, the kill switch, the state database) through
``tyche.runtime`` and ``tyche.config``; from U2 on it runs commands as ``tyche``
subprocesses, so the page can never do what the CLI cannot.

This is the only package that imports the web framework (an import contract says so).
"""

from tyche.api.app import DEFAULT_PORT, HOST, create_app, default_app_dir, serve
from tyche.api.security import TOKEN_HEADER, new_token

__all__ = [
    "DEFAULT_PORT",
    "HOST",
    "TOKEN_HEADER",
    "create_app",
    "default_app_dir",
    "new_token",
    "serve",
]
