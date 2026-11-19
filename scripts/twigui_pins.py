#!/usr/bin/env python3
"""Pin the libretro cores a TwigUI-Next release writes onto spruce's card (docs/twigui-next.md).

Used by scripts/waves.py twigui, which writes the pixel2-twiguinext wave.

Reads a TwigUI-Next checkout at a release commit (its twig package's install/emulators.json and each package's
package.mk) and that release's card cores (RetroArch/.retroarch/cores64 extracted from its twigUI_SDCARD.7z),
and writes one record per core: card hash, package, source pin and patches, and how it compares with spruceOS."""
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


def tree_sha256(root: Path) -> tuple[str, int]:
    """A folder's fingerprint: sha256 over its sorted "relative path, file sha256" lines."""
    lines = sorted(f"{f.relative_to(root)} {sha256(f)}" for f in root.rglob("*") if f.is_file())
    return hashlib.sha256("\n".join(lines).encode()).hexdigest(), len(lines)


def kind_of(path: str, card: Path) -> str:
    if path.startswith(CORES + "/") and path.endswith("_libretro.so"):
        return "core"
    if card.is_dir():
        return "directory"
    with card.open("rb") as f:
        return "elf" if f.read(4) == b"\x7fELF" else "data"


def pins(twigui: str, rev: str, release: str, device: str, card_root: str, archive: str, spruceos: str,
         spruce_rev: str) -> dict:
    """The record for one release: where it came from, and one entry per file its card install writes."""
    rev = git(twigui, "rev-parse", rev).strip()
    tree = git(twigui, "ls-tree", "-r", "--name-only", rev).split("\n")
    twig = fields(git(twigui, "show", f"{rev}:projects/twigUI/packages/twig/package.mk"), "twig")
    spruce_rev = git(spruceos, "rev-parse", spruce_rev).strip()
    files = {}
    for entry in json.loads(git(twigui, "show", f"{rev}:{ANCHOR}"))["emulators"]:
        pkg = package_dir(tree, entry["package"], device)
        package = {k.removeprefix("PKG_").lower(): v for k, v in
                   fields(git(twigui, "show", f"{rev}:{pkg}/package.mk"), entry["package"]).items()}
        patches = [line.split(None, 3)[2:] for line in
                   git(twigui, "ls-tree", "-r", rev, "--", f"{pkg}/patches").splitlines()]
        for f in entry["files"]:
            if f["src"].endswith(".info"):
                continue
            # A folder (src ending in /) lands as the destination folder itself, as on the card.
            path = f["dest"].strip("/") if f["src"].endswith("/") else f"{f['dest'].strip('/')}/{f['src']}"
            card = Path(card_root) / path
            if not card.exists():
                sys.exit(f"not on the card: {path}")
            kind = kind_of(path, card)
            if kind == "directory":
                digest, count = tree_sha256(card)
                size, shipped = None, None
            else:
                digest, size, count = sha256(card), card.stat().st_size, None
                try:
                    shipped = hashlib.sha256(subprocess.run(["git", "-C", spruceos, "cat-file", "blob", f"{spruce_rev}:{path}"],
                                                            capture_output=True, check=True).stdout).hexdigest()
                except subprocess.CalledProcessError:
                    shipped = None
            files[path] = {
                "sha256": digest, "kind": kind, **({"size": size} if size is not None else {"files": count}),
                "package": entry["package"], "package_dir": pkg, **package,
                "patches": {p[1]: p[0][:12] for p in patches if len(p) == 2},
                "spruceos": "absent" if shipped is None else ("same" if shipped == digest else "differs"),
            }
    name, digest, size, where = archive.split(" ", 3)
    cores_dir = Path(card_root) / CORES
    return {
        "twigui_next": {"url": "https://github.com/spruceUI/twigUI-next", "release": release, "commit": rev,
                        "device": device, "spruceos_pin": twig.get("PKG_VERSION")},
        "card_archive": {"name": name, "sha256": digest, "size": int(size), "in": where},
        "compared_with": {"spruceos": spruce_rev},
        "files": dict(sorted(files.items())),
        "card_cores_not_from_twigui_next": sorted(p.name for p in cores_dir.iterdir()
                                                  if f"{CORES}/{p.name}" not in files),
    }
