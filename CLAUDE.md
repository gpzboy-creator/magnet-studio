# MagnetStudio

> מסמך העבודה הראשי לכל סוכן AI ומפתח (Claude, Codex, Cursor, Gemini…). `AGENTS.md` מפנה לכאן.
> **בסוף כל עבודה:** לעדכן "סטטוס ומה הלאה" למטה + רשומה ב-[docs/JOURNAL.md](docs/JOURNAL.md).
> ארכיטקטורה ואלגוריתמים: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## מה זה
אפליקציית דסקטופ (Windows & macOS) להכנת תמונות מגנטים מאירועים: הלבשת מסגרות/תבניות על תמונות,
שיפור להדפסה והדפסה. בעלים: שחר לוי גונן (Gpzboy). ריפו פרטי: `gpzboy-creator/magnet-studio`.

## דרישות עיקריות
- **פלטפורמות:** Windows ו-macOS (Python 3.10+ + PyQt6). פיתוח/בדיקות גם על Linux (offscreen).
- **גדלים (ס"מ) ב-300 DPI:**
  | גודל | פיקסלים |
  |------|---------|
  | 7.5x10 | 886 x 1181 |
  | 10x10 | 1181 x 1181 |
  | 15x20 | 1772 x 2362 |
  | 5x15 סטריפ | 591 x 1772 |
- **מצבי הדפסה:**
  1. **מדפסת טרמית** – תמונה אחת לכל הדפסה, בגודל המגנט המדויק.
  2. **פריסת A4** – כמה מגנטים על A4 (2480x3508 ב-300 DPI) עם קווי חיתוך.
     - **Auto-Orientation:** `core/layout.py` בודק כיוון מקורי מול סיבוב 90° ובוחר את המקסימום
       (7.5x10 → 6 לדף, 2x3 מסובב; 10x10 → 4; 15x20 → 1). גריד ממורכז, קווי חיתוך אפורים בהירים.
     - ברירת מחדל: שוליים 0.3 ס"מ, רווח 0.2 ס"מ (גדול יותר → 7.5x10 יורד ל-4 לדף).
  - "שמירה לקובץ PDF (בדיקה)" זמין תמיד – לפיתוח בלי מדפסת.
- **תיקייה במעקב (Hot Folder, watchdog):** תמונות חדשות מעובדות ומודפסות אוטומטית (באירועים).
- **תבניות (JSON):** חלונות תמונה (גם סטריפ 3-4), טקסט חי בעברית (RTL), גרפיקה PNG. עורך ויזואלי.
- **סגנון מגנטים ישראלי (ברירת מחדל במחולל):** חלון תמונה שקוף (alpha 0) · סרגל תחתון עם שמות + סמל
  (לב / טבעות / זר) + תאריך כפי שהוקלד · קרדיט צלם אנכי בשוליים הימניים (`CreditLayer`) · עיטורי פינות
  (ענפי זית / צבעי מים) שחופפים מעט את שולי התמונה.
- **זוג כיווניות:** כל מסגרת לתמונה בודדת נוצרת כ-`TemplatePair` (portrait + landscape) בקובץ JSON אחד;
  `render_magnet` / הדפסה בוחרים אוטומטית לפי כיוון התמונה מהמצלמה (אחרי סיבוב EXIF).
- **מחולל מסגרות AI:** תיאור חופשי בעברית → תבנית. Gemini Structured Output (סכמת Pydantic `FrameDesign`),
  רקע אמנותי ממודל תמונה של Gemini עם Alpha Hole Punch, ו-Fallback דטרמיניסטי מלא באופליין.
- **גופנים:** מצורפים Heebo, Assistant, Rubik (Regular+Bold) ו-Varela Round – SIL OFL
  (`magnetstudio/assets/fonts/`, רישיונות ב-`licenses/`). גופני משתמש בתיקיית הנתונים שלו.
- **Fast AI Enhancer:** LUT מקומי (הרמת צללים + רוויה ל-Dye-Sub). סגנונות ענן Gemini אופציונליים עם Fallback.

## מבנה הפרויקט
```
pyproject.toml          חבילה, תלויות ([ai] אופציונלי, [dev] לבדיקות/בנייה), pytest
AGENTS.md               כניסה לסוכנים אחרים → מפנה לכאן
docs/                   ARCHITECTURE.md · JOURNAL.md (יומן) · screenshots/ · history/ (גרסאות CLAUDE.md, מפרטי AI Studio)
run.bat / run.command / run.sh   הרצה מהריפו בלי התקנה (.venv מקומית)
launcher/               MagnetStudio.bat / .command – מפעיל שמוריד את ה-build האחרון מהשחרור ומפעיל
.devcontainer/          Codespaces: התוכנה בענן בלשונית דפדפן (live.py, setup.sh, start.sh, LIVE.md)
packaging/              magnetstudio.spec + build.py (PyInstaller) + launcher.py + ensure_env.py
magnetstudio/
  __init__.py           __version__
  __main__.py / app.py  נקודת כניסה: לוג, hooks, מיגרציה, keychain, גופנים, theme, חלון, SIGINT/SIGTERM
  paths.py              כל מיקום קובץ: משאבים מצורפים (לקריאה) מול תיקיות משתמש (platformdirs)
  core/                 Python טהור – בלי Qt
    sizes.py            גדלים והמרות ס"מ↔פיקסלים
    image_processor.py  טעינה (EXIF) וחיתוך לגודל היעד
    framer.py           render_magnet: חיתוך → שיפור → מסגרת PNG / תבנית JSON
    templates.py        מודל תבנית, JSON, רינדור Pillow
    fonts.py            רישום גופנים: סריקה, מיפוי משפחה→קובץ ל-Pillow, הורדת חבילת ברירת מחדל
    ai_enhancer.py      LUT מקומי + Gemini (enhance_local / enhance_cloud / enhance)
    layout.py           פריסת A4 (best-fit)
    print_jobs.py       PrintJob, PrintMode, build_pages, prepare_jobs (בלי Qt)
    watcher.py          מעקב תיקייה (watchdog)
    settings.py         הגדרות: שמירה אטומית, טעינה בטוחה
    secrets.py          מפתח Gemini ב-keychain (keyring) + Fallback
    migrate.py          העתקה חד-פעמית מהמבנה הישן (config/, assets/ בתוך הריפו)
    applog.py           לוג מתחלף + hooks לחריגות
  generator/            מחולל מסגרות (בלי Qt): parse · colors · layout · styles · ornaments · presets · ai · pipeline
  services/             Qt בלי widgets
    print_queue.py      PrintQueueController + Stage + QueueItem – כל מצב התור
    printer.py          זיהוי מדפסות, PrintWorker (QThread), QPainter→QPrinter, Dry Run ל-PDF
    enhancement_worker.py, generator_worker.py, fonts_qt.py
  ui/                   PyQt6 widgets בלבד
    main_window.py      חלון ראשי – מציג את מצב הבקר, בונה PrintJob לפי הבחירות (job_factory)
    theme.py            עיצוב כהה: ThemeColors, QSS, RTL גלובלי
    widgets.py          ltr(), make_thumb()
    components/queue_panel.py  QueuePanel + QueueCardWidget (88px) + ReprintGuard
    designer.py, frame_generator_dialog.py, settings_dialog.py, toast.py
  assets/               לקריאה בלבד: fonts/, templates/ (sample_*), ui/ (SVG)
tests/                  pytest; conftest מבודד (תיקיית בית זמנית + keyring בזיכרון)
```

## מוסכמות
- **שכבות:** `core/` ו-`generator/` לא מייבאים Qt (בדיקה אוכפת). `services/` – Qt בלי `QtWidgets`.
  `ui/` רק מציג ומבקש פעולות. אף שכבה לא מייבאת מ-`ui/`.
- **נתיבים:** רק דרך `magnetstudio/paths.py`. לעולם לא לכתוב לתוך `magnetstudio/` (במחשב מותקן זה
  Program Files / .app – לא כתיב, ועדכון מוחק). תבניות משתמש → `paths.user_templates_dir()`.
- **סודות:** מפתח API רק דרך `core/secrets.py` (`get_api_key`, `store_api_key`) – לא ב-settings.json.
- **תור הדפסה:** כל שינוי מצב דרך `PrintQueueController` (`window.queue`). לא להחזיק מצב תור בחלון.
  `Stage`: INCOMING → QUEUED → ENHANCING → COMPOSING → SPOOLING → PRINTED / FAILED.
  תג בכרטיסייה: QUEUED אחרי הדפסה קודמת מוצג "בהדפסה" (SPOOLING).
- כל חישובי הגודל דרך `core/sizes.py` – לא לכתוב מספרי פיקסלים בקוד.
- כל העיבוד ב-300 DPI; שמירה עם `dpi=(300, 300)`.
- סדר עיבוד: טעינה → חיתוך לגודל הדפסה → שיפור (enhancer) → מסגרת/תבנית.
- תבנית – שכבות: רקע → שכבות z<0 → חלונות תמונה (שקופים) → שכבות z≥0 → קרדיט צלם
  (תמיד עליון; מסובב ב-transpose מדויק, בלי resampling).
- JSON: `load_frame` / `save_frame` לתבנית בודדת או לזוג; `load_template` על זוג מחזיר גרסה אחת.
  גרפיקה מ-`_generated/` תמיד מועתקת ל-`<שם>_assets/` בשמירה.
- טקסט הקרדיט: הגדרה `photographer_credit` (ברירת מחדל: "שחר לוי גונן | 0525860073").
- שוליים בטוחים (≥3 מ"מ) נשמרים גם בתחתית הסרגל; צבע תאריך ושמות בניגודיות ≥ 4.5:1.
- טקסט: גודל בפיקסלים של הקנבס. העורך מציג טקסט ברינדור Pillow עצמו – WYSIWYG.
- עברית: libraqm אם קיים ב-Pillow, אחרת python-bidi.
- כל גישה לגופנים דרך `core/fonts.py` (`get_font`, `resolve_font_path`) – לא `ImageFont.truetype` ישירות.
  רישום ל-Qt: `services/fonts_qt.register_qt_fonts()`.
- `render_text_layer` מרפד לפי גבולות הדיו האמיתיים ומחזיר `info["offset"]`; מי שממקם טקסט חייב
  להוסיף את ה-offset.
- UI: צבעים רק מ-`ThemeColors` (ui/theme.py). סגנון לפי property `class` או objectName;
  אחרי שינוי property → `theme.repolish`. חיצים: SVG ב-`assets/ui/`.
- RTL: `apply_theme` קובע `app.setLayoutDirection(RightToLeft)`. רצף LTR בתוך עברית ("+1", "×3")
  עוטפים ב-`widgets.ltr()`.
- מקלדת בתור (eventFilter ברמת האפליקציה ב-MainWindow, לא כשמקלידים בשדה טקסט/מספר):
  ↑/↓ בחירה · רווח מדפיס את הנבחרת וממשיך לבאה · תמונה שכבר הודפסה דורשת רווח כפול תוך 1.5 ש'
  (`ReprintGuard`) – Esc/↑/↓ מבטלים · כפתור "הדפס" בעכבר/מגע מדפיס מיד. כפתורי הכרטיסייה NoFocus.
  רווח מוחזק (auto-repeat) לא נחשב לחיצה כפולה. תמונה שכבר בתור לא נשלחת שוב ברווח.
- עבודה ארוכה (הדפסה, שיפור ענן, מחולל AI) – תמיד ב-QThread, אף פעם לא ב-GUI thread.
- הגדרות: לשמור רק דרך `MainWindow.persist_settings(reason)` – אחרי כל הדפסה, שינוי מסגרת,
  Hot Folder, מתג שיפור, דיאלוג הגדרות וסגירה. `save_settings` אטומי ולא זורק.
- לוג: `log = logging.getLogger(__name__)` בכל מודול; שגיאה לא צפויה → `log.exception(...)`.
  1MB × 6 קבצים. כפתורי "פתח תיקיית לוגים" ו"תיקיית תבניות וגופנים" בהגדרות.
- כל קריאת ענן חייבת Fallback מקומי; האפליקציה עובדת מלא באופליין באירוע.
- Imagen הושבת ב-17.8.2026 – רקעים נוצרים במודל תמונה של Gemini (`gemini_art_model` בהגדרות).
- פלט AI עובר תמיד `design_to_template` (הידוק לשוליים בטוחים, ניגודיות, טקסט לא על חלון תמונה).
- **בדיקות:** לעולם לא לגעת בהגדרות/לוג/keychain אמיתיים – conftest נותן `MAGNETSTUDIO_HOME` זמני
  ו-keyring בזיכרון לכל בדיקה. חלון שנוצר בבדיקה נסגר ב-`close()` (לא `hide()` – ה-eventFilter נשאר).
  `QApplication.instance() or QApplication(...)` – אף פעם לא שני QApplication.
- **Git:** commit לכל שלב לוגי, הודעה באנגלית (שורת סיכום + נקודות). הבדיקות חייבות לעבור לפני commit.

## הרצה, בדיקות, בנייה
**הרצה ישירות מהריפו (בלי התקנה):** לחיצה כפולה על `run.bat` (Windows) / `run.command` (Mac) / `./run.sh` (Linux).
בפעם הראשונה נוצרת `.venv` בתוך הריפו (uv אם קיים, אחרת Python 3.10+); `packaging/ensure_env.py` מתקין מחדש
רק כש-`pyproject.toml` משתנה. `MAGNETSTUDIO_EXIT_AFTER_MS` סוגר את האפליקציה אוטומטית (בדיקת CI של הסקריפטים).
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[ai,dev]"
python -m magnetstudio                                  # או: magnetstudio
pytest                                                  # ~45 ש', offscreen, תיקיות זמניות
pytest tests/test_print_queue.py -q                     # קובץ בודד
python packaging/build.py                               # → dist/MagnetStudio/ (PyInstaller)
```
משתני סביבה: `MAGNETSTUDIO_HOME` (כל נתוני המשתמש בתיקייה אחת) · `MAGNETSTUDIO_SETTINGS` ·
`MAGNETSTUDIO_LOG_DIR` · `GEMINI_API_KEY` · `QT_QPA_PLATFORM=offscreen` (בלי מסך).

## סטטוס ומה הלאה (עודכן 24.11.2026)
**נעשה:** שלד, גדלים, פריסת A4, הדפסה (טרמי/A4/PDF), Hot Folder, תבניות + עורך + מחולל (אופליין + Gemini),
גופנים עבריים, Fast Enhancer, ממשק כהה, סגנון מגנטים ישראלי (אנכי+אופקי), הגנת הדפסה חוזרת.
**סקירת ארכיטקטורה – כל 6 השלבים הושלמו** (פירוט ביומן): שמירה מיידית + לוג · חבילה + pytest ·
פיצול המחולל · תיקיות משתמש + keychain + core בלי Qt + PyInstaller · PrintQueueController.
26 בדיקות עוברות (Linux). הקוד בריפו הפרטי `gpzboy-creator/magnet-studio` (ענף `main`).
**הורדה (נבנית אוטומטית בכל push):** https://github.com/gpzboy-creator/magnet-studio/releases/tag/latest
**תצוגה חיה בדפדפן (בדיקת כל שינוי, בלי התקנה):** https://codespaces.new/gpzboy-creator/magnet-studio?quickstart=1
  (`.devcontainer/` – Qt VNC + noVNC, `live.py` מושך מ-GitHub כל 20 ש' ומפעיל מחדש)
**מפעיל שמתעדכן לבד:** `launcher/MagnetStudio.bat` / `.command` – בודק עדכון, מוריד, מפעיל; מפתח GitHub לקריאה בלבד.
**הרצה מהריפו:** `run.bat` / `run.command` / `run.sh` (נבדק ב-Linux, וב-CI על Windows/Mac – עם Python ועם uv).

**לא נבדק במציאות:** מדפסת טרמית אמיתית (גודל נייר מותאם בדרייבר) · Gemini חי (שמות מודלים) ·
הרצה ובנייה על Windows/Mac (נבנה ונבדק רק על Linux) · מיגרציה מהתקנה ישנה אמיתית של שחר.

**הבא בתור (הצעות):**
1. **ניקוד עברי נחתך ב-Windows** (נמצא ב-CI: 0.2–1% דיו + יישור לימין) – לבדוק libraqm/python-bidi ב-Windows ולתקן.
   + לתקן את `test_fonts` (גופן "תורם" לפי מערכת הפעלה; לא לפתוח דיאלוג) ואת סף הזמן ב-`test_ai_enhancer`.
2. לפתוח את התצוגה החיה ב-Codespaces בפעם הראשונה ולוודא שעולה (setup.sh לא נבדק ב-Codespaces אמיתי; הקלדה בעברית ב-noVNC).
   אחר כך: להריץ על Windows/Mac אמיתי ולבדוק עם מדפסת אמיתית באירוע ניסיון.
3. אייקון לאפליקציה (`.ico` / `.icns`) + חתימה (macOS notarization) + installer (Inno Setup / DMG).
4. CI קיים (`.github/workflows/build.yml`); אחרי התיקונים – להפוך את הבדיקות לחוסמות.
