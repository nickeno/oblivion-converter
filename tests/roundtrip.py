"""Read-only round-trip check over every Remastered save found (Game Pass wgs or given paths).

For each save: GVAS re-serialize is byte exact, .ess re-serialize is byte exact, and sealing with stored
Kraken blocks then re-opening gives the same inner data. Finding no saves counts as a failure.
tests/convert_test.py covers converting and adding saves.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from osc import xgp
from osc.ess import parse_ess, serialize_ess
from osc.gvas import parse_gvas, serialize_gvas
from osc.remastered import open_save, seal_save, decode_segments
from osc.gvas import find_prop


def check(label: str, raw: bytes) -> bool:
    t = time.time()
    outer = parse_gvas(raw)
    assert serialize_gvas(outer) == raw, 'outer GVAS not byte exact'
    save = open_save(raw)
    payload = decode_segments(find_prop(outer.props, 'AltarSaveData').data)
    assert serialize_gvas(save.inner) == payload[4:], 'inner GVAS not byte exact'
    ess = parse_ess(save.ess)
    assert serialize_ess(ess) == save.ess, '.ess not byte exact'
    sealed = seal_save(open_save(raw), save.ess)
    again = open_save(sealed)
    assert again.ess == save.ess and serialize_gvas(again.inner) == payload[4:], 'seal/reopen mismatch'
    print(f'OK  {label[:60]:60s} v0.{ess.minor_version} lvl {ess.pc_level:3d} recs {len(ess.records):6d} '
          f'plugins {len(ess.plugins)} sealed {len(sealed)/1e6:.1f} MB  {time.time()-t:.1f}s')
    return True


def main():
    paths = [Path(p) for p in sys.argv[1:]]
    items = [(p.name, p.read_bytes()) for p in paths]
    if not items:
        for d in xgp.default_wgs_dirs():
            for s in xgp.list_saves(d):
                if s.name.startswith(('Save', 'autosave', 'quicksave')) and not s.name.startswith('Save_'):
                    items.append((s.name, s.data_file.read_bytes()))
    if not items:
        print('No saves found to check. Pass .sav files (copies) on the command line.')
        return 2
    bad = 0
    for label, raw in items:
        try:
            check(label, raw)
        except Exception as e:
            bad += 1
            print(f'FAIL {label}: {type(e).__name__}: {e}')
    print(f'{len(items) - bad}/{len(items)} passed')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
