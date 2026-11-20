"""Classic Oblivion save (.ess) — top-level parser/serializer that keeps every byte it does not interpret.

Layout per https://en.uesp.net/wiki/Oblivion_Mod:Save_File_Format; structure of the 0.127 variant
cross-checked with ORSE's src/shared/ess.ts (MIT).
"""
import codecs
from dataclasses import dataclass, field
from typing import Optional

from .binio import Reader, Writer

PLAYER_REF = 0x14            # the player's own change record
_CP1252_HOLES = (0x81, 0x8D, 0x8F, 0x90, 0x9D)      # bytes cp1252 has no letter for


def _keep_holes(err):
    """Those five bytes survive a read and write unchanged (saves from non-western game versions have them)."""
    if isinstance(err, UnicodeDecodeError):
        return ''.join(map(chr, err.object[err.start:err.end])), err.end
    if isinstance(err, UnicodeEncodeError):
        return bytes(ord(c) if ord(c) in _CP1252_HOLES else 0x3F for c in err.object[err.start:err.end]), err.end
    raise err


codecs.register_error('osc_keep', _keep_holes)


def decode_text(b: bytes) -> str:
    return b.decode('cp1252', 'osc_keep')


def encode_text(s: str) -> bytes:
    return s.encode('cp1252', 'osc_keep')


class EssError(Exception):
    pass


@dataclass
class ChangeRecord:
    form_id: int
    type: int
    flags: int
    version: int
    data: bytes


@dataclass
class Ess:
    minor_version: int
    exe_time: bytes
    header_version: int
    save_num: int
    pc_name: str
    pc_level: int
    pc_location: str
    game_days: float
    game_ticks: int
    game_time: bytes
    screenshot: bytes            # u32 size prefix NOT included; raw (w, h, pixels)
    plugins: list
    next_object_id: int
    world_id: int
    world_x: int
    world_y: int
    pc_cell: int
    pc_pos: tuple
    globals: list
    tes_class_size: int
    death_counts: list
    game_mode_seconds: float
    processes: bytes
    spec_event: bytes
    weather: bytes
    player_combat_count: int
    created: bytes               # createdNum + created records, verbatim
    quick_keys: bytes
    reticule: bytes
    interface_data: bytes
    regions: list
    records: list
    temp_effects: bytes
    form_ids: list
    world_spaces: list
    padding: bytes = b''


def _bz(r: Reader) -> str:
    n = r.u8()
    b = r.bytes(n)
    return decode_text(b[:max(0, n - 1)])


def _bs(r: Reader) -> str:
    return decode_text(r.bytes(r.u8()))


MAX_BZ = 254                 # a bzstring has a one-byte length that counts its closing zero
MAX_PLUGINS = 255


def fit_text(s: str, limit: int = MAX_BZ) -> str:
    """`s` cut so it fits a one-byte-length string field."""
    while len(encode_text(s)) > limit:
        s = s[:-1]
    return s.rstrip()


def _wbz(w: Writer, s: str):
    b = encode_text(s)
    if len(b) > MAX_BZ:
        raise EssError(f'text too long for the save ({len(b)} bytes): {s[:40]}...')
    w.u8(len(b) + 1); w.bytes(b); w.u8(0)


def _wbs(w: Writer, s: str):
    b = encode_text(s)
    if len(b) > 255:
        raise EssError(f'text too long for the save ({len(b)} bytes): {s[:40]}...')
    w.u8(len(b)); w.bytes(b)


def parse_ess(d: bytes) -> Ess:
    r = Reader(d)
    if r.bytes(12) != b'TES4SAVEGAME':
        raise EssError('not a TES4SAVEGAME file')
    if r.u8() != 0:
        raise EssError('unexpected major version')
    minor = r.u8()
    exe_time = r.bytes(16)
    header_version = r.u32()
    r.u32()  # header size
    save_num = r.u32()
    pc_name = _bz(r)
    pc_level = r.u16()
    pc_location = _bz(r)
    game_days = r.f32()
    game_ticks = r.u32()
    game_time = r.bytes(16)
    screenshot = r.bytes(r.u32())
    plugins = [_bs(r) for _ in range(r.u8())]
    form_ids_offset = r.u32()
    records_num = r.u32()
    next_object_id = r.u32()
    world_id = r.u32()
    world_x = r.u32()
    world_y = r.u32()
    pc_cell = r.u32()
    pc_pos = (r.f32(), r.f32(), r.f32())
    globals_ = [(r.u32(), r.f32()) for _ in range(r.u16())]
    tes_class_size = r.u16()
    death_counts = [(r.u32(), r.u16()) for _ in range(r.u32())]
    game_mode_seconds = r.f32()
    processes = r.bytes(r.u16())
    spec_event = r.bytes(r.u16())
    weather = r.bytes(r.u16())
    player_combat_count = r.u32()
    created_start = r.pos
    for _ in range(r.u32()):
        r.bytes(4)
        size = r.u32()
        r.bytes(12 + size)
    created = d[created_start:r.pos]
    quick_keys = r.bytes(r.u16())
    reticule = r.bytes(r.u16())
    interface_data = r.bytes(r.u16())
    r.u16()  # regions size
    regions = [(r.u32(), r.u32()) for _ in range(r.u16())]
    records = []
    for _ in range(records_num):
        fid, typ, flags, ver, size = r.u32(), r.u8(), r.u32(), r.u8(), r.u16()
        records.append(ChangeRecord(fid, typ, flags, ver, r.bytes(size)))
    temp_effects = r.bytes(r.u32())
    if r.pos != form_ids_offset:
        raise EssError(f'formIds expected at {form_ids_offset}, parsed up to {r.pos}')
    form_ids = [r.u32() for _ in range(r.u32())]
    world_spaces = [r.u32() for _ in range(r.u32())]
    return Ess(minor, exe_time, header_version, save_num, pc_name, pc_level, pc_location, game_days,
               game_ticks, game_time, screenshot, plugins, next_object_id, world_id, world_x, world_y,
               pc_cell, pc_pos, globals_, tes_class_size, death_counts, game_mode_seconds, processes,
               spec_event, weather, player_combat_count, created, quick_keys, reticule, interface_data,
               regions, records, temp_effects, form_ids, world_spaces, d[r.pos:])


