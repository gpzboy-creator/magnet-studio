"""Build the desktop app:  python packaging/build.py  →  dist/MagnetStudio/"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                              "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
                              str(ROOT / "packaging" / "magnetstudio.spec")], cwd=ROOT))
