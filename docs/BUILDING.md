# Building it yourself

Windows on a 64-bit Intel or AMD PC, with 64-bit Python 3.12 or newer. The decoder `ooz.dll` is 64-bit
(x64), so 32-bit Python and ARM Python can't load it.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m osc.app
```

`requirements.txt` pins the exact versions the released .exe is built with.

Make the zip (it lands in `dist`):

```
.venv\Scripts\python packaging\build.py
```

Remastered saves are packed with Oodle. Reading them needs `ooz.dll`. A built copy is in `third_party/ooz/build`,
next to `build.cmd` which rebuilds it from `third_party/ooz/src`. It finds Visual Studio by itself (any edition
with the C++ tools).

There is also a command line: `python -m osc --help`.

[NOTES.md](../NOTES.md) has what was worked out about both save formats.
