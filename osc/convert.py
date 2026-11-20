"""Conversions between Oblivion (2006, .ess v0.125) and Oblivion Remastered (.sav with embedded .ess v0.127).

Both directions are EXPERIMENTAL: the top-level save layout is identical between 125 and 127, but
per-record differences are still being mapped. Unknown bytes are passed through untouched.
"""
import datetime
import io
import re
import struct
import uuid
from typing import Optional

from .binio import Reader, Writer
from .ess import MAX_PLUGINS, Ess, fit_text, parse_ess, player_look, serialize_ess, set_player_name
from .gvas import FStr, Prop, _read_props, _write_props, find_prop, read_fstr, text_prop_string, write_fstr
from .remastered import RemasteredSave, open_save, seal_save

OG_VERSION = 125
REMASTER_VERSION = 127
OG_SHOT_W, OG_SHOT_H = 256, 144
ALTAR_PLUGINS = ('altaresp', 'altardeluxe')

# UE-side extras kept when building a Remastered save from a template; the rest belong to the
# template's world (physics poses, cinematics, sneaking actors, created-form visuals) and are dropped.
KEEP_EXTRAS = ('UserInputTextSaveData', 'VRaceSexSave', 'VAltarSaveIdentificationData',
               'VAltarPersuasionMenuSaveData')   # plus the player's own 'Phenotype' (face), matched exactly
SLOT_NAME_MAX = 32          # name and location are cut to these in the slot name (it becomes a file name)
LOC_KEY_MAX = 60

# Remastered gives placed objects (change records 49-51 with change flag 0x20) two extra-data entries of its own:
# 0x5E with a 16-byte id and 0x5F with a 128-byte text buffer ("0.0-8.0-6.00.0", "NotSpatiallyLoaded", ...).
# The original game's reader only knows types up to 0x5C and skips an unknown one as a single byte, so the
# payloads were read as more entries and the load crashed (Oblivion.exe+0x58139e, a copy past the buffer).
# The two type bytes stay, so the entry count still matches; their payloads are cut.
REF_TYPES = (49, 50, 51)
ALTAR_EXTRAS_LEN = 1 + 16 + 1 + 128
_ALTAR_TEXT = re.compile(rb'[\x20-\x7e]*\x00')


class ConvertError(Exception):
    """The save can't be converted; the message says why in plain words."""


# ----------------------------------------------------------------------------- helpers
def _text_payload(s: str, flags: int) -> bytes:
    w = Writer()
    w.u32(flags); w.u8(0xFF); w.u32(1); write_fstr(w, s)
    return w.out()


def _pretty_location(loc: str) -> str:
    if loc.startswith('LOC_FN_'):
        loc = loc[7:].rstrip('0123456789')   # FortUrasek02 -> FortUrasek
    out = ''
    for i, c in enumerate(loc):
        if i and c.isupper() and (loc[i - 1].islower() or (i + 1 < len(loc) and loc[i + 1].islower() and loc[i - 1].isupper())):
            out += ' '
        out += c
    return out


def _pad_to(data: bytes, align: int) -> bytes:
    return data + b'\0' * (-len(data) % align)


def _jpeg_to_og_screenshot(jpeg: Optional[bytes]) -> bytes:
    w = Writer()
    w.u32(OG_SHOT_W); w.u32(OG_SHOT_H)
    pixels = None
    if jpeg:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(jpeg)).convert('RGB').resize((OG_SHOT_W, OG_SHOT_H))
            pixels = img.tobytes()
        except Exception:
            pixels = None
    w.bytes(pixels or bytes([40, 40, 40]) * (OG_SHOT_W * OG_SHOT_H))
    return w.out()


def _og_screenshot_to_jpeg(shot: bytes, size) -> Optional[bytes]:
    try:
        from PIL import Image
        r = Reader(shot)
        w, h = r.u32(), r.u32()
        img = Image.frombytes('RGB', (w, h), r.bytes(w * h * 3)).resize(size)
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=90)
        return buf.getvalue()
    except Exception:
        return None


def _jpeg_size(jpeg: bytes):
    try:
        from PIL import Image
        return Image.open(io.BytesIO(jpeg)).size
    except Exception:
        return None


def _plain_jpeg(size) -> Optional[bytes]:
    """A dark picture, for a save that has none (so it never shows another save's picture)."""
    try:
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', size, (40, 40, 40)).save(buf, 'JPEG', quality=80)
        return buf.getvalue()
    except Exception:
        return None


