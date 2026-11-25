# Third-party parts

## In this repository

| What | Where | License |
| --- | --- | --- |
| ooz by powzix (Kraken, LZNA and Bitknit decoders), with a few added safety checks | `third_party/ooz/` | GPL-3.0-or-later (stated in the `kraken.cpp` header) |
| GVAS (Unreal save) reader, ported from ORSE's `src/shared/gvas.ts` | `osc/gvas.py` | MIT, notice below |
| Nunito font, by Vernon Adams and the Nunito project authors | `osc/ui/assets/nunito.woff2` | SIL Open Font License 1.1 |
| Game logos and artwork (the two Oblivion logos, the stone wall, the gate sign and its fire) | `osc/ui/assets/`, `packaging/app.ico` | Property of Bethesda Softworks / ZeniMax Media. Not covered by this project's license. |

## Shipped in the zip

| What | License |
| --- | --- |
| Python | PSF License |
| pywebview | BSD-3-Clause |
| pythonnet, clr-loader | MIT |
| bottle | MIT |
| proxy-tools | MIT |
| Pillow | MIT-CMU |
| Microsoft Edge WebView2 loader (part of pywebview) | Microsoft, redistributable |

Because ooz is GPL, the whole tool is released under GPL-3.0-or-later.

## Used as reference only, no code copied

- UESP, Oblivion save file format: https://en.uesp.net/wiki/Oblivion_Mod:Save_File_Format
- ORSE's other files (the `.ess` and save layout): https://github.com/Microb4ek/OblivionRemastered-save-editor-ORSE
- GPSaveConverter by Fr33dan: https://github.com/Fr33dan/GPSaveConverter

## ORSE license

`osc/gvas.py` is a port of ORSE's GVAS reader (https://github.com/Microb4ek/OblivionRemastered-save-editor-ORSE).

```
MIT License

Copyright (c) 2026 ORSE contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
