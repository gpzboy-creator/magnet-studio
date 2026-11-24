"""Central font registry: custom fonts (assets/fonts/) first, then system fonts.

- scan:     assets/fonts/*.ttf|*.otf (+ system font folders), family → {style: path}
- Qt:       register_qt_fonts() → QFontDatabase.addApplicationFont, so custom fonts appear
            in QFontDialog / the designer's font picker. Qt family names become aliases,
            so a name picked in the UI always resolves to the same file for Pillow.
- Pillow:   get_font(family, size, bold) → ImageFont.truetype on the mapped file.
            Variable fonts get their weight axis set (400 / 700).
- bundle:   ensure_default_fonts() downloads Heebo, Assistant, Rubik, Varela Round
            (SIL OFL, Google Fonts) when assets/fonts/ is empty.
- add:      add_font_file(path) copies a user font in and refreshes everything live.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont, features

from magnetstudio.paths import BUNDLED_FONTS_DIR

FONTS_DIR = BUNDLED_FONTS_DIR
FONT_EXTS = (".ttf", ".otf")
SYSTEM_EXTS = (".ttf", ".otf", ".ttc")
HAS_RAQM = features.check_feature("raqm")

GOOGLE_FONTS_RAW = "https://raw.githubusercontent.com/google/fonts/main/ofl/{dir}/{file}"
DEFAULT_FONTS = [  # (repo dir, file, is_variable)
    ("heebo", "Heebo[wght].ttf", True),
    ("assistant", "Assistant[wght].ttf", True),
    ("rubik", "Rubik[wght].ttf", True),
    ("varelaround", "VarelaRound-Regular.ttf", False),
]

# fallbacks with good Hebrew coverage, tried when a family is missing
DEFAULT_FAMILIES = ["Heebo", "Assistant", "Rubik", "Arial", "Arial Hebrew", "Segoe UI",
                    "Noto Sans Hebrew", "DejaVu Sans", "FreeSans"]

_lock = threading.RLock()
_custom: dict[str, dict[str, str]] = {}
_system: dict[str, dict[str, str]] | None = None
_aliases: dict[str, str] = {}        # lower-case name → canonical family
_qt_registered: dict[str, list[str]] = {}  # path → Qt families


# ============================================================== scanning

def _system_dirs() -> list[Path]:
    home = Path.home()
    if sys.platform == "win32":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        dirs = [windir / "Fonts", Path(os.environ.get("LOCALAPPDATA", home)) / "Microsoft/Windows/Fonts"]
    elif sys.platform == "darwin":
        dirs = [Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"),
                Path("/Library/Fonts"), home / "Library/Fonts"]
    else:
        dirs = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
                home / ".fonts", home / ".local/share/fonts"]
    return [d for d in dirs if d.is_dir()]


def font_names(path: str | Path) -> tuple[str, str] | None:
    """(family, style) as Pillow/FreeType sees it, or None if unreadable."""
    try:
        family, style = ImageFont.truetype(str(path), 12).getname()
    except Exception:
        return None
    return (family, style or "Regular") if family else None


def _scan(paths, recursive: bool, exts) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for d in paths:
        it = d.rglob("*") if recursive else d.glob("*")
        for p in sorted(it):
            if p.suffix.lower() in exts and p.is_file():
                names = font_names(p)
                if names:
                    index.setdefault(names[0], {}).setdefault(names[1], str(p))
    return index


def refresh_fonts(rescan_system: bool = False) -> None:
    """Rescan assets/fonts/ (cheap) and optionally system folders (slow, cached)."""
    global _custom, _system
    with _lock:
        _custom = _scan([FONTS_DIR], False, FONT_EXTS) if FONTS_DIR.is_dir() else {}
        if _system is None or rescan_system:
            _system = _scan(_system_dirs(), True, SYSTEM_EXTS)
        _aliases.clear()
        for fam in list(_system) + list(_custom):  # custom wins on name clash
            _aliases[fam.lower()] = fam
        for path, qt_fams in _qt_registered.items():
            canon = _family_of_path(path)
            for q in qt_fams:
                if canon:
                    _aliases.setdefault(q.lower(), canon)
        get_font.cache_clear()


def _ensure_scanned() -> None:
    if _system is None:
        refresh_fonts()


def _family_of_path(path: str) -> str | None:
    for idx in (_custom, _system or {}):
        for fam, styles in idx.items():
            if path in styles.values():
                return fam
    return None


def font_index() -> dict[str, dict[str, str]]:
    """{family: {style: path}} – custom fonts override system fonts with the same name."""
    _ensure_scanned()
    with _lock:
        merged = {k: dict(v) for k, v in (_system or {}).items()}
        for fam, styles in _custom.items():
            merged[fam] = dict(styles)
        return merged


def custom_font_families() -> list[str]:
    _ensure_scanned()
    return sorted(_custom, key=str.lower)


def system_font_families() -> list[str]:
    _ensure_scanned()
    return sorted((f for f in (_system or {}) if f not in _custom), key=str.lower)


def available_font_families() -> list[str]:
    """Custom fonts first, then system fonts (each group alphabetical)."""
    return custom_font_families() + system_font_families()


def canonical_family(name: str) -> str | None:
    """Registry family for any spelling / Qt alias of `name`, or None if unknown."""
    _ensure_scanned()
    return _aliases.get(name.lower()) if name else None


def is_custom_family(family: str) -> bool:
    _ensure_scanned()
    return _aliases.get(family.lower(), family) in _custom


# ============================================================== resolving

def _pick_style(styles: dict[str, str], bold: bool) -> str:
    want = ("Bold",) if bold else ("Regular", "Book", "Normal", "Roman", "Medium")
    for w in want:
        for style, path in styles.items():
            if style.lower() == w.lower():
                return path
    if bold:
        for style, path in styles.items():
            if "bold" in style.lower() and "italic" not in style.lower() and "semi" not in style.lower():
                return path
    plain = [p for s, p in styles.items() if "italic" not in s.lower() and "oblique" not in s.lower()]
    return (plain or list(styles.values()))[0]


def resolve_font_path(family: str = "", bold: bool = False) -> str | None:
    """File for `family` (any case, Qt alias ok); falls back to Hebrew-capable defaults."""
    _ensure_scanned()
    with _lock:
        for fam in ([family] if family else []) + DEFAULT_FAMILIES:
            canon = _aliases.get(fam.lower())
            if canon:
                styles = _custom.get(canon) or (_system or {}).get(canon)
                if styles:
                    return _pick_style(styles, bold)
    return None


def _apply_weight(font: ImageFont.FreeTypeFont, bold: bool) -> None:
    """Variable fonts: set the wght axis (their default instance is often Light)."""
    try:
        axes = font.get_variation_axes()
    except Exception:
        return
    values, changed = [], False
    for ax in axes:
        name = ax.get("name", b"")
        name = name.decode(errors="ignore") if isinstance(name, bytes) else str(name)
        v = ax.get("default", ax["minimum"])
        if name.lower() in ("weight", "wght"):
            v = max(ax["minimum"], min(ax["maximum"], 700 if bold else 400))
            changed = True
        values.append(v)
    if changed:
        font.set_variation_by_axes(values)


@lru_cache(maxsize=256)
def get_font(family: str, size: int, bold: bool = False, font_path: str = "") -> ImageFont.FreeTypeFont:
    path = font_path if font_path and Path(font_path).exists() else resolve_font_path(family, bold)
    engine = ImageFont.Layout.RAQM if HAS_RAQM else ImageFont.Layout.BASIC
    if not path:
        return ImageFont.load_default(size)
    font = ImageFont.truetype(path, size, layout_engine=engine)
    _apply_weight(font, bold)
    return font


# ============================================================== Qt registration

def register_qt_fonts() -> list[str]:
    """Register every custom font with Qt (idempotent). Needs a QGuiApplication."""
    try:
        from PyQt6.QtGui import QFontDatabase, QGuiApplication
    except ImportError:
        return []
    if QGuiApplication.instance() is None:
        return []
    _ensure_scanned()
    added = []
    with _lock:
        for styles in _custom.values():
            for path in styles.values():
                if path in _qt_registered:
                    continue
                fid = QFontDatabase.addApplicationFont(path)
                fams = list(QFontDatabase.applicationFontFamilies(fid)) if fid >= 0 else []
                _qt_registered[path] = fams
                added += fams
        canon_by_path = {p: _family_of_path(p) for p in _qt_registered}
        for path, fams in _qt_registered.items():
            for q in fams:
                if canon_by_path[path]:
                    _aliases.setdefault(q.lower(), canon_by_path[path])
    return sorted(set(added))


def qt_family(family: str) -> str:
    """Name Qt knows this family by (for QFont previews)."""
    canon = _aliases.get(family.lower(), family)
    for path, fams in _qt_registered.items():
        if fams and _family_of_path(path) == canon:
            return fams[0]
    return family


# ============================================================== adding fonts

def _sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def add_font_file(src: str | Path) -> str:
    """Copy a TTF/OTF into assets/fonts/, refresh the registry and Qt. Returns the family name."""
    src = Path(src)
    if src.suffix.lower() not in FONT_EXTS:
        raise ValueError("רק קובצי TTF או OTF נתמכים")
    names = font_names(src)
    if not names:
        raise ValueError(f"הקובץ {src.name} אינו גופן תקין")
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = FONTS_DIR / src.name
    if dst.exists() and dst.resolve() != src.resolve():
        if _sha1(dst) != _sha1(src):  # same name, different font → keep both
            n = 2
            while (FONTS_DIR / f"{src.stem}-{n}{src.suffix}").exists():
                n += 1
            dst = FONTS_DIR / f"{src.stem}-{n}{src.suffix}"
    if not dst.exists():
        shutil.copy2(src, dst)
    refresh_fonts()
    register_qt_fonts()
    return names[0]


# ============================================================== default font bundle

def _download(url: str, dst: Path, timeout: float) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MagnetStudio"})
        with urllib.request.urlopen(req, timeout=timeout) as r, \
                tempfile.NamedTemporaryFile(delete=False, dir=dst.parent, suffix=".part") as tmp:
            shutil.copyfileobj(r, tmp)
        tmp_path = Path(tmp.name)
        if dst.suffix.lower() in FONT_EXTS and not font_names(tmp_path):
            tmp_path.unlink(missing_ok=True)
            return False
        tmp_path.replace(dst)
        return True
    except Exception:
        return False


def _instance_static(vf_path: Path, family: str) -> list[Path]:
    """Variable font → static Regular + Bold (needs fontTools; otherwise keep the VF)."""
    try:
        from fontTools.ttLib import TTFont
        from fontTools.varLib import instancer
    except ImportError:
        return [vf_path]
    out = []
    try:
        for style, w in (("Regular", 400), ("Bold", 700)):
            inst = instancer.instantiateVariableFont(TTFont(vf_path), {"wght": w}, updateFontNames=True)
            p = vf_path.with_name(f"{family}-{style}.ttf")
            inst.save(p)
            out.append(p)
        vf_path.unlink(missing_ok=True)
        return out
    except Exception:
        return [vf_path]


def ensure_default_fonts(force: bool = False, timeout: float = 15.0) -> list[str]:
    """Download the Hebrew font bundle if assets/fonts/ has no fonts. Returns new files.
    Safe offline: failures are skipped silently."""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    if not force and any(p.suffix.lower() in FONT_EXTS for p in FONTS_DIR.iterdir()):
        return []
    lic_dir = FONTS_DIR / "licenses"
    lic_dir.mkdir(exist_ok=True)
    new: list[str] = []
    for d, fname, variable in DEFAULT_FONTS:
        url = GOOGLE_FONTS_RAW.format(dir=d, file=urllib.request.quote(fname))
        family = fname.split("[")[0].split("-")[0]
        dst = FONTS_DIR / (f"{family}-VF.ttf" if variable else fname)
        if not _download(url, dst, timeout):
            continue
        new += [p.name for p in (_instance_static(dst, family) if variable else [dst])]
        _download(GOOGLE_FONTS_RAW.format(dir=d, file="OFL.txt"), lic_dir / f"OFL-{d}.txt", timeout)
    if new:
        refresh_fonts()
    return new


try:
    from PyQt6.QtCore import QThread, pyqtSignal

    class FontDownloadWorker(QThread):
        """Runs ensure_default_fonts() off the GUI thread; register Qt fonts on `done`."""
        done = pyqtSignal(list)

        def run(self) -> None:
            self.done.emit(ensure_default_fonts())
except ImportError:
    FontDownloadWorker = None  # type: ignore[assignment,misc]