def strip_altar_extras(data: bytes) -> bytes:
    """A placed object's change record without the payloads of Remastered's 0x5E/0x5F extra-data entries."""
    out, start, i = bytearray(), 0, data.find(b'\x5e')
    while 0 <= i and i + ALTAR_EXTRAS_LEN <= len(data):
        if data[i + 17] == 0x5F and _ALTAR_TEXT.match(data, i + 18, i + ALTAR_EXTRAS_LEN):
            out += data[start:i] + b'\x5e\x5f'
            start = i + ALTAR_EXTRAS_LEN
            i = data.find(b'\x5e', start)
        else:
            i = data.find(b'\x5e', i + 1)
    return bytes(out + data[start:]) if start else data


def display_name(save: RemasteredSave) -> str:
    return text_prop_string(save.detail('DisplayPlayerName')) or ''


# ----------------------------------------------------------------------------- Remastered -> OG
def remastered_to_og(sav_bytes: bytes, save_num: Optional[int] = None) -> bytes:
    save = open_save(sav_bytes)
    e = parse_ess(save.ess)
    e.minor_version = OG_VERSION
    e.header_version = OG_VERSION
    if save_num is not None:
        e.save_num = save_num
    name = fit_text(display_name(save))
    if name:
        # Remastered keeps a text key (UI_UserInputText_...) as the name, also in the player's own record
        set_player_name(e, e.pc_name, name)
        e.pc_name = name
    loc = save.detail('PlayerLocation')
    e.pc_location = fit_text(_pretty_location(loc.value.s if loc else e.pc_location))
    thumb = save.detail('SaveThumbnail')
    e.screenshot = _jpeg_to_og_screenshot(thumb.data if thumb else None)
    for rec in e.records:
        rec.version = OG_VERSION
        if rec.type in REF_TYPES and rec.flags & 0x20:
            rec.data = strip_altar_extras(rec.data)
    e.padding = b''
    return serialize_ess(e)


# ----------------------------------------------------------------------------- OG -> Remastered
def _altar_items(save: RemasteredSave):
    sa = find_prop(save.inner.props, 'SerializedAltarSaveDataArray')
    return sa.structs['items'] if sa and sa.structs else []


def _item_name(item) -> str:
    p = find_prop(item, 'SaveDataName')
    return p.value.s if p else ''


def _item_blob(item) -> Prop:
    return find_prop(item, 'SerializedData')


def _parse_blob(data: bytes):
    r = Reader(data)
    props = _read_props(r, len(data))
    return props, data[r.pos:]


def _serialize_blob(props, trailer: bytes) -> bytes:
    w = Writer()
    _write_props(w, props)
    w.bytes(trailer)
    return w.out()


def _set_user_text(save: RemasteredSave, key: str, value: str) -> bool:
    """Rewrite one entry of UserInputTextsMap (MapProperty<Str, Text>) inside the UE extras."""
    for item in _altar_items(save):
        if not _item_name(item).startswith('UserInputTextSaveData'):
            continue
        blob = _item_blob(item)
        props, trailer = _parse_blob(blob.data)
        mp = find_prop(props, 'UserInputTextsMap')
        if not mp:
            return False
        r = Reader(mp.raw)
        r.u32()                      # keys to remove
        count = r.u32()
        for _ in range(count):
            k_start = r.pos
            k = read_fstr(r).s
            v_start = r.pos
            flags = r.u32(); hist = r.u8()
            if hist == 0xFF:
                if r.u32():
                    read_fstr(r)
            else:
                raise ValueError('unsupported FText history in UserInputTextsMap')
            if k == key:
                mp.raw = mp.raw[:v_start] + _text_payload(value, flags) + mp.raw[r.pos:]
                blob.data = _serialize_blob(props, trailer)
                return True
        return False
    return False


def _set_guid_struct(props, name: str, guid: bytes):
    p = find_prop(props, name)
    if p and p.kind == 'struct' and p.raw is not None and len(p.raw) == 16:
        p.raw = guid


def _loc_norm(s: str) -> str:
    return ''.join(c for c in s if c.isalnum()).lower()


def location_key(og_location: str, known=()) -> str:
    """'Anvil Mages Guild' -> 'LOC_FN_AnvilMagesGuild' (Remastered stores a localisation key).
    `known` are real keys from Remastered saves; one that reads the same is used as it is
    ('Fort Urasek' -> 'LOC_FN_FortUrasek02')."""
    want = _loc_norm(og_location)
    for k in known:
        if k.startswith('LOC_FN_') and _loc_norm(_pretty_location(k)) == want:
            return k
    return ('LOC_FN_' + ''.join(c for c in og_location if c.isalnum()))[:LOC_KEY_MAX]


def slot_name_for(number: int, play_seconds: int, name: str, loc_key: str, level: int) -> str:
    h, rem = divmod(max(0, play_seconds), 3600)
    m, s = divmod(rem, 60)
    name = name.strip()[:SLOT_NAME_MAX].strip()
    return f'Save {number}, Playing Time {h:02d}.{m:02d}.{s:02d} - {name} - {loc_key[:LOC_KEY_MAX]}, Level {level}'


