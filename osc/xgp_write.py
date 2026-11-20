"""Write a new save into an Xbox / Game Pass (wgs) save folder.

Layout and sync-state values follow GPSaveConverter (Fr33dan, open source), which imports saves into
Game Pass for many games:
  index header state   2 = changed since last upload, 3 = synced
  container state      1 = synced, 2 = changed, 3 = deleted, 5 = created here (never uploaded)
A new container gets state 5 and an empty cloud ETag, so the Xbox services upload it when the game starts.

Oblivion Remastered also keeps `saves_meta` (AllSavesDetails map: slot name -> SaveGameDetails) which the
load menu reads, so the new save is added there too. That blob is rewritten in place and marked changed.

The game must be closed while this runs. Back up the wgs folder first.
"""
import datetime
import os
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
    w.u32(len(s)); w.bytes(s.encode('utf-16-le'))


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


def read_index(path: Path) -> Index:
    r = Reader(path.read_bytes())
    version, count, unk1 = r.u32(), r.u32(), r.u32()
    idx = Index(version, unk1, _rws(r), r.u64(), r.u32(), _rws(r), r.u64())
    for _ in range(count):
        idx.entries.append(IndexEntry(_rws(r), _rws(r), _rws(r), r.u8(), r.u32(), r.bytes(16),
                                      r.u64(), r.u64(), r.u64()))
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
    base = next((p for k, p in entries if k.s == base_slot), None) if base_slot else None
    if base is None:
        base = next(p for k, p in entries if (t := find_prop(p, 'Type')) and t.value.s.endswith('Manual'))
    import copy
    new = copy.deepcopy(base)
    by_name = {p.name.s: p for p in details_props}
    new = [copy.deepcopy(by_name[p.name.s]) if p.name.s in by_name else p for p in new]
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
def _blob_path(folder: Path, entry: IndexEntry) -> Path:
    from .xgp import read_container_files
    return read_container_files(folder / entry.folder_name)['Data']


def import_save(wgs_user_dir: Path, sav_bytes: bytes, slot_name: str, details_props) -> str:
    """Add `sav_bytes` as a new save. Returns the container name."""
    index_path = wgs_user_dir / 'containers.index'
    idx = read_index(index_path)
    name = container_name(slot_name)
    if any(e.name == name for e in idx.entries):
        raise ImportError_(f'A save named {name} already exists')
    now = _now_filetime()

    # 1. saves_meta (in place)
    meta_e = next(e for e in idx.entries if e.name == 'saves_meta')
    meta_blob = _blob_path(wgs_user_dir, meta_e)
    new_meta = meta_with_entry(meta_blob.read_bytes(), slot_name, details_props)

    # 2. new container folder + container.1 + data blob
    folder_guid, file_guid = uuid.uuid4(), uuid.uuid4()
    folder = wgs_user_dir / folder_guid.hex.upper()
    folder.mkdir()
    (folder / file_guid.hex.upper()).write_bytes(sav_bytes)
    w = Writer()
    w.u32(4); w.u32(1)
    w.bytes('Data'.encode('utf-16-le').ljust(128, b'\0'))
    w.bytes(b'\0' * 16)                 # no cloud copy yet
    w.bytes(file_guid.bytes_le)
    (folder / 'container.1').write_bytes(w.out())

    meta_blob.write_bytes(new_meta)

    # 3. index
    entry = IndexEntry(name, name, '', 1, CONTAINER_CREATED, folder_guid.bytes_le, now, 0, len(sav_bytes))
    place = next((i for i, e in enumerate(idx.entries) if e.name > name), len(idx.entries))   # ordinal order
    idx.entries.insert(place, entry)
    meta_e.mtime, meta_e.size = now, len(new_meta)
    if meta_e.state == 1:
        meta_e.state = CONTAINER_CHANGED
    idx.mtime, idx.state = now, INDEX_CHANGED
    tmp = index_path.with_name('containers.index.osc_tmp')
    tmp.write_bytes(write_index(idx))
    os.replace(tmp, index_path)
    return name