def _player_name_at(e: Ess, rec: ChangeRecord, name: str) -> int:
    """Where the player's record holds `name` (as a bzstring right after race, hair, eyes and sex), or -1."""
    b = encode_text(name)
    if len(b) > MAX_BZ:
        return -1
    at = rec.data.rfind(bytes([len(b) + 1]) + b + b'\0')
    return at if at >= 21 else -1


def set_player_name(e: Ess, old: str, new: str) -> bool:
    """Rename the player inside their own change record (the header copy is only for the load menu)."""
    rec = next((r for r in e.records if r.form_id == PLAYER_REF), None)
    if rec is None:
        return False
    at = _player_name_at(e, rec, old)
    if at < 0:
        return False
    old_b, new_b = encode_text(old), encode_text(fit_text(new))
    rec.data = rec.data[:at] + bytes([len(new_b) + 1]) + new_b + b'\0' + rec.data[at + len(old_b) + 2:]
    return True


def player_look(e: Ess) -> Optional[tuple]:
    """(race, sex) of the player, or None when it can't be read. Race is (plugin, form id) so it compares
    across saves; sex is 0 male, 1 female.

    The player's record ends with: race, hair, eyes (4 bytes each), hair length (4), hair colour (4), sex (1),
    then the name. https://en.uesp.net/wiki/Oblivion_Mod:Save_File_Format/Player_Data
    A converted save still has the old name there instead of Remastered's text key, so it reads as None:
    its face came from another character and says nothing about its own race.
    """
    rec = next((r for r in e.records if r.form_id == PLAYER_REF), None)
    if rec is None:
        return None
    at = _player_name_at(e, rec, e.pc_name)
    if at < 0:
        return None
    sex = rec.data[at - 1]
    iref = int.from_bytes(rec.data[at - 21:at - 17], 'little')
    if sex > 1 or iref >= len(e.form_ids):
        return None
    form = e.form_ids[iref]
    plugin = e.plugins[form >> 24].lower() if (form >> 24) < len(e.plugins) else str(form >> 24)
    return (plugin, form & 0xFFFFFF), sex


def serialize_ess(e: Ess, keep_padding: bool = True) -> bytes:
    w = Writer()
    w.bytes(b'TES4SAVEGAME'); w.u8(0); w.u8(e.minor_version)
    w.bytes(e.exe_time)
    w.u32(e.header_version)
    size_at = w.reserve(4)
    hdr_start = len(w)
    w.u32(e.save_num)
    _wbz(w, e.pc_name)
    w.u16(e.pc_level)
    _wbz(w, e.pc_location)
    w.f32(e.game_days); w.u32(e.game_ticks); w.bytes(e.game_time)
    w.u32(len(e.screenshot)); w.bytes(e.screenshot)
    w.patch_u32(size_at, len(w) - hdr_start)
    if len(e.plugins) > MAX_PLUGINS:
        raise EssError(f'too many plugins ({len(e.plugins)}, the game allows {MAX_PLUGINS})')
    w.u8(len(e.plugins))
    for p in e.plugins:
        _wbs(w, p)
    fid_off_at = w.reserve(4)
    w.u32(len(e.records)); w.u32(e.next_object_id)
    w.u32(e.world_id); w.u32(e.world_x); w.u32(e.world_y); w.u32(e.pc_cell)
    for v in e.pc_pos:
        w.f32(v)
    w.u16(len(e.globals))
    for iref, val in e.globals:
        w.u32(iref); w.f32(val)
    w.u16(e.tes_class_size)
    w.u32(len(e.death_counts))
    for iref, cnt in e.death_counts:
        w.u32(iref); w.u16(cnt)
    w.f32(e.game_mode_seconds)
    for blob in (e.processes, e.spec_event, e.weather):
        w.u16(len(blob)); w.bytes(blob)
    w.u32(e.player_combat_count)
    w.bytes(e.created)
    for blob in (e.quick_keys, e.reticule, e.interface_data):
        w.u16(len(blob)); w.bytes(blob)
    w.u16(2 + len(e.regions) * 8); w.u16(len(e.regions))
    for iref, unk in e.regions:
        w.u32(iref); w.u32(unk)
    for rec in e.records:
        if len(rec.data) > 0xFFFF:
            raise EssError(f'change record {rec.form_id:08x} too big')
        w.u32(rec.form_id); w.u8(rec.type); w.u32(rec.flags); w.u8(rec.version)
        w.u16(len(rec.data)); w.bytes(rec.data)
    w.u32(len(e.temp_effects)); w.bytes(e.temp_effects)
    w.patch_u32(fid_off_at, len(w))
    w.u32(len(e.form_ids))
    for f in e.form_ids:
        w.u32(f)
    w.u32(len(e.world_spaces))
    for f in e.world_spaces:
        w.u32(f)
    if keep_padding:
        w.bytes(e.padding)
    return w.out()
