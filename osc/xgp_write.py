"""Write a new save into an Xbox / Game Pass (wgs) save folder.

Layout and sync-state values follow GPSaveConverter (Fr33dan, open source), which imports saves into
Game Pass for many games:
  index header state   2 = changed since last upload, 3 = synced
  container state      1 = synced, 2 = changed, 3 = deleted, 5 = created here (never uploaded)
A new container gets state 5 and an empty cloud ETag, so the Xbox services upload it when the game starts.

Oblivion Remastered also keeps `saves_meta` (AllSavesDetails map: slot name -> SaveGameDetails) which the
load menu reads, so the new save is added there too, as the next revision of that container (marked changed).

The game must be closed while this runs. Back up the wgs folder first.
"""
import copy
import datetime
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .binio import Reader, Writer
from .gvas import FStr, _read_props, _write_props, find_prop, parse_gvas, read_fstr, serialize_gvas, write_fstr

INDEX_CHANGED, CONTAINER_CHANGED, CONTAINER_CREATED = 2, 2, 5


def _now_filetime() -> int:
    return int((datetime.datetime.now(datetime.timezone.utc)
                - datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)).total_seconds() * 10_000_000)


def _rws(r: Reader) -> str:
    n = r.u32()
    return r.bytes(n * 2).decode('utf-16-le')


