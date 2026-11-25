"""Builds dist/NickenosOblivionConverter.zip: a folder with the .exe and its files (no console window).

    python packaging/build.py
Needs: pip install -r requirements.txt, and third_party/ooz/build/ooz.dll (see docs/BUILDING.md).

It's a folder in a zip and not one .exe that unpacks itself: virus scanners flag the single .exe much more
often (4 of 71 on VirusTotal against 1 of 70), and Nexus locks every bare .exe until a moderator checks it.
"""
import platform
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

if struct.calcsize('P') != 8 or platform.machine().upper() not in ('AMD64', 'X86_64'):
    sys.exit('Build with 64-bit Python on an x64 PC: ooz.dll is x64 and the .exe has to match it.')

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
NAME = 'NickenosOblivionConverter'
TITLE = "Nickeno's Oblivion Converter"
sys.path.insert(0, str(ROOT))
from osc import __version__  # noqa: E402

ooz = ROOT / 'third_party' / 'ooz' / 'build' / 'ooz.dll'
if not ooz.is_file():
    sys.exit('third_party/ooz/build/ooz.dll is missing, build it first (see README)')


def version_file() -> Path:
    """What Windows shows under Properties > Details. An .exe without it looks more suspicious to scanners."""
    nums = (tuple(int(n) for n in __version__.split('.')) + (0, 0, 0, 0))[:4]
    strings = {'CompanyName': 'nickeno', 'FileDescription': TITLE, 'FileVersion': __version__,
               'InternalName': NAME, 'LegalCopyright': 'GPL-3.0, github.com/nickeno/oblivion-converter',
               'OriginalFilename': NAME + '.exe', 'ProductName': TITLE, 'ProductVersion': __version__}
    rows = ',\n      '.join(f'StringStruct({k!r}, {v!r})' for k, v in strings.items())
    out = ROOT / 'build' / 'version_info.txt'
    out.parent.mkdir(exist_ok=True)
    out.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      {rows}])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding='utf-8')
    return out


subprocess.check_call([sys.executable, str(HERE / 'make_icon.py')])
subprocess.check_call([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
    '--name', NAME,
    '--icon', str(HERE / 'app.ico'),
    '--version-file', str(version_file()),
    '--add-data', f'{ROOT / "osc" / "ui"};osc/ui',
    '--add-binary', f'{ooz};osc',
    '--exclude-module', 'numpy',
    '--paths', str(ROOT),
    '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build'), '--specpath', str(ROOT / 'build'),
    str(HERE / 'run.py'),
])

app = ROOT / 'dist' / NAME
# Nexus refuses an upload with a zip inside a zip, so Python's own library is unpacked next to the other files
library = app / '_internal' / 'base_library.zip'
with zipfile.ZipFile(library) as z:
    z.extractall(library.parent)
library.unlink()

out = ROOT / 'dist' / (NAME + '.zip')
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for f in sorted(app.rglob('*')):
        if f.is_file():
            z.write(f, f.relative_to(app.parent))
print('built', out)
