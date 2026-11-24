# PyInstaller spec – build with:  python packaging/build.py   (or: pyinstaller packaging/magnetstudio.spec)
# Produces dist/MagnetStudio/ (a folder app; on macOS also dist/MagnetStudio.app).
# Bundled assets (fonts, sample templates, icons) go to <bundle>/magnetstudio/assets, which is
# where magnetstudio/paths.py:resource_dir() looks when sys.frozen is set.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
APP = "MagnetStudio"

hidden = (
    collect_submodules("keyring.backends")      # keychain backends are loaded by entry point
    + collect_submodules("magnetstudio")
    + ["platformdirs", "bidi", "bidi.algorithm"]
)

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "magnetstudio" / "assets"), "magnetstudio/assets")],
    hiddenimports=hidden,
    excludes=["tkinter", "pytest", "numpy", "pypdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=APP,
    console=False,                              # GUI app: no terminal window on Windows
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP)

if sys.platform == "darwin":
    app = BUNDLE(coll, name=f"{APP}.app", bundle_identifier="com.gpzboy.magnetstudio",
                 info_plist={"NSHighResolutionCapable": True, "LSApplicationCategoryType": "public.app-category.photography"})
