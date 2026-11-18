# Emulator inventory and coverage

Which emulators spruceOS offers, which files it ships for them, and which of those files a recipe here builds.

| file | what |
|---|---|
| [`manifests/emulator-inventory.json`](../manifests/emulator-inventory.json) | generated from a spruceOS commit: every system's `default_emulator` and `Emulator*` option lists (with their device lists), and the sha256 of every core in `RetroArch/.retroarch/cores{,64}/` and every standalone file the names map points at |
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
- `closed_source`, `not_emulator` or `unresolved`: why there is nothing to build, with the reason.

An optional `note` is shown in the report.

## Statuses

| status | meaning |
|---|---|
| reproduces | a recipe records this file's exact sha256 as shipped. The card path may be one spruceOS has since renamed; the report then names it |
| recipe | a recipe here builds this file, but no recorded sha256 matches what ships |
| no recipe | the file ships, and nothing here builds it |
| not shipped | a menu offers it, but the file is not in the tree |
| closed source, not an emulator, unresolved | from the names map |

The Check workflow appends the report to its run summary. It is not a gate: some gaps are known and listed in the report.
Regenerate the inventory when spruceOS's emulators change, and commit it with the recipes that close the gaps.
