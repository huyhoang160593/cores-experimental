# Emulator inventory and coverage

Which emulators spruceOS offers, which files it ships for them, and which of those files a recipe here builds.

| file | what |
|---|---|
| [`manifests/emulator-inventory.json`](../manifests/emulator-inventory.json) | generated from a spruceOS commit: every platform (its `device_names()`, arch and whether it has a 32-bit RetroArch), every system's `default_emulator`, launcher, RA Build row and `Emulator*` option lists (with their device lists), and the sha256 of every core in `RetroArch/.retroarch/cores{,64}/` and every standalone file the names map points at |
| [`manifests/emulator-names.json`](../manifests/emulator-names.json) | kept by hand: what an option name stands for when it is not a shipped core's name |

```bash
python3 scripts/cores.py inventory --spruceos ~/spruceOS --rev origin/Development   # regenerate the inventory
python3 scripts/cores.py coverage            # markdown report; --json for the rows; --strict fails on gaps
```

## Names

An option name counts as a core when `RetroArch/.retroarch/cores{,64}/<name>_libretro.so` ships, after any trailing
`_libretro` or `-libretro` is dropped. Every other name needs an entry in `emulator-names.json`, read from spruceOS's
launcher scripts (`spruce/scripts/emu/`). An entry has one of these:

- `core`: the core it launches, for names such as `Flycast-libretro`;
- `paths`: the card paths of a standalone emulator's binaries. A file inside a `.7z` is written `archive!member`, and
  `inventory` hashes it with `7zz` or `7z`;
- `base_image`: the file comes with a device's base OS, not the card; the value names the base's package that
  builds it, which is its recipe;
- `blacklisted`: why cores-experimental must not build it, with its `paths`; `check` fails if any recipe builds one
  of them;
- `closed_source`, `not_emulator` or `unresolved`: why there is nothing to build, with the reason.

An optional `note` is shown in the report.

## Folders

A device loads a core from one folder: `cores/` (32-bit) when the device is armhf or runs its 32-bit RetroArch,
`cores64/` otherwise. `coverage` follows spruceOS's launcher (`set_emu_core_from_emu_json` in
`spruce/scripts/emu/lib/general_functions.sh`) for every platform, system and RA Build value the system's row
allows: it takes the `Emulator*` key the launcher reads on that device (or `default_emulator`), and the folder it
loads from. The RA Build only counts on a device with `DEVICE_HAS_32_BIT_RA=true` and in a system with a `raBuild`
row. So a core's rows are the folders some device loads it from, shipped or not, plus any shipped copy that no
device loads. Every row lists those device `families` (the last name `device_names()` prints).

- a core a device loads from a folder where it does not ship is `not shipped` at that path: a gap;
- a shipped core file that no device loads from its folder, under any name, is **spare**. The report counts spare
  files apart from the statuses, and lists them last. A shipped core that no menu offers at all gets a row too,
  with the note `no menu offers it`;
- a standalone's row lists the families that reach its option. Which binary each family then runs is decided in
  the launch scripts, and is not modelled.

`check` fails on what the model does not cover: a system launched by anything other than `standard_launch.sh`
(or `vulkan_launch.sh`, which sources it), a core inside an `Emu/<system>/` folder (it would win over the core
folder), or a platform with no `PLATFORM_ARCHITECTURE`. The model was checked against the Emu Inventory session's
analysis (`CFW/Spruce/docs/research/emulator-arch-inventory-20261111`) at spruceOS d7ce3dc52: the same 44 spare
files, and the same needed files.

## Statuses

| status | meaning |
|---|---|
| reproduces | a recipe records this file's exact sha256 as shipped, the record is not marked `unverified`, and the file is not in its `differs`. The card path may be one spruceOS has since renamed; the report then names it |
| recipe | a recipe here builds this file, but no recorded sha256 matches what ships |
| base image | the base OS of the devices that use it provides the file; the names map points at the base's recipe |
| no recipe | the file ships, and nothing here builds it |
| blacklisted | the file ships, but must not be rebuilt and shipped (for example a licence forbids redistributing it) |
| not shipped | a menu offers it, but the file is not in the tree; for a core, at the folder a device would load it from |
| closed source, not an emulator, unresolved | from the names map |

The Check workflow appends the report to its run summary. It is not a gate: some gaps are known and listed in the report.
Regenerate the inventory when spruceOS's emulators change, and commit it with the recipes that close the gaps.