def planned_slot_name(e: Ess, number: int, known_locations=()) -> str:
    """The slot name og_to_remastered gives this original save, worked out without converting it."""
    return slot_name_for(number, int(e.game_ticks) // 1000, e.pc_name,
                         location_key(e.pc_location, known_locations), e.pc_level)


def og_to_remastered(ess_bytes: bytes, template_sav: bytes, record_version: int = OG_VERSION,
                     keep_all_extras: bool = False, save_number: int = 99, known_locations=()) -> bytes:
    save = open_save(template_sav)
    tmpl = parse_ess(save.ess)
    e = parse_ess(ess_bytes)
    og_name, og_loc, og_shot = e.pc_name, e.pc_location, e.screenshot
    slot_name = planned_slot_name(e, save_number, known_locations)
    loc_key = location_key(og_loc, known_locations)

    # player name text: Remastered's header holds a key (UI_UserInputText_...) that UserInputTextsMap
    # turns into the name. A template without that entry gets the plain name in the header instead.
    named = _set_user_text(save, tmpl.pc_name, og_name)
    # The player's own record holds the name too, and Remastered shows a plain name there as "[NL]name".
    # It gets the key only when the borrowed face fits (same race and sex): a save whose record name matches
    # its header is trusted as a face template later, and a save with someone else's face must not be.
    try:
        face_fits = player_look(tmpl) is not None and player_look(tmpl) == player_look(e)
    except Exception:
        face_fits = False
    if named and face_fits:
        set_player_name(e, og_name, tmpl.pc_name)

    # .ess header: Remastered keeps no screenshot and uses localisation keys for name/location
    e.minor_version = REMASTER_VERSION
    e.header_version = REMASTER_VERSION
    e.exe_time = tmpl.exe_time
    e.pc_name = tmpl.pc_name if named else fit_text(og_name)
    e.pc_location = loc_key
    e.screenshot = b''
    for rec in e.records:
        rec.version = record_version
    if not any(p.lower().startswith(ALTAR_PLUGINS) for p in e.plugins):
        if len(e.plugins) >= MAX_PLUGINS:
            raise ConvertError('This save uses 255 mods, so there is no room for the one Remastered adds.')
        e.plugins.append('AltarESPMain.esp')
    e.padding = b''
    ess_out = _pad_to(serialize_ess(e), 0x1000)

    # save details
    det = save.details.props
    find_prop(det, 'PlayerLevel').value = e.pc_level
    find_prop(det, 'InGameDate').value = float(e.game_days)
    pt = find_prop(det, 'PlayTime')
    if pt and pt.raw is not None:
        pt.raw = struct.pack('<q', int(e.game_ticks) * 10_000)   # ms -> 100 ns ticks
    dn = find_prop(det, 'DisplayPlayerName')
    if dn is not None:
        dn.raw = _text_payload(og_name, Reader(dn.raw).u32())
    find_prop(det, 'PlayerLocation').value = FStr(loc_key)
    slot = find_prop(det, 'SlotName')
    if slot is not None:
        slot.value = FStr(slot_name)
    sn = find_prop(det, 'SaveName')
    if sn is not None:
        sn.value = FStr('Save')
    num = find_prop(det, 'SaveNumber')
    if num is not None:
        num.value = save_number - 1
    sd = find_prop(det, 'SaveDate')
    if sd is not None and sd.raw is not None and len(sd.raw) == 8:
        ticks = int((datetime.datetime.now() - datetime.datetime(1, 1, 1)).total_seconds() * 10_000_000)
        sd.raw = struct.pack('<q', ticks)
    thumb = find_prop(det, 'SaveThumbnail')
    if thumb is not None and thumb.data:
        size = _jpeg_size(thumb.data) or (512, 288)
        jpg = _og_screenshot_to_jpeg(og_shot, size) or _plain_jpeg(size)
        if jpg:
            thumb.data = jpg

    # fresh character / save ids so the game treats this as its own character
    char_id, save_id = uuid.uuid4().bytes_le, uuid.uuid4().bytes_le
    _set_guid_struct(det, 'CharacterId', char_id)

    # UE extras
    items = _altar_items(save)
    kept = []
    for item in items:
        nm = _item_name(item)
        base = nm if nm == 'Phenotype' else nm.rsplit('_', 1)[0]
        if keep_all_extras or base in KEEP_EXTRAS or nm == 'Phenotype':
            if base == 'VAltarSaveIdentificationData':
                blob = _item_blob(item)
                props, trailer = _parse_blob(blob.data)
                _set_guid_struct(props, 'CharacterId', char_id)
                _set_guid_struct(props, 'SaveID', save_id)
                blob.data = _serialize_blob(props, trailer)
            kept.append(item)
    if items is not None and not keep_all_extras:
        items[:] = kept

    return seal_save(save, ess_out)
