"""The app window: the screen in osc/ui, talking to osc.library.

    python -m osc.app                 open the app
    python -m osc.app --serve 8770    no window: serve the same screen for a browser (open /?dev), for testing
    python -m osc.app --selftest f    open, write what the screen shows to file f, close (checks a packaged build)
"""
import json
import os
import sys
import threading
import traceback
from pathlib import Path

from . import library

TITLE = "Nickeno's Oblivion Converter"
UI_DIR = Path(__file__).resolve().parent / 'ui'


def _log(text: str):
    try:
        d = library.backups_dir().parent
        d.mkdir(parents=True, exist_ok=True)
        log = d / 'errors.log'
        if log.is_file() and log.stat().st_size > 1_000_000:        # keep it small: only the newest part
            log.write_bytes(log.read_bytes()[-200_000:])
        with open(log, 'a', encoding='utf-8') as f:
            f.write(text.rstrip() + '\n\n')
    except Exception:
        pass


def _groups(entries) -> list:
    """Saves grouped by character, newest character first, newest save first."""
    out = {}
    for e in entries:
        g = out.get(e.character_key)
        if g is None:
            target = None
            if e.store == 'xbox':
                target = 'xbox:' + e.id.split(':')[1]
            elif e.store == 'steam':
                target = 'steam'
            g = out[e.character_key] = {'key': e.character_key, 'name': e.character.strip() or 'No name',
                                        'store': e.store, 'target': target, 'saves': []}
        g['saves'].append(e.to_json())
    return list(out.values())


def _data() -> dict:
    return {'ok': True, 'og': _groups(library.list_og()), 'rem': _groups(library.list_remastered()),
            'status': library.status()}


class Api:
    """What the screen can ask for. Every answer is plain JSON; errors come back as {ok: False, error}."""

    _lock = threading.Lock()

    def load(self):
        try:
            return _data()
        except Exception:
            _log(traceback.format_exc())
            return {'ok': False, 'error': "Your saves couldn't be read. Close the app and open it again."}

    def thumb(self, entry_id):
        try:
            return library.thumbnail(str(entry_id))
        except Exception:
            return None

    def convert(self, entry_id, target=None):
        with self._lock:                    # one convert at a time
            try:
                entry_id = str(entry_id)
                if entry_id.startswith('og:'):
                    res = library.to_remastered(entry_id, target or None)
                else:
                    res = library.to_og(entry_id)
                return {'ok': True, 'new_id': res['id'], 'title': res['title'], 'where': res['where'],
                        'backup': res.get('backup'), 'data': _data()}
            except library.UserError as e:
                return {'ok': False, 'error': str(e)}
            except Exception:
                _log(traceback.format_exc())
                return {'ok': False, 'error': "That save couldn't be converted. Your other saves were not touched."}

    def open_backups(self):
        try:
            d = library.backups_dir()
            d.mkdir(parents=True, exist_ok=True)
            os.startfile(d)
            return {'ok': True}
        except Exception:
            return {'ok': False, 'error': "The backups folder couldn't be opened."}


# ----------------------------------------------------------------------------- browser test server
def serve(port: int):
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    api = Api()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(UI_DIR), **k)

        def do_POST(self):
            name = self.path[5:] if self.path.startswith('/api/') else ''
            # the header keeps other web pages from calling this (it forces a cross-origin check they fail)
            if self.headers.get('X-OSC') != '1' or name.startswith('_') or not callable(getattr(api, name, None)):
                return self.send_error(404)
            args = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'[]')
            body = json.dumps(getattr(api, name)(*args)).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def end_headers(self):
            self.send_header('Cache-Control', 'no-store')
            super().end_headers()

        def log_message(self, *a):
            pass

    print(f'http://127.0.0.1:{port}/?dev')
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()


def _selftest(window, out_path: str):
    import time
    from . import oodle
    report = {'ok': False}
    js = """JSON.stringify({ rows: document.querySelectorAll('.row').length,
        pictures: document.querySelectorAll('.thumb img.in').length,
        looking: !!document.querySelector('.empty') && document.querySelector('.empty').textContent.indexOf('Looking') === 0,
        fire: !!(window.Fire && window.Fire.ok), bridge: !!(window.pywebview && window.pywebview.api.load) })"""
    try:
        report['ooz'] = str(oodle._find_dll())
        end = time.time() + 20
        while time.time() < end:
            time.sleep(.5)
            try:
                state = json.loads(window.evaluate_js(js) or '{}')
            except Exception:
                continue
            report.update(state)
            if state.get('bridge') and not state.get('looking') and (not state.get('rows') or state.get('pictures')):
                report['ok'] = bool(state.get('fire'))
                break
    except Exception:
        report['error'] = traceback.format_exc()
    Path(out_path).write_text(json.dumps(report, indent=1), encoding='utf-8')
    window.destroy()


def main():
    if '--serve' in sys.argv:
        return serve(int(sys.argv[sys.argv.index('--serve') + 1]))
    import webview
    window = webview.create_window(TITLE, str(UI_DIR / 'index.html'), js_api=Api(), width=1280, height=820,
                                   min_size=(940, 640), background_color='#15120f')
    # a local server instead of file:// so the fire's pictures can be drawn by the graphics card
    if '--selftest' in sys.argv:
        return webview.start(_selftest, (window, sys.argv[sys.argv.index('--selftest') + 1]), http_server=True)
    webview.start(http_server=True)


if __name__ == '__main__':
    main()
