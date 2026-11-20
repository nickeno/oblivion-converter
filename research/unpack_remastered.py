"""Unpack AltarSaveData from an Oblivion Remastered GVAS save using ooz.dll (read-only)."""
import ctypes, struct, sys, re

save_path, dll_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
d = open(save_path, 'rb').read()
i = d.find(b'AltarSaveData')
j = d.find(b'ByteProperty', i) + len(b'ByteProperty') + 1 + 1
n = struct.unpack_from('<I', d, j)[0]
blob = d[j + 4:j + 4 + n]

ooz = ctypes.CDLL(dll_path)
ooz.Kraken_Decompress.restype = ctypes.c_int
ooz.Kraken_Decompress.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]

p, out = 0, bytearray()
while p + 33 <= len(blob):
    cs = struct.unpack_from('<q', blob, p + 8)[0]
    sc, su = struct.unpack_from('<qq', blob, p + 17)
    k = (su + cs - 1) // cs
    q = p + 33
    infos = [struct.unpack_from('<qq', blob, q + 16 * m) for m in range(k)]
    q += 16 * k
    for c, u in infos:
        dst = ctypes.create_string_buffer(u + 64)
        r = ooz.Kraken_Decompress(bytes(blob[q:q + c]), c, dst, u)
        if r != u:
            print('FAILED at', q, 'ret', r); sys.exit(1)
        out += dst.raw[:u]
        q += c
    p = q
open(out_path, 'wb').write(out)
print('unpacked', len(out), 'bytes')
print('head hex:', out[:64].hex(' '))
print('head txt:', bytes(out[:64]))
for m in (b'TES4SAVEGAME', b'Oblivion.esm', b'AltarESPMain', b'Knights.esp', b'DLCShiveringIsles', b'GVAS'):
    print(f'{m.decode():20s} first@ {out.find(m)}  count {out.count(m)}')
strs = [s.decode() for s in re.findall(rb'[\x20-\x7e]{8,}', bytes(out[:200000]))]
print('early strings:', strs[:40])
