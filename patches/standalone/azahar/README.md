# azahar patches

The patch series ArkOS builds its azahar libretro core with: christianhaitian/rk3566_core_builds
[`patches/azahar-patch-000…029`](https://github.com/christianhaitian/rk3566_core_builds/tree/e76af8133b07c4faf75c203e029a94531fc1420e/patches)
at e76af8133b07c4faf75c203e029a94531fc1420e, applied in order to azahar-emu/azahar 2126.2 by
`scripts/azahar.sh` there. spruceOS ships that build (`RetroArch/.retroarch/cores64/azahar_libretro.so`).

27 files are byte-identical to the originals. 022, 024 and 025 are re-cut: after patch 000 one context line differs,
so GNU patch applies them with fuzz, while `git apply` refuses them. Each re-cut file says so at the top. The series
applied here gives the same tree as ArkOS's `patch -Np1`, and the same shader cache key that the shipped core embeds
(`88af26b923ef56594d9a88f5ae5d9f05`).

## Authors

| patches | from |
|---|---|
| 000, 015, 019 | TheGammaSqueeze (GammaOS), azahar-nano: 000 is GammaOSNextDistribution-14 8d68e5ecaab, made on 2126.1.2 and rebased onto 2126.2 |
| 020 | TheGammaSqueeze's e62a0042457, adapted by the dArkOS RG52 Mini port |
| 021 | Wunk, upstream azahar 847d329ee |
| 022, 023, 024 | Wunk, upstream azahar d260a99e2, 4034f6c16, 7e77ca648 |
| 025 | M-1, upstream azahar 56d991979 |
| 026 | OpenSauce04, upstream azahar d433dfded |
| 009 | TheGammaSqueeze's three azahar-nano commits of 2026-10-20 after 8d68e5ecaab, carried by the dArkOS RG52 Mini port |
| 010 | upstream azahar 9ee6bc70f (SIMD texture codec), carried by the dArkOS RG52 Mini port |
| 001-008, 011-014, 016-018, 027-029 | the dArkOS RG52 Mini port (christianhaitian's rk3566_core_builds, with thanks there to TheGammaSqueeze and mamaich) |

## Licence

azahar is GPL-2.0-or-later (its `license.txt`). These patches change that code and are carried under the same
licence. Their headers have no licence lines of their own. rk3566_core_builds' own scripts are MIT (its
`LICENSE.md`).
