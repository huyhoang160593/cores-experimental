"""spruceOS's emulator inventory, and how this repository's recipes cover it.

`generate` reads a spruceOS checkout at one commit. It records every system's emulators and every shipped file they
use, with its sha256, in manifests/emulator-inventory.json. `coverage` checks that file against the recipes, offline.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

CORE_DIRS = {"armhf": "RetroArch/.retroarch/cores", "arm64": "RetroArch/.retroarch/cores64"}
CORE_FILE = re.compile(r"^RetroArch/\.retroarch/(cores64|cores)/(.+)_libretro\.so$")
EMU_DIR_CORE = re.compile(r"^Emu/[^/]+/[^/]+_libretro\.so$")  # would win over CORE_DIR: not modelled, so check() flags it
EMU_KEY = re.compile(r"^Emulator(_.+)?$")
PLATFORM_DIR = "spruce/scripts/platform"
RA_BUILDS = ("64-bit", "32-bit")
STANDARD_LAUNCH = ("standard_launch.sh", "vulkan_launch.sh")  # vulkan_launch sources standard_launch
ORDER = ("reproduces", "recipe", "base image", "no recipe", "not shipped", "blacklisted", "closed source",
         "not an emulator", "unresolved")


def _git(repo: Path, *args: str, text: bool = True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True, text=text).stdout


def _member_sha256(repo: Path, rev: str, archive: str, member: str) -> str | None:
    """sha256 of one file inside a .7z in the tree, or None when no 7-Zip is installed."""
    tool = shutil.which("7zz") or shutil.which("7z")
    if tool is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "archive.7z"
        path.write_bytes(_git(repo, "cat-file", "blob", f"{rev}:{archive}", text=False))
        subprocess.run([tool, "x", "-y", f"-o{tmp}/x", str(path), member], capture_output=True, check=True)
        found = Path(tmp) / "x" / member
        return hashlib.sha256(found.read_bytes()).hexdigest() if found.is_file() else None


def _cfg_values(show, path: str) -> dict:
    """The exports of a platform .cfg, following its `. /mnt/SDCARD/...cfg` includes."""
    values = {}
    for line in show(path).splitlines():
        if m := re.match(r"\s*\.\s+/mnt/SDCARD/(spruce/scripts/platform/\S+\.cfg)", line):
            values.update(_cfg_values(show, m.group(1)))
        elif m := re.match(r'\s*export\s+(\w+)=("([^"]*)"|(\S*))', line):
            values[m.group(1)] = m.group(3) if m.group(3) is not None else m.group(4)
    return values


def devices(spruceos: Path, commit: str) -> list[dict]:
    """Every platform spruceOS boots as: the names device_names() gives it, its arch, and whether it has a 32-bit RA.
    Ported from the Emu Inventory session's emu_inventory.py; the Mini models share MiyooMini.cfg."""
    show = lambda path: _git(spruceos, "show", f"{commit}:{path}")  # noqa: E731
    body = show("spruce/scripts/helperFunctions.sh").split("device_names() {", 1)[1].split("\n}\n", 1)[0]
    tokens = {platform: re.findall(r'echo "([A-Z0-9_]+)"', m.group(2))
              for m in re.finditer(r"^\s+([\w|]+)\)\s+(.*?);;", body, re.M) for platform in m.group(1).split("|")}
    cfgs = sorted(p for p in _git(spruceos, "ls-tree", "-r", "--name-only", commit, "--", PLATFORM_DIR).splitlines()
                  if p.endswith(".cfg") and "Common" not in p)
    minis = [p.rsplit("/", 1)[1][:-4] for p in cfgs if p.rsplit("/", 1)[1].startswith("MIYOO_MINI")]
    units = []
    for path in cfgs:
        platform = path.rsplit("/", 1)[1][:-4]
        if platform.startswith("MIYOO_MINI"):
            continue
        cfg = _cfg_values(show, path)
        facts = {"platform": platform, "parent": cfg.get("PLATFORM_PARENT", ""),
                 "arch": cfg.get("PLATFORM_ARCHITECTURE", ""), "dual_ra": cfg.get("DEVICE_HAS_32_BIT_RA") == "true"}
        if platform == "MiyooMini":  # device_names prints get_miyoo_mini_variant, then the family
            units += [{"unit": model, "names": [model, "MIYOO_MINI_FAMILY"], **facts} for model in minis]
        else:
            units.append({"unit": platform, "names": tokens.get(platform, []), **facts})
    return units


