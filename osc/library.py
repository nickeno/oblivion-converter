"""Finds saves on this PC and converts them. This is what the app window talks to.

Paths can be overridden for testing: OSC_OG_SAVES, OSC_STEAM_REM, OSC_WGS (a wgs user folder),
OSC_BACKUPS.
"""
import base64
import ctypes
import datetime
import hashlib
import io
import os
import re
import struct
import uuid
import zipfile
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from . import xgp, xgp_write
from .binio import Reader
from .convert import (OG_SHOT_H, OG_SHOT_W, ConvertError, display_name, og_to_remastered, planned_slot_name,
                      remastered_to_og, _pretty_location)
from .ess import decode_text, parse_ess, player_look
from .gvas import find_prop, parse_gvas, text_prop_string
from .remastered import open_save

REMASTERED_EXES = ('OblivionRemastered-WinGDK-Shipping.exe', 'OblivionRemastered-Win64-Shipping.exe')
APP_DIR_NAME = "Nickeno's Oblivion Converter"
KEEP_BACKUPS = 20          # newest backups kept per store; each is a zip of the whole save folder
KEEP_BACKUPS_MIN = 3       # always kept, also when they are big
BACKUPS_MAX_BYTES = 2 * 1024 ** 3      # older ones go once a store's backups pass this


class UserError(Exception):
    """Something the user can fix; the message is shown as-is."""


class save_lock:
    """One convert at a time on this PC: also across two app windows and the command line.
    A named Windows mutex, so it goes away by itself if the app is closed or crashes."""
    NAME = 'Local\\NickenosOblivionConverter.convert'

    def __enter__(self):
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.CreateMutexW.restype = wintypes.HANDLE
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.ReleaseMutex.argtypes = k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.k32, self.h = k32, k32.CreateMutexW(None, False, self.NAME)
        if not self.h:
            raise UserError("The converter couldn't start the convert. Try again.")
        if k32.WaitForSingleObject(self.h, 60_000) not in (0, 0x80):      # signaled, or left by a crashed app
            k32.CloseHandle(self.h)
            raise UserError('Another convert is still running. Try again when it is done.')
        return self

    def __exit__(self, *exc):
        self.k32.ReleaseMutex(self.h)
        self.k32.CloseHandle(self.h)


# ----------------------------------------------------------------------------- folders
def documents_dir() -> Path:
    """The real Documents folder, also when it is moved to OneDrive."""
    try:
        class GUID(ctypes.Structure):
            _fields_ = [('a', wintypes.DWORD), ('b', wintypes.WORD), ('c', wintypes.WORD), ('d', ctypes.c_ubyte * 8)]
        u = uuid.UUID('FDD39AD0-238F-46AF-ADB4-6C85480369C7')     # FOLDERID_Documents
        g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        p = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
            path = p.value
            ctypes.windll.ole32.CoTaskMemFree(p)
            return Path(path)
    except Exception:
        pass
    return Path.home() / 'Documents'


def og_saves_dir() -> Path:
    if os.environ.get('OSC_OG_SAVES'):
        return Path(os.environ['OSC_OG_SAVES'])
    home = documents_dir() / 'My Games' / 'Oblivion'
    return _ini_saves_dir(home) or home / 'Saves'


def _ini_saves_dir(home: Path) -> Optional[Path]:
    """The save folder Oblivion.ini points at (SLocalSavePath). Save profiles from mod managers change it.
    Used even when it doesn't exist yet: showing the default folder's saves instead would mix up profiles."""
    try:
        for line in (home / 'Oblivion.ini').read_text('cp1252', 'replace').splitlines():
            key, _, value = line.partition('=')
            if key.strip().lower() == 'slocalsavepath':
                value = value.split(';')[0].strip().strip('"')
                return home / value if value else None
    except OSError:
        pass
    return None


def steam_rem_dir() -> Path:
    return Path(os.environ.get('OSC_STEAM_REM') or
                documents_dir() / 'My Games' / 'Oblivion Remastered' / 'Saved' / 'SaveGames')


def xbox_dirs() -> list:
    if os.environ.get('OSC_WGS'):
        return [Path(os.environ['OSC_WGS'])]
    return xgp.default_wgs_dirs()


