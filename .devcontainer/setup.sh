#!/bin/bash
# Codespace setup: Qt's system libraries, the app (editable), websockify + noVNC.
# Safe to run again; start.sh runs it whenever the "done" marker is missing (self-healing).
set -e
cd "$(dirname "$0")/.."
MARKER="$HOME/.magnetstudio-setup-done"

# The base image ships a Yarn apt source whose signing key has expired – it breaks `apt-get update`.
# We don't need Yarn, so drop that source and never let a third-party repo stop the setup.
sudo rm -f /etc/apt/sources.list.d/yarn.list
sudo apt-get update -q || echo "apt-get update reported problems – continuing"
# virtual screen + VNC + a small window manager, and the X libraries Qt's xcb platform needs
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends \
    xvfb x11vnc openbox fonts-dejavu-core \
    libgl1 libegl1 libx11-6 libx11-xcb1 libxcb1 libxkbcommon0 libxkbcommon-x11-0 libfontconfig1 libfreetype6 \
    libdbus-1-3 libglib2.0-0 libxrender1 libxi6 libsm6 libice6 \
    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
    libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 libxcb-xfixes0 libxcb-sync1 libxcb-shm0

python -m pip install -q --upgrade pip
python -m pip install -q -e ".[ai]" websockify

NOVNC="$HOME/novnc"
if [ ! -f "$NOVNC/vnc.html" ]; then
    rm -rf "$NOVNC"
    git clone -q --depth 1 --branch v1.5.0 https://github.com/novnc/noVNC.git "$NOVNC"
fi
mkdir -p test-photos
python -c "import PyQt6.QtWidgets, websockify, magnetstudio" && command -v Xvfb x11vnc openbox >/dev/null && date > "$MARKER"
echo "Setup done."
