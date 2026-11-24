"""Used by run.bat / run.sh: install MagnetStudio's libraries into the local .venv – on the first
run, and again only when pyproject.toml changed (e.g. after `git pull` added a dependency).

Runs with the .venv's own python, stdlib only. Nothing is installed outside the repo folder.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = Path(sys.prefix) / ".magnetstudio-deps"


def main() -> int:
    if sys.prefix == sys.base_prefix:
        print("ensure_env.py must run inside the .venv", file=sys.stderr)
        return 2
    want = hashlib.sha256((ROOT / "pyproject.toml").read_bytes()).hexdigest()
    if MARKER.exists() and MARKER.read_text().strip() == want:
        return 0
    print("Installing MagnetStudio's libraries into .venv (first run or after an update – a few minutes)...")
    pip = [sys.executable, "-m", "pip", "--disable-pip-version-check"]
    subprocess.call(pip + ["install", "-q", "--upgrade", "pip"])
    code = subprocess.call(pip + ["install", "-q", "-e", f"{ROOT}[ai]"])
    if code == 0:
        MARKER.write_text(want)
    return code


if __name__ == "__main__":
    sys.exit(main())
