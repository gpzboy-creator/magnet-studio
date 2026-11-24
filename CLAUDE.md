# MagnetStudio

## מה זה
אפליקציית דסקטופ (Windows & macOS) להכנת תמונות מגנטים: הלבשת מסגרות/תבניות על תמונות, שיפור להדפסה והדפסה.

## דרישות עיקריות
- **פלטפורמות:** Windows ו-macOS (Python + PyQt6).
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
  - הדפסה רצה ב-`PrintWorker` (QThread). "שמירה ל-PDF (Dry Run)" זמין תמיד לפיתוח בלי מדפסת.
- **תיקייה במעקב (watchdog):** תמונות חדשות מעובדות ומודפסות אוטומטית (באירועים).
- **תבניות (JSON):** חלונות תמונה (גם סטריפ 3-4), טקסט חי בעברית (RTL), גרפיקה PNG. עורך ויזואלי.
- **סגנון מגנטים ישראלי (ברירת מחדל במחולל):** חלון תמונה שקוף (alpha 0) · סרגל תחתון עם שמות + סמל
  (לב / טבעות / זר) + תאריך כפי שהוקלד · קרדיט צלם אנכי בשוליים הימניים (`CreditLayer`) · עיטורי פינות
  (ענפי זית / צבעי מים) שחופפים מעט את שולי התמונה.
- **זוג כיווניות:** כל מסגרת לתמונה בודדת נוצרת כ-`TemplatePair` (portrait + landscape) בקובץ JSON אחד;
  `render_magnet` / הדפסה בוחרים אוטומטית לפי כיוון התמונה מהמצלמה (אחרי סיבוב EXIF).
- **מחולל מסגרות AI:** תיאור חופשי בעברית → תבנית. Gemini Structured Output (סכמת Pydantic `FrameDesign`),
  רקע אמנותי ממודל תמונה של Gemini עם Alpha Hole Punch, ו-Fallback דטרמיניסטי מלא באופליין.
- **גופנים מותאמים:** `assets/fonts/` (TTF/OTF) נסרקת בעלייה, נרשמת ל-Qt ומופיעה ראשונה בבורר הגופנים.
  מצורפים Heebo, Assistant, Rubik (Regular+Bold) ו-Varela Round – SIL OFL, רישיונות ב-`assets/fonts/licenses/`.
- **Fast AI Enhancer:** LUT מקומי (הרמת צללים + רוויה ל-Dye-Sub). סגנונות ענן Gemini אופציונליים עם Fallback.

## מבנה הפרויקט
```
main.py                 נקודת כניסה
core/                   מנוע (ללא תלות ב-ui/)
  sizes.py              גדלים והמרות ס"מ↔פיקסלים
  fonts.py              רישום גופנים: סריקה, Qt, מיפוי משפחה→קובץ ל-Pillow, הורדת חבילת ברירת מחדל
  image_processor.py    טעינה (EXIF) וחיתוך לגודל היעד
  framer.py             render_magnet: חיתוך → שיפור → מסגרת PNG / תבנית JSON
  templates.py          מודל תבנית, JSON, רינדור Pillow (render_overlay_frame, compose_magnet)
  ai_enhancer.py        LUT מקומי, Gemini, EnhancementWorker
  frame_generator.py    parse_event (Regex), FrameDesign, build_preset_template, FrameGeneratorWorker
  layout.py             פריסת A4 (best-fit)
  printer.py            זיהוי מדפסות, PrintWorker, Dry Run ל-PDF
  watcher.py            מעקב תיקייה
  settings.py           הגדרות: שמירה אטומית, טעינה בטוחה (קובץ פגום → ברירת מחדל + גיבוי)
  applog.py             לוג מתחלף לקובץ + hooks לחריגות לא צפויות
ui/                     PyQt6
  main_window.py        חלון ראשי: סרגל עליון, פאנל הגדרות, תצוגה מקדימה, QueuePanel
  theme.py              עיצוב AI Studio: ThemeColors, get_theme_qss() + APP_QSS, RTL גלובלי
  widgets.py            עזרים: ltr(), make_thumb(), QueueItem
  components/queue_panel.py  QueuePanel (צ'יפים: מדפסת · Hot Folder · סה״כ) + QueueCardWidget (88px)
  designer.py           עורך תבניות (QGraphicsView)
  frame_generator_dialog.py  דיאלוג "✨ מחולל AI"
  settings_dialog.py    הגדרות שיפור / Gemini
  toast.py              הודעות קופצות
config/settings.json    הגדרות ברירת מחדל
assets/templates/       תבניות JSON ומסגרות PNG (+ <שם>_assets/ לגרפיקה של תבנית)
  _generated/           שכבות שהמחולל יצר (לפני שמירה כתבנית)
assets/fonts/           גופנים מותאמים (נסרקים אוטומטית, "הוסף גופן מהמחשב…" מעתיק לכאן)
tests/                  test_printer / test_templates / test_ai_enhancer / test_frame_generator
```

