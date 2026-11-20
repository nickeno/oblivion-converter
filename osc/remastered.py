"""Oblivion Remastered .sav container.

    outer GVAS (VAltarSaveContainer)
      AltarSaveData: TArray<uint8> = FArchive::SerializeCompressed segments, each:
          u64 tag 0x222222229E2A83C1, i64 chunkSize (0x20000), u8 compressor (2 = Oodle),
          {i64 compressed, i64 uncompressed} summary, {i64, i64} per chunk, then Kraken streams
      -> u32 length + inner GVAS (VAltarSaveGame)
           OblivionData: TArray<uint8>   classic .ess (v0.127), zero padded
           SaveGameDetails               name, level, location, play time, JPEG thumbnail
           SerializedAltarSaveDataArray  UE-side extras (face, physics poses, ...)

Structure knowledge credited to ORSE (MIT) and our own analysis.
"""
from dataclasses import dataclass
from typing import Optional

from . import oodle
from .binio import Reader, Writer
from .gvas import GvasFile, Prop, find_prop, parse_gvas, serialize_gvas

TAG = 0x222222229E2A83C1
CHUNK = 0x20000
MAX_CHUNK = 0x1000000      # the game uses 0x20000; anything far past that is a broken file
COMPRESSOR_OODLE = 2


class SaveFormatError(Exception):
    pass


@dataclass
class RemasteredSave:
    outer: GvasFile
    inner: GvasFile
    ess: bytes                 # OblivionData bytes (may include zero padding)

    @property
    def details(self) -> Optional[Prop]:
        return find_prop(self.inner.props, 'SaveGameDetails')

    def detail(self, name: str) -> Optional[Prop]:
        d = self.details
        return find_prop(d.props, name) if d and d.props else None


def _altar_array(outer: GvasFile) -> Prop:
    p = find_prop(outer.props, 'AltarSaveData')
    if not p or p.kind != 'array' or p.data is None:
        raise SaveFormatError('AltarSaveData not found - is this an Oblivion Remastered save?')
    return p


def decode_segments(data: bytes) -> bytes:
    r = Reader(data)
    out = bytearray()
    while r.pos < len(data):
        tag = r.u64()
        if tag != TAG:
            raise SaveFormatError(f'bad compressed-archive tag at {r.pos - 8}')
        chunk = r.i64()
        r.u8()
        sc, su = r.i64(), r.i64()
        # sizes come from the file: check them before trusting them
        if not 0 < chunk <= MAX_CHUNK or su < 0 or not 0 <= sc <= r.remaining():
            raise SaveFormatError('bad compressed segment sizes')
        n = (su + chunk - 1) // chunk
        if n * 16 > r.remaining():
            raise SaveFormatError('bad compressed chunk count')
        chunks = [(r.i64(), r.i64()) for _ in range(n)]
        total_c = 0
        for cs, us in chunks:
            if not 0 <= us <= chunk or not 0 <= cs <= r.remaining():
                raise SaveFormatError('bad compressed chunk size')
            out += oodle.decompress(r.bytes(cs), us)
            total_c += cs
        if total_c != sc:
            raise SaveFormatError('compressed segment size mismatch')
    return bytes(out)


def encode_segments(payload: bytes) -> bytes:
    w = Writer()
    for off in range(0, len(payload), CHUNK):
        block = payload[off:off + CHUNK]
        c = oodle.compress_stored(block)
        w.u64(TAG); w.i64(CHUNK); w.u8(COMPRESSOR_OODLE)
        w.i64(len(c)); w.i64(len(block))
        w.i64(len(c)); w.i64(len(block))
        w.bytes(c)
    return w.out()


def open_save(file_bytes: bytes) -> RemasteredSave:
    outer = parse_gvas(file_bytes)
    payload = decode_segments(_altar_array(outer).data)
    inner_len = Reader(payload).u32()
    if inner_len != len(payload) - 4:
        raise SaveFormatError(f'inner length {inner_len} != {len(payload) - 4}')
    inner = parse_gvas(payload[4:])
    od = find_prop(inner.props, 'OblivionData')
    if not od or od.kind != 'array' or od.data is None:
        raise SaveFormatError('OblivionData not found in the save')
    return RemasteredSave(outer, inner, od.data)


def seal_save(save: RemasteredSave, ess: bytes) -> bytes:
    """Rebuild the .sav with new OblivionData. Property trees are re-serialized from the model."""
    od = find_prop(save.inner.props, 'OblivionData')
    od.data = ess
    inner_bytes = serialize_gvas(save.inner)
    payload = len(inner_bytes).to_bytes(4, 'little') + inner_bytes
    _altar_array(save.outer).data = encode_segments(payload)
    return serialize_gvas(save.outer)
