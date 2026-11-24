#!/bin/sh
# macOS: double-click in Finder to run MagnetStudio from this folder (opens Terminal).
# First time: right-click → Open (the file is not signed). Logic is in run.sh.
cd "$(dirname "$0")" && exec ./run.sh "$@"
