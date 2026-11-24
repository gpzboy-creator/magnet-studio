#!/bin/bash
# Every Codespace start: launch the live preview in the background (log: /tmp/magnetstudio-live.log).
cd "$(dirname "$0")/.."
setsid nohup python .devcontainer/live.py > /tmp/magnetstudio-live.log 2>&1 < /dev/null &
echo "MagnetStudio live preview starting – open the PORTS tab → 6080 if the browser tab did not open."
