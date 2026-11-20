"""Builds dist/NickenosOblivionConverter.exe (one file, no console window).

    python packaging/build.py
Needs: pip install pywebview pillow pyinstaller, and third_party/ooz/build/ooz.dll (see README).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
ooz = ROOT / 'third_party' / 'ooz' / 'build' / 'ooz.dll'
if not ooz.is_file():
    sys.exit('third_party/ooz/build/ooz.dll is missing, build it first (see README)')
subprocess.check_call([sys.executable, str(HERE / 'make_icon.py')])
subprocess.check_call([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
    '--name', 'NickenosOblivionConverter',
    '--icon', str(HERE / 'app.ico'),
    '--add-data', f'{ROOT / "osc" / "ui"};osc/ui',
    '--add-binary', f'{ooz};osc',
    '--exclude-module', 'numpy',
    '--paths', str(ROOT),
    '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build'), '--specpath', str(ROOT / 'build'),
    str(HERE / 'run.py'),
])
print('built', ROOT / 'dist' / 'NickenosOblivionConverter.exe')
