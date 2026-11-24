# AGENTS.md – instructions for AI coding agents

This repo is **MagnetStudio**, a Python/PyQt6 desktop app (Windows & macOS) that frames and prints
event photo magnets at 300 DPI. The owner (Shahar) writes in Hebrew; the docs are mostly Hebrew.

## Read first (in this order)
1. [`CLAUDE.md`](CLAUDE.md) – **the source of truth**: requirements, layout, conventions, commands,
   and the "סטטוס ומה הלאה" (status / what's next) section. It applies to every agent, not only Claude.
2. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) – layers, print flow, algorithms, file locations.
3. [`docs/JOURNAL.md`](docs/JOURNAL.md) – development journal: what was done, decisions and why.

## Ground rules (summary – details in CLAUDE.md)
- Layers: `core/` + `generator/` never import Qt (a test enforces it); `services/` = Qt without
  widgets; `ui/` = widgets only, it displays state and asks for actions.
- All file paths come from `magnetstudio/paths.py`. Never write inside the `magnetstudio/` package.
- The API key lives in the OS keychain (`core/secrets.py`), never in `settings.json`.
- Print-queue state lives only in `services/print_queue.py › PrintQueueController`.
- Everything must work offline; every cloud call has a local fallback.
- Tests never touch real user data: `tests/conftest.py` isolates the home folder and the keychain.

## Commands
```bash
pip install -e ".[ai,dev]"
pytest                      # must pass before every commit (~45 s, offscreen)
python -m magnetstudio      # run the app
python packaging/build.py   # PyInstaller build → dist/MagnetStudio/
```

## When you finish a piece of work
1. `pytest` green.
2. Add an entry at the top of `docs/JOURNAL.md` (template at the bottom of that file).
3. Update "סטטוס ומה הלאה" in `CLAUDE.md`.
4. One commit per logical step, English message (summary line + bullets).

The repo is **private** – it contains the photographer's name and phone number (default credit text).
