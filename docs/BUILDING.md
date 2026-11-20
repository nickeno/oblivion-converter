# Building it yourself

Windows, Python 3.12 or newer.

```
python -m venv .venv
.venv\Scripts\pip install pywebview pillow pyinstaller
.venv\Scripts\python -m osc.app
```

Make the single .exe:

```
.venv\Scripts\python packaging\build.py
```

Remastered saves are packed with Oodle. Reading them needs `ooz.dll`. A built copy is in `third_party/ooz/build`,
next to `build.cmd` which rebuilds it from `third_party/ooz/src` with the Visual Studio C++ compiler.

There is also a command line: `python -m osc --help`.

[NOTES.md](../NOTES.md) has what was worked out about both save formats.
