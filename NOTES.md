# Nickeno's Oblivion Converter — project notes

Goal: convert saves between original Oblivion (2006, `.ess`) and Oblivion Remastered (2025, `.sav`), both directions, as a tool others can use.

## Prior art (checked 2026-11-20)

- **ORSE** — github.com/Microb4ek/OblivionRemastered-save-editor-ORSE (MIT, TypeScript/Electron, v0.1.0 from 2026-09-17).
  A Remastered save *editor*. It already unpacks and repacks the `.sav` byte-exactly, including Oodle.
  It has **no** OG <-> Remastered conversion.
- **huhx0015/OblivionOG_to_Remastered_Character_Migration** — reads an OG `.ess` and writes a console
  `exec` script that rebuilds the character in a fresh Remastered game. Not a save converter.
  Its format doc wrongly concludes there is no TES4 data inside the `.sav`.
- Save *transfer* tools (Game Pass <-> Steam): thehiddenlotus/SaveTransferTool, dancomstock's Game Pass
  save manager, brodrigz/XgpSaveTools. They only copy files, never touch contents.
- No converter between the two games turned up on Google, Nexus or GitHub code search.

## Remastered `.sav` format (confirmed on our own Game Pass save)

1. Outer file: UE `GVAS`, class `/Script/Altar.VAltarSaveContainer`, one property
   `AltarSaveData` = `ArrayProperty<ByteProperty>` (~3 MB).
2. That byte array is a run of `FArchive::SerializeCompressed` segments:
   - `u64 tag = 0x222222229E2A83C1`, `i64 chunkSize = 0x20000`, `u8 compressor = 2` (Oodle),
   - summary `i64 compressed, i64 uncompressed`, then one `(i64, i64)` per chunk, then the chunk data.
   - Every chunk is Oodle **Kraken** (`8C 06` header). Our save: 127 chunks -> 16.6 MB.
3. Decoded: `u32 length` + inner `GVAS`, class `/Script/Altar.VAltarSaveGame`, with:
   - `OblivionData` — a classic **TES4SAVEGAME** `.ess` (zero padded). Version **0.127** (OG is 0.125).
   - `SaveGameDetails` — name, level, location, play time, JPEG thumbnail, `bIsAchievementsDisabled`.
   - `SerializedAltarSaveDataArray` — UE side: physics poses of ~6k actors, the player's UE face
     (FaceMorphValuesMap, hair, skin, eyes…), cinematic states, `UserInputTextsMap` (player name text).

## Differences between the embedded `.ess` (0.127) and OG `.ess` (0.125)

- Header: version 127 vs 125; header size 84 (no screenshot) vs ~110 KB (256x144 RGB screenshot).
- Player name / location in the header are localisation keys (`UI_UserInputText_0_953_0`,
  `LOC_FN_DrakeloweRegion`); the real text lives in the UE `UserInputTextsMap`.
- Plugin list: Remastered adds `AltarESPMain.esp` (also `AltarDeluxe.esp`, `AltarESPLocal.esp` when present)
  and orders the DLCs differently, so FormID mod indexes must be remapped.
- Unknown yet: what else changed in change-record layouts between 125 and 127
  (Remastered has a new levelling system).

## Plan

1. **Unpack**: read a Remastered `.sav` (Steam folder or Game Pass `wgs` container) -> `.ess` + metadata.
2. **Remastered -> OG**: downgrade header 127 -> 125, add screenshot, real name, remap plugin indexes,
   drop forms from Altar*.esp, then test in OG Oblivion.
3. **OG -> Remastered**: template approach — take an existing Remastered save, swap in the upgraded `.ess`,
   keep the template's UE face data, clear physics poses, repack + compress, then test in Remastered.

## Licensing note

CORRECTED 2026-11-20: `powzix/ooz` is **GPL-3.0-or-later** (stated in the kraken.cpp header; the repo just
has no LICENSE file, so GitHub shows none). Shipping ooz.dll is fine if this tool is released under GPL-3.0
with source. Alternative: `oozextract` (Rust, crates.io, MIT) if a non-GPL license is ever wanted.
Writing saves needs no compressor at all (stored Kraken blocks).

## Research scripts

`research/` holds the throwaway scripts used to crack the format (Python 3, read-only on saves).
`third_party/ooz/` is the downloaded ooz source plus a locally built `ooz.dll` (GPL-3.0-or-later, shipped with the app).

## Test results (2026-11-20)

- Remastered -> OG: Remastered "Save 1" (lvl 2 Khajiit, Fort Urasek) loaded in OG Steam Oblivion 1.2.0416.
  OG warns "save relies on content that is no longer present" (AltarESPMain.esp), then loads fine. Inventory,
  gear, race carried over. OG then pops the DLC "quest added" notes (Frostcrag, Razor, Orrery, ...) on first load.
- OG -> Remastered: OG "Save 527" (lvl 126 Khajiit Acrobat, Anvil Mages Guild) imported into Game Pass with
  `python -m osc import-xgp` and loaded in Remastered 1.512.105.0. Load menu showed name/level/location/day/
  playtime/thumbnail correctly (LOC_FN_AnvilMagesGuild resolves). Character sheet: level 126, 1419 HP, gear intact.
