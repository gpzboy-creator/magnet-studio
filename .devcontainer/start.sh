#!/bin/bash
# Every Codespace start: finish the setup if it never completed, then launch the live preview
# in the background (log: /tmp/magnetstudio-live.log).
cd "$(dirname "$0")/.."
if [ ! -f "$HOME/.magnetstudio-setup-done" ]; then
    echo "Setup is not complete – running it now (a few minutes)..."
    bash .devcontainer/setup.sh > /tmp/magnetstudio-setup.log 2>&1 || { echo "Setup failed – see /tmp/magnetstudio-setup.log"; tail -20 /tmp/magnetstudio-setup.log; }
fi
pkill -f ".devcontainer/live.py" 2>/dev/null; rm -f /tmp/magnetstudio-live.pid
# Xvfb wants a root-owned, sticky /tmp/.X11-unix (missing after a container restart)
sudo mkdir -p /tmp/.X11-unix 2>/dev/null && sudo chown root:root /tmp/.X11-unix && sudo chmod 1777 /tmp/.X11-unix
setsid nohup python .devcontainer/live.py > /tmp/magnetstudio-live.log 2>&1 < /dev/null &
echo "MagnetStudio live preview starting – open the PORTS tab → 6080 if the browser tab did not open."
