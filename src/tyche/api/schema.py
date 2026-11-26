"""Writes the API's OpenAPI schema, from which the app's TypeScript types are made.

    uv run python -m tyche.api.schema ui/src/api/openapi.json

Then ``npm run api:types`` in ``ui/`` turns it into ``src/api/schema.d.ts``. Both files
are committed; a test fails when ``openapi.json`` no longer matches the API.
"""

import json
import sys
from pathlib import Path
from typing import Any

from tyche.api.app import create_app
from tyche.config import Workspace


def openapi() -> dict[str, Any]:
    """The API's schema. It does not depend on the workspace or the token."""
    app = create_app(Workspace(Path.cwd()), "schema-only", environ={})
    return app.openapi()


def render() -> str:
    """The schema as the committed file holds it."""
    return json.dumps(openapi(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m tyche.api.schema <output.json>", file=sys.stderr)
        return 2
    Path(argv[1]).write_text(render(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