## מוסכמות
- כל חישובי הגודל דרך `core/sizes.py` – לא לכתוב מספרי פיקסלים בקוד.
- כל העיבוד ב-300 DPI; שמירה עם `dpi=(300, 300)`.
- `core/` לא מייבא מ-`ui/`. (`core/printer.py` ו-`EnhancementWorker` משתמשים ב-Qt ללא widgets.)
- סדר עיבוד: טעינה → חיתוך לגודל הדפסה → שיפור (enhancer) → מסגרת/תבנית.
- תבנית – שכבות: רקע → שכבות z<0 (מאחורי התמונה) → חלונות תמונה (שקופים) → שכבות z≥0 (מעל התמונה)
  → קרדיט צלם (תמיד עליון; מסובב ב-transpose מדויק, בלי resampling).
- JSON: `load_frame` / `save_frame` לתבנית בודדת או לזוג; `load_template` על זוג מחזיר גרסה אחת.
  גרפיקה מ-`_generated/` תמיד מועתקת ל-`<שם>_assets/` בשמירה.
- טקסט הקרדיט: הגדרה `photographer_credit` (ברירת מחדל: "שחר לוי גונן | 0525860073").
- שוליים בטוחים (≥3 מ"מ) נשמרים גם בתחתית הסרגל; צבע תאריך ושמות בניגודיות ≥ 4.5:1.
- טקסט: גודל בפיקסלים של הקנבס. העורך מציג טקסט ברינדור Pillow עצמו – WYSIWYG.
- עברית: libraqm אם קיים ב-Pillow, אחרת python-bidi.
- כל גישה לגופנים דרך `core/fonts.py` (`get_font`, `resolve_font_path`) – לא `ImageFont.truetype` ישירות.
- `render_text_layer` מרפד לפי גבולות הדיו האמיתיים (ניקוד, זנבות, קו מתאר) ומחזיר `info["offset"]`;
  מי שממקם טקסט חייב להוסיף את ה-offset (כבר מטופל ב-`_composite` וב-`TextItem.setOffset`).
- גופנים משתנים (Variable): עדיף להמיר ל-Regular/Bold סטטיים; אחרת `get_font` קובע ציר wght=400/700.
- UI: צבעים רק מ-`ThemeColors` (ui/theme.py). סגנון לפי property `class` (card / action-btn / primary)
  או objectName; אחרי שינוי property → `theme.repolish`. חיצים: SVG ב-`assets/ui/`.
- RTL: `apply_theme` קובע `app.setLayoutDirection(RightToLeft)` – בלי זה Qt מסדר טקסט מעורב לא נכון.
  רצף LTR בתוך עברית ("+1", "×3") עוטפים ב-`widgets.ltr()`.
- כרטיסיית תור: 88px; תגיות QueueItemStatus: התקבלה → משופרת/מורכבת → בהדפסה → הודפסה / נכשלה.
  כל PrintJob נושא `tag` = מזהה הכרטיסייה; המונה סופר מגנטים ונשמר ב-`print_count_total`.
- מקלדת בתור (eventFilter ברמת האפליקציה ב-MainWindow, לא כשמקלידים בשדה טקסט/מספר):
  ↑/↓ בחירה · רווח מדפיס את הנבחרת וממשיך לבאה · תמונה שכבר הודפסה (PRINTED) דורשת רווח כפול
  תוך 1.5 ש' (`ReprintGuard`) – Esc/↑/↓ מבטלים · כפתור "הדפס" בעכבר/מגע מדפיס מיד, בלי אישור.
  כפתורי הכרטיסייה NoFocus – רווח לא יכול "ללחוץ" עליהם. רווח מוחזק (auto-repeat) לא נחשב לחיצה כפולה.
- עבודה ארוכה (הדפסה, שיפור ענן, מחולל AI) – תמיד ב-QThread, אף פעם לא ב-GUI thread.
- הגדרות: לשמור רק דרך `MainWindow.persist_settings(reason)` – נקרא אחרי כל הדפסה, שינוי מסגרת,
  Hot Folder, מתג שיפור ודיאלוג הגדרות. `save_settings` אטומי (temp + fsync + os.replace) ולא זורק.
- לוג: `log = logging.getLogger(__name__)` בכל מודול; שגיאה לא צפויה → `log.exception(...)`.
  תיקייה: Windows %LOCALAPPDATA%\MagnetStudio\Logs · Mac ~/Library/Logs/MagnetStudio ·
  Linux ~/.local/state/MagnetStudio/logs. 1MB × 6 קבצים. כפתור "פתח תיקיית לוגים" בהגדרות.
- בדיקות שיוצרות MainWindow חייבות להגדיר MAGNETSTUDIO_SETTINGS ו-MAGNETSTUDIO_LOG_DIR לתיקייה זמנית.
- כל קריאת ענן חייבת Fallback מקומי; האפליקציה עובדת מלא באופליין באירוע.
- Imagen הושבת ב-17.8.2026 – רקעים נוצרים במודל תמונה של Gemini (`gemini_art_model` בהגדרות).
- פלט AI עובר תמיד `design_to_template` (הידוק לשוליים בטוחים, ניגודיות, טקסט לא על חלון תמונה).

## הרצה ובדיקות
```
pip install -r requirements.txt
python main.py

pip install -r requirements-dev.txt
python tests/test_printer.py
python tests/test_templates.py
python tests/test_ai_enhancer.py
python tests/test_frame_generator.py
python tests/test_fonts.py
python tests/test_ui.py
python tests/test_frames_style.py
python tests/test_queue_guard.py
python tests/test_persistence.py
```

## סטטוס ומה הלאה (עודכן 24.11.2026)
**נעשה:** שלד, גדלים, פריסת A4, הדפסה (טרמי/A4/PDF), Hot Folder, תבניות + עורך + מחולל (אופליין + Gemini),
גופנים עבריים, Fast Enhancer, ממשק כהה, סגנון מגנטים ישראלי (אנכי+אופקי), הגנת הדפסה חוזרת,
שמירה מיידית של הגדרות/מונה + לוג (שלבים 1–2 מסקירת הארכיטקטורה). 10 סוויטות בדיקה עוברות.

**לא נבדק במציאות:** מדפסת טרמית אמיתית (גודל נייר מותאם בדרייבר) · Gemini חי (שמות מודלים) ·
הרצה על Windows/Mac.

**הבא בתור (סקירת ארכיטקטורה):**
3. הוצאת `PrintQueueController` מ-main_window (מצב התור במקום אחד).
4. הגדרות בתיקיית המשתמש + מפתח API ב-keyring + נתיבים שעובדים אחרי PyInstaller.
5. פיצול `frame_generator.py` (parse / styles / ornaments / layout / ai).
6. חבילת Python (pyproject) + מעבר ל-pytest.

