# Waves of cores

cores-experimental tracks four waves of cores, plus everything else it pins. Each wave is one generated manifest in
`manifests/waves/`, written by `scripts/waves.py`. The catalog and `standalone-builds.json` hold the recipes
(how a core builds); a wave says which files it means and which recipe and commit, if any, reproduces each one.

| wave | defined by | manifest |
|---|---|---|
| `pixel2-twiguinext` | a TwigUI-Next release's card (the cores and standalones it writes over spruce's) and the base-image files spruce uses | `waves/pixel2-twiguinext.json` ([details](twigui-next.md)) |
| `spruce-nightly` | spruceOS `Development` at the inventory's commit | `waves/spruce-nightly.json` |
| `spruce-stable46` | spruceOS `v4.6.0` | `waves/spruce-stable46.json` |
| `edge` | each recipe source's newest release tag (`vN.N…` or `rN`) when its commit is newer than the recipe's pin, else the requested branch's tip | `waves/edge.json` |
| `custom` | the recipes no other wave uses: experiments, variants, candidates | `waves/custom.json` |

## Entries

A file entry (spruce and TwigUI-Next waves) has the file's `sha256` and a `status`:

- spruce waves: the coverage status (`reproduces`, `recipe`, `no recipe`, …, see [inventory](inventory.md)), the
  `recipes` that build the path, the device `families` that load or run it, `spare: true` for a shipped core no
  device loads from that folder, and for a reproduced file its `pin` (recipe, source URL and commit). A
  `not shipped` core entry is a folder a device loads it from where spruce ships nothing;
- `pixel2-twiguinext`: `pinned` (the package and its source pin are recorded), `reproduced` (rebuilt byte for byte,
  `verified` says how) or `near` (rebuilt, with a known difference in `verified`).

A manifest is generated: regenerate it rather than editing it. The hand-kept facts of an entry (`pin`, `evidence`,
`verified`) carry over to the next run while the entry's sha256 stays the same.

## Regenerate

```
python3 scripts/waves.py spruce spruce-nightly --spruceos <spruceOS> --rev <Development commit>
python3 scripts/waves.py spruce spruce-stable46 --spruceos <spruceOS> --rev v4.6.0
python3 scripts/waves.py twigui pixel2-twiguinext ...        # docs/twigui-next.md
python3 scripts/waves.py edge                                # git ls-remote per source, GitHub API for dates
python3 scripts/waves.py custom                              # after the others
python3 scripts/waves.py summary
```

## Notes

- The spruce waves come from the emulator inventory, which follows spruce's emulator menus and the folder each
  device loads from. Every shipped core is in them, spare or not, so a recipe that builds a spare file is not
  `custom`; apps such as vTree are in no wave, so their recipes are. At d7ce3dc52, spruce-nightly has 44 spare
  cores (43 that no menu offers, plus `cores64/mupen64plus`: N64 offers `mupen64plus` only on 32-bit lists), and 7
  folder gaps: `cores/` flycast2021 and flycast2024 (the 32-bit RA Build on the Flip, the XX and dArkMoss), the
  Mini's puae, km_puae_xtreme_amped and km_mame2003_xtreme, and freej2me_plus in both folders.
- spruce-nightly's 49 GCC 9.4 cores without a reproducing recipe carry a hand-kept `pin`
  (`confidence`: `unambiguous`, `likely` or `ambiguous`; `verified: false`) and its `evidence`: 37 came with
  spruceOS 327c258ee (built 2025-05-05/06), one with 4a96070f8, the rest with their 2026 imports. A build at the pin
  that matches would make them `reproduces`.
