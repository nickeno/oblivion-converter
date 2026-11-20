"""Command line: python -m osc <command> ...

  list                               list Oblivion Remastered saves (Game Pass + Steam folders)
  info <save>                        show what's inside a .sav or .ess
  extract-ess <remastered> -o F      dump the raw embedded .ess (v0.127)
  to-og <remastered> -o F.ess        Remastered -> original Oblivion (experimental)
  to-remastered <og.ess> --template <remastered> -o F.sav    original -> Remastered (experimental)

<remastered> is a .sav path or "xgp:<save name or the start of one>" for a Game Pass save.
"""
import argparse
import os
import sys
from pathlib import Path

from . import library, xgp
from .convert import display_name, og_to_remastered, remastered_to_og
from .ess import parse_ess
from .remastered import open_save
from .xgp_write import write_atomic


def steam_save_dirs():
    p = library.steam_rem_dir()             # the real Documents folder, also when OneDrive moved it
    return [p] if p.is_dir() else []


def find_xgp(spec: str):
    """(profile folder, save) for "xgp:<name>": an exact name, else the one save whose name starts so."""
    want = spec[4:].lower()
    found = [(d, s) for d in library.xbox_dirs() for s in xgp.list_saves(d)]
    exact = [x for x in found if x[1].name.lower() == want]
    hits = exact or [x for x in found if x[1].name.lower().startswith(want)]
    if not hits:
        raise SystemExit(f'No Game Pass save starting with "{spec[4:]}"')
    if len(hits) > 1:
        raise SystemExit(f'"{spec[4:]}" fits {len(hits)} Game Pass saves. Give more of the name:\n  '
                         + '\n  '.join(f'xgp:{s.name}' for _, s in hits[:10]))
    return hits[0]


def load_remastered(spec: str) -> bytes:
    if spec.lower().startswith('xgp:'):
        return find_xgp(spec)[1].data_file.read_bytes()
    return Path(spec).read_bytes()


def _write_out(out: str, data: bytes, *inputs: str):
    """Write the result without ever replacing an input file, and never leave half a file."""
    path = Path(out)
    for i in inputs:
        if i and not i.lower().startswith('xgp:') and path.exists() and os.path.samefile(path, i):
            raise SystemExit(f'{out} is also an input file. Pick another output name.')
    write_atomic(path, data)


def cmd_list(_):
    for d in library.xbox_dirs():
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
    _write_out(a.out, s.ess, a.save)
    print(f'wrote {a.out} ({len(s.ess)} bytes)')


def cmd_to_og(a):
    out = remastered_to_og(load_remastered(a.save))
    _write_out(a.out, out, a.save)
    print(f'wrote {a.out} ({len(out)} bytes) - EXPERIMENTAL, keep backups')


def cmd_to_rem(a):
    out = og_to_remastered(Path(a.ess).read_bytes(), load_remastered(a.template),
                           record_version=a.record_version, keep_all_extras=a.keep_extras)
    _write_out(a.out, out, a.ess, a.template)
    print(f'wrote {a.out} ({len(out)} bytes) - EXPERIMENTAL, keep backups')


def cmd_import_xgp(a):
    dirs = library.xbox_dirs()
    if not dirs:
        raise SystemExit('No Game Pass Oblivion Remastered save folder found')
    if a.template.lower().startswith('xgp:'):
        wgs, tmpl = find_xgp(a.template)            # the new save goes to the template's own profile
        template = tmpl.data_file.read_bytes()
    else:
        template = Path(a.template).read_bytes()
        wgs = next((d for d in dirs if d.name == a.profile), None) if a.profile else (dirs[0] if len(dirs) == 1 else None)
        if wgs is None:
            raise SystemExit('Pick the Game Pass profile with --profile, one of:\n  ' + '\n  '.join(d.name for d in dirs))
    if a.profile and wgs.name != a.profile:
        raise SystemExit(f'The template is in profile {wgs.name}, not {a.profile}.')
    sav = og_to_remastered(Path(a.ess).read_bytes(), template, record_version=a.record_version, save_number=a.number)
    try:
        name, backup = library.import_to_game_pass(wgs, sav)
    except library.UserError as e:
        raise SystemExit(str(e))
    print(f'imported as {name} ({len(sav)} bytes), backup in {backup} - start the game to see it under Load')


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
    p.add_argument('--profile', help='Game Pass profile folder name (needed when there are several)')
    p.add_argument('--record-version', type=int, default=125, choices=(125, 127))
    p.set_defaults(fn=cmd_import_xgp)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == '__main__':
    main()
