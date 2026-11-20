# Standalone emulators

Some emulators spruce ships are executables rather than libretro cores. Each
variant is a recipe in [`manifests/standalone-builds.json`](../manifests/standalone-builds.json):
pinned sources, a pinned toolchain image, the build commands, what it ships, and the
hashes of the files spruce ships today.

```bash
python3 scripts/cores.py standalone list
python3 scripts/cores.py standalone script flycast-standalone   # the build script
python3 scripts/cores.py standalone toolchain flycast-standalone  # its image and archive
python3 scripts/cores.py standalone build flycast-standalone --out results
```

On GitHub, the *Build a standalone* workflow builds one recipe by name. It stops
straight away if the recipe's image archive is not on the `toolchains` release.

A build leaves the shipped files in `results/<name>/dist/`, laid out as the
recipe's `output.spruce` map puts them on the card. Next to `dist/` are the build
script, `build.log`, `elf.tsv` (every shipped ELF's SONAME and NEEDED entries) and
`record.json`.

## Recipe fields

| field | meaning |
|---|---|
| `extends` | start from another recipe's fields; any top-level key given here replaces the parent's whole |
| `abstract` | a base for `extends` only, never built |
| `description` | which emulator, version and devices |
| `source` | repository `url`, full `commit`, its `tree` (checked after checkout), `requested_ref`, `submodules: true` to fetch them, and `path` to check it out somewhere other than `/src` (some builds embed their paths) |
| `extra_sources` | more repositories, the same fields plus an absolute `path` to check out into |
| `downloads` | files fetched at build time: `url`, `sha256` (checked before use) and an absolute `path` |
| `patches` | `{"diff": "patches/standalone/..."}`, applied with `git apply` (which fails if the diff no longer applies); `{"script": ...}`, run with Python; or `{"mail": ..., "committer": "Name <email>", "commit": ...}`, `git format-patch` mails applied with `git am` as that committer at the mails' dates, which recreates their commits: `HEAD` must then be `commit`. `dir` picks the tree (default `/src`) |
| `toolchain` | the image in `manifests/toolchains.json` |
| `source_date_epoch` | fixed build date, so the output does not depend on when it was built |
| `env` | variables exported before the build |
| `cmake` | `target`, `cross_defines` and `defines` for an arm64 CMake build of one target |
| `steps` | shell commands instead of `cmake`, run in `/src` with `$CROSS` (the toolchain's target triplet), `$SOURCE`, `$BUILD_DIR` and `$DIST` set |
| `output.files` | what ships: `from` (a path in the container), `to` (under `dist/`), `strip` (`-s` or `--strip-unneeded`), `mode`, or `dir: true` to copy a directory |
| `output.spruce` | where `dist/` paths go on the card: a key ending in `/` maps a folder, and a file's own key wins over its folder's |
| `needed` | `device`: libraries the target devices provide; `forbidden`: libraries no shipped ELF may need (some devices lack them, or they must be opened at run time) |
| `shipped` | the spruceOS commit and the sha256 of each file spruce ships, to compare a build with (`match`, `differs` or `missing` in `record.json`). `unverified: true` until a build has matched them: coverage then counts the files as `recipe`, not `reproduces`. `differs` names files spruce ships that the build is known not to reproduce, with the reason: compared as `differs, as known`, never counted as reproduced |

Python patch scripts from the spruceUI wrapper repositories are kept as diffs,
generated once against the pinned source: a script that no longer matches does
nothing and still succeeds, while a diff that no longer applies stops the build.

## What passes

There is no load test: a standalone emulator needs a display. A build passes when
every output exists and every library a shipped ELF needs is either on the
`device` list or shipped by the build itself, and nothing is `forbidden`. SDL2 is
never shipped: each device's SDL2 carries its own video driver. Whether the bytes
match what spruce ships is recorded, not required.

## Images

Each recipe builds in the environment its spruceUI wrapper repository used, rebuilt
from pinned parts (`Dockerfile.standalone.<name>`, loaded by `manifests/toolchains.json`):

| image | used by | built on |
|---|---|---|
| `arm64-standalone` (v2) | `flycast-standalone`, `flycast-standalone-t3-lto`, `yabasanshiro-standalone`, `mupen64plus-standalone` | the arm64 image, with OpenSSL, curl and SDL2 built in (v1); v2 adds Arm's GNU Toolchain 10.3-2021.07 at `/opt/arm-gnu-10.3`, focal's arm64 boost, freetype and EGL, and a link-only SDL2 2.28.5 and SDL2_ttf 2.0.15 in `/opt/standalone-deps-arm64` ([Saturn and N64](#saturn-and-n64-the-way-flycast-builds)) |
| `standalone-vtree`, `-pcsx_rearmed`, `-moonlight`, `-gl4es`, `-ppsspp`, `-mupen64plus`, `-scummvm` | the 64-bit build of that emulator (`gl4es`: BigPEmu; `ppsspp`: H700) | the pinned arm64 base plus the wrapper's package list |
| `standalone-dsperate`, `standalone-yabasanshiro` | `dsperate-arm64`, `yabasanshiro-arm64` | the same, plus the Kitware CMake release the wrapper's build used |
| `standalone-armhf` | every `-a30` recipe | the pinned armhf base (the A30 GCC 13.2 toolchain and its glibc 2.23 sysroot) plus the tools the wrappers' `Dockerfile.a30` install |
| `standalone-flip` | `ppsspp-flip`, `ppsspp-darkmoss3566`, `ppsspp-darkmoss3326` | Debian bookworm (by digest) with steward-fu's Flip toolchain (GCC 13.3) |
| `standalone-trimui` | `ppsspp-trimui` | the arm64 base's GCC 9.4 over Linaro 7.5's glibc and TrimUI's tg5040 SDK |
| `standalone-tsps` | `ppsspp-smartpros` | the compiler and sysroot of TrimUI's tg5050 SDK (GCC 10.3) |
| `standalone-yabasanshiro-pgo` | `yabasanshiro-arm64-pgo`, `yabasanshiro-libretro`, `flycast-libretro-t3` | `standalone-yabasanshiro` plus Arm's GNU Toolchain 10.3-2021.07, a generic sysroot (its glibc 2.33, Khronos GLES headers, a stub libGLESv2) and the two builds' PGO profiles ([Saturn](#saturn-builds-spruceos-455)) |
| `standalone-mini` | `pcsx_rearmed-mini`, `scummvm-mini` | the armhf base (Ubuntu 24.04) with steward-fu's Onion toolchain (GCC 8.3, glibc 2.28) |
| `standalone-miyoomini` | `vtree-mini` | `aemiii91/miyoomini-toolchain`, by the digest its `latest` tag has had since 2026-01-20 |
| `standalone-azahar` | `azahar-libretro` | ArkOS's Debian trixie build chroot as an amd64 cross toolchain: the dated image and snapshot.debian.org of 2026-10-27, clang 19, and trixie's arm64 glibc, libstdc++ and binutils |
| `standalone-xroar` | `xroar` | native arm64 Debian buster, run under qemu: the dated `buster-20240612` image and `snapshot.debian.org` of that day, with buster's own gcc-8 8.3.0-6, which the binary's banner names |
| `standalone-gvu-arm64`, `-a30` | `gvu-arm64`, `gvu-a30` | Sundownersport/GVU's GHCR builder images (`gvu-builder-brick`, `gvu-builder-a30`, created 2026-04-11), which its workflow says can no longer be rebuilt: their `debian:bullseye-20260406` base by digest and their apt install from `snapshot.debian.org` at 2026-04-11 19:00 UTC (GCC 10.2.1-6cross1, binutils 2.35.2) |
| `standalone-mupen64plus-pow2` | `mupen64plus-pow2` | plain focal, with `gcc-10-aarch64-linux-gnu` (the `gcc-10-cross` source package, focal `6ubuntu6`) instead of the default gcc-9 cross: the shipped binary's GCC banner and its statically linked libgcc's build path both name that package |
| `cores-spruce-arm64`, `-armhf` | `pokedaisy-*` | not rebuilt: Cores-spruce's own core images (its `build-docker.yml` run 36087575366 at 871d60759, 2026-09-25; Ubuntu 20.04 with the GCC 9.4 aarch64 cross, and the A30 buildroot GCC 13.2), copied from its release and retagged, because its pokedaisy builds ran in them |

A toolchain with a `platform` (`standalone-xroar`: `linux/arm64`) is an image for another architecture: Build a
standalone registers qemu for it first, and the build runs it with `docker run --platform`.

The arm64 base is Ubuntu 20.04, whose archive no longer changes, so a package list
pins its versions. Libraries a wrapper built from source inside its image are built
by the recipe instead, from pinned sources or checked downloads.

## Reproducing a wrapper's build

- **Paths.** Build in the wrapper's paths: `__FILE__`, RUNPATH and install
  prefixes end up in binaries.
- **Build times.** A file that embeds `__DATE__ __TIME__` needs the original time as
  `source_date_epoch`. When two files embed different times (pcsx_rearmed's
  `main.c` and `menu.c`, ScummVM's `base/version.cpp` and
  `engines/bagel/spacebar/master_win.cpp`), the recipe builds at the earlier one,
  deletes the later object and runs `make` again at the later time.
- **Revisions.** `git config core.abbrev N` keeps an embedded `git describe` hash
  at the length the wrapper's shallow clone produced.
- **autoconf.** On a build host where qemu runs foreign binaries (`binfmt_misc`),
  a `configure` given only `--host` runs its target test programs, decides it is
  not cross-compiling and configures differently. Recipes always pass `--build`.
- **Link order.** Ubuntu 20.04's make 4.2.1 does not sort the glob in ScummVM's
  `-include engines/*/module.mk`, so the detection objects link in whatever order
  the build host's filesystem lists `engines/`. `scummvm-arm64` pins the order the
  wrapper's runner had (`arm64-1-detection-order.patch`); make 4.3 (Ubuntu 24.04)
  sorts it.
- **Which run shipped.** A wrapper's latest release asset is not always what spruce
  ships: spruceOS's import commit dates the run it took. spruce's 64-bit
  mupen64plus mixes two runs, so it takes two recipes.
- **The A30 toolchain's `python3`** comes first on that image's PATH and has no SSL
  module; downloads use the system one.
- **PGO builds** need the compiler at the path their training build used: GCC
  resolves a symlinked install to its real path, and header paths go into the
  profile's function ids, so a different path matches the profile differently
  and changes inlining and LTO partitioning. `standalone-yabasanshiro-pgo` keeps
  the compiler at both paths its two builds were trained with.

## Status

Built against spruceOS `73bb91a19` (2026-10-11); "match" is byte for byte.

| recipe | ships | result |
|---|---|---|
| `flycast-standalone` | `Emu/DC/flycast`, `lib64/` | 3 of 4 match; `libcrypto.so.1.1` differs only in OpenSSL's build date |
| `flycast-standalone-t3-lto` | `Emu/DC/flycast`, `lib64/` of spruceOS `e6bcaae8c` (4.5.5, Development) | the same: 3 of 4 match |
| `yabasanshiro-standalone` | would replace `Emu/SATURN/yabasanshiro`, `lib64/` | built (2026-10-16); `lib64/` matches what spruce ships, the executable is a new build |
| `mupen64plus-standalone` | would replace all of `Emu/N64/mupen64plus/` | built (2026-10-16); a new build, not shipped yet |
| `flycast-libretro-t3` | `RetroArch/.retroarch/cores64/flycast_libretro.so` of spruceOS `d3f48c1cf` (4.5.5, Development) | match |
| `vtree-arm64`, `vtree-a30`, `vtree-mini` | `App/FileManagement/vtree.*`, `lib-A30/` | match |
| `azahar-libretro` | `RetroArch/.retroarch/cores64/azahar_libretro.so` of spruceOS `7592638d0` | match (run 44416076138) |
| `pcsx_rearmed-arm64`, `-a30`, `-mini` | `Emu/PS/pcsx_64`, `pcsx_a30`, `pcsx_mini`, the `libSDL-1.2.so.0` copies | match |
| `moonlight` | `App/Moonlight/.../moonlight` and 32 libraries | match |
| `bigpemu` | `Emu/JAGUAR/bigpemu/` (134 files, gl4es included) | match |
| `dsperate-arm64`, `dsperate-a30` | `Emu/NDS/dsperate`, `dsperate.a30` | match |
| `ppsspp-h700`, `-a30`, `-trimui`, `-smartpros` | `Emu/PSP/PPSSPPSDL_*` | match |
| `ppsspp-flip`, `-darkmoss3566`, `-darkmoss3326` | `Emu/PSP/PPSSPPSDL_Flip` (Vulkan), `_dArkMoss3566`, `_dArkMoss3326` of spruceOS `7592638d0` | match (runs 44403715782, 44403753952, 44403735142) |
| `yabasanshiro-arm64` | `Emu/SATURN/yabasanshiro`, `lib64/` | match |
| `yabasanshiro-arm64-pgo` | `Emu/SATURN/yabasanshiro`, `lib64/` of spruceOS `fcd5aca3d` (4.5.5, Development) | `lib64/` matches; the executable matched as the local research build, but differs on GitHub's runners (run 44444954188) |
| `yabasanshiro-libretro` | `RetroArch/.retroarch/cores64/yabasanshiro_generic_libretro.so` of spruceOS `fcd5aca3d` (4.5.5, Development) | match |
| `mupen64plus-arm64-gliden64-ovl` | `Emu/N64/mupen64plus/mupen64plus-video-GLideN64.so` of spruceOS `f21a6faa5` (4.5.5, Development) | match |
| `mupen64plus-arm64-20260404`, `mupen64plus-arm64` | `Emu/N64/mupen64plus/`: frontend, core, audio, input and RSP plugins from the first, video plugins and overlay settings from the second | match |
| `mupen64plus-a30` | `Emu/N64/mupen64plus-a30/` | match |
| `scummvm-a30`, `scummvm-mini` | `Emu/SCUMMVM/scummvm.a30`, `scummvm.mini` and its 96 plugins (inside spruceOS's 7z files), `liba30/`, `fixjoy`, `libmini/libfluidlite.so` | match |
| `scummvm-arm64` | `Emu/SCUMMVM/scummvm.64` (inside spruceOS's 7z), 12 libraries of `lib/` | match |
| `gametank-arm64`, `gametank-a30` | `Emu/GAMETANK/gametank/GameTankEmulator`, `gametank-a30/GameTankEmulator` of spruceOS `7592638d0` | match (runs 44416840843, 44416866778) |
| `openbor-trimui` | `Emu/OPENBOR/OpenBOR_TrimUI` of spruceOS `7592638d0` | built (run 44431097991), differs: the shipped binary's compiler is TrimUI's Linaro GCC 7.5, not GCC 9.4 |
| `openbor-new` | `Emu/OPENBOR/OpenBOR_new` of spruceOS `7592638d0` | built (run 44431121128), differs: same compiler, libraries and banner, but the shipped `.text` is 115 KB larger and has no RPATH, so the vendor's flags differ |
| `xroar` | `Emu/COCO/xroar` of spruceOS `7592638d0` | built (run 44434199145), differs: same modules, NEEDED list and section sizes, but Debian's SDL2 links libpulse (and so libsndfile), so ld exports xroar's own `sf_*` compat functions and the code shifts; the original machine's SDL2 did not |
| `gvu-arm64`, `gvu-a30` | `Emu/MEDIA/bin64/gvu`, `bin32/gvu` of spruceOS `7592638d0` | match (runs 44440415230, 44440434774) |
| `pokedaisy-{arm64,armhf}-20261112`, `-20261113` | `RetroArch/.retroarch/cores{64,}/pokedaisy_{ds,gbc}` (11-12) and `pokedaisy_gba` (11-13) of spruceOS `7592638d0` | match, all six (runs 44571273959, 44571303318, 44571331513, 44571360523): Cores-spruce runs 43141364046 and 43467900814 at pokedaisy-lr 7af02b6, armGBA b1c4a69 / 4bd15f1, with the tree owned by the runner's uid as there |
| `yabasanshiro-libretro-trimui` | `RetroArch/.retroarch/cores64/yabasanshiro_a133p_libretro.so`, `yabasanshiro_libretro.so` of spruceOS `7592638d0` | differs, as known: TrimUI's own changes (no libchdr, no Musashi) are not published; NEEDED list and compiler match (run 44567232442) |
| `mupen64plus-pow2` | `Emu/N64/pow2/mupen64plus`, `data/` of spruceOS `7592638d0` | `data/` matches; the executable has the same code, data and build ID, and differs only in four linker veneer names (run 44447436936) |

Some files next to these in spruceOS come from elsewhere and are not compared:
ScummVM's `lib/` extras and seven of `libmini/`'s libraries, among others.

## Flycast v2.7

`flycast-standalone` is the `Emu/DC/flycast` spruce ships (Dreamcast, NAOMI and
Atomiswave on every 64-bit device). It builds in the `arm64-standalone` image
([`Dockerfile.arm64.standalone`](../Dockerfile.arm64.standalone)): the arm64 image
plus ALSA and udev headers, and OpenSSL 1.1.1w, curl 8.7.1 and SDL2 2.28.5 in
`/opt/flycast-standalone-deps-arm64`. It reproduces the shipped executable,
`libcurl.so.4` and `libssl.so.1.1` byte for byte. `libcrypto.so.1.1` differs only
in OpenSSL's embedded build date and the build ID derived from it (33 bytes):
spruce's copy comes from an earlier build of the same image recipe.

## Flycast with GCC 10.3 (spruceOS 4.5.5)

`flycast-standalone-t3-lto` is the `Emu/DC/flycast` spruceOS 4.5.5 ships: the same
source, CMake line and dependencies as `flycast-standalone`, compiled with Arm's GNU
Toolchain 10.3-2021.07 and `-O3 -flto=8` instead of Ubuntu 20.04's GCC 9.4. On the
lab boards it ran Sega Rally's demo 14.5 to 17.5 % faster than the GCC 9.4 build,
ahead of the same build without LTO and of GCC 13.3 (the Dreamcast benchmarks,
outside this repository). A compiler wrapper puts the flags last on every call and adds
what Ubuntu's cross GCC does by default (PIE, `--as-needed`), so the binary needs the
same libraries as before and glibc 2.30 at most. It was first built in the research
record `20261014-0002-flycast-sa-fanout` and reproduces it byte for byte.

`flycast-libretro-t3` is the `RetroArch/.retroarch/cores64/flycast_libretro.so`
spruceOS 4.5.5 ships, the Dreamcast, NAOMI and Atomiswave default on every 64-bit
device but the Pixel 2. It is Flycast v2.6 with GLES and Vulkan as before, built with
the same Arm toolchain at CMake's Release flags instead of Ubuntu 20.04's GCC 9.4,
and picked by the same benchmarks. It links that toolchain's glibc, so devices need
glibc 2.33. It was first built as `t3-rel` in the research record
`20261013-1817-flycast-fanout-A5` with TrimUI's tg5050 SDK, whose compiler and glibc
are Arm's. The recipe builds in `standalone-yabasanshiro-pgo`, which has them at the
SDK's paths and the same CMake 4.4.3, and reproduces that core byte for byte.

## Saturn and N64 the way Flycast builds

`yabasanshiro-standalone` and `mupen64plus-standalone` build the Saturn and N64
standalones the way Flycast's are built: in `arm64-standalone`, from sources and
patches in this repository, with Arm's GNU Toolchain 10.3-2021.07, the compiler the
shipped Flycast and Saturn builds use (the same wrapper as `flycast-standalone-t3-lto`,
over focal's arm64 packages). Neither needs its spruceUI wrapper repository; the
reproductions of what those repositories built stay as `yabasanshiro-arm64` and the
`mupen64plus-*` recipes.

- **`yabasanshiro-standalone`**: the source and patches of `yabasanshiro-arm64-pgo`
  (spruceOS 4.5.5), `-O3 -flto`, plus `json-local.patch`: nlohmann/json v3.2.0 is a
  pinned checkout instead of the GitHub zip the build downloaded unpinned. No PGO:
  that recipe's profiles were trained on its own build, so this one needs a new
  training run before it can match it. `lib64/` keeps the three focal libraries the
  wrapper bundled (libpng16, zlib, boost filesystem), byte for byte the files spruce
  ships.
- **`mupen64plus-standalone`**: the frontend, core and all six plugins from one set of
  sources (each Mupen64Plus repository at its 2026-09-11 master, GLideN64 `c8ef81c`),
  where spruce ships a mix of two builds. Patches 1-8: save and quit, the centred
  viewport, the overlay hooks and the 2026-10-15 GLideN64 fixes. The overlay menu's
  sources are in `patches/standalone/mupen64plus/overlay/` (mupen64plus-spruce
  `cbff82e`, which includes patch 9's fix). The wrapper's `-O3 -flto=auto`.

Both link SDL2 2.28.5 (the lowest any 64-bit device has) instead of focal's 2.0.10;
YabaSanshiro configures with the arm64 image's CMake, not Kitware's 4.4.3. Neither is
tested on devices yet. The A30 builds stay on their wrapper recipes. v2 still builds
both Flycast recipes byte for byte as v1 and `standalone-flycast-t3` did.

## Saturn builds (spruceOS 4.5.5)

spruceOS 4.5.5 (Development, `fcd5aca3d`, merged in #1873) ships two Saturn
builds picked by device benchmarks. Both were first built for those benchmarks, in
the research records `20261013-1113-yabasanshiro-rbgfix` and
`20261013-1351-saturn-sa-pgo-rbgfix` (outside this repository); these recipes
rebuild them.

- **`yabasanshiro-libretro`**: `RetroArch/.retroarch/cores64/yabasanshiro_generic_libretro.so`.
  libretro/yabause `f448097` plus two mails that recreate commit `892985a4`, so the
  core reports `v3.4.2 892985a`:
  - the GLES 3.1/3.2 entry points the libretro build declared but never
    resolved (the compute-shader and tessellation options called NULL);
  - the compute-shader rotation background (RBG): the window and CRAM buffers
    bound on every dispatch, which Mali and PowerVR drivers need or they drop the
    dispatch; a texture-fetch barrier and an orphaned VRAM map; `uint` literals
    in the 16bpp palette fetch.

  Then `dynarec-fix-nopragma.patch`: the AArch64 dynarec's templates kept
  values in caller-saved registers across memory-handler calls; it renames them
  and drops the 2020 `-O1` pragma that hid the bug. Built with Arm's GNU Toolchain
  10.3-2021.07 (GCC 10.3), `-O3 -flto` and PGO. The core catalog builds every core in its own
  image and takes no profile, so this build is a recipe here.
- **`yabasanshiro-arm64-pgo`**: `Emu/SATURN/yabasanshiro`. `yabasanshiro-arm64`
  plus the same dynarec fix and RBG fix for devMiyax's tree (whose `getTexture`
  already uses `GL_ALL_BARRIER_BITS`), and `bench-framelimit-env.patch`:
  `YB_FRAMELIMIT=1` switches the 60 Hz limiter off, and unset it limits as before.
  Built with the same GCC 10.3, `-O3 -flto=8` and PGO, against the image's focal
  arm64 packages; `cc-wrapper-t3.sh` adds what Ubuntu's cross GCC does by default
  (PIE, `--as-needed`), so the binary needs only the libraries the CI build needs.

**No vendor SDK.** Both were first built with the compiler from TrimUI's tg5050 SDK, and the core
also with its sysroot. That compiler is Arm's GNU Toolchain 10.3-2021.07, unmodified, and the
sysroot's C library is that toolchain's glibc 2.33, so the image takes the toolchain from Arm and
builds the core's sysroot from it, the Khronos GLES headers the core was compiled against, and a
stub `libGLESv2.so.2`.

**Profiles.** `toolchain-inputs/yabasanshiro-pgo/` holds gcov counters of the
emulator's own code (no game data), written by `-fprofile-generate` builds of the
same sources running Sega Rally from power-on to frame 1680 on four lab boards
(Smart Pro S, Brick Pro, two RG XX; the libretro set adds the Flip). Each recipe
sums its set with the toolchain's `gcov-tool` (`pgo-merge.sh`). GCC drops the
profile of a function whose code changed after training: `context_reset`,
`retro_run` and the RBG generator's `init` and `update` in the core, the RBG
generator's `init` and `update` in the standalone. The other
`-Wcoverage-mismatch` warnings are line shifts, whose profiles GCC still uses.

## Saturn on the Pixel 2: three cores

The Pixel 2's Saturn option (spruceOS 32e36c798, 2026-02-15) selects `cores64/yabasanshiro_libretro.so`, a file
three builds compete for:

| core | where it comes from | pin | here |
|---|---|---|---|
| spruce's card file (shipped) | TrimUI's own build (raymanfeng, Linaro GCC 7.5, tg5040 SDK), via tenlevels' Brick paks; the stripped copy of `yabasanshiro_a133p` | libretro/yabause 7513c8459 plus TrimUI's unpublished changes | `yabasanshiro-libretro-trimui`: builds, differs as known. It links TrimUI's PowerVR libraries and `libtmenu`, so it cannot load on the Pixel 2 |
| TwigUI-Next's card file | TwigUI-Next 1.2.0 (twig-base 0d4954c435) builds `yabasanshiro-lr` and writes it over spruce's: 5b669a8c…, GCC 15.2 | libretro/yabause 39535a6 with its `01-optimization.patch`, `FORCE_GLES=1` | built with TwigUI-Next's own toolchain, not here: B412 (salusa, 2026-11-19, `scripts/build_mt yabasanshiro-lr` at 0d4954c435) reproduced it byte for byte (record `devices/builds/20261119-1042-twigui-next-mpv-yaba-repro`) |
| recommended | spruce's generic core, on every other 64-bit device since 2026-10-13 | libretro/yabause f448097, T3 PGO | `yabasanshiro-libretro`: reproduces. On paper it fits the Pixel 2 (glibc 2.33 against 2.41, GLES 3.1 against Panfrost's, ARMv8.0-safe atomics); untested there |

## OpenBOR standalones (DCurrent and LNS)

`openbor-trimui` and `openbor-new` rebuild two of the three DCurrent/OpenBOR commits spruce
ships (`openbor_functions.sh` picks the binary). `OpenBOR_mod` and `OpenBOR_64_mod` are the
"LNS" engine that Final Fight LNS needs (below). No spruceUI wrapper repository for OpenBOR was
found, so the DCurrent build flags are inferred from the engine's `Makefile`
(`BUILD_LINUX_LE_arm`) and from each binary's NEEDED list.

- **The LNS engine.** Both banners say "OpenBOR v3.0 Build 6330 LNS v0.10g". That is
  [gonzalomvp/openbor](https://github.com/gonzalomvp/openbor), a DCurrent fork, branch
  `v6330-fflns` (its default), whose tip has been `4c8677c2` since 2024-01-07; it grew out of
  `v6330-fflns_v10g`. Its `version.sh` hardcodes `VERSION_BUILD "6330 LNS v0.10g"`, so the banner
  does not depend on the clone's depth. In its `Makefile`, `BUILD_OPENGL=0` still turns OpenGL
  on: the switches are tested with `ifdef`, which any non-empty value passes.
- **`OpenBOR_64_mod`** (arm64, since 0cd1a7fa2, PR #1537 "OpenBOR for fflns"). wakeboxer built it
  in [ljhmd0825/OpenBoR-spruce](https://github.com/ljhmd0825/OpenBoR-spruce) at `53ba4100`
  (`build_fflns.sh`, CI run 25722043280, 2026-05-12): a focal image with the GCC 9.4 aarch64
  cross and focal's arm64 SDL2, SDL2_gfx, Vorbis, libvpx 6 and libpng, his
  `patches/fflns/001-default-fflns-cfg.patch`, and `make BUILD_LINUX=1 BUILD_OPENGL=0
  BUILD_LOADGL=0 BUILD_AMD64=1 ARCHFLAGS="" NO_STRIP=1 SDKPATH=/usr
  LIBRARIES=/usr/lib/aarch64-linux-gnu`. The workflow never pushed its image, so
  `Dockerfile.standalone.openbor-fflns` rebuilds it from focal by digest; the script also copied
  the `libpng16.so.16` and `libz.so.1` that spruce ships in `lib64mod/`.
- **`openbor-lns-a30`** rebuilds `OpenBOR_mod` (armhf, compiled 2024-06-13 with the A30's
  Buildroot 2024.02.1 GCC 13.2, before spruce's public history) from the same commit. Who built
  it is not known, so the flags come from the binary: `BUILD_LINUX` with OpenGL, Vorbis and
  WebM off and Tremor on (its NEEDED list has `libvorbisidec`, `libSDL2_gfx` and no `libvpx`,
  and its strings no OpenGL loader), `LIBRARIES` empty (its RPATH is empty) and `ARCHFLAGS`
  cleared (`BUILD_LINUX` sets `-m64`). Whether it had `-fomit-frame-pointer` (`BUILD_AMD64`
  unset) is not known, so the recipe also builds `OpenBOR_mod-omitfp` for comparison.

- **No `OpenBOR_Flip` recipe.** It was built with the Flip's own RK3566 Buildroot SDK (GCC
  11.3.0, Buildroot 2021.11) and links Vorbis, libvpx 7 and libpng16. steward-fu's Flip
  sysroot in `standalone-flip` has none of those, so it cannot build here.
- **Version banners.** `engine/version.sh` writes `#define VERSION_BUILD "<n>"` from
  `git rev-list --count HEAD`. That gives b8303cc's shipped "Build 7144", so `openbor-trimui`
  runs it and checks the define. At b00efbc it would give 7141, not the shipped "v4.0 Build
  0", so `openbor-new` writes `version.h` by hand.
- **`openbor-trimui`.** The shipped RPATH
  `/home/raymanfeng/work/a133p/app/openbor/engine/../../../sdk//usr/lib` is the Makefile's
  `-Wl,-rpath,"$(SDKPATH)/usr/lib"`. The recipe builds at that path, with a copy of the
  sysroot three directories up. `CC` carries `--sysroot` for that copy (with its `lib/`), because
  the `libpthread.so` and `libc.so` scripts name absolute paths, which ld maps only inside the sysroot. The shipped binary was built with TrimUI's
  Linaro GCC 7.5, not this image's GCC 9.4, so it is not expected to match.
- **`openbor-new`.** Its NEEDED list (`libvorbisidec.so.1`, no `libvpx`) means `BUILD_TREMOR=1`
  without Vorbis or WebM. The binary says WebM playback is not supported, yet `sdl/video.h`
  includes webmlib's `yuv.h` either way, so the recipe keeps `source/webmlib` on the include
  path. It also drops the Makefile's `-Werror`, which GCC 13 trips on in `openbor.c`; warning
  flags do not change the code. The shipped binary has the image's compiler (Buildroot
  2024.02.1, GCC 13.2.0).
