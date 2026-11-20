"""Little-endian binary reader/writer helpers."""
import struct


class Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.d = data
        self.pos = pos

    def _unpack(self, fmt: str, n: int):
        v = struct.unpack_from(fmt, self.d, self.pos)[0]
        self.pos += n
        return v

    def u8(self): return self._unpack('<B', 1)
    def i8(self): return self._unpack('<b', 1)
    def u16(self): return self._unpack('<H', 2)
    def i16(self): return self._unpack('<h', 2)
    def u32(self): return self._unpack('<I', 4)
    def i32(self): return self._unpack('<i', 4)
    def u64(self): return self._unpack('<Q', 8)
    def i64(self): return self._unpack('<q', 8)
    def f32(self): return self._unpack('<f', 4)
    def f64(self): return self._unpack('<d', 8)

    def bytes(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.d):
            raise ValueError(f'read of {n} bytes at {self.pos} runs past end ({len(self.d)})')
        v = self.d[self.pos:self.pos + n]
        self.pos += n
        return bytes(v)

    def remaining(self) -> int:
        return len(self.d) - self.pos


class Writer:
    def __init__(self):
        self.buf = bytearray()

    def __len__(self): return len(self.buf)

    # no masking: a count or length too big for its field raises instead of wrapping into a broken file
    def u8(self, v): self.buf += struct.pack('<B', v)
    def i8(self, v): self.buf += struct.pack('<b', v)
    def u16(self, v): self.buf += struct.pack('<H', v)
    def i16(self, v): self.buf += struct.pack('<h', v)
    def u32(self, v): self.buf += struct.pack('<I', v)
    def i32(self, v): self.buf += struct.pack('<i', v)
    def u64(self, v): self.buf += struct.pack('<Q', v)
    def i64(self, v): self.buf += struct.pack('<q', v)
    def f32(self, v): self.buf += struct.pack('<f', v)
    def f64(self, v): self.buf += struct.pack('<d', v)
    def bytes(self, b): self.buf += b

    def reserve(self, n: int) -> int:
        at = len(self.buf)
        self.buf += b'\0' * n
        return at

    def patch_i32(self, at: int, v: int): struct.pack_into('<i', self.buf, at, v)
    def patch_u32(self, at: int, v: int): struct.pack_into('<I', self.buf, at, v)

    def out(self) -> bytes:
        return bytes(self.buf)
