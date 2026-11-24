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
- **Fast AI Enhancer:** LUT מקומי (הרמת צללים + רוויה ל-Dye-Sub). סגנונות ענן Gemini אופציונליים עם Fallback.

## מבנה הפרויקט
```
main.py                 נקודת כניסה
core/                   מנוע (ללא תלות ב-ui/)
  sizes.py              גדלים והמרות ס"מ↔פיקסלים
  image_processor.py    טעינה (EXIF) וחיתוך לגודל היעד
  framer.py             render_magnet: חיתוך → שיפור → מסגרת PNG / תבנית JSON
  templates.py          מודל תבנית, JSON, רינדור Pillow (render_overlay_frame, compose_magnet)
  ai_enhancer.py        LUT מקומי, Gemini, EnhancementWorker
  layout.py             פריסת A4 (best-fit)
  printer.py            זיהוי מדפסות, PrintWorker, Dry Run ל-PDF
  watcher.py            מעקב תיקייה
  settings.py           הגדרות
ui/                     PyQt6
  main_window.py        חלון ראשי, תור הדפסה, לפני/אחרי, גרירת קבצים
  designer.py           עורך תבניות (QGraphicsView)
  settings_dialog.py    הגדרות שיפור / Gemini
  toast.py              הודעות קופצות
config/settings.json    הגדרות ברירת מחדל
assets/templates/       תבניות JSON ומסגרות PNG (+ <שם>_assets/ לגרפיקה של תבנית)
assets/fonts/           (אופציונלי) גופנים נוספים – נסרקים אוטומטית
tests/                  test_printer / test_templates / test_ai_enhancer
```

## מוסכמות
- כל חישובי הגודל דרך `core/sizes.py` – לא לכתוב מספרי פיקסלים בקוד.
- כל העיבוד ב-300 DPI; שמירה עם `dpi=(300, 300)`.
- `core/` לא מייבא מ-`ui/`. (`core/printer.py` ו-`EnhancementWorker` משתמשים ב-Qt ללא widgets.)
- סדר עיבוד: טעינה → חיתוך לגודל הדפסה → שיפור (enhancer) → מסגרת/תבנית.
- תבנית – שכבות: רקע → שכבות z<0 (מאחורי התמונה) → חלונות תמונה (שקופים) → שכבות z≥0 (מעל התמונה).
- טקסט: גודל בפיקסלים של הקנבס. העורך מציג טקסט ברינדור Pillow עצמו – WYSIWYG.
- עברית: libraqm אם קיים ב-Pillow, אחרת python-bidi.
- עבודה ארוכה (הדפסה, שיפור ענן) – תמיד ב-QThread, אף פעם לא ב-GUI thread.

## הרצה ובדיקות
```
pip install -r requirements.txt
python main.py

pip install -r requirements-dev.txt
python tests/test_printer.py
python tests/test_templates.py
python tests/test_ai_enhancer.py
```
