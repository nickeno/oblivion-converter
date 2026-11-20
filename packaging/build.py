"""Builds dist/NickenosOblivionConverter.exe (one file, no console window).

    python packaging/build.py
Needs: pip install -r requirements.txt, and third_party/ooz/build/ooz.dll (see docs/BUILDING.md).
"""
import platform
import struct
import subprocess
import sys
from pathlib import Path

if struct.calcsize('P') != 8 or platform.machine().upper() not in ('AMD64', 'X86_64'):
    sys.exit('Build with 64-bit Python on an x64 PC: ooz.dll is x64 and the .exe has to match it.')

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
