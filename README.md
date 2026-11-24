# MagnetStudio

Desktop app (Windows & macOS) for event photo magnets: frames camera photos at exact magnet sizes
(7.5×10, 10×10, 15×20, 5×15 strip – 300 DPI) and prints them on a thermal / dye-sub printer or as
A4 sheets. Hot folder, Hebrew text frames, a visual frame designer and an AI frame generator.

אפליקציית דסקטופ להלבשת מסגרות והדפסת מגנטים מאירועים. פרטים מלאים – ארכיטקטורה, מוסכמות וסטטוס –
ב-[CLAUDE.md](CLAUDE.md).

## Easiest: the self-updating launcher (no Python, no install)

Download `MagnetStudio-Launcher-Windows.zip` (or `-macOS.zip`) once from the
[latest release](https://github.com/gpzboy-creator/magnet-studio/releases/tag/latest), unzip it into a
folder you keep, and double-click `MagnetStudio.bat` / `MagnetStudio.command` every time. It checks for a
newer build, downloads it if there is one, and starts the app; offline it starts the version you have.
The first time it asks for a read-only GitHub token (it opens the page and explains what to tick).

## Run straight from the repo (no install)

Get the code (GitHub → **Code → Download ZIP** and unzip, or `git clone`), then double-click:

| Windows | macOS | Linux |
|---------|-------|-------|
| `run.bat` | `run.command` (first time: right-click → Open) | `./run.sh` |

The first run creates a local `.venv` folder **inside the repo** and downloads the libraries into it
(a few minutes); after that it starts immediately. Nothing is installed system-wide. It needs either
**uv** (fetches Python by itself – one-line install: <https://docs.astral.sh/uv/>) or **Python 3.10+**.
After `git pull` the scripts update the libraries automatically if the dependencies changed.
To start over, delete the `.venv` folder.

Ready-made app (no Python at all): <https://github.com/gpzboy-creator/magnet-studio/releases/tag/latest>

## Install & run (developers)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -e ".[ai]"        # [ai] = optional Gemini features; the app works without them
python -m magnetstudio        # or just: magnetstudio
```

## Tests

```bash
pip install -e ".[ai,dev]"
pytest
```

Tests run offscreen and use temporary folders – they never touch your real settings, templates or log.

## Build the desktop app

```bash
pip install -e ".[ai,dev]"
python packaging/build.py     # → dist/MagnetStudio/  (run it on Windows for .exe, on macOS for .app)
```

## Where your data lives

Settings, your own templates and fonts, logs and print files are kept in the OS user folders –
never inside the app – so updates don't touch them (Windows `%LOCALAPPDATA%\MagnetStudio`,
macOS `~/Library/Application Support/MagnetStudio`, logs in `~/Library/Logs/MagnetStudio`,
print files in `Documents/MagnetStudio`). The Gemini API key is stored in the OS keychain.
On first start, data from an older version (`config/settings.json`, user templates/fonts in
`assets/`) is copied over automatically – keep the old folder until you've checked it.
`MAGNETSTUDIO_HOME=<folder>` puts everything in one folder (portable / USB).

## Layout

```
magnetstudio/
  app.py          entry point (logging, crash hooks, migration, fonts, theme, main window)
  paths.py        every file location (bundled assets vs. per-user data)
  core/           image processing, templates, layout, print jobs, settings, secrets, log – no Qt
  generator/      AI / offline frame generator – no Qt
  services/       Qt without widgets: print queue controller, printing, background workers
  ui/             PyQt6 widgets
  assets/         bundled fonts, sample templates, icons (read-only)
tests/            pytest (offscreen, isolated user folders + in-memory keychain)
packaging/        PyInstaller spec + build script
docs/             architecture, development journal, screenshots, history
```

## Documentation (for people and AI agents)

| File | What |
|------|------|
| [CLAUDE.md](CLAUDE.md) | Source of truth: requirements, layout, conventions, commands, **status & next steps** |
| [AGENTS.md](AGENTS.md) | Entry point for any AI coding agent (Codex, Cursor, Gemini…) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, print flow, algorithms, file locations, architecture review |
| [docs/JOURNAL.md](docs/JOURNAL.md) | Development journal (יומן) – what was done, decisions, bugs found |
| [docs/screenshots/](docs/screenshots/) | The app through its versions |
| [docs/history/](docs/history/) | Earlier CLAUDE.md versions, original AI Studio design specs |