def backups_dir() -> Path:
    return Path(os.environ.get('OSC_BACKUPS') or documents_dir() / APP_DIR_NAME / 'Backups')


class _ProcessEntry(ctypes.Structure):          # PROCESSENTRY32W
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wintypes.DWORD),
                ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD),
                ('pcPriClassBase', wintypes.LONG), ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]


def running_exes() -> set:
    """Lowercase names of the running programs, asked from Windows directly (no helper program is started)."""
    out = set()
    try:
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry)]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        snap = k32.CreateToolhelp32Snapshot(2, 0)               # TH32CS_SNAPPROCESS
        if not snap or snap == ctypes.c_void_p(-1).value:
            return out
        try:
            pe = _ProcessEntry()
            pe.dwSize = ctypes.sizeof(_ProcessEntry)
            more = k32.Process32FirstW(snap, ctypes.byref(pe))
            while more:
                out.add(pe.szExeFile.lower())
                more = k32.Process32NextW(snap, ctypes.byref(pe))
        finally:
            k32.CloseHandle(snap)
    except Exception:
        pass
    return out


def remastered_running() -> bool:
    exes = running_exes()
    return any(e.lower() in exes for e in REMASTERED_EXES)


# ----------------------------------------------------------------------------- model
@dataclass
class SaveEntry:
    id: str
    game: str              # 'og' | 'remastered'
    store: str             # 'og' | 'xbox' | 'steam'
    title: str             # 'Save 527', 'Autosave 5', 'Quicksave'
    character: str
    character_key: str     # groups saves of one character
    level: int
    location: str
    play_seconds: int
    saved_at: float        # unix time
    kind: str              # 'manual' | 'auto' | 'quick'

    def to_json(self):
        return asdict(self)


# ----------------------------------------------------------------------------- original Oblivion
def _bz(r: Reader) -> str:
    n = r.u8()
    return decode_text(r.bytes(n)[:max(0, n - 1)])


def _og_header(head: bytes):
    """Fields up to the screenshot, from the first ~1 KB of an .ess."""
    r = Reader(head)
    if r.bytes(12) != b'TES4SAVEGAME':
        return None
    r.u8(); r.u8(); r.bytes(16); r.u32(); r.u32()
    save_num = r.u32()
    name = _bz(r)
    level = r.u16()
    loc = _bz(r)
    days = r.f32()
    ticks = r.u32()
    st_offset = r.pos
    st = struct.unpack('<8H', r.bytes(16))          # SYSTEMTIME of the real-world save
    shot_size = r.u32()
    return dict(save_num=save_num, name=name, level=level, location=loc, days=days, ticks=ticks,
                systime=st, systime_offset=st_offset, shot_offset=r.pos, shot_size=shot_size)


def _systime_to_unix(st) -> Optional[float]:
    y, mo, _dow, d, h, mi, s, ms = st
    try:
        return datetime.datetime(y, mo, d, h, mi, s, ms * 1000).timestamp()
    except Exception:
        return None


def _og_title(stem: str) -> tuple:
    low = stem.lower()
    if low.startswith('autosave'):
        return 'Autosave', 'auto'
    if low.startswith('quicksave'):
        return 'Quicksave', 'quick'
    return stem.split(' - ')[0].strip() or stem, 'manual'


def _dir_tag(d: Path) -> str:
    """Short tag of a folder, so an id made for one save profile never opens a same-named file in another."""
    return hashlib.sha1(str(d).lower().encode('utf-8', 'replace')).hexdigest()[:8]


def og_id(d: Path, name: str) -> str:
    return f'og:{_dir_tag(d)}:{name}'


def og_path(entry_id: str) -> Path:
    """The .ess an 'og:<folder tag>:<file>' id points at, in the current save folder."""
    _, tag, name = (entry_id.split(':', 2) + ['', ''])[:3]
    d = og_saves_dir()
    if tag != _dir_tag(d):
        raise UserError('That save is gone. Refresh the list.')
    return _file_in(d, name)


