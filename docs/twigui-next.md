# TwigUI-Next's cores on spruce's card

TwigUI-Next (spruceUI/twigUI-next, the GKD Pixel 2's base) builds its own libretro cores and writes them over spruce's
when it assembles a card: its `twig` package unpacks a pinned spruceOS (`PKG_VERSION`) and copies the files its
`install/emulators.json` lists from each package's build. A Pixel 2 runs those cores until a spruce update writes
spruce's copies over them.

The `pixel2-twiguinext` wave (`manifests/waves/pixel2-twiguinext.json`, see [waves](waves.md)) pins the 84 files release 1.2.0 writes onto the card, 71 cores and 13 standalone files (binaries, DraStic's two libraries, PPSSPP's data), (twig-base 0d4954c435, device RK3326S, spruceOS
pin 04d2bdf97): for each card path, the sha256 and size in the release's `twigUI_SDCARD.7z`, the package and the
`package.mk` the build system picks (device, then project, then `packages/`), its source pin (`version` is a commit or
release, with `sha256` for a tarball), licence, and its patches by git blob. `spruceos` compares the card file with
spruceOS `7592638d0`: none is the same file (68 differ; `pokedaisy`, `sameduck` and `tgbdual` are not in spruceOS).
`gloopy` and `mkxp-z` on that card are spruce's own.

## Reproduced

| card path | how |
|---|---|
| `RetroArch/.retroarch/cores64/yabasanshiro_libretro.so` | byte for byte: B412, `scripts/build_mt yabasanshiro-lr` at 0d4954c435 with TwigUI-Next's toolchain on salusa (record `devices/builds/20261119-1042-twigui-next-mpv-yaba-repro`) |

The rest are pinned, not yet reproduced. They build with TwigUI-Next's own toolchain (GCC 15.2, glibc 2.41), not in an
image here, so reproducing them is a TwigUI-Next build (`scripts/build_mt <package>` at 0d4954c435, as B412 did, in a
copy of a TwigUI-Next build tree; B412's copy has since been removed).

## Regenerate

```
python3 scripts/waves.py twigui pixel2-twiguinext --twigui <twigUI-next checkout> --rev 0d4954c435 --release 1.2.0 \
  --card <twigUI_SDCARD.7z extracted: at least every path its install list names> \
  --archive "twigUI_SDCARD.7z <sha256> <size> <where it came from>" \
  --spruceos <spruceOS checkout> --spruce-rev 7592638d0 --base usr/bin/mpv:<sha256>:mpv
```

`--verified PATH=EVIDENCE` records a reproduction (evidence starting "byte for byte" makes it `reproduced`, anything
else `near`); it carries over to later runs while the file's sha256 stays the same.

The card archive is inside the release asset `twigUI_V1.2.0_update.tar.gz` (sha256 c74fa1ca…), as
`twigUI_SDCARD.7z` (sha256 a4a5717a…, 517,579,089 bytes).
