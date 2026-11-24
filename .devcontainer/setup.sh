#!/bin/bash
# One-time Codespace setup: Qt's system libraries, the app (editable), websockify + noVNC.
set -e
cd "$(dirname "$0")/.."
sudo apt-get update -q
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends \
    libgl1 libegl1 libx11-6 libxcb1 libxkbcommon0 libfontconfig1 libfreetype6 libdbus-1-3 libglib2.0-0
python -m pip install -q --upgrade pip
python -m pip install -q -e ".[ai]" websockify
NOVNC="$HOME/novnc"
if [ ! -f "$NOVNC/vnc.html" ]; then
    git clone -q --depth 1 --branch v1.5.0 https://github.com/novnc/noVNC.git "$NOVNC"
fi
mkdir -p test-photos
echo "Setup done."