def _wws(w: Writer, s: str):
    b = s.encode('utf-16-le', 'surrogatepass')
    w.u32(len(b) // 2); w.bytes(b)             # the count is UTF-16 units, not letters


@dataclass
class IndexEntry:
    name: str
    name2: str
    etag: str
    num: int
    state: int
    guid: bytes          # 16 bytes, bytes_le
    mtime: int
    unknown: int
    size: int

    @property
    def folder_name(self) -> str:
        return uuid.UUID(bytes_le=self.guid).hex.upper()


@dataclass
class Index:
    version: int
    unknown1: int
    package: str
    mtime: int
    state: int
    index_id: str
    unknown3: int
    entries: list = field(default_factory=list)


def parse_index(raw: bytes) -> Index:
    r = Reader(raw)
    version, count, unk1 = r.u32(), r.u32(), r.u32()
    idx = Index(version, unk1, _rws(r), r.u64(), r.u32(), _rws(r), r.u64())
    for _ in range(count):
        idx.entries.append(IndexEntry(_rws(r), _rws(r), _rws(r), r.u8(), r.u32(), r.bytes(16),
                                      r.u64(), r.u64(), r.u64()))
    return idx


def read_index(path: Path) -> Index:
    return parse_index(path.read_bytes())


def read_index_for_writing(path: Path) -> Index:
    """The index, only when this app can write it back exactly as it was (a newer layout would lose data)."""
    raw = path.read_bytes()
    try:
        idx = parse_index(raw)
        same = write_index(idx) == raw
    except Exception:
        same = False
    if not same:
        raise ImportError_("The Game Pass save list is in a format this app doesn't know yet, "
                           "so nothing was changed. Look for a newer version of the app.")
    return idx


def write_index(idx: Index) -> bytes:
    w = Writer()
    w.u32(idx.version); w.u32(len(idx.entries)); w.u32(idx.unknown1)
    _wws(w, idx.package); w.u64(idx.mtime); w.u32(idx.state); _wws(w, idx.index_id); w.u64(idx.unknown3)
    for e in idx.entries:
        _wws(w, e.name); _wws(w, e.name2); _wws(w, e.etag)
        w.u8(e.num); w.u32(e.state); w.bytes(e.guid); w.u64(e.mtime); w.u64(e.unknown); w.u64(e.size)
    return w.out()


def container_name(slot_name: str) -> str:
    """'Save 1, Playing Time 01.14.32 - nick - LOC_FN_X, Level 2' -> 'Save1PlayingTime011432-nick-LOC_FN_XLevel2'
    'autosave 5 - nick (9FA11841-...)' -> 'autosave5-nick9FA11841-...'"""
    return ''.join(c for c in slot_name if c.isascii() and (c.isalnum() or c in '_-'))


class ImportError_(Exception):
    pass


class RollbackError(ImportError_):
    """Writing failed and putting the old files back failed too: the save folder may be out of step."""


NO_TEMPLATE = 'Save once in Oblivion Remastered first, so there is a save to copy settings from.'


def write_atomic(path: Path, data: bytes, overwrite: bool = True):
    """Write next to the file, then swap it in, so a crash never leaves half a file behind.
    The temporary name is short and unique, so two writers never share it and long names still fit.
    With overwrite=False an existing file is never replaced (Windows' rename refuses to)."""
    tmp = path.with_name(f'.osc{uuid.uuid4().hex[:12]}.tmp')
    try:
        with open(tmp, 'xb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if overwrite:
            os.replace(tmp, path)
        else:
            os.rename(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


# ----------------------------------------------------------------------------- saves_meta
def _meta_map(meta):
    mp = find_prop(meta.props, 'AllSavesDetails')
    r = Reader(mp.raw)
    removed, n = r.u32(), r.u32()
    entries = []
    for _ in range(n):
        k = read_fstr(r)
        entries.append((k, _read_props(r, len(mp.raw))))
    return mp, removed, entries


def _store_meta_map(mp, removed, entries):
    w = Writer()
    w.u32(removed); w.u32(len(entries))
    for k, props in entries:
        write_fstr(w, k); _write_props(w, props)
    mp.raw = w.out()


def meta_with_entry(meta_bytes: bytes, slot_name: str, details_props, base_slot: str = None) -> bytes:
    """Add (or replace) one AllSavesDetails entry. Fields the .sav details lack (Type, bIsESS, ...) are
    copied from `base_slot`'s entry, or the first manual save's."""
    meta = parse_gvas(meta_bytes)
    mp, removed, entries = _meta_map(meta)

    def save_type(props):
        t = find_prop(props, 'Type')
        return t if t is not None and t.kind == 'enum' else None

    base = next((p for k, p in entries if k.s == base_slot), None) if base_slot else None
    if base is None:
        base = next((p for k, p in entries if (t := save_type(p)) and t.value.s.endswith('Manual')), None)
    if base is None:                    # only autosaves or quicksaves so far: borrow one of those
        if not entries:
            raise ImportError_(NO_TEMPLATE)
        base = entries[0][1]
    new = copy.deepcopy(base)
    by_name = {p.name.s: p for p in details_props}
    new = [copy.deepcopy(by_name[p.name.s]) if p.name.s in by_name else p for p in new]
    t = save_type(new)
    if t is not None and not t.value.s.endswith('Manual'):      # the new one is a normal save
        t.value.s = t.value.s.rsplit('::', 1)[0] + '::Manual'
    entries = [(k, p) for k, p in entries if k.s != slot_name]
    entries.insert(0, (FStr(slot_name), new))
    _store_meta_map(mp, removed, entries)
    return serialize_gvas(meta)


def meta_without_entry(meta_bytes: bytes, slot_name: str) -> bytes:
    meta = parse_gvas(meta_bytes)
    mp, removed, entries = _meta_map(meta)
    _store_meta_map(mp, removed, [(k, p) for k, p in entries if k.s != slot_name])
    return serialize_gvas(meta)


# ----------------------------------------------------------------------------- import
def _container_bytes(files) -> bytes:
    """container.N: version 4, then per file a 64-letter name, the cloud copy's guid and the local file's guid."""
    w = Writer()
    w.u32(4); w.u32(len(files))
    for fname, cloud, local in files:
        w.bytes(fname.encode('utf-16-le').ljust(128, b'\0')[:128])
        w.bytes(cloud); w.bytes(local)
    return w.out()


def _guid_name(b: bytes) -> str:
    return uuid.UUID(bytes_le=b).hex.upper()


def import_save(wgs_user_dir: Path, sav_bytes: bytes, slot_name: str, details_props, base_slot: str = None) -> str:
    """Add `sav_bytes` as a new save. Returns the container name.

    Nothing the game reads changes until the last step, writing containers.index. Before that the new save
    and the new revision of saves_meta are only extra files nobody points at; the game itself saves the same
    way (a new container.N and data file each time, the old ones removed after). A crash or a failed write
    before the index is in leaves the saves exactly as they were."""
    from .xgp import container_file, read_container
    index_path = wgs_user_dir / 'containers.index'
    idx = read_index_for_writing(index_path)
    name = container_name(slot_name)
    if any(e.name == name for e in idx.entries):
        raise ImportError_(f'A save named {name} already exists')
    now = _now_filetime()

    # 1. saves_meta: worked out first, so a save list we can't read stops this before anything is written
    meta_e = next((e for e in idx.entries if e.name == 'saves_meta'), None)
    if meta_e is None:
        raise ImportError_(NO_TEMPLATE)
    meta_folder = wgs_user_dir / meta_e.folder_name
    meta_cfile = container_file(meta_folder, meta_e.num)
    meta_files = read_container(meta_cfile)
    data_i = next((i for i, f in enumerate(meta_files) if f[0] == 'Data'), None)
    if data_i is None:
        raise ImportError_(NO_TEMPLATE)
    meta_blob = meta_folder / _guid_name(meta_files[data_i][2])
    old_meta = meta_blob.read_bytes()
    new_meta = meta_with_entry(old_meta, slot_name, details_props, base_slot)

    made = []                       # taken away again if this stops before the index is written
    folder_guid, file_guid = uuid.uuid4(), uuid.uuid4()
    folder = wgs_user_dir / folder_guid.hex.upper()
    in_place = meta_e.num >= 255    # the revision number is one byte: past that, rewrite the old file
    try:
        # 2. new container folder + container.1 + data blob
        folder.mkdir()
        made.append(folder)
        write_atomic(folder / file_guid.hex.upper(), sav_bytes, overwrite=False)
        write_atomic(folder / 'container.1', _container_bytes([('Data', b'\0' * 16, file_guid.bytes_le)]),
                     overwrite=False)    # no cloud copy yet

        # 3. the next revision of saves_meta, beside the current one (keeps its cloud guid, like the game)
        if not in_place:
            blob_guid = uuid.uuid4()
            new_blob = meta_folder / blob_guid.hex.upper()
            write_atomic(new_blob, new_meta, overwrite=False)
            made.append(new_blob)
            files = list(meta_files)
            files[data_i] = ('Data', files[data_i][1], blob_guid.bytes_le)
            new_cfile = meta_folder / f'container.{meta_e.num + 1}'
            write_atomic(new_cfile, _container_bytes(files))      # a leftover from a crash is not in use
            made.append(new_cfile)

        # 4. the index: this is the moment the game sees the new save
        entry = IndexEntry(name, name, '', 1, CONTAINER_CREATED, folder_guid.bytes_le, now, 0, len(sav_bytes))
        place = next((i for i, e in enumerate(idx.entries) if e.name > name), len(idx.entries))   # ordinal order
        idx.entries.insert(place, entry)
        meta_e.mtime, meta_e.size = now, len(new_meta)
        if not in_place:
            meta_e.num += 1
        if meta_e.state == 1:
            meta_e.state = CONTAINER_CHANGED
        idx.mtime, idx.state = now, INDEX_CHANGED
        new_index = write_index(idx)
        if in_place:
            write_atomic(meta_blob, new_meta)
            try:
                write_atomic(index_path, new_index)
            except BaseException:
                try:
                    write_atomic(meta_blob, old_meta)
                except BaseException:
                    raise RollbackError("The save couldn't be added and the save list couldn't be put back. "
                                        "Restore the backup before playing.")
                raise
        else:
            write_atomic(index_path, new_index)
    except BaseException:
        for p in reversed(made):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    p.unlink()
                except OSError:
                    pass
        raise

    # 5. the old revision of saves_meta is no longer used (the game removes its old ones the same way)
    if not in_place:
        for p in (meta_cfile, meta_blob):
            try:
                p.unlink()
            except OSError:
                pass
    return name
