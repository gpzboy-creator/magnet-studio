"""Live preview: MagnetStudio on a virtual screen, shown in the browser through noVNC.

    browser ──https──► :6080 websockify + noVNC ──► :5900 x11vnc ──► Xvfb :99 (+ openbox) ◄── MagnetStudio

(Qt's built-in "vnc" platform was tried first: it sends pixels in the wrong byte order – colours come
out swapped in noVNC – and has weak keyboard support, so a real X server + x11vnc is used.)

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
DISPLAY = ":99"


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
    changed = git("diff", "--name-only", before, after).stdout.split()
    if ".devcontainer/setup.sh" in changed or "pyproject.toml" in changed:
        log("Setup / dependencies changed – re-running setup")
        subprocess.run(["bash", str(ROOT / ".devcontainer" / "setup.sh")])
    if any(c.startswith(".devcontainer/") for c in changed):
        raise RestartSelf()                # the preview itself changed – start.sh restarts it
    return True


class RestartSelf(Exception):
    pass


def start_app() -> subprocess.Popen:
    env = dict(os.environ, DISPLAY=DISPLAY, QT_QPA_PLATFORM="xcb", MAGNETSTUDIO_HOME=str(HOME),
               MAGNETSTUDIO_START_MAXIMIZED="1")
    env.pop("MAGNETSTUDIO_EXIT_AFTER_MS", None)
    log(f"Starting MagnetStudio ({git('log', '-1', '--format=%h %s').stdout.strip()})")
    return subprocess.Popen([sys.executable, "-m", "magnetstudio"], cwd=ROOT, env=env)


def start_screen(size: str, vnc_port: int, web_port: int) -> list[subprocess.Popen]:
    """Xvfb + window manager + x11vnc + websockify/noVNC. They keep running across app restarts,
    so the browser tab stays connected while the app reloads. Each writes /tmp/magnetstudio-<name>.log."""
    def run(name: str, cmd: list[str], env=None) -> subprocess.Popen:
        out = open(f"/tmp/magnetstudio-{name}.log", "w")
        return subprocess.Popen(cmd, env=env, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)

    # leftovers of a previous run (killed preview, container restart) would block the display/ports
    for pattern in (f"^Xvfb {DISPLAY} ", f"^x11vnc -display {DISPLAY} ", f"-m websockify --web {NOVNC} "):
        subprocess.run(["pkill", "-f", pattern], capture_output=True)
    subprocess.run(["pkill", "-x", "openbox"], capture_output=True)        # exact process name only
    time.sleep(0.5)
    Path(f"/tmp/.X{DISPLAY[1:]}-lock").unlink(missing_ok=True)
    Path(f"/tmp/.X11-unix/X{DISPLAY[1:]}").unlink(missing_ok=True)

    procs = [run("xvfb", ["Xvfb", DISPLAY, "-screen", "0", f"{size}x24", "-nolisten", "tcp"])]
    sock = Path(f"/tmp/.X11-unix/X{DISPLAY[1:]}")
    for _ in range(100):                                  # wait up to 10 s for the X socket
        if sock.exists() or procs[0].poll() is not None:
            break
        time.sleep(0.1)
    if not sock.exists():
        log(f"Xvfb did not start (exit {procs[0].poll()}): " + Path("/tmp/magnetstudio-xvfb.log").read_text()[-800:])
    env = dict(os.environ, DISPLAY=DISPLAY)
    procs.append(run("openbox", ["openbox"], env))
    procs.append(run("x11vnc", ["x11vnc", "-display", DISPLAY, "-rfbport", str(vnc_port), "-localhost", "-forever",
                                "-shared", "-nopw", "-xkb", "-add_keysyms", "-noxrecord", "-noxdamage"]))
    procs.append(run("websockify", [sys.executable, "-m", "websockify", "--web", str(NOVNC), str(web_port),
                                    f"localhost:{vnc_port}"]))
    time.sleep(1.5)
    for name, p in zip(("xvfb", "openbox", "x11vnc", "websockify"), procs):
        if p.poll() is not None:
            log(f"{name} exited (code {p.returncode}): "
                + Path(f"/tmp/magnetstudio-{name}.log").read_text(errors="replace")[-600:])
    return procs


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
    ap.add_argument("--size", default="1600x900")
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
    try:
        import websockify  # noqa: F401
        import PyQt6.QtWidgets  # noqa: F401
    except ImportError as e:
        log(f"Setup incomplete ({e}) – run: bash .devcontainer/setup.sh")
    screen = start_screen(a.size, a.vnc_port, a.web_port)
    log(f"Browser view on port {a.web_port} (screen {a.size})")

    stop = {"flag": False}
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.__setitem__("flag", True))

    app = start_app()
    seen, last_pull = snapshot(), time.monotonic()
    try:
        while not stop["flag"]:
            time.sleep(1.5)
            restart = False
            if not a.no_pull and time.monotonic() - last_pull > PULL_EVERY:
                last_pull = time.monotonic()
                try:
                    pull()
                except RestartSelf:
                    raise
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
                app = start_app()
    except RestartSelf:
        log("Live preview updated – restarting it")
        stop_all(app, screen)
        os.execvp("bash", ["bash", str(ROOT / ".devcontainer" / "start.sh")])
    finally:
        stop_all(app, screen)
    return 0


def stop_all(app: subprocess.Popen, screen: list[subprocess.Popen]) -> None:
    stop_app(app)
    for p in reversed(screen):
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
    PIDFILE.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
