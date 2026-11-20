"""Xbox / Game Pass save containers (wgs) — read-only listing.

Layout as used by community XGP save tools (e.g. HarukaMa's Starfield importer, which the
Oblivion Remastered Game Pass tools are forked from):

containers.index: u32 version(14), u32 count, u32 ?, str package, u64 filetime, u32 ?, str index_id, u64 ?,
  then per entry: str name, str name2, str id, u8 container_num, u32 ?, guid folder, u64 mtime, u64 ?, u64 size
container.N:      u32 version(4), u32 count, then per file: wchar[64] name, guid cloud, guid local
strings are u32 char count + UTF-16LE.
"""
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from .binio import Reader

PACKAGE_PREFIX = 'BethesdaSoftworks.ProjectAltar_'


def _wstr(r: Reader) -> str:
    n = r.u32()
    return r.bytes(n * 2).decode('utf-16-le')


def _guid_name(b: bytes) -> str:
    return uuid.UUID(bytes_le=b).hex.upper()


@dataclass
class XgpSave:
    name: str            # e.g. Save1PlayingTime025733-nickeno-LOC_FN_...
    folder: Path
    data_file: Path      # the blob that holds the .sav bytes
    size: int
    mtime_filetime: int


def default_wgs_dirs():
    base = Path(os.environ.get('LOCALAPPDATA', '')) / 'Packages'
    if not base.is_dir():
        return []
    out = []
    for pkg in base.glob(PACKAGE_PREFIX + '*'):
        wgs = pkg / 'SystemAppData' / 'wgs'
        if wgs.is_dir():
            out += [p for p in wgs.iterdir() if (p / 'containers.index').is_file()]
    return out


def container_file(folder: Path, num: int) -> Path:
    """The container.N the index points at. The game writes a new N on every save and removes the old one,
    so a leftover older or newer file must not be picked by mistake."""
    p = folder / f'container.{num}'
    if p.is_file():
        return p
    raise FileNotFoundError(f'{p.name} is missing in {folder.name}')


def read_container(path: Path) -> list:
    """[(file name, cloud guid bytes, local guid bytes)] from a container.N file."""
    r = Reader(path.read_bytes())
    r.u32()
    out = []
    for _ in range(r.u32()):
        name = r.bytes(128).decode('utf-16-le', 'replace').split('\0', 1)[0]
        out.append((name, r.bytes(16), r.bytes(16)))
    return out


def read_container_files(folder: Path, num: int) -> dict:
    return {name: folder / _guid_name(local) for name, _cloud, local in read_container(container_file(folder, num))}


def list_saves(wgs_user_dir: Path):
    r = Reader((wgs_user_dir / 'containers.index').read_bytes())
    r.u32()
    count = r.u32()
    r.u32()
    _wstr(r)
    r.u64(); r.u32()
    _wstr(r)
    r.u64()
    saves = []
    for _ in range(count):
        name = _wstr(r); _wstr(r); _wstr(r)
        num = r.u8(); r.u32()
        folder = wgs_user_dir / _guid_name(r.bytes(16))
        mtime = r.u64(); r.u64()
        size = r.u64()
        try:                    # one broken container hides only itself
            data = read_container_files(folder, num).get('Data')
        except Exception:
            continue
        if data and data.is_file():
            saves.append(XgpSave(name, folder, data, size, mtime))
    return saves
