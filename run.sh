#!/bin/sh
# Run MagnetStudio straight from this folder (macOS / Linux). No system-wide install:
# - with uv (https://docs.astral.sh/uv/): uv makes .venv here and even fetches Python if needed;
# - otherwise with python3 ≥ 3.10: a local .venv is created on the first run.
cd "$(dirname "$0")" || exit 1

if command -v uv >/dev/null 2>&1; then
    exec uv run --extra ai python -m magnetstudio "$@"
fi

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
        PY="$c"; break
    fi
done
if [ -z "$PY" ]; then
    echo "MagnetStudio needs Python 3.10+ or uv. Easiest – install uv (one line), then run this again:"
    echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "or install Python from https://www.python.org/downloads/"
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "First run: creating a local environment in .venv ..."
    "$PY" -m venv .venv || exit 1
fi
.venv/bin/python packaging/ensure_env.py || { echo "Setup failed – see the messages above."; exit 1; }
exec .venv/bin/python -m magnetstudio "$@"