def generate(spruceos: Path, rev: str, names: dict) -> dict:
    """The inventory of spruceOS at rev: devices, systems, their emulators, and the sha256 of every file they use."""
    commit = _git(spruceos, "rev-parse", f"{rev}^{{commit}}").strip()
    tree = {}
    for line in _git(spruceos, "ls-tree", "-r", commit, "--", "Emu", "RetroArch/.retroarch").splitlines():
        meta, path = line.split("\t", 1)
        tree[path] = meta.split()[2]
    wanted = [p for p in tree if CORE_FILE.match(p) or EMU_DIR_CORE.match(p)]
    for entry in names.values():
        wanted += [p.split("!")[0] for p in entry.get("paths", [])]
    files = {}
    for path in sorted(set(wanted)):
        if path in tree:
            blob = _git(spruceos, "cat-file", "blob", tree[path], text=False)
            files[path] = hashlib.sha256(blob).hexdigest()
    for entry in names.values():
        for path in entry.get("paths", []):
            if "!" in path:
                archive, member = path.split("!", 1)
                files[path] = _member_sha256(spruceos, commit, archive, member) if archive in tree else None
    systems = {}
    for path in sorted(p for p in tree if re.match(r"^Emu/[^/]+/config\.json$", p)):
        config = json.loads(_git(spruceos, "show", f"{commit}:{path}"))
        menu = config.get("menuOptions") or {}
        systems[path.split("/")[1]] = {
            "devices": config.get("devices"),
            "default": config.get("default_emulator"),
            "launch": config.get("launch") or "",
            "options": {key: {"devices": value.get("devices"), "options": value.get("options") or []}
                        for key, value in menu.items() if EMU_KEY.match(key)},
        }
        if isinstance(menu.get("raBuild"), dict):
            systems[path.split("/")[1]]["raBuild"] = {"devices": menu["raBuild"].get("devices") or [],
                                                      "options": menu["raBuild"].get("options") or list(RA_BUILDS)}
    return {"note": "Generated by `scripts/cores.py inventory --spruceos <checkout>`; edit emulator-names.json, not this.",
            "spruceos": {"commit": commit, "date": _git(spruceos, "show", "-s", "--format=%cs", commit).strip()},
            "devices": devices(spruceos, commit), "systems": systems, "files": files}


NAME_KEYS = {"core", "paths", "base_image", "blacklisted", "closed_source", "not_emulator", "unresolved", "note"}
REASON_KEYS = (("blacklisted", "blacklisted"), ("base_image", "base image"), ("closed_source", "closed source"), ("not_emulator", "not an emulator"),
               ("unresolved", "unresolved"))


