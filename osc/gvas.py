"""Unreal Engine 5 GVAS SaveGame (tagged properties) reader/writer.

Ported from ORSE's src/shared/gvas.ts (MIT, Copyright (c) 2026 ORSE contributors; the full notice is in
THIRD-PARTY.md). Anything not understood is kept as raw bytes so files round-trip byte for byte.
"""
from dataclasses import dataclass, field
from typing import Any, Optional

from .binio import Reader, Writer


class GvasError(Exception):
    pass


@dataclass
class FStr:
    """An Unreal FString. Unreal writes one byte per letter (each byte is the letter's code, like Latin-1)
    when every letter is plain ASCII, else UTF-16 with a negative length counted in UTF-16 units."""
    s: str
    wide: Optional[bool] = None     # None: pick like Unreal does when written
    empty: bool = False             # serialized as length 0 (no terminator)


def read_fstr(r: Reader) -> FStr:
    n = r.i32()
    if n == 0:
        return FStr('', False, True)
    if n < 0:
        s = r.bytes(-n * 2)[:-2].decode('utf-16-le', 'surrogatepass')
        return FStr(s, True)
    s = r.bytes(n)[:-1].decode('latin-1')
    return FStr(s, False)


def write_fstr(w: Writer, f) -> None:
    if isinstance(f, str):
        f = FStr(f)
    s, wide = f.s, f.wide
    if f.empty or (s == '' and wide is None):
        w.i32(0)
        return
    if wide is None:
        wide = any(ord(c) > 0x7F for c in s)
    elif not wide and any(ord(c) > 0xFF for c in s):
        wide = True                 # can't be one byte per letter any more
    if wide:
        b = s.encode('utf-16-le', 'surrogatepass')
        w.i32(-(len(b) // 2 + 1))
        w.bytes(b + b'\0\0')
    else:
        b = s.encode('latin-1')
        w.i32(len(b) + 1)
        w.bytes(b + b'\0')


@dataclass
class Prop:
    name: FStr
    type: FStr
    index: int
    kind: str                 # int uint int64 float double bool byte enum str struct array raw
    value: Any = None
    # extra per-kind data
    enum_name: Optional[FStr] = None
    struct_name: Optional[FStr] = None
    guid: bytes = b''
    props: Optional[list] = None       # struct sub-properties
    raw: Optional[bytes] = None        # struct raw / array raw / raw payload
    header: bytes = b''                # raw-kind header bytes
    inner_type: Optional[FStr] = None  # array inner type
    data: Optional[bytes] = None       # ByteProperty array payload
    ints: Optional[list] = None
    strs: Optional[list] = None
    structs: Optional[dict] = None
    prop_guid: Optional[bytes] = None  # the optional property GUID (a flag byte, then 16 bytes when set)


def _read_guid_flag(r: Reader) -> Optional[bytes]:
    return r.bytes(16) if r.u8() else None


def _write_guid_flag(w: Writer, guid: Optional[bytes]) -> None:
    if guid is None:
        w.u8(0)
    else:
        w.u8(1); w.bytes(guid)


@dataclass
class GvasFile:
    header: dict
    props: list
    trailer: bytes = b''


NATIVE_STRUCTS = {'Vector', 'Rotator', 'Quat', 'Guid', 'DateTime', 'Timespan', 'LinearColor', 'Color',
                  'Vector2D', 'IntPoint', 'Transform', 'Vector4', 'Box', 'IntVector'}


def parse_gvas(d: bytes) -> GvasFile:
    if d[:4] != b'GVAS':
        raise GvasError('Not a GVAS file')
    r = Reader(d, 4)
    h = {
        'file_version': r.i32(),
        'pkg_version': (r.u32(), r.u32()),
        'engine': (r.u16(), r.u16(), r.u16(), r.u32()),
        'branch': read_fstr(r),
        'custom_version_format': r.i32(),
    }
    n = r.i32()
    h['custom_versions'] = [(r.bytes(16), r.i32()) for _ in range(n)]
    h['class_name'] = read_fstr(r)
    props = _read_props(r, len(d))
    return GvasFile(h, props, d[r.pos:])


def _read_props(r: Reader, end: int) -> list:
    out = []
    while r.pos < end:
        name = read_fstr(r)
        if name.s == 'None':
            return out
        typ = read_fstr(r)
        size = r.i32()
        index = r.i32()
        out.append(_read_value(r, name, typ, size, index))
    raise GvasError('property list without None terminator')


def _read_value(r: Reader, name: FStr, typ: FStr, size: int, index: int) -> Prop:
    t = typ.s
    p = Prop(name, typ, index, 'raw')
    if t == 'IntProperty':
        p.prop_guid = _read_guid_flag(r); p.kind, p.value = 'int', r.i32()
    elif t == 'UInt32Property':
        p.prop_guid = _read_guid_flag(r); p.kind, p.value = 'uint', r.u32()
    elif t in ('Int64Property', 'UInt64Property'):
        p.prop_guid = _read_guid_flag(r); p.kind, p.value = 'int64', r.i64()
    elif t == 'FloatProperty':
        p.prop_guid = _read_guid_flag(r); p.kind, p.value = 'float', r.f32()
    elif t == 'DoubleProperty':
        p.prop_guid = _read_guid_flag(r); p.kind, p.value = 'double', r.f64()
    elif t == 'BoolProperty':
        v = r.u8(); p.prop_guid = _read_guid_flag(r); p.kind, p.value = 'bool', bool(v)
    elif t == 'ByteProperty':
        p.enum_name = read_fstr(r); p.prop_guid = _read_guid_flag(r)
        p.kind = 'byte'
        p.value = r.u8() if p.enum_name.s == 'None' else read_fstr(r)
    elif t == 'EnumProperty':
        p.enum_name = read_fstr(r); p.prop_guid = _read_guid_flag(r); p.kind, p.value = 'enum', read_fstr(r)
    elif t in ('StrProperty', 'NameProperty', 'ObjectProperty'):
        p.prop_guid = _read_guid_flag(r); p.kind, p.value = 'str', read_fstr(r)
    elif t == 'StructProperty':
        p.kind = 'struct'
        p.struct_name = read_fstr(r)
        p.guid = r.bytes(16)
        p.prop_guid = _read_guid_flag(r)
        raw = r.bytes(size)
        sub = _try_props(raw, p.struct_name.s)
        if sub is not None:
            p.props = sub
        else:
            p.raw = raw
    elif t == 'ArrayProperty':
        p.kind = 'array'
        p.inner_type = read_fstr(r)
        p.prop_guid = _read_guid_flag(r)
        start = r.pos
        count = r.u32()
        it = p.inner_type.s
        if it == 'ByteProperty' and size == 4 + count:
            p.data = r.bytes(count)
        elif it == 'IntProperty' and size == 4 + count * 4:
            p.ints = [r.i32() for _ in range(count)]
        elif it in ('StrProperty', 'NameProperty'):
            strs = [read_fstr(r) for _ in range(count)]
            if r.pos != start + size:
                r.pos = start; p.raw = r.bytes(size)
            else:
                p.strs = strs
        elif it == 'StructProperty':
            sa = {'name': read_fstr(r), 'type': read_fstr(r)}
            r.i32()  # total element bytes
            sa['index'] = r.i32()
            sa['struct_name'] = read_fstr(r)
            sa['guid'] = r.bytes(16)
            sa['prop_guid'] = _read_guid_flag(r)
            elems_end = start + size
            items, ok = [], sa['struct_name'].s not in NATIVE_STRUCTS
            for _ in range(count):
                if not ok:
                    break
                save = r.pos
                try:
                    items.append(_read_props(r, elems_end))
                except Exception:
                    r.pos = save; ok = False; break
                if r.pos > elems_end:
                    ok = False
            if ok and r.pos == elems_end:
                sa['items'] = items
                p.structs = sa
            else:
                r.pos = start; p.raw = r.bytes(size)
        else:
            r.pos = start; p.raw = r.bytes(size)
        r.pos = start + size
    elif t == 'MapProperty':
        h0 = r.pos; read_fstr(r); read_fstr(r); _read_guid_flag(r)
        p.header = r.d[h0:r.pos]; p.raw = r.bytes(size)
    elif t == 'SetProperty':
        h0 = r.pos; read_fstr(r); _read_guid_flag(r)
        p.header = r.d[h0:r.pos]; p.raw = r.bytes(size)
    else:  # TextProperty, SoftObjectProperty, ...: the guid flag (and guid) then payload
        h0 = r.pos; _read_guid_flag(r)
        p.header = r.d[h0:r.pos]; p.raw = r.bytes(size)
    return p


def _try_props(raw: bytes, struct_name: str):
    if struct_name in NATIVE_STRUCTS or len(raw) < 9:
        return None
    r = Reader(raw)
    try:
        props = _read_props(r, len(raw))
        return props if r.pos == len(raw) else None
    except Exception:
        return None


def serialize_gvas(f: GvasFile) -> bytes:
    w = Writer()
    h = f.header
    w.bytes(b'GVAS')
    w.i32(h['file_version'])
    w.u32(h['pkg_version'][0]); w.u32(h['pkg_version'][1])
    maj, mn, pt, cl = h['engine']
    w.u16(maj); w.u16(mn); w.u16(pt); w.u32(cl)
    write_fstr(w, h['branch'])
    w.i32(h['custom_version_format'])
    w.i32(len(h['custom_versions']))
    for g, v in h['custom_versions']:
        w.bytes(g); w.i32(v)
    write_fstr(w, h['class_name'])
    _write_props(w, f.props)
    w.bytes(f.trailer)
    return w.out()


def _write_props(w: Writer, props: list) -> None:
    for p in props:
        _write_prop(w, p)
    write_fstr(w, FStr('None'))


def _write_prop(w: Writer, p: Prop) -> None:
    write_fstr(w, p.name)
    write_fstr(w, p.type)
    size_at = w.reserve(4)
    w.i32(p.index)
    k = p.kind
    g = p.prop_guid
    if k == 'int':
        _write_guid_flag(w, g); start = len(w); w.i32(p.value)
    elif k == 'uint':
        _write_guid_flag(w, g); start = len(w); w.u32(p.value)
    elif k == 'int64':
        _write_guid_flag(w, g); start = len(w); w.i64(p.value)
    elif k == 'float':
        _write_guid_flag(w, g); start = len(w); w.f32(p.value)
    elif k == 'double':
        _write_guid_flag(w, g); start = len(w); w.f64(p.value)
    elif k == 'bool':
        w.u8(1 if p.value else 0); _write_guid_flag(w, g); start = len(w)
    elif k == 'byte':
        write_fstr(w, p.enum_name); _write_guid_flag(w, g); start = len(w)
        if isinstance(p.value, int):
            w.u8(p.value)
        else:
            write_fstr(w, p.value)
    elif k == 'enum':
        write_fstr(w, p.enum_name); _write_guid_flag(w, g); start = len(w); write_fstr(w, p.value)
    elif k == 'str':
        _write_guid_flag(w, g); start = len(w); write_fstr(w, p.value)
    elif k == 'struct':
        write_fstr(w, p.struct_name); w.bytes(p.guid); _write_guid_flag(w, g); start = len(w)
        if p.props is not None:
            _write_props(w, p.props)
        else:
            w.bytes(p.raw)
    elif k == 'array':
        write_fstr(w, p.inner_type); _write_guid_flag(w, g); start = len(w)
        if p.raw is not None:
            w.bytes(p.raw)
        elif p.data is not None:
            w.u32(len(p.data)); w.bytes(p.data)
        elif p.ints is not None:
            w.u32(len(p.ints))
            for x in p.ints:
                w.i32(x)
        elif p.strs is not None:
            w.u32(len(p.strs))
            for s in p.strs:
                write_fstr(w, s)
        elif p.structs is not None:
            sa = p.structs
            w.u32(len(sa['items']))
            write_fstr(w, sa['name']); write_fstr(w, sa['type'])
            total_at = w.reserve(4)
            w.i32(sa['index']); write_fstr(w, sa['struct_name']); w.bytes(sa['guid'])
            _write_guid_flag(w, sa.get('prop_guid'))
            elems_start = len(w)
            for item in sa['items']:
                _write_props(w, item)
            w.patch_i32(total_at, len(w) - elems_start)
        else:
            raise GvasError('array without payload')
    elif k == 'raw':
        w.bytes(p.header); start = len(w); w.bytes(p.raw)
    else:
        raise GvasError(f'cannot write property kind {k}')
    w.patch_i32(size_at, len(w) - start)


def find_prop(props: list, name: str) -> Optional[Prop]:
    for p in props or []:
        if p.name.s == name:
            return p
    return None


def text_prop_string(p: Optional[Prop]) -> Optional[str]:
    """Plain culture-invariant FText literal (history type -1) -> str."""
    if not p or p.kind != 'raw' or not p.raw:
        return None
    r = Reader(p.raw)
    try:
        r.u32()
        if r.u8() == 0xFF:
            if not r.u32():
                return ''
            return read_fstr(r).s
    except Exception:
        pass
    return None
