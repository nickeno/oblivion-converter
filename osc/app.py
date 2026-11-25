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


def _groups(entries, labels=None) -> list:
    """Saves grouped by character, newest character first, newest save first. `labels` names each
    Remastered save folder (two Game Pass profiles get their own number)."""
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
                                        'store': e.store, 'target': target,
                                        'store_label': (labels or {}).get(target, ''), 'saves': []}
        g['saves'].append(e.to_json())
    return list(out.values())


def _data() -> dict:
    labels = {t['id']: t['short'] for t in library.remastered_targets()}
    return {'ok': True, 'og': _groups(library.list_og()), 'rem': _groups(library.list_remastered(), labels),
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
        with self._lock:                    # one convert at a time in this window (library locks across apps)
            try:
                entry_id = str(entry_id)
                if entry_id.startswith('og:'):
                    res = library.to_remastered(entry_id, target or None)
                else:
                    res = library.to_og(entry_id)
            except library.UserError as e:
                return {'ok': False, 'error': str(e)}
            except Exception:
                _log(traceback.format_exc())
                return {'ok': False, 'error': "That save couldn't be converted. Your other saves were not touched."}
            # the save is written: a list that can't be read now must not turn this into a failure
            try:
                data = _data()
            except Exception:
                _log(traceback.format_exc())
                data = None
            return {'ok': True, 'new_id': res['id'], 'title': res['title'], 'where': res['where'],
                    'backup': res.get('backup'), 'note': res.get('note'), 'data': data}

    def open_backups(self):
        try:
            d = library.backups_dir()
            d.mkdir(parents=True, exist_ok=True)
            os.startfile(d)
            return {'ok': True}
        except Exception:
            return {'ok': False, 'error': "The backups folder couldn't be opened."}


# ----------------------------------------------------------------------------- browser test server
API_CALLS = ('load', 'thumb', 'convert', 'open_backups')
MAX_BODY = 64 * 1024


def serve(port: int):
    import hmac
    import secrets
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    api = Api()
    token = secrets.token_urlsafe(24)        # new each start; only the printed address knows it

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(UI_DIR), **k)

        def do_POST(self):
            name = self.path[5:] if self.path.startswith('/api/') else ''
            # the token header keeps other programs and web pages from calling this (a custom header also
            # forces a cross-origin check web pages fail)
            if not hmac.compare_digest(self.headers.get('X-OSC', ''), token) or name not in API_CALLS:
                return self.send_error(404)
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                return self.send_error(400)
            if not 0 <= length <= MAX_BODY:
                return self.send_error(413)
            try:
                args = json.loads(self.rfile.read(length) or b'[]')
                if not isinstance(args, list) or len(args) > 4:
                    raise ValueError
            except ValueError:
                return self.send_error(400)
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

    print(f'http://127.0.0.1:{port}/?dev={token}', flush=True)
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
        start = time.time()
        end = start + 20
        while time.time() < end:
            time.sleep(.5)
            try:
                state = json.loads(window.evaluate_js(js) or '{}')
            except Exception:
                continue
            report.update(state)
            # an empty list only counts after a few seconds: a cold start can be read before the page drew anything
            settled = state.get('pictures') or (not state.get('rows') and time.time() - start > 5)
            if state.get('bridge') and not state.get('looking') and settled:
                report['ok'] = bool(state.get('fire'))
                break
    except Exception:
        report['error'] = traceback.format_exc()
    Path(out_path).write_text(json.dumps(report, indent=1), encoding='utf-8')
    window.destroy()


WEBVIEW2_LINK = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703'       # Microsoft's own small installer
WEBVIEW2_KEYS = ('{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', '{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}',
                 '{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}', '{65C35B14-6C1D-4122-AC46-7148CC9D6497}')


def _has_webview2() -> bool:
    """Is the part of Windows that draws the window there? (Windows 11 has it, an old Windows 10 may not.)
    Without it the window would open in the old Internet Explorer engine and show a broken page."""
    import winreg
    for root, base in ((winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients'),
                       (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\EdgeUpdate\Clients'),
                       (winreg.HKEY_CURRENT_USER, r'SOFTWARE\Microsoft\EdgeUpdate\Clients')):
        for key in WEBVIEW2_KEYS:
            try:
                with winreg.OpenKey(root, base + '\\' + key) as k:
                    if str(winreg.QueryValueEx(k, 'pv')[0]).strip('0.'):
                        return True
            except OSError:
                continue
    return False


def _webview_renderer() -> str:
    """What pywebview will draw with: 'edgechromium' is WebView2. It also needs .NET 4.6.2 or newer, and
    without that it quietly falls back to the old Internet Explorer engine, which can't show this screen."""
    try:
        from webview.platforms import winforms
        return winforms.renderer
    except Exception:
        return ''


def _ask_for_webview2():
    import ctypes
    import webbrowser
    text = ("This app needs Microsoft Edge WebView2, and this PC doesn't have it (or Windows is missing "
            ".NET Framework 4.6.2 or newer, which Windows Update installs).\n\n"
            "Press OK to get WebView2 from Microsoft. Install it, then open the app again.")
    if ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x1 | 0x30) == 1:       # OK/Cancel, warning sign
        webbrowser.open(WEBVIEW2_LINK)


def main():
    if '--serve' in sys.argv:
        return serve(int(sys.argv[sys.argv.index('--serve') + 1]))
    if not _has_webview2() or _webview_renderer() != 'edgechromium':
        return _ask_for_webview2()
    import webview
    window = webview.create_window(TITLE, str(UI_DIR / 'index.html'), js_api=Api(), width=1280, height=820,
                                   min_size=(940, 640), background_color='#15120f')
    # a local server instead of file:// so the fire's pictures can be drawn by the graphics card
    if '--selftest' in sys.argv:
        return webview.start(_selftest, (window, sys.argv[sys.argv.index('--selftest') + 1]), http_server=True)
    webview.start(http_server=True)


if __name__ == '__main__':
    main()
