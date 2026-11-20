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

## Status

At CE `70c1089` (2026-11-20), from `waves.py summary`:

| wave | files | reproduces | recipe | not shipped | no recipe | spare |
|---|---|---|---|---|---|---|
| `spruce-nightly` (spruceOS `d7ce3dc52`) | 245 | 98 | 134 | 10 | 3 | 44 |
| `spruce-stable46` (`v4.6.0`) | 233 | 74 | 144 | 10 | 5 | 42 |

`recipe` counts the files a recipe builds but does not reproduce yet. `pixel2-twiguinext`: 85 files, 83 pinned,
one reproduced and one near. `edge`: 172 recipes (143 at a branch tip, 29 at a tag). `custom`: 21 recipes.

## Notes

- The spruce waves come from the emulator inventory, which follows spruce's emulator menus and the folder each
  device loads from. Every shipped core is in them, spare or not, so a recipe that builds a spare file is not
  `custom`; apps such as vTree are in no wave, so their recipes are. At d7ce3dc52, spruce-nightly has 44 spare
  cores (43 that no menu offers, plus `cores64/mupen64plus`: N64 offers `mupen64plus` only on 32-bit lists), and 7
  folder gaps: `cores/` flycast2021 and flycast2024 (the 32-bit RA Build on the Flip, the XX and dArkMoss), the
  Mini's puae, km_puae_xtreme_amped and km_mame2003_xtreme, and freej2me_plus in both folders.
- A core without a reproducing recipe carries a hand-kept `pin` (`confidence`: `unambiguous`, `likely` or
  `ambiguous`; `verified`) and its `evidence`. A build at the pin that matches makes it `reproduces`. On 11-19
  spruce-nightly had 49 such GCC 9.4 cores, 37 of them from spruceOS 327c258ee (built 2025-05-05/06). Nine pins
  are left: bluemsx, px68k (verified code, build ID differs) and km_ludicrousn64_2k22_xtreme_amped of
  cobaltgit's builds, the two Flycast-campaign cores, armsnes (`likely`), and the three vendor files below.
- The 2025-05-06 batch (41 cores) was cobaltgit's local libretro-super build, at `/root/libretro-super`, with
  Ubuntu's GCC 9.4 and exported `-mcpu=cortex-a53 -fomit-frame-pointer`, plus `-ffast-math` for some cores.
  Their short hashes are 8 characters in big repos (full clones), and vice and puae2021 embed their build time.
  At those flags (flag fan-out rounds 1-4, 11-19/20), eight cores have spruce's code and data sections. Such an
  entry's `verified` says so, and its status stays `recipe`. CE's catalog recipes keep their portable flags.
- The build was native: GNU ld's build ID covers `.strtab`'s size, and the native linker's `crti.o`/`crtn.o` paths are
  20 characters shorter than the cross ones. With CFLAGS/CXXFLAGS `-mcpu=cortex-a53 -fomit-frame-pointer
  -ffast-math` exported, which a Makefile adds to compiles but rarely to the link (so `crtfastmath.o` stays out),
  and a wrapper that adds `-B` pointing at the native paths, CE's cross toolchain reproduces 22 cores byte for byte
  (round 7). Their `<core>-arm64-20250506` recipes extend `batch1-arm64-20250506`, which carries that build; six more
  (a5200, nestopia, prosystem, quicknes, snes9x, tyrquake) match with the Makefiles' own `" <hash>"` version strings
  and tyrquake's embedded build time, 28 in all. crocods (29) links its sources in the builder filesystem's
  `$(wildcard)` order, recovered from spruce's file (function sizes place code objects, data offsets and a linker map
  the data-only ones, `.dynstr` the rest) and listed explicitly by a patch; genesis_plus_gx and mednafen_supergrafx
  (31) the same way. chailove (32) is C++, where an inline function stays in whichever object links first: its order
  came from simulating ld's placement (cold, startup, then main code), checked on CE's own build and linker map, until
  the function sizes equalled spruce's; fbneo and fbalpha2012 (35) the same way. px68k differs
  only in its build ID (round 7), so its pin is recorded as verified code and its recipe lists the build ID in
  `shipped.differs`. vice_xvic (33) was built after vice_x64 in the same tree with libretro-super's clean skipped
  (`NOCLEAN=1`), so x64's stale objects link in; its recipe repeats both builds.
- Files that Cores-spruce workflows built are reproduced by standalone recipes in CE's copies of its images
  (`cores-spruce-arm64`, `cores-spruce-armhf`), repeating the run's commands. Two traps: CE's build script clears
  the image's `CMAKE_TOOLCHAIN_FILE`, which CMake cores need back; and a workflow that builds a runner-owned
  checkout as root gets no git hash (git refuses the checkout), which `chown -R 1001:1001 <source>` reproduces.
- The nightly files that had no recipe (traced with the Emu Inventory session on 11-19 and 11-20) carry their
  provenance as `evidence` (and a source `pin` where one is known). These now reproduce byte for byte: `OpenBOR_mod`
  and `OpenBOR_new` (steward-fu's A30 ports), advmame and `OpenBOR_64_mod` (wakeboxer's CI builds, in their builder
  images), and `cores64/uae4arm` (Lakka v4.x's RPi3-Composite build, rebuilt with Lakka's own build system). Three
  are vendor binaries whose toolchain is not published, so they stay `no recipe`: Miyoo's `OpenBOR_Flip` and A30
  `cores/mupen64plus`, and TrimUI's `cores64/mupen64plus` (spare).
- Parked, recipe kept: mkxp-z (PR #255's CI) has the same code and ZIPs but differs in about 300 KB of unnamed
  .rodata. GameTank's arm64 core differs too: in CE's container zig adds outline atomics and all of compiler-rt.
  Its armhf core matches.
- The 15 third-party core files with a catalog recipe that does not reproduce them carry their provenance too
  (Flycast campaign builds, christianhaitian and Onion prebuilts, KMFDManic's builds, private LLVM builds). One is a
  risk on the device: `cores64/np2kai_libretro.so` needs `GLIBC_2.34`, above the TrimUI devices' 2.33.
- DSperate v3.4.0 reproduces on both builds of 504e78012: the A30 build at the v3.4.0 tag, and the aarch64 build
  at 109ecfd5 with upstream's PGO profile, in `standalone-dsperate-v2` ([standalone](standalone.md#status)).
