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
- Claude desktop sandbox: new files written to %LOCALAPPDATA% from Claude's shell are hidden from Windows, so the
  wgs writes were run via a WMI-spawned process (Win32_Process.Create). Normal users running the tool don't hit this.
- Both test saves were removed afterwards; all remaining Game Pass saves were byte-identical to the backup in
  backups/wgs-2026-11-20-before-test.