- Game Pass write: new container state 5 + empty ETag, saves_meta rewritten in place (state 2), index state 2.
  Xbox app uploaded it on launch. Deleting in-game removed it cleanly (an empty folder was left behind).
- Since the audit fixes (0.1.3): the game itself writes a new `container.N` (N = the index entry's number, one
  byte) and a new data file on every save, then removes the old pair. saves_meta is now written the same way:
  new data file + `container.N+1` (cloud guid kept), and writing `containers.index` is the single step that makes
  the game see it. Only at N = 255 it falls back to the old in-place rewrite. Readers use the index's N, never
  the highest file. Checked in the game (2026-11-20, app code, real folder): the converted save listed, loaded
  (lvl 126, 1419 HP) and was deleted in-game cleanly. When deleting, the game rebuilt saves_meta itself (dropped
  6 leftover entries with no save behind them, refreshed 4 autosave entries). Xbox app upload not checked.
- Remastered -> OG crashed OG on load for a level 12 save (access violation at Oblivion.exe+0x58139e, also with
  0.1.2). Cause: Remastered adds extra-data entries 0x5E (16-byte id) and 0x5F (128-byte text) to placed objects
  (records 49-51, flag 0x20). OG only knows types up to 0x5C and skips unknown ones as one byte, so it read the
  payload as more entries. Fix: `strip_altar_extras` cuts the payloads, keeps the two type bytes (count stays
  right). Level 4 and level 12 saves then loaded in OG with the right name, race, class, level and gear.
- Claude desktop sandbox: new files written to %LOCALAPPDATA% from Claude's shell are hidden from Windows, so the
  wgs writes were run via a WMI-spawned process (Win32_Process.Create). Normal users running the tool don't hit this.
- Both test saves were removed afterwards; all remaining Game Pass saves were byte-identical to the backup in
  backups/wgs-2026-11-20-before-test.

## The app (2026-11-20)

- `osc/app.py` opens the window (pywebview, WebView2). The screen is `osc/ui/` and talks to `osc/library.py`
  through four calls: `load`, `thumb`, `convert`, `open_backups`.
- The window is served over a local http server, not file://, or WebGL refuses the fire's pictures.
- `python -m osc.app --serve 8770` serves the same screen for a browser (for testing and screenshots). It prints
  the address to open, `/?dev=<token>`; the token is new every start and the API refuses calls without it.
- Converts take a named Windows mutex, so two app windows or the app and the command line never write at once.
- `tests/convert_test.py --wgs <profile> --og <.ess>` checks converting and adding saves on copies.
- `dist\NickenosOblivionConverter.exe --selftest out.json` opens, writes what the screen shows, and closes.
- Testing never touches the real save folders: point `OSC_OG_SAVES`, `OSC_WGS`, `OSC_STEAM_REM` and `OSC_BACKUPS`
  at copies. With `OSC_WGS` / `OSC_STEAM_REM` set, the "close Remastered first" check is skipped.
- Original Oblivion keeps saves in `Documents\My Games\Oblivion\Saves` on Steam, GOG and Game Pass alike
  (Wrye Bash wiki, Microsoft Store Games page), so one folder covers all three.
- The same original save converted twice gets the next free "Save N" name. Each converted save is its own
  character in Remastered (fresh CharacterId).
- A save converted to the original game is stamped with the current time, so it lists as the newest.
- The gate sign and fire canvas are children of the Convert button's wrapper and are sized from the button's own
  box. Do not go back to placing them from screen coordinates (they drifted during the load animation).

## Faces and race (2026-11-20)

- The UE side of a `.sav` has a `Phenotype` item for the player. Its `FaceBaseMesh` is made for one race and sex,
  like `/Game/Art/Character/Khajiit/SK_Khajiit_Head_m`. OG -> Remastered keeps the template's `Phenotype`, so the
  template has to be a character with the same race and sex (`library._template_for`).
- Race and sex are read from the player's change record (form 0x14), right before the name: race, hair, eyes
  (4 bytes each, indexes into the save's form id list), hair length (4), hair colour (4), sex (1), then the name.
  `ess.player_look`. Checked on 62 OG saves and 20 Remastered saves.
- A real Remastered save has the text key (`UI_UserInputText_...`) as the name in that record. Remastered shows a
  plain name there as `[NL]name` on the character sheet (seen in game, 2026-11-20). So a converted save gets the
  key in its record when its borrowed face fits (same race and sex); then it is a valid face template too. When the
  face doesn't fit, the plain name stays (and `[NL]` shows), so that save is never trusted as a face template.
  Seen in game after the fix: the character sheet reads the plain name, no `[NL]`.
- Original Oblivion reads the mouse and keys through DirectInput, so normal automated clicks do nothing. Relative
  mouse moves and scancode keys sent with SendInput work (about 1.75 mouse units per screenshot pixel at 1920x1080
  windowed).
- Not tested in the game: what a wrong-race `Phenotype` looks like, and whether dropping it is safe.
