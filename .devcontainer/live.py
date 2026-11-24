"""Live preview: MagnetStudio on a VNC screen, shown in the browser through noVNC.

    browser ──https──► :6080 websockify + noVNC ──► :5900 Qt "vnc" platform ◄── MagnetStudio

- Restarts the app when its code changes (magnetstudio/**) and whenever it exits/crashes.
- Every PULL_EVERY seconds: `git pull --ff-only` – changes pushed to GitHub show up by themselves.
  If pyproject.toml changed, reinstalls the dependencies first. Skipped while you have local edits.
- User data (settings, templates, print counter, PDFs) lives in ~/.magnetstudio-live – it survives
  restarts and Codespace stops. Put test photos in test-photos/ (drag them into VS Code's file list).

Run: python .devcontainer/live.py [--no-pull]   (started automatically by start.sh)
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOVNC = Path(os.environ.get("NOVNC_DIR", Path.home() / "novnc"))
HOME = Path(os.environ.get("MAGNETSTUDIO_HOME", Path.home() / ".magnetstudio-live"))
PIDFILE = Path("/tmp/magnetstudio-live.pid")
WATCH = [ROOT / "magnetstudio"]
WATCH_EXT = {".py", ".json", ".ttf", ".otf", ".svg", ".png"}
PULL_EVERY = 20


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def snapshot() -> dict[str, float]:
    out = {}
    for base in WATCH:
        for p in base.rglob("*"):
            if p.suffix in WATCH_EXT and "__pycache__" not in p.parts and "_generated" not in p.parts:
                try:
                    out[str(p)] = p.stat().st_mtime
                except OSError:
                    pass
    return out


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=60)


def pull() -> bool:
    """git pull --ff-only when the tree is clean. True if new commits arrived."""
    if git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        return False                      # local edits in the Codespace – don't touch them
    before = git("rev-parse", "HEAD").stdout.strip()
    if git("pull", "--ff-only", "-q").returncode != 0:
        return False
    after = git("rev-parse", "HEAD").stdout.strip()
    if before == after:
        return False
    log(f"Pulled {before[:7]} → {after[:7]}: " + git("log", "-1", "--format=%s").stdout.strip())
    if git("diff", "--name-only", before, after, "--", "pyproject.toml").stdout.strip():
        log("Dependencies changed – reinstalling")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", f"{ROOT}[ai]"])
    return True


def start_app(size: str, vnc_port: int) -> subprocess.Popen:
    env = dict(os.environ, QT_QPA_PLATFORM=f"vnc:size={size}:port={vnc_port}", MAGNETSTUDIO_HOME=str(HOME))
    env.pop("MAGNETSTUDIO_EXIT_AFTER_MS", None)
    log(f"Starting MagnetStudio ({git('log', '-1', '--format=%h %s').stdout.strip()})")
    return subprocess.Popen([sys.executable, "-m", "magnetstudio"], cwd=ROOT, env=env)


def stop_app(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)      # app closes its window cleanly and saves settings
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--vnc-port", type=int, default=5900)
    ap.add_argument("--web-port", type=int, default=6080)
    ap.add_argument("--no-pull", action="store_true")
    a = ap.parse_args()

    if PIDFILE.exists():
        try:
            os.kill(int(PIDFILE.read_text()), 0)
            log("Live preview already running")
            return 0
        except (ProcessLookupError, ValueError, PermissionError):
            pass
    PIDFILE.write_text(str(os.getpid()))
    HOME.mkdir(parents=True, exist_ok=True)

    # noVNC: the forwarded port opens straight into the viewer, reconnecting after each app restart
    (NOVNC / "index.html").write_text(
        '<!doctype html><meta http-equiv="refresh" content="0; url=vnc.html?autoconnect=true'
        '&reconnect=true&reconnect_delay=1500&resize=scale&show_dot=true&path=websockify">', encoding="utf-8")
    web = subprocess.Popen([sys.executable, "-m", "websockify", "--web", str(NOVNC), str(a.web_port),
                            f"localhost:{a.vnc_port}"], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    log(f"Browser view on port {a.web_port}")

    stop = {"flag": False}
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.__setitem__("flag", True))

    app = start_app(a.size, a.vnc_port)
    seen, last_pull = snapshot(), time.monotonic()
    try:
        while not stop["flag"]:
            time.sleep(1.5)
            restart = False
            if not a.no_pull and time.monotonic() - last_pull > PULL_EVERY:
                last_pull = time.monotonic()
                try:
                    pull()
                except Exception as e:  # noqa: BLE001 – offline etc.
                    log(f"git pull skipped: {e}")
            now = snapshot()
            if now != seen:
                time.sleep(1.0)               # let a multi-file change finish
                now, restart = snapshot(), True
                log("Code changed – restarting")
            seen = now
            if app.poll() is not None:
                log(f"App exited (code {app.returncode}) – starting again")
                time.sleep(2)
                restart = True
            if restart:
                stop_app(app)
                app = start_app(a.size, a.vnc_port)
    finally:
        stop_app(app)
        web.terminate()
        PIDFILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
