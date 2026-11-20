"""Command line: python -m osc <command> ...

  list                               list Oblivion Remastered saves (Game Pass + Steam folders)
  info <save>                        show what's inside a .sav or .ess
  extract-ess <remastered> -o F      dump the raw embedded .ess (v0.127)
  to-og <remastered> -o F.ess        Remastered -> original Oblivion (experimental)
  to-remastered <og.ess> --template <remastered> -o F.sav    original -> Remastered (experimental)

<remastered> is a .sav path or "xgp:<save name prefix>" for a Game Pass save.
"""
import argparse
import os
import sys
from pathlib import Path

from . import xgp
from .convert import display_name, og_to_remastered, remastered_to_og
from .ess import parse_ess
from .remastered import open_save


def steam_save_dirs():
    p = Path(os.path.expanduser('~/Documents/My Games/Oblivion Remastered/Saved/SaveGames'))
    return [p] if p.is_dir() else []


def load_remastered(spec: str) -> bytes:
    if spec.lower().startswith('xgp:'):
        want = spec[4:].lower()
        for d in xgp.default_wgs_dirs():
            for s in xgp.list_saves(d):
                if s.name.lower().startswith(want):
                    return s.data_file.read_bytes()
        raise SystemExit(f'No Game Pass save starting with "{spec[4:]}"')
    return Path(spec).read_bytes()


def cmd_list(_):
    for d in xgp.default_wgs_dirs():
        print(f'Game Pass ({d.name}):')
        for s in xgp.list_saves(d):
            if s.name.startswith(('Save_', 'WinGDK_', 'saves_meta')):
                continue
            print(f'  xgp:{s.name}')
    for d in steam_save_dirs():
        print(f'Steam ({d}):')
        for f in sorted(d.glob('*.sav')):
            if f.stem != 'saves_meta':
                print(f'  {f}')


def _print_ess(e, label):
    print(f'{label}: v0.{e.minor_version}  {e.pc_name!r} level {e.pc_level} at {e.pc_location!r}  '
          f'day {e.game_days:.1f}  {len(e.records)} change records')
    print('  plugins: ' + ', '.join(e.plugins))


def cmd_info(a):
    if a.save.lower().endswith('.ess'):
        _print_ess(parse_ess(Path(a.save).read_bytes()), 'Original Oblivion save')
        return
    s = open_save(load_remastered(a.save))
    _print_ess(parse_ess(s.ess), 'Remastered save (embedded .ess)')
    print(f'  display name: {display_name(s)!r}')


def cmd_extract(a):
    s = open_save(load_remastered(a.save))
    Path(a.out).write_bytes(s.ess)
    print(f'wrote {a.out} ({len(s.ess)} bytes)')


def cmd_to_og(a):
    out = remastered_to_og(load_remastered(a.save))
    Path(a.out).write_bytes(out)
    print(f'wrote {a.out} ({len(out)} bytes) - EXPERIMENTAL, keep backups')


def cmd_to_rem(a):
    out = og_to_remastered(Path(a.ess).read_bytes(), load_remastered(a.template),
                           record_version=a.record_version, keep_all_extras=a.keep_extras)
    Path(a.out).write_bytes(out)
    print(f'wrote {a.out} ({len(out)} bytes) - EXPERIMENTAL, keep backups')


def cmd_import_xgp(a):
    from . import xgp_write
    from .gvas import find_prop
    dirs = xgp.default_wgs_dirs()
    if not dirs:
        raise SystemExit('No Game Pass Oblivion Remastered save folder found')
    sav = og_to_remastered(Path(a.ess).read_bytes(), load_remastered(a.template),
                           record_version=a.record_version, save_number=a.number)
    s = open_save(sav)
    slot = find_prop(s.details.props, 'SlotName').value.s
    name = xgp_write.import_save(dirs[0], sav, slot, s.details.props)
    print(f'imported as {name} ({len(sav)} bytes) - start the game to see it under Load')


def main(argv=None):
    ap = argparse.ArgumentParser(prog='osc', description='Oblivion <-> Oblivion Remastered save converter')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list').set_defaults(fn=cmd_list)
    p = sub.add_parser('info'); p.add_argument('save'); p.set_defaults(fn=cmd_info)
    p = sub.add_parser('extract-ess'); p.add_argument('save'); p.add_argument('-o', '--out', required=True); p.set_defaults(fn=cmd_extract)
    p = sub.add_parser('to-og'); p.add_argument('save'); p.add_argument('-o', '--out', required=True); p.set_defaults(fn=cmd_to_og)
    p = sub.add_parser('to-remastered'); p.add_argument('ess'); p.add_argument('--template', required=True)
    p.add_argument('-o', '--out', required=True)
    p.add_argument('--record-version', type=int, default=125, choices=(125, 127))
    p.add_argument('--keep-extras', action='store_true', help="keep the template's physics/cinematic data")
    p.set_defaults(fn=cmd_to_rem)
    p = sub.add_parser('import-xgp', help='convert an OG save and add it to your Game Pass saves (game closed!)')
    p.add_argument('ess'); p.add_argument('--template', required=True)
    p.add_argument('--number', type=int, default=99, help='save slot number shown in game')
    p.add_argument('--record-version', type=int, default=125, choices=(125, 127))
    p.set_defaults(fn=cmd_import_xgp)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == '__main__':
    main()
