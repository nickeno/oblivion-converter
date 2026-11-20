"""Converting and adding saves, on copies only.

    python tests/convert_test.py --wgs <a Game Pass profile folder> --og <one or more .ess files>

Everything given is copied into a temporary folder first and only the copies are changed, so the real save
folders can be passed safely (with the game closed, so the copy is a clean one). Each check prints OK or FAIL.
"""
import argparse
import hashlib
import os
import random
import shutil
import struct
import sys
import tempfile
import threading
import traceback
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from osc import app, cli, convert, library, oodle, xgp, xgp_write                    # noqa: E402
from osc.binio import Reader, Writer                                                   # noqa: E402
from osc.ess import parse_ess, player_look, serialize_ess                              # noqa: E402
from osc.gvas import FStr, _read_props, _write_props, find_prop, parse_gvas, read_fstr, write_fstr  # noqa: E402
from osc.remastered import SaveFormatError, open_save                                 # noqa: E402

ARGS = None
TMP = None
RESULTS = []
CHECKS = []


def test(fn):
    CHECKS.append(fn)
    return fn


def check(fn):
    try:
        fn()
        RESULTS.append((fn.__name__, None))
        print(f'OK    {fn.__name__}')
    except Exception:
        RESULTS.append((fn.__name__, traceback.format_exc()))
        print(f'FAIL  {fn.__name__}\n{traceback.format_exc()}')
    return fn


_run = [0]


def fresh(steam=False):
    """New copies of the test saves, and the app pointed at them."""
    _run[0] += 1
    root = TMP / f'run{_run[0]}'
    wgs = root / 'wgs' / ARGS.wgs.name
    shutil.copytree(ARGS.wgs, wgs)
    og = root / 'og'
    og.mkdir(parents=True)
    for f in ARGS.og:
        shutil.copy2(f, og / f.name)
    sd = root / 'steam'
    if steam:
        sd.mkdir()
        saves = {s.name: s for s in xgp.list_saves(wgs)}
        meta = library._meta_by_container(saves['saves_meta'].data_file.read_bytes())
        shutil.copy2(saves['saves_meta'].data_file, sd / 'saves_meta.sav')
        for name, s in saves.items():
            if name in meta and name != 'saves_meta':
                shutil.copy2(s.data_file, sd / (library._safe_filename(meta[name][0]) + '.sav'))
        os.environ['OSC_STEAM_REM'] = str(sd)
    else:
        os.environ['OSC_STEAM_REM'] = str(root / 'no-steam')
    os.environ.update(OSC_WGS=str(wgs), OSC_OG_SAVES=str(og), OSC_BACKUPS=str(root / 'backups'))
    return root, wgs, og, sd