def check(names: dict, inventory: dict) -> list[str]:
    """Problems in emulator-names.json, and inventory paths it no longer names."""
    problems = []
    for name, entry in names.items():
        extra = set(entry) - NAME_KEYS
        kinds = [key for key in ("core", "paths", *(key for key, _ in REASON_KEYS)) if key in entry]
        if extra:
            problems.append(f"emulator-names {name}: unknown keys {sorted(extra)}")
        if not kinds:
            problems.append(f"emulator-names {name}: needs core, paths, base_image, blacklisted, closed_source, "
                            "not_emulator or unresolved")
        if "paths" in entry and not (isinstance(entry["paths"], list) and all(isinstance(p, str) for p in entry["paths"])):
            problems.append(f"emulator-names {name}: paths must be a list of card paths")
    named = {p for entry in names.values() for p in entry.get("paths", [])}
    if missing := sorted(p for p in named if "!" in p and inventory["files"].get(p) is None):
        problems.append(f"emulator-inventory: archive members not hashed (regenerate with 7-Zip installed): {missing}")
    # The folder rule in reached() is set_emu_core_from_emu_json's: it holds only for what it models.
    if odd := sorted(s for s, e in inventory["systems"].items() if not e.get("launch", "").endswith(STANDARD_LAUNCH)):
        problems.append(f"emulator-inventory: systems not launched by standard_launch.sh, so not modelled: {odd}")
    if odd := sorted(p for p in inventory["files"] if EMU_DIR_CORE.match(p)):
        problems.append(f"emulator-inventory: cores in an Emu folder win over CORE_DIR, not modelled: {odd}")
    if odd := sorted(u["unit"] for u in inventory.get("devices", []) if u["names"] and not u["arch"]):
        problems.append(f"emulator-inventory: devices with no PLATFORM_ARCHITECTURE: {odd}")
    return problems


def blacklist_problems(names: dict, catalog: dict, standalones: dict) -> list[str]:
    """A blacklisted name's card files must never be a recipe's output: the reason says why none may be built."""
    banned = {path: (name, entry["blacklisted"]) for name, entry in names.items() if "blacklisted" in entry
              for path in entry.get("paths", [])}
    return [f"{recipe} builds {path}, which emulator-names blacklists ({banned[path][0]}: {banned[path][1]})"
            for path, builders in recipes_by_path(catalog, standalones).items() if path in banned
            for recipe, _ in builders]


def offered(inventory: dict) -> dict:
    """{emulator name: [where it is offered]}, from every system's default and option lists."""
    names: dict[str, list[str]] = {}
    for system, entry in inventory["systems"].items():
        if entry["default"]:
            names.setdefault(entry["default"], []).append(f"{system} (default)")
        for key, menu in entry["options"].items():
            devices = ",".join(menu["devices"] or ["all"])
            for option in menu["options"]:
                names.setdefault(option, []).append(f"{system} {key} [{devices}]")
    return names


def _claims(option: dict | None, unit: dict) -> bool:
    return bool(option) and any(name in (option.get("devices") or []) for name in unit["names"])


def launcher_key(system: dict, unit: dict, build: str) -> str | None:
    """The Emulator* key set_emu_core_from_emu_json (general_functions.sh) reads on a device, None for the default.
    build is the effective RA Build: "" unless the device has a 32-bit RetroArch and the system an RA Build row."""
    menu = system["options"]
    arch = next((key for key, value in (("Emulator_32", "32-bit"), ("Emulator_64", "64-bit"))
                 if build == value and _claims(menu.get(key), unit)), "")
    claimed = next((key for key in menu if (not arch or key == arch) and _claims(menu[key], unit)), None)
    if arch and claimed == arch:
        return arch
    for name in (unit["platform"], unit["parent"]):
        if name and f"Emulator_{name}" in menu:
            return f"Emulator_{name}"
    if claimed:
        return claimed
    suffix = "32" if unit["arch"] == "armhf" or build == "32-bit" else "64"
    return next((key for key in (f"Emulator_{suffix}", "Emulator") if key in menu), None)


