"""Entry script for PyInstaller (it needs a file, not a `-m` module)."""
import sys

from magnetstudio.app import main

if __name__ == "__main__":
    sys.exit(main())
