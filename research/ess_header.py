"""Parse the TES4SAVEGAME header of a classic .ess or the one embedded in a Remastered save."""
import struct, sys

def extract_inner(path):
    d = open(path, 'rb').read()
    if d.startswith(b'TES4SAVEGAME'):
        return d, None
    # unpacked Remastered: find OblivionData byte array
    i = d.find(b'OblivionData')
    j = d.find(b'ArrayProperty', i)
    size = struct.unpack_from('<q', d, j + len(b'ArrayProperty') + 1)[0]
    k = d.find(b'ByteProperty', j) + len(b'ByteProperty') + 1 + 1
    n = struct.unpack_from('<I', d, k)[0]
    return d[k + 4:k + 4 + n], (i, k + 4, n, len(d))

def parse(b):
    o = 12
    major, minor = b[o], b[o + 1]; o += 2
    exe_time = struct.unpack_from('<8H', b, o); o += 16
    hdr_ver, hdr_size = struct.unpack_from('<II', b, o); o += 8
    hdr_start = o
    save_num = struct.unpack_from('<I', b, o)[0]; o += 4
    def bz():
        nonlocal o
        L = b[o]; s = b[o + 1:o + 1 + L].rstrip(b'\0'); o += 1 + L; return s
    name = bz(); level = struct.unpack_from('<H', b, o)[0]; o += 2
    loc = bz(); days, ticks = struct.unpack_from('<fI', b, o); o += 8
    game_time = struct.unpack_from('<8H', b, o); o += 16
    shot_size, w, h = struct.unpack_from('<III', b, o)
    o += 4 + shot_size
    hdr_end = hdr_start + hdr_size
    nplug = b[o]; o += 1
    plugins = []
    for _ in range(nplug):
        L = b[o]; plugins.append(b[o + 1:o + 1 + L].decode('latin1')); o += 1 + L
    form_ids_off, records_num, next_obj, world, wx, wy = struct.unpack_from('<IIIIii', b, o)
    return dict(major=major, minor=minor, hdr_ver=hdr_ver, hdr_size=hdr_size, header_ends_at=hdr_end,
                screenshot=f'{w}x{h} ({shot_size} bytes, {shot_size / max(1, w * h):.2f} B/px)',
                save_num=save_num, name=name, level=level, loc=loc, days=round(days, 2),
                plugins=plugins, form_ids_offset=form_ids_off, records=records_num,
                next_object_id=hex(next_obj), worldspace=hex(world), total=len(b))

for path in sys.argv[1:]:
    inner, info = extract_inner(path)
    print('==', path.split('/')[-1][:70])
    if info: print('   embedded at', info[1], 'size', info[2], 'of outer', info[3])
    for k, v in parse(inner).items(): print(f'   {k:16s} {v}')
    if info and len(sys.argv) > 1:
        open(path + '.inner.ess', 'wb').write(inner)
