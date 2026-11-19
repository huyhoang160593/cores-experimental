#!/usr/bin/env python3
"""Pin the libretro cores a TwigUI-Next release writes onto spruce's card (docs/twigui-next.md).

Reads a TwigUI-Next checkout at a release commit (its twig package's install/emulators.json and each package's
package.mk) and that release's card cores (RetroArch/.retroarch/cores64 extracted from its twigUI_SDCARD.7z),
and writes one record per core: card hash, package, source pin and patches, and how it compares with spruceOS."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ANCHOR = "projects/twigUI/packages/twig/install/emulators.json"
CORES = "RetroArch/.retroarch/cores64"
FIELDS = ("PKG_VERSION", "PKG_SHA256", "PKG_SITE", "PKG_URL", "PKG_GIT_CLONE_BRANCH", "PKG_LICENSE")


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


def package_dir(tree: list[str], name: str, device: str) -> str:
    """The package.mk TwigUI-Next's get_pkg_directory picks: device, then project (local), then packages/ (global)."""
    for roots in ((f"projects/twigUI/devices/{device}/packages/", "projects/twigUI/packages/"), ("packages/",)):
        found = [p[:-len("/package.mk")] for p in tree
                 if p.endswith(f"/{name}/package.mk") and p.startswith(roots)]
        if len(found) > 1:
            sys.exit(f"{name}: more than one package.mk: {found}")
        if found:
            return found[0]
    sys.exit(f"{name}: no package.mk")


def fields(text: str, name: str) -> dict:
    out = {"PKG_NAME": name}
    for line in text.splitlines():
        m = re.match(r'^(PKG_[A-Z0-9_]+)="([^"]*)"', line)
        if m and m.group(1) in FIELDS and m.group(1) not in out:
            out[m.group(1)] = m.group(2)
    for key in ("PKG_SITE", "PKG_URL"):
        for _ in range(3):  # ${PKG_SITE}/archive/${PKG_VERSION}.tar.gz and friends
            if key in out:
                out[key] = re.sub(r"\$\{?(PKG_[A-Z_]+)\}?", lambda m: out.get(m.group(1), m.group(0)), out[key])
    return {k: v for k, v in out.items() if k in FIELDS}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--twigui", required=True, help="TwigUI-Next checkout")
    ap.add_argument("--rev", required=True, help="release commit (e.g. the 1.2.0 tag's)")
    ap.add_argument("--release", required=True, help="release name, e.g. 1.2.0")
    ap.add_argument("--device", default="RK3326S")
    ap.add_argument("--cores", required=True, help="the card's RetroArch/.retroarch/cores64, extracted")
    ap.add_argument("--archive", required=True, help="'<name> <sha256> <size> <where>' of the card archive")
    ap.add_argument("--spruceos", required=True, help="spruceOS checkout")
    ap.add_argument("--spruce-rev", required=True, help="spruceOS commit to compare with")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    rev = git(a.twigui, "rev-parse", a.rev).strip()
    tree = git(a.twigui, "ls-tree", "-r", "--name-only", rev).split("\n")
    twig = fields(git(a.twigui, "show", f"{rev}:projects/twigUI/packages/twig/package.mk"), "twig")
    spruce_rev = git(a.spruceos, "rev-parse", a.spruce_rev).strip()
    cores = {}
    for entry in json.loads(git(a.twigui, "show", f"{rev}:{ANCHOR}"))["emulators"]:
        for f in entry["files"]:
            if not f["src"].endswith("_libretro.so") or f["dest"].strip("/") != CORES:
                continue
            path = f"{CORES}/{f['src']}"
            card = Path(a.cores) / f["src"]
            pkg = package_dir(tree, entry["package"], a.device)
            patches = [line.split(None, 3)[2:] for line in
                       git(a.twigui, "ls-tree", "-r", rev, "--", f"{pkg}/patches").splitlines()]
            try:
                shipped = hashlib.sha256(subprocess.run(["git", "-C", a.spruceos, "cat-file", "blob", f"{spruce_rev}:{path}"],
                                                        capture_output=True, check=True).stdout).hexdigest()
            except subprocess.CalledProcessError:
                shipped = None
            digest = sha256(card) if card.is_file() else None
            cores[path] = {
                "sha256": digest, "size": card.stat().st_size if card.is_file() else None,
                "package": entry["package"], "package_dir": pkg,
                **{k.removeprefix("PKG_").lower(): v for k, v in
                   fields(git(a.twigui, "show", f"{rev}:{pkg}/package.mk"), entry["package"]).items()},
                "patches": {p[1]: p[0][:12] for p in patches if len(p) == 2},
                "spruceos": "absent" if shipped is None else ("same" if shipped == digest else "differs"),
            }
    others = sorted(p.name for p in Path(a.cores).iterdir() if f"{CORES}/{p.name}" not in cores)
    name, digest, size, where = a.archive.split(" ", 3)
    record = {
        "note": "Generated by scripts/twigui_pins.py (docs/twigui-next.md); regenerate, don't edit.",
        "twigui_next": {"url": "https://github.com/spruceUI/twigUI-next", "release": a.release, "commit": rev,
                        "device": a.device, "spruceos_pin": twig.get("PKG_VERSION")},
        "card_archive": {"name": name, "sha256": digest, "size": int(size), "in": where},
        "compared_with": {"spruceos": spruce_rev},
        "cores": dict(sorted(cores.items())),
        "card_cores_not_from_twigui_next": others,
    }
    Path(a.out).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    missing = [p for p, c in cores.items() if c["sha256"] is None]
    print(f"{len(cores)} cores pinned ({len(missing)} not on the card), {len(others)} other card cores; "
          f"against spruceOS {spruce_rev[:9]}: "
          + ", ".join(f"{k} {sum(c['spruceos'] == k for c in cores.values())}" for k in ("same", "differs", "absent")))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
