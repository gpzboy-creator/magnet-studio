# MagnetStudio

Desktop app (Windows & macOS) for event photo magnets: frames camera photos at exact magnet sizes
(7.5×10, 10×10, 15×20, 5×15 strip – 300 DPI) and prints them on a thermal / dye-sub printer or as
A4 sheets. Hot folder, Hebrew text frames, a visual frame designer and an AI frame generator.

אפליקציית דסקטופ להלבשת מסגרות והדפסת מגנטים מאירועים. פרטים מלאים – ארכיטקטורה, מוסכמות וסטטוס –
ב-[CLAUDE.md](CLAUDE.md).

## Install & run

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

## Layout

```
magnetstudio/
  app.py          entry point (logging, crash hooks, fonts, theme, main window)
  paths.py        every file location (bundled assets vs. per-user data)
  core/           image processing, templates, layout, settings, log – no Qt
  generator/      AI / offline frame generator
  services/       Qt, non-widget: printing, background workers, print queue controller
  ui/             PyQt6 widgets
  assets/         bundled fonts, sample templates, icons
tests/            pytest
packaging/        PyInstaller spec
```
