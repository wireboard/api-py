"""Entry point for ``python -m wireboard_api``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