def snapshot(folder: Path) -> dict:
    return {str(p.relative_to(folder)): hashlib.sha1(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file()}


def og_entry():
    return library.list_og()[0]


def index_entry(wgs, name):
    return next((e for e in xgp_write.read_index(wgs / 'containers.index').entries if e.name == name), None)


# ----------------------------------------------------------------------------- formats
@test
def strings_one_byte_and_utf16():
    w = Writer()
    write_fstr(w, FStr('caf\xe9', False))          # one byte per letter, like Unreal writes it
    assert w.out() == struct.pack('<i', 5) + b'caf\xe9\0'
    assert read_fstr(Reader(w.out())).s == 'caf\xe9'
    w = Writer()
    write_fstr(w, 'a\U0001F600')                   # an emoji is two UTF-16 units
    assert struct.unpack('<i', w.out()[:4])[0] == -4
    assert read_fstr(Reader(w.out())).s == 'a\U0001F600'
    w = Writer()
    xgp_write._wws(w, 'a\U0001F600')
    assert struct.unpack('<I', w.out()[:4])[0] == 3 and xgp_write._rws(Reader(w.out())) == 'a\U0001F600'


@test
def property_with_guid():
    w = Writer()
    write_fstr(w, 'X'); write_fstr(w, 'IntProperty'); w.i32(4); w.i32(0)
    w.u8(1); w.bytes(bytes(range(16))); w.i32(7)
    write_fstr(w, 'None')
    raw = w.out()
    props = _read_props(Reader(raw), len(raw))
    assert props[0].value == 7 and props[0].prop_guid == bytes(range(16))
    w2 = Writer()
    _write_props(w2, props)
    assert w2.out() == raw


@test
def text_fields_never_wrap():
    e = parse_ess(ARGS.og[0].read_bytes())
    e.pc_location = 'A' * 300
    try:
        serialize_ess(e)
        raise AssertionError('a 300 letter location was written')
    except Exception as x:
        assert 'too long' in str(x)


def first_save_bytes(wgs):
    return next(s for s in xgp.list_saves(wgs) if s.name.startswith('Save')).data_file.read_bytes()


@test
def compressed_sizes_checked():
    _, wgs, _, _ = fresh()
    raw = first_save_bytes(wgs)
    outer = parse_gvas(raw)
    data = find_prop(outer.props, 'AltarSaveData').data
    at = raw.index(data[:64])
    for patch_at, value in ((16, b'\x03'), (25, struct.pack('<q', struct.unpack_from('<q', data, 25)[0] + 1))):
        bad = bytearray(raw)
        bad[at + patch_at:at + patch_at + len(value)] = value
        try:
            open_save(bytes(bad))
            raise AssertionError(f'a broken segment header at {patch_at} was accepted')
        except SaveFormatError:
            pass


@test
def decoder_survives_broken_input():
    _, wgs, _, _ = fresh()
    data = find_prop(parse_gvas(first_save_bytes(wgs)).props, 'AltarSaveData').data
    r = Reader(data, 8 + 8 + 1)
    sc, su = r.i64(), r.i64()
    cs, us = r.i64(), r.i64()
    n = (su + 0x20000 - 1) // 0x20000
    chunk = data[17 + 16 + n * 16:][:cs]
    assert oodle.decompress(chunk, us)[:4]                 # the real chunk decodes
    rnd = random.Random(1)
    for i in range(400):                                    # cut short, or filled with noise
        if i % 2:
            src = chunk[:rnd.randrange(0, len(chunk))]
        else:
            src = chunk[:2] + bytes(rnd.randrange(256) for _ in range(rnd.randrange(0, 600)))
        try:
            oodle.decompress(src, us)
        except ValueError:
            pass
    for hdr in (b'\x8c\x0a', b'\x8c\x05', b'\x00\x00'):     # other decoders are refused before the DLL
        try:
            oodle.decompress(hdr + b'\0' * 100, 1000)
            raise AssertionError('a non-Kraken stream was decoded')
        except ValueError:
            pass


# ----------------------------------------------------------------------------- Game Pass
@test
def game_pass_import_commits_with_the_index():
    _, wgs, _, _ = fresh()
    meta_before = index_entry(wgs, 'saves_meta')
    old_cfile = wgs / meta_before.folder_name / f'container.{meta_before.num}'
    res = library.to_remastered(og_entry().id)
    meta_after = index_entry(wgs, 'saves_meta')
    assert meta_after.num == meta_before.num + 1 and meta_after.state == 2
    assert not old_cfile.exists(), 'the old saves_meta revision was left behind'
    files = sorted(p.name for p in (wgs / meta_after.folder_name).iterdir())
    assert len(files) == 2 and f'container.{meta_after.num}' in files, files
    new = index_entry(wgs, res['container'])
    assert new is not None and new.state == 5 and new.etag == ''
    ids = [s.id for s in library.list_remastered()]
    assert res['id'] in ids
    meta = library._meta_by_container({s.name: s for s in xgp.list_saves(wgs)}['saves_meta'].data_file.read_bytes())
    assert res['container'] in meta
    raw = (wgs / 'containers.index').read_bytes()
    assert xgp_write.write_index(xgp_write.parse_index(raw)) == raw
    res2 = library.to_remastered(og_entry().id)
    assert res2['title'] != res['title'] and res2['container'] != res['container']


@test
def converted_player_record_uses_the_name_key():
    _, wgs, og, _ = fresh()
    res = library.to_remastered(og_entry().id)
    e = parse_ess(open_save(library._rem_bytes(res['id'])).ess)
    fits = res['note'] is None
    assert e.pc_name.startswith('UI_UserInputText'), e.pc_name
    # with a fitting face the record holds the key (no "[NL]name" in game) and the save can be a template
    assert (player_look(e) is not None) == fits
    back = parse_ess(Path(library.to_og(res['id'])['path']).read_bytes())
    assert not back.pc_name.startswith('UI_') and player_look(back) is not None


@test
def failed_index_write_changes_nothing():
    _, wgs, _, _ = fresh()
    library.to_remastered(og_entry().id)                     # a backup folder exists now, ignore it
    before = snapshot(wgs)
    real = xgp_write.write_atomic

    def broken(path, data, overwrite=True):
        if path.name == 'containers.index':
            raise OSError('disk full (test)')
        return real(path, data, overwrite)
    xgp_write.write_atomic = broken
    try:
        try:
            library.to_remastered(og_entry().id)
            raise AssertionError('the import did not fail')
        except OSError:
            pass
    finally:
        xgp_write.write_atomic = real
    assert snapshot(wgs) == before, 'files changed after a failed import'


@test
def failed_rollback_says_restore_the_backup():
    _, wgs, _, _ = fresh()
    path = wgs / 'containers.index'
    idx = xgp_write.read_index(path)
    meta = next(e for e in idx.entries if e.name == 'saves_meta')
    folder = wgs / meta.folder_name
    (folder / f'container.{meta.num}').rename(folder / 'container.255')
    meta.num = 255                                            # revision numbers are full: rewrite in place
    path.write_bytes(xgp_write.write_index(idx))
    real = xgp_write.write_atomic
    calls = []

    def broken(path, data, overwrite=True):
        calls.append(path.name)
        if path.name == 'containers.index' or calls.count(path.name) > 1:
            raise OSError('disk full (test)')
        return real(path, data, overwrite)
    xgp_write.write_atomic = broken
    try:
        try:
            library.to_remastered(og_entry().id)
            raise AssertionError('the import did not fail')
        except library.UserError as e:
            assert 'Restore the backup' in str(e) and '.zip' in str(e), str(e)
    finally:
        xgp_write.write_atomic = real


@test
def two_converts_at_once_both_land():
    _, wgs, _, _ = fresh()
    sid, out = og_entry().id, []
    threads = [threading.Thread(target=lambda: out.append(library.to_remastered(sid))) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(out) == 2 and out[0]['container'] != out[1]['container']
    names = {e.name for e in xgp_write.read_index(wgs / 'containers.index').entries}
    assert out[0]['container'] in names and out[1]['container'] in names
    meta = library._meta_by_container({s.name: s for s in xgp.list_saves(wgs)}['saves_meta'].data_file.read_bytes())
    assert out[0]['container'] in meta and out[1]['container'] in meta


@test
def newer_index_layout_is_refused():
    _, wgs, _, _ = fresh()
    p = wgs / 'containers.index'
    p.write_bytes(p.read_bytes() + b'\x01\x02\x03\x04')
    before = snapshot(wgs)
    try:
        library.to_remastered(og_entry().id)
        raise AssertionError('a changed index layout was written over')
    except library.UserError as e:
        assert "doesn't know" in str(e)
    after = snapshot(wgs)
    assert after == before


@test
def reader_follows_the_index_revision():
    _, wgs, _, _ = fresh()
    s = next(s for s in xgp.list_saves(wgs) if s.name.startswith('Save'))
    e = index_entry(wgs, s.name)
    (s.folder / f'container.{e.num + 7}').write_bytes(b'\x04\0\0\0\x01\0\0\0' + b'\0' * 160)
    again = next(x for x in xgp.list_saves(wgs) if x.name == s.name)
    assert again.data_file == s.data_file


@test
def one_broken_container_hides_only_itself():
    _, wgs, _, _ = fresh()
    saves = xgp.list_saves(wgs)
    s = next(s for s in saves if s.name.startswith('Save'))
    e = index_entry(wgs, s.name)
    (s.folder / f'container.{e.num}').write_bytes(b'\x04\0')
    assert len(xgp.list_saves(wgs)) == len(saves) - 1


@test
def broken_template_does_not_block_a_good_one():
    _, wgs, og, _ = fresh()
    ess = (og / ARGS.og[0].name).read_bytes()
    first, _, _ = library._template_for(ess, 'xbox', wgs.name)
    data = xgp.list_saves(wgs)
    victim = next(s for s in data if f'xbox:{wgs.name}:{s.name}' == first.id)
    victim.data_file.write_bytes(b'GVAS broken')
    library._meta_cache.clear()
    second, raw, _ = library._template_for(ess, 'xbox', wgs.name)
    assert second is not None and second.id != first.id and open_save(raw)


@test
def two_profiles_stay_apart():
    root, wgs, _, _ = fresh()
    twin = root / 'wgs' / 'SECOND_PROFILE'
    shutil.copytree(wgs, twin)
    real = library.xbox_dirs
    library.xbox_dirs = lambda: [wgs, twin]
    try:
        groups = app._data()['rem']
        keys = [g['key'] for g in groups]
        assert len(keys) == len(set(keys))
        assert {g['target'] for g in groups} == {f'xbox:{wgs.name}', 'xbox:SECOND_PROFILE'}
        assert {g['store_label'] for g in groups} == {'Game Pass 1', 'Game Pass 2'}
    finally:
        library.xbox_dirs = real


# ----------------------------------------------------------------------------- original game
@test
def to_og_never_overwrites_a_save():
    _, wgs, og, _ = fresh()
    keep = og / 'save 3 - lowercase test.ess'
    shutil.copy2(ARGS.og[0], keep)
    before = keep.read_bytes()
    rem = next(s for s in library.list_remastered() if s.title.startswith('Save'))
    res = library.to_og(rem.id)
    assert keep.read_bytes() == before
    n = int(res['title'].split()[1])
    others = [int(p.name.split()[1]) for p in og.glob('*.ess') if p.name.lower().startswith('save ')
              and p.name.split()[1].isdigit()]
    assert n == max(o for o in others if o != n) + 1 or n > 3
    assert Path(res['path']).is_file() and res['id'] in [s.id for s in library.list_og()]


@test
def to_og_names_the_player_in_their_record():
    _, wgs, og, _ = fresh()
    rem = next(s for s in library.list_remastered() if s.title.startswith('Save'))
    e = parse_ess(Path(library.to_og(rem.id)['path']).read_bytes())
    assert not e.pc_name.startswith('UI_UserInputText'), e.pc_name
    assert player_look(e) is not None, 'the player record still has the text key'


def _altar_pair(text: bytes) -> bytes:
    return b'\x5e' + bytes(range(1, 17)) + b'\x5f' + (text + b'\0').ljust(128, b'\xcd')


@test
def remastered_extras_are_cut_for_og():
    head = struct.pack('<H', 4) + b'\x12' + bytes(8)              # count 4, then an 8-byte entry
    tail = b'\x47' + bytes(6)
    body = head + _altar_pair(b'0.0-8.0-6.00.0') + tail
    assert convert.strip_altar_extras(body) == head + b'\x5e\x5f' + tail
    body = head + _altar_pair(b'NotSpatiallyLoaded') + tail
    assert convert.strip_altar_extras(body) == head + b'\x5e\x5f' + tail
    loose = head + b'\x5e' + bytes(40) + tail                     # a 0x5E byte that isn't the pair
    assert convert.strip_altar_extras(loose) == loose
    _, wgs, og, _ = fresh()
    for rem in [s for s in library.list_remastered() if s.title.startswith('Save')][:3]:
        e = parse_ess(Path(library.to_og(rem.id)['path']).read_bytes())
        for r in e.records:
            if r.type in convert.REF_TYPES and r.flags & 0x20:
                assert convert.strip_altar_extras(r.data) == r.data, f'{r.form_id:08X} still has the pair'


@test
def stale_original_id_is_refused():
    root, _, og, _ = fresh()
    sid = og_entry().id
    other = root / 'other-profile'
    other.mkdir()
    shutil.copy2(og / ARGS.og[0].name, other / ARGS.og[0].name)
    os.environ['OSC_OG_SAVES'] = str(other)
    try:
        library.og_path(sid)
        raise AssertionError('an id from another save folder was used')
    except library.UserError:
        pass


@test
def long_location_still_converts():
    _, wgs, og, _ = fresh()
    e = parse_ess(ARGS.og[0].read_bytes())
    e.pc_location = 'Very Long Place ' * 15
    (og / 'Save 900 - long.ess').write_bytes(serialize_ess(e))
    sid = next(s.id for s in library.list_og() if s.id.endswith('Save 900 - long.ess'))
    res = library.to_remastered(sid)
    assert len(res['container']) < 200


@test
def full_plugin_list_is_refused():
    _, wgs, og, _ = fresh()
    e = parse_ess(ARGS.og[0].read_bytes())
    e.plugins = [f'Mod{i}.esp' for i in range(255)]
    (og / 'Save 901 - mods.ess').write_bytes(serialize_ess(e))
    sid = next(s.id for s in library.list_og() if s.id.endswith('Save 901 - mods.ess'))
    try:
        library.to_remastered(sid)
        raise AssertionError('a 256th plugin was added')
    except library.UserError as x:
        assert '255' in str(x)


# ----------------------------------------------------------------------------- Steam, backups, app, CLI
@test
def steam_import_and_full_backup():
    _, wgs, og, sd = fresh(steam=True)
    before = sorted(p.name for p in sd.iterdir())
    res = library.to_remastered(og_entry().id, 'steam')
    assert Path(res['path']).is_file()
    meta = library._meta_by_container((sd / 'saves_meta.sav').read_bytes())
    assert Path(res['path']).stem in meta
    with zipfile.ZipFile(res['backup']) as z:
        packed = sorted(Path(n).name for n in z.namelist())
    assert packed == before, (packed, before)


@test
def backups_never_collide_or_pack_themselves():
    root, wgs, _, _ = fresh()
    os.environ['OSC_BACKUPS'] = str(wgs / 'inside-backups')
    a = library._backup(wgs, 'GamePass')
    b = library._backup(wgs, 'GamePass')
    assert a != b and a.is_file() and b.is_file()
    with zipfile.ZipFile(b) as z:
        assert not any('inside-backups' in n for n in z.namelist())


@test
def app_reports_success_when_the_list_fails_after():
    fresh()
    real = app._data
    app._data = lambda: (_ for _ in ()).throw(RuntimeError('list broke (test)'))
    try:
        res = app.Api().convert(og_entry().id)
    finally:
        app._data = real
    assert res['ok'] and res['data'] is None and res['new_id']


@test
def cli_keeps_its_input():
    _, wgs, _, _ = fresh()
    src = wgs.parent / 'input.sav'
    src.write_bytes(first_save_bytes(wgs))
    before = src.read_bytes()
    try:
        cli.main(['extract-ess', str(src), '-o', str(src)])
        raise AssertionError('the input was overwritten')
    except SystemExit as e:
        assert 'input' in str(e)
    assert src.read_bytes() == before


@test
def cli_import_uses_the_app_safeguards():
    root, wgs, og, _ = fresh()
    tmpl = next(s for s in xgp.list_saves(wgs) if s.name.startswith('Save'))
    cli.main(['import-xgp', str(og / ARGS.og[0].name), '--template', 'xgp:' + tmpl.name, '--number', '77'])
    assert any(e.name.startswith('Save77') for e in xgp_write.read_index(wgs / 'containers.index').entries)
    assert list((root / 'backups').glob('GamePass_*.zip')), 'no backup was made'


def main():
    global ARGS, TMP
    ap = argparse.ArgumentParser()
    ap.add_argument('--wgs', type=Path, required=True, help='a Game Pass profile folder (it is copied)')
    ap.add_argument('--og', type=Path, nargs='+', required=True, help='original .ess saves (they are copied)')
    ARGS = ap.parse_args()
    TMP = Path(tempfile.mkdtemp(prefix='osc_test_'))
    print('working in', TMP)
    try:
        for fn in list(CHECKS):
            check(fn)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    bad = [n for n, err in RESULTS if err]
    print(f'{len(RESULTS) - len(bad)}/{len(RESULTS)} passed')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
