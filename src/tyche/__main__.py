"""Allow ``python -m tyche``."""

import sys

from tyche.cli import main

if __name__ == "__main__":
    sys.exit(main())