def list_og() -> list:
    d = og_saves_dir()
    out = []
    if not d.is_dir():
        return out
    for f in d.glob('*.ess'):
        try:
            with open(f, 'rb') as fh:
                h = _og_header(fh.read(2048))
            if not h:
                continue
            title, kind = _og_title(f.stem)
            when = _systime_to_unix(h['systime']) or f.stat().st_mtime
            out.append(SaveEntry(og_id(d, f.name), 'og', 'og', title, h['name'], 'og:' + h['name'].lower(),
                                 h['level'], h['location'], h['ticks'] // 1000, when, kind))
        except Exception:
            continue
    out.sort(key=lambda s: s.saved_at, reverse=True)
    return out


def _og_thumbnail(path: Path) -> Optional[bytes]:
    with open(path, 'rb') as fh:
        head = fh.read(2048)
        h = _og_header(head)
        if not h or h['shot_size'] < 8:
            return None
        fh.seek(h['shot_offset'])
        shot = fh.read(h['shot_size'])
    from PIL import Image
    r = Reader(shot)
    w, hgt = r.u32(), r.u32()
    img = Image.frombytes('RGB', (w, hgt), r.bytes(w * hgt * 3))
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=85)
    return buf.getvalue()


# ----------------------------------------------------------------------------- Remastered
def _ticks_to_unix(ticks: int) -> Optional[float]:
    try:
        return (datetime.datetime(1, 1, 1) + datetime.timedelta(microseconds=ticks // 10)).timestamp()
    except Exception:
        return None


def _rem_entry(entry_id: str, store: str, props: list, group: str = None) -> SaveEntry:
    """`group` sets which saves are listed as one character: a Game Pass profile's own ('xbox:<profile>')."""
    def v(n, default=None):
        p = find_prop(props, n)
        return p if p is not None else default
    name = text_prop_string(v('DisplayPlayerName')) or ''
    level = v('PlayerLevel').value if v('PlayerLevel') else 0
    loc = v('PlayerLocation').value.s if v('PlayerLocation') else ''
    pt = v('PlayTime'); play = struct.unpack('<q', pt.raw)[0] // 10_000_000 if pt and pt.raw else 0
    sd = v('SaveDate'); when = _ticks_to_unix(struct.unpack('<q', sd.raw)[0]) if sd and sd.raw else None
    typ = v('Type').value.s if v('Type') else ''
    num = v('SaveNumber').value if v('SaveNumber') else 0
    save_name = v('SaveName').value.s.lower() if v('SaveName') else ''
    if 'Quick' in typ or save_name == 'quicksave':
        title, kind = 'Quicksave', 'quick'
    elif 'Auto' in typ or save_name == 'autosave':
        title, kind = f'Autosave {num + 1}', 'auto'
    else:
        title, kind = f'Save {num + 1}', 'manual'
    cid = v('CharacterId')
    ckey = (cid.raw.hex() if cid is not None and cid.raw else name.lower())
    return SaveEntry(entry_id, 'remastered', store, title, name, (group or store) + ':' + ckey, level,
                     _pretty_location(loc) if loc.startswith('LOC_') else loc, play, when or 0, kind)


_meta_cache: dict = {}


def _meta_by_container(meta_bytes: bytes) -> dict:
    """container/file name -> (slot key, props) from saves_meta."""
    key = (len(meta_bytes), hash(meta_bytes))
    if key in _meta_cache:
        return _meta_cache[key]
    meta = parse_gvas(meta_bytes)
    _mp, _rem, entries = xgp_write._meta_map(meta)
    out = {}
    for k, props in entries:
        out[xgp_write.container_name(k.s)] = (k.s, props)
        out[k.s] = (k.s, props)
    _meta_cache.clear()
    _meta_cache[key] = out
    return out


SKIP_REM = ('saves_meta', 'save_settings', 'wingdk_save_settings')


def list_remastered() -> list:
    out = []
    for wgs in xbox_dirs():
        try:
            saves = xgp.list_saves(wgs)
        except Exception:
            continue
        by_name = {s.name: s for s in saves}
        meta = {}
        if 'saves_meta' in by_name:
            try:
                meta = _meta_by_container(by_name['saves_meta'].data_file.read_bytes())
            except Exception:
                meta = {}
        for s in saves:
            if s.name.lower() in SKIP_REM:
                continue
            eid = f'xbox:{wgs.name}:{s.name}'
            try:
                props = meta[s.name][1] if s.name in meta else open_save(s.data_file.read_bytes()).details.props
                out.append(_rem_entry(eid, 'xbox', props, 'xbox:' + wgs.name))
            except Exception:
                continue
    sd = steam_rem_dir()
    if sd.is_dir():
        meta = {}
        mf = sd / 'saves_meta.sav'
        if mf.is_file():
            try:
                meta = _meta_by_container(mf.read_bytes())
            except Exception:
                meta = {}
        for f in sd.glob('*.sav'):
            if f.stem.lower() in SKIP_REM:
                continue
            try:
                props = meta[f.stem][1] if f.stem in meta else open_save(f.read_bytes()).details.props
                out.append(_rem_entry('steam:' + f.name, 'steam', props))
            except Exception:
                continue
    out.sort(key=lambda s: s.saved_at, reverse=True)
    return out


def _file_in(folder: Path, name: str) -> Path:
    """folder/name, only when `name` is a plain file name (an id can't point outside the save folder)."""
    if not name or name in ('.', '..') or Path(name).name != name or ':' in name:
        raise UserError('That save is gone. Refresh the list.')
    return folder / name


def _rem_bytes(entry_id: str) -> bytes:
    kind, rest = entry_id.split(':', 1)
    if kind == 'steam':
        return _file_in(steam_rem_dir(), rest).read_bytes()
    wgs_name, name = rest.split(':', 1)
    for wgs in xbox_dirs():
        if wgs.name == wgs_name:
            for s in xgp.list_saves(wgs):
                if s.name == name:
                    return s.data_file.read_bytes()
    raise UserError('That save is gone. Refresh the list.')


def _rem_thumbnail(entry_id: str) -> Optional[bytes]:
    kind, rest = entry_id.split(':', 1)
    try:
        if kind == 'xbox':
            wgs_name, name = rest.split(':', 1)
            for wgs in xbox_dirs():
                if wgs.name == wgs_name:
                    saves = {s.name: s for s in xgp.list_saves(wgs)}
                    if 'saves_meta' in saves:
                        meta = _meta_by_container(saves['saves_meta'].data_file.read_bytes())
                        if name in meta:
                            p = find_prop(meta[name][1], 'SaveThumbnail')
                            if p is not None and p.data:
                                return p.data
        elif kind == 'steam':
            mf = steam_rem_dir() / 'saves_meta.sav'
            if mf.is_file():
                meta = _meta_by_container(mf.read_bytes())
                stem = Path(rest).stem
                if stem in meta:
                    p = find_prop(meta[stem][1], 'SaveThumbnail')
                    if p is not None and p.data:
                        return p.data
    except Exception:
        pass
    p = open_save(_rem_bytes(entry_id)).detail('SaveThumbnail')
    return p.data if p is not None and p.data else None


# ----------------------------------------------------------------------------- public API
def thumbnail(entry_id: str) -> Optional[str]:
    """data: URL of the save's picture. Not cached here: autosaves and quicksaves are overwritten in place."""
    try:
        if entry_id.startswith('og:'):
            jpg = _og_thumbnail(og_path(entry_id))
        else:
            jpg = _rem_thumbnail(entry_id)
    except Exception:
        jpg = None
    return 'data:image/jpeg;base64,' + base64.b64encode(jpg).decode() if jpg else None


def status() -> dict:
    return {
        'og_dir': str(og_saves_dir()), 'og_found': og_saves_dir().is_dir(),
        'xbox_found': bool(xbox_dirs()), 'steam_dir': str(steam_rem_dir()), 'steam_found': steam_rem_dir().is_dir(),
        'backups_dir': str(backups_dir()),
    }


def _hms(seconds: int) -> str:
    h, rem = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rem, 60)
    return f'{h:02d}.{m:02d}.{s:02d}'


def _safe_filename(s: str) -> str:
    return _clean(s) or 'Save'


def _clean(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', s).strip()


MAX_PATH = 250                  # Windows' classic path limit (260) with room to spare


def _og_filename(folder: Path, n: int, name: str, loc: str, level: int, seconds: int) -> Path:
    """'Save 12 - Name - Place, Level 3, Playing Time 01.02.03.ess', with name and place cut short when the
    whole path would be too long for Windows."""
    name, loc = _clean(name)[:40].strip(), _clean(loc)[:60].strip()
    while True:
        path = folder / f'Save {n} - {name} - {loc}, Level {level}, Playing Time {_hms(seconds)}.ess'
        over = len(str(path)) - MAX_PATH
        if over <= 0 or (not name and not loc):
            return path
        if loc:
            loc = loc[:max(0, len(loc) - over)].strip()
        else:
            name = name[:max(0, len(name) - over)].strip()


def _set_save_num(data: bytes, n: int) -> bytes:
    """The save number in an .ess header (always at byte 38)."""
    return data[:38] + struct.pack('<I', n) + data[42:]


def to_og(entry_id: str, target_dir: Optional[str] = None) -> dict:
    """Remastered save -> new .ess in the original game's Saves folder (or target_dir)."""
    with save_lock():
        return _to_og(entry_id, target_dir)


def _to_og(entry_id: str, target_dir: Optional[str]) -> dict:
    out_dir = Path(target_dir) if target_dir else og_saves_dir()
    if not out_dir.is_dir():
        raise UserError("Original Oblivion's save folder wasn't found. Start the original game once, or pick a folder.")
    nums = []
    for f in out_dir.iterdir():
        m = re.match(r'save (\d+)\b', f.name, re.IGNORECASE)        # Windows names ignore case
        if m and f.suffix.lower() == '.ess':
            nums.append(int(m.group(1)))
    n = max(nums, default=0) + 1
    data = remastered_to_og(_rem_bytes(entry_id), save_num=n)
    h = _og_header(data[:2048])
    # the new save is made now, so it shows up as the newest one
    now = datetime.datetime.now()
    stamp = struct.pack('<8H', now.year, now.month, (now.weekday() + 1) % 7, now.day,
                        now.hour, now.minute, now.second, now.microsecond // 1000)
    data = data[:h['systime_offset']] + stamp + data[h['systime_offset'] + 16:]
    for _ in range(100):
        path = _og_filename(out_dir, n, h['name'], h['location'], h['level'], h['ticks'] // 1000)
        try:
            xgp_write.write_atomic(path, _set_save_num(data, n), overwrite=False)     # never over a save
            break
        except FileExistsError:
            n += 1
    else:
        raise UserError("No free save name was found in the original game's save folder.")
    return {'id': og_id(out_dir, path.name), 'path': str(path), 'title': f'Save {n}',
            'where': 'Original Oblivion > Load'}


def _inside(p: Path, root: Path) -> bool:
    return p == root or root in p.parents


def _backup(src: Path, label: str) -> Path:
    """A zip of `src` (a folder or one file) in the backups folder. Never overwrites another backup, and
    never packs the backups folder itself when it sits inside `src`."""
    bdir = backups_dir()
    bdir.mkdir(parents=True, exist_ok=True)
    broot = bdir.resolve()
    stamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    for i in range(1000):
        zpath = bdir / (f'{label}_{stamp}.zip' if i == 0 else f'{label}_{stamp}_{i}.zip')
        try:
            fh = open(zpath, 'xb')
            break
        except FileExistsError:
            continue
    else:
        raise UserError("A backup couldn't be made, so nothing was changed.")
    try:
        with fh, zipfile.ZipFile(fh, 'w', zipfile.ZIP_DEFLATED) as z:
            if src.is_dir():
                for f in sorted(src.rglob('*')):
                    if f.is_file() and not _inside(f.resolve(), broot) and not f.name.startswith('.osc'):
                        z.write(f, f.relative_to(src.parent))
            else:
                z.write(src, src.name)
    except BaseException:
        try:
            zpath.unlink()
        except OSError:
            pass
        raise
    total = 0
    for i, old in enumerate(sorted(bdir.glob(f'{label}_*.zip'), reverse=True)):    # names sort by date
        try:
            total += old.stat().st_size
            if i >= KEEP_BACKUPS or (i >= KEEP_BACKUPS_MIN and total > BACKUPS_MAX_BYTES):
                old.unlink()
        except OSError:
            pass
    return zpath


FACE_NOTE = ("The face may look off: no Remastered character of the same race and sex was found. "
             "Make one in Remastered, then convert again.")


def _template_for(ess: bytes, store: str, wgs_name: Optional[str] = None) -> tuple:
    """(save to build on, its bytes, face fits). The new save borrows that save's Remastered face, and a face
    is made for one race and sex. So: the newest save of a character with the same race and sex, else the same
    race, else simply the newest save. A save that won't open is skipped, it never blocks a good one."""
    try:
        want = player_look(parse_ess(ess))
    except Exception:
        want = None
    newest = same_race = None
    seen = set()
    for s in list_remastered():
        if s.store != store or (wgs_name is not None and s.id.split(':')[1] != wgs_name):
            continue
        if want is not None and s.character_key in seen:     # one look per character: its newest good save
            continue
        try:
            raw = _rem_bytes(s.id)
            look = player_look(parse_ess(open_save(raw).ess))
        except Exception:
            continue
        seen.add(s.character_key)
        newest = newest or (s, raw)
        if want is None:
            break
        if look == want:
            return s, raw, True
        if look is not None and look[0] == want[0]:
            same_race = same_race or (s, raw)
    pick = same_race or newest
    return (pick[0], pick[1], False) if pick else (None, None, False)


def remastered_targets() -> list:
    t = []
    dirs = xbox_dirs()
    for i, wgs in enumerate(dirs, 1):
        label = 'Game Pass / Xbox app' + (f' (profile {i})' if len(dirs) > 1 else '')
        t.append({'id': f'xbox:{wgs.name}', 'label': label, 'short': 'Game Pass' + (f' {i}' if len(dirs) > 1 else '')})
    if steam_rem_dir().is_dir():
        t.append({'id': 'steam', 'label': 'Steam', 'short': 'Steam'})
    return t


def _known_locations(meta: dict) -> list:
    """Real location keys (LOC_FN_...) from a save list, so a converted save reuses the game's own key."""
    out = []
    for _slot, props in meta.values():
        p = find_prop(props, 'PlayerLocation')
        if p is not None and p.kind == 'str' and p.value.s.startswith('LOC_FN_') and p.value.s not in out:
            out.append(p.value.s)
    return out


def to_remastered(entry_id: str, target: Optional[str] = None) -> dict:
    """OG .ess -> new Remastered save, added to the Game Pass or Steam save folder."""
    if not entry_id.startswith('og:'):
        raise UserError('Pick an original Oblivion save.')
    with save_lock():
        return _to_remastered(entry_id, target)


def _to_remastered(entry_id: str, target: Optional[str]) -> dict:
    targets = remastered_targets()
    if not targets:
        raise UserError("No Oblivion Remastered saves were found. Play Remastered and save once first.")
    target = target or targets[0]['id']
    if target not in [t['id'] for t in targets]:
        raise UserError("That Oblivion Remastered save folder is gone. Refresh and try again.")
    check_game_closed(target)
    try:
        ess = og_path(entry_id).read_bytes()
        og = parse_ess(ess)
    except OSError:
        raise UserError('That save is gone. Refresh the list.')

    def build(template: bytes, taken, known) -> tuple:
        """The converted save under the first free 'Save N' name (the same save converted twice)."""
        n = next((n for n in range(1, 1000) if not taken(planned_slot_name(og, n, known))), None)
        if n is None:
            raise UserError('That save has been converted too many times. Delete some copies in Remastered first.')
        try:
            sav = og_to_remastered(ess, template, save_number=n, known_locations=known)
        except ConvertError as e:
            raise UserError(str(e))
        details = open_save(sav).details.props
        return sav, details, find_prop(details, 'SlotName').value.s, n

    if target.startswith('xbox:'):
        wgs_name = target.split(':', 1)[1]
        wgs = next((w for w in xbox_dirs() if w.name == wgs_name), None)
        tmpl, tmpl_bytes, fits = _template_for(ess, 'xbox', wgs_name)
        if wgs is None or tmpl is None:
            raise UserError('Save once in Oblivion Remastered first, so there is a save to copy settings from.')
        names = {e.name.lower() for e in xgp_write.read_index(wgs / 'containers.index').entries}
        saves = {s.name: s for s in xgp.list_saves(wgs)}
        meta = _meta_by_container(saves['saves_meta'].data_file.read_bytes()) if 'saves_meta' in saves else {}
        tmpl_name = tmpl.id.split(':', 2)[2]
        base_slot = meta[tmpl_name][0] if tmpl_name in meta else None
        sav, details, slot, n = build(tmpl_bytes, lambda s: xgp_write.container_name(s).lower() in names,
                                      _known_locations(meta))
        backup = _backup(wgs, 'GamePass')
        try:
            name = xgp_write.import_save(wgs, sav, slot, details, base_slot)
        except xgp_write.RollbackError as e:
            raise UserError(f'{e} It is in {backup}.')
        except xgp_write.ImportError_ as e:
            raise UserError(str(e))
        return {'id': f'xbox:{wgs_name}:{name}', 'title': f'Save {n}', 'container': name, 'backup': str(backup),
                'where': 'Oblivion Remastered > Load > ' + display_name(open_save(sav)),
                'note': None if fits else FACE_NOTE}

    # Steam: the save is a plain file named after its slot, listed in saves_meta.sav
    sd = steam_rem_dir()
    tmpl, tmpl_bytes, fits = _template_for(ess, 'steam')
    if tmpl is None:
        raise UserError('Save once in Oblivion Remastered first, so there is a save to copy settings from.')
    mf = sd / 'saves_meta.sav'
    meta_bytes = mf.read_bytes() if mf.is_file() else None
    meta = {}
    if meta_bytes is not None:
        try:
            meta = _meta_by_container(meta_bytes)
        except Exception:
            meta = {}
    tmpl_stem = Path(tmpl.id.split(':', 1)[1]).stem
    base_slot = meta[tmpl_stem][0] if tmpl_stem in meta else None
    slots = {k.lower() for k in meta}
    sav, details, slot, n = build(
        tmpl_bytes, lambda s: (sd / (_safe_filename(s) + '.sav')).exists() or _safe_filename(s).lower() in slots,
        _known_locations(meta))
    path = sd / (_safe_filename(slot) + '.sav')
    if len(str(path)) > MAX_PATH:
        raise UserError("The Remastered save folder's path is too long for this save's name.")
    new_meta = None
    if meta_bytes is not None:          # worked out before anything is written
        try:
            new_meta = xgp_write.meta_with_entry(meta_bytes, path.stem, details, base_slot)
        except xgp_write.ImportError_ as e:
            raise UserError(str(e))
    backup = _backup(sd, 'Steam')
    try:
        xgp_write.write_atomic(path, sav, overwrite=False)
    except FileExistsError:
        raise UserError('A save with that name showed up meanwhile. Try again.')
    if new_meta is not None:
        try:
            xgp_write.write_atomic(mf, new_meta)
        except BaseException:           # no half-added save: take the new file away again
            try:
                path.unlink()
            except OSError:
                pass
            raise
    return {'id': 'steam:' + path.name, 'title': f'Save {n}', 'path': str(path),
            'backup': str(backup), 'where': 'Oblivion Remastered > Load',
            'note': None if fits else FACE_NOTE}


def check_game_closed(target: str):
    """The game keeps its saves open while it runs (a test copy of the folder is not the game's)."""
    test_copy = os.environ.get('OSC_WGS' if target.startswith('xbox:') else 'OSC_STEAM_REM')
    if not test_copy and remastered_running():
        raise UserError('Close Oblivion Remastered first, then try again.')


def import_to_game_pass(wgs: Path, sav: bytes) -> tuple:
    """For the command line: add a ready .sav to one Game Pass profile, with the same lock, game check and
    backup as the app. Returns (container name, backup zip)."""
    with save_lock():
        check_game_closed('xbox:' + wgs.name)
        details = open_save(sav).details.props
        slot = find_prop(details, 'SlotName').value.s
        backup = _backup(wgs, 'GamePass')
        try:
            return xgp_write.import_save(wgs, sav, slot, details), backup
        except xgp_write.RollbackError as e:
            raise UserError(f'{e} It is in {backup}.')
        except xgp_write.ImportError_ as e:
            raise UserError(str(e))
