"""Allow `python -m arb ...` invocation."""
from .cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