def reached(inventory: dict) -> dict:
    """{emulator name: {arch: {device family}}}: which families run each name, and the core folder they load from.
    Every RA Build value the system's row allows is followed; a folder is armhf when the device is, or runs 32-bit RA."""
    found: dict[str, dict[str, set]] = {}
    for system in inventory["systems"].values():
        for unit in inventory.get("devices", []):
            if not unit["names"] or (system["devices"] and not set(unit["names"]) & set(system["devices"])):
                continue
            for stored in system.get("raBuild", {}).get("options", RA_BUILDS):
                build = stored if unit["dual_ra"] and "raBuild" in system else ""
                key = launcher_key(system, unit, build)
                options = (system["options"].get(key) or {}).get("options") if key else None
                arch = "armhf" if unit["arch"] == "armhf" or build == "32-bit" else "arm64"
                for name in options or ([system["default"]] if system["default"] else []):
                    found.setdefault(name, {}).setdefault(arch, set()).add(unit["names"][-1])
    return found


def resolve(name: str, inventory: dict, names: dict, reach: dict | None = None) -> dict:
    """What a name stands for: a core's card files, a standalone's paths, or why it has none. A core's files are
    the folders some device loads it from, shipped or not, and any shipped copy no device loads (families empty)."""
    entry = names.get(name, {})
    reach = reached(inventory) if reach is None else reach
    if "core" in entry or not entry:
        core = entry.get("core") or re.sub(r"[-_]libretro$", "", name)
        families = {f"{folder}/{core}_libretro.so": sorted(reach.get(name, {}).get(arch, ()))
                    for arch, folder in CORE_DIRS.items()}
        shipped = [path for path in families if path in inventory["files"]]
        if shipped or entry:
            paths = [path for path in families if path in shipped or families[path]]
            return {"kind": "core", "paths": paths, "families": {p: families[p] for p in paths},
                    "note": entry.get("note", "")}
        return {"kind": "unresolved", "paths": [], "note": ""}
    for key, kind in REASON_KEYS:
        if key in entry:
            return {"kind": kind, "paths": entry.get("paths", []), "note": entry[key]}
    return {"kind": "standalone", "paths": entry["paths"], "note": entry.get("note", "")}


def _matched(spec: dict) -> dict:
    """The shipped files a build has matched: none while the record is unverified, and none it knows differ."""
    shipped = spec.get("shipped", {})
    if shipped.get("unverified"):
        return {}
    return {path: digest for path, digest in shipped.get("files", {}).items() if path not in shipped.get("differs", {})}


def recipes_by_path(catalog: dict, standalones: dict) -> dict:
    """{card path: [(recipe, the sha256 a build of it has matched as shipped, or None)]} for everything a recipe builds."""
    found: dict[str, list] = {}
    for core, spec in catalog.items():
        shipped = _matched(spec)
        for arch in spec["targets"]:
            path = f"{CORE_DIRS[arch]}/{spec['build']['artifact_name']}"
            found.setdefault(path, []).append((core, shipped.get(path)))
    for name, spec in standalones.items():
        spruce = spec.get("output", {}).get("spruce", {})
        shipped = _matched(spec)
        for item in spec.get("output", {}).get("files", []):
            card = _card_path(item["to"], spruce)
            if card:
                found.setdefault(card, []).append((f"standalone:{name}", shipped.get(item["to"])))
            if item.get("dir"):  # a copied folder: its shipped files map one by one
                for dist, digest in shipped.items():
                    if dist.startswith(item["to"].rstrip("/") + "/") and _card_path(dist, spruce):
                        found.setdefault(_card_path(dist, spruce), []).append((f"standalone:{name}", digest))
    return found


def _card_path(dist: str, spruce: dict) -> str | None:
    """Where a dist/ path lands on the card: its own key first, else the longest folder key that holds it."""
    if dist in spruce:
        return spruce[dist]
    folders = [key for key in spruce if key.endswith("/") and dist.startswith(key)]
    if not folders:
        return None
    key = max(folders, key=len)
    return spruce[key].rstrip("/") + "/" + dist[len(key):]


