"""Oodle Kraken handling.

Decoding uses an ooz-based DLL (Kraken_Decompress). Encoding writes *stored* Kraken blocks
(header byte 0xCC = restart + uncompressed, 0x06 = Kraken) — valid Oodle streams that need no compressor,
just bigger files.
"""
import ctypes
import os
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_dll = None

KRAKEN_STORED_HEADER = b'\xCC\x06'
MAX_BLOCK = 0x40000


def _find_dll() -> Path:
    candidates = [os.environ.get('OSC_OOZ_DLL'),
                  _HERE / 'ooz.dll',
                  _HERE.parent / 'third_party' / 'ooz' / 'build' / 'ooz.dll']
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    raise FileNotFoundError('ooz.dll not found (set OSC_OOZ_DLL or build third_party/ooz)')


def _lib():
    global _dll
    if _dll is None:
        _dll = ctypes.CDLL(str(_find_dll()))
        _dll.Kraken_Decompress.restype = ctypes.c_int
        _dll.Kraken_Decompress.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
    return _dll


def decompress(src: bytes, raw_len: int) -> bytes:
    if src[:2] == KRAKEN_STORED_HEADER and len(src) == raw_len + 2 and raw_len <= MAX_BLOCK:
        return bytes(src[2:])   # fast path for our own stored blocks
    dst = ctypes.create_string_buffer(raw_len + 64)
    n = _lib().Kraken_Decompress(bytes(src), len(src), dst, raw_len)
    if n != raw_len:
        raise ValueError(f'Oodle decompress failed ({n} != {raw_len})')
    return dst.raw[:raw_len]


def compress_stored(raw: bytes) -> bytes:
    """Wrap raw bytes as stored Kraken blocks (no actual compression)."""
    out = bytearray()
    for off in range(0, len(raw), MAX_BLOCK):
        out += KRAKEN_STORED_HEADER + raw[off:off + MAX_BLOCK]
    return bytes(out)
