# Source patches

A core's patches are listed in its catalog entry (`overlays`, see
[docs/catalog.md](../docs/catalog.md)) and applied in order after the source is
checked out. A patch that no longer applies fails the build. When a core moves
to a new commit, update any patch that stops applying, and delete it once
upstream has fixed the problem.

| core | patch | fixes | arch |
|------|-------|-------|------|
| dosbox_pure | `dosbox_pure/makefile-echo-and-sort.patch` | sorts its source list and prints each compile command | arm64, armhf |
| easyrpg | `easyrpg/liblcf-pinned-clone.patch` | pins the liblcf checkout its build clones | arm64, armhf |
| flycast | `flycast/lzma-hwcap2-guards.patch` | guards `HWCAP2_*` names missing from the A30 sysroot | armhf |
| flycast2021, flycast2024 | `sigsegv-handler-repair.patch` | resumes a SIGSEGV that was sent (`si_code <= 0`), not caused by a fault; stock v1.2/v2.4 die two seconds into content on TrimUI devices ([diagnosis](https://github.com/spruceUI/spruceOS/commit/c0d8676cb)) | arm64 |
| flycast2024 | `flycast2024/fog-r8-internalformat.patch` | backports upstream 130675aae (#1886): fog renders wrong on GLES3 | arm64 |
| km_ludicrousn64_2k22_xtreme_amped | `km_ludicrousn64_2k22_xtreme_amped/makefile-fcommon.patch` | builds with `-fcommon`: its C sources still define tentative globals in several files, which GCC 10+ rejects (armhf link) | arm64, armhf |
| km_ludicrousn64_2k22_xtreme_amped | `km_ludicrousn64_2k22_xtreme_amped/arm64-dynarec-build-fixes.patch` | the aarch64 dynarec as committed does not compile: restores a dropped `#endif`, flushes `ptr` (no separate RX mapping) and stores `reg` where a rename left `tr` | arm64, armhf |
| km_ludicrousn64_2k22_xtreme_amped | `km_ludicrousn64_2k22_xtreme_amped/shaderutils-include-string.patch` | adds the `#include <string>` GLideN64's ShaderUtils.h needs | arm64, armhf |
| km_parallel_n64_xtreme_amped_turbo | `makefile-fcommon.patch` | adds `-fcommon` (the fork predates GCC 10) | armhf |
| km_parallel_n64_xtreme_amped_turbo | `glide64-rdp-gspvertex-def.patch`, `rdp-gspvertex-extern.patch` | one definition of `_gSPVertex` | armhf |
| km_parallel_n64_xtreme_amped_turbo | `glsm-gldouble-typedef.patch` | restores the `GLdouble` typedef under GLES2 | armhf |
| km_parallel_n64_xtreme_amped_turbo | `parallel-al-stdexcept.patch` | adds a missing `<stdexcept>` include | armhf |
| mupen64plus_next | `mupen64plus_next/buffer-swap-mode.patch` | core option `mupen64plus-BufferSwapMode` for GLideN64's buffer swap mode; the default, OnVIUpdate, is the old fixed value | arm64 |
| squirreljme | `squirreljme/system-map-arm32-or.patch` | fixes a missing `OR` in its ARM32 CMake check | armhf |
| squirreljme | `decode-host-cc.patch`, `sourceize-host-cc.patch` | builds two build-time tools with the host compiler | armhf |
| swanstation | `swanstation/openbios-cmake-3.16.patch` | OpenBIOS builds with CMake 3.16 | arm64 |

The `*-sort-wildcard-sources.patch` files (chailove, crocods, fbalpha2012,
fbneo, fceumm, ffmpeg, genesis_plus_gx, genesis_plus_gx_wide, lowresnx,
mednafen_supergrafx, np2kai, puzzlescript, retro8, x1) sort the makefile's
source list, so the link order and therefore the output do not depend on file
system order.

`standalone/<name>/` holds what the [standalone recipes](../docs/standalone.md)
use (patches, toolchain files, helper scripts). A standalone build mounts this
folder at `/recipe/patches`. `standalone/batch1/` does the
opposite of the sort patches above: it lists each core's sources in the order
the 2025-05-06 builder's file system gave them, so the link reproduces spruce's
file ([how](../docs/waves.md#notes)). `standalone/mkxp-z/rezip.py` rewrites
the built ZIPs in the CI runner's entry order, times and owners.