def card_status(path: str, inventory: dict, recipes: dict) -> tuple[str, list[str]]:
    shipped = inventory["files"].get(path)
    builders = recipes.get(path, [])
    archive = path.split("!", 1)
    if not builders and len(archive) == 2:  # a binary inside an archive is built under its member path
        builders = [b for card, items in recipes.items() if card.endswith("/" + archive[1]) for b in items]
    if path not in inventory["files"]:
        return "not shipped", [b[0] for b in builders]
    if any(digest and digest == shipped for _, digest in builders):
        return "reproduces", [b[0] for b in builders if b[1] == shipped]
    if shipped and not builders:  # a recipe that records these bytes at a card path spruce has since renamed
        moved = sorted({f"{name} (as {card})" for card, items in recipes.items() for name, digest in items
                        if digest == shipped})
        if moved:
            return "reproduces", moved
    return ("recipe" if builders else "no recipe"), [b[0] for b in builders]


def coverage(inventory: dict, names: dict, catalog: dict, standalones: dict) -> list[dict]:
    """One row per offered emulator and card file, with its status and the recipes that build it."""
    recipes = recipes_by_path(catalog, standalones)
    reach = reached(inventory)
    rows = []
    for name, where in sorted(offered(inventory).items(), key=lambda item: item[0].lower()):
        target = resolve(name, inventory, names, reach)
        runs = sorted(set().union(*reach.get(name, {}).values()))  # a standalone's binary per device is not modelled
        if target["kind"] in {kind for _, kind in REASON_KEYS} or not target["paths"]:
            status = target["kind"] if target["kind"] != "core" else "not shipped"
            rows.append({"name": name, "where": where, "kind": target["kind"], "path": "", "status": status,
                         "recipes": [], "families": runs, "note": target.get("note", "")})
            continue
        for path in target["paths"]:
            status, builders = card_status(path, inventory, recipes)
            rows.append({"name": name, "where": where, "kind": target["kind"], "path": path, "status": status,
                         "recipes": builders, "families": target.get("families", {}).get(path, runs),
                         "note": target.get("note", "")})
    listed = {row["path"] for row in rows}
    for path in sorted(p for p in inventory["files"] if CORE_FILE.match(p) and p not in listed):
        status, builders = card_status(path, inventory, recipes)
        rows.append({"name": CORE_FILE.match(path).group(2), "where": [], "kind": "core", "path": path,
                     "status": status, "recipes": builders, "families": [], "note": "no menu offers it"})
    return rows


def spare(rows: list[dict]) -> set[str]:
    """Shipped core files no device loads from their folder, under any name: dead weight on the card."""
    used = {row["path"] for row in rows if row["families"]}
    return {row["path"] for row in rows if row["kind"] == "core" and row["path"] and row["status"] != "not shipped"
            and row["path"] not in used}


def report(rows: list[dict], inventory: dict) -> str:
    unused = spare(rows)
    counts = {status: sum(1 for row in rows if row["status"] == status and row["path"] not in unused)
              for status in ORDER}
    lines = [f"# Emulator inventory coverage (spruceOS {inventory['spruceos']['commit'][:9]}, "
             f"{inventory['spruceos']['date']})", "",
             " · ".join(f"{status}: {count}" for status, count in counts.items() if count)
             + f" · spare (shipped, no device loads it from there): {len(unused)}", "",
             "| emulator | kind | card path | status | recipes | loaded or run by | offered in |",
             "|---|---|---|---|---|---|---|"]
    for row in sorted(rows, key=lambda r: (r["path"] in unused, ORDER.index(r["status"]), r["name"].lower(), r["path"])):
        where = "; ".join(row["where"][:3]) + (f" (+{len(row['where']) - 3})" if len(row["where"]) > 3 else "")
        note = f" ({row['note']})" if row["note"] else ""
        status = row["status"] + (", spare" if row["path"] in unused else "")
        lines.append(f"| `{row['name']}` | {row['kind']} | `{row['path']}` | {status}{note} | "
                     f"{', '.join(row['recipes'])} | {', '.join(row['families'])} | {where} |")
    return "\n".join(lines) + "\n"
