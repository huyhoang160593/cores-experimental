#!/usr/bin/env python3
"""The waves of cores cores-experimental tracks (docs/waves.md), one manifest each in manifests/waves/.

  spruce NAME --spruceos DIR --rev REV   what a spruceOS ref ships (spruce-nightly, spruce-stable46)
  spruce NAME --spruceos DIR --nightly TAG|latest
                                         the same at the Development commit a spruce nightly was built from
  twigui NAME --twigui DIR --rev REV ... what a TwigUI-Next release writes onto spruce's card (pixel2-twiguinext)
  edge                                   each recipe source's latest release tag, else its branch tip
  custom                                 recipes no other wave uses
  summary                                counts per wave
  diff NAME [--rev REV]                  what changed in a wave since its manifest at REV (default HEAD)

A manifest is generated; the hand-kept facts in an entry (`pin`, `evidence`, `verified`) carry over while its
sha256 stays the same."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from corebuild import inventory, standalone  # noqa: E402
from corebuild.catalog import Repo, load_json  # noqa: E402

WAVES = ROOT / "manifests/waves"
KEPT = ("pin", "evidence", "verified")
RELEASE_TAG = re.compile(r"^(v?\d+(\.\d+)*|r\d+)$")
NIGHTLY_TAG = re.compile(r"Release tag for this run: (v\d[\w.\-]*)")
NIGHTLY_DEV = re.compile(r"Current Development commit: ([0-9a-f]{40})")
SPRUCEOS = "spruceUI/spruceOS"


def write(name: str, data: dict) -> Path:
    WAVES.mkdir(parents=True, exist_ok=True)
    path = WAVES / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return path


def carry(name: str, section: str, entries: dict) -> dict:
    """Keep hand-added facts from the wave's previous manifest for entries whose sha256 has not changed."""
    old_path = WAVES / f"{name}.json"
    old = load_json(old_path).get(section, {}) if old_path.exists() else {}
    for key, entry in entries.items():
        prev = old.get(key, {})
        if prev.get("sha256") == entry.get("sha256"):
            entry.update({k: prev[k] for k in KEPT if k in prev and k not in entry})
    return entries


def recipe_sources(repo: Repo, builds: dict) -> dict:
    """{recipe name as coverage names it: source} for catalog cores and standalone recipes."""
    out = {core: spec["source"] for core, spec in repo.cores.items()}
    out.update({f"standalone:{name}": spec["source"] for name, spec in builds.items() if "source" in spec})
    return out


def parse_nightly_log(text: str) -> tuple[str | None, str | None]:
    """The release tag and Development commit a create-nightly run log prints."""
    tag, dev = NIGHTLY_TAG.search(text), NIGHTLY_DEV.search(text)
    return (tag.group(1) if tag else None, dev.group(1) if dev else None)


def nightly(tag: str) -> dict:
    """Which Development commit a spruce nightly was built from, from its create-nightly run log ("latest": newest).
    The release notes say it too, but old releases are deleted and spruceOSNightlies' tags all point at one commit."""
    gh = ["gh", "run", "list", "-R", SPRUCEOS, "--workflow", "create-nightly.yml", "--status", "success",
          "--limit", "60", "--json", "databaseId,createdAt"]
    for run in json.loads(subprocess.run(gh, capture_output=True, text=True, check=True).stdout):  # newest first
        log = subprocess.run(["gh", "run", "view", str(run["databaseId"]), "-R", SPRUCEOS, "--log"],
                             capture_output=True, text=True).stdout
        found, commit = parse_nightly_log(log)
        if found and commit and tag in ("latest", found):
            return {"tag": found, "run": run["databaseId"], "built": run["createdAt"], "commit": commit}
    sys.exit(f"--nightly {tag}: not among the last 60 successful create-nightly runs")


def shipped_records(repo: Repo, builds: dict) -> tuple[dict, dict]:
    """({recipe: {card path: sha256}} to check against the tree, {recipe: entry} for records not checked there,
    {recipe: count} of retired files in checked records):
    catalog cores by card path, standalone files by their output.spruce map. `retired` files are left out; a record
    with only those is `retired`, one of a package outside spruceOS (`source`, no `spruceos`) is `elsewhere`.
    Records come from the raw manifest, so an `extends` child inherits none."""
    shipped = {core: spec["shipped"] for core, spec in repo.cores.items() if spec.get("shipped")}
    cards = {core: {path: path for path in record["files"]} for core, record in shipped.items()}
    raw = load_json(ROOT / standalone.MANIFEST)["builds"]
    for name, spec in builds.items():
        record = raw.get(name, {}).get("shipped", {})
        if record.get("files"):
            spruce = spec.get("output", {}).get("spruce", {})
            shipped[f"standalone:{name}"] = record
            cards[f"standalone:{name}"] = {dist: inventory._card_path(dist, spruce) for dist in record["files"]}
    checked, skipped = {}, {}
    for name, record in shipped.items():
        if "source" in record and "spruceos" not in record:
            skipped[name] = {"files": len(record["files"]), "status": "elsewhere", "source": record["source"]}
            continue
        live = {cards[name][key]: digest for key, digest in record["files"].items()
                if key not in record.get("retired", {}) and cards[name][key]}
        if live:
            checked[name] = live
        else:
            skipped[name] = {"files": len(record["files"]), "status": "retired"}
    retired = {name: len(record["retired"]) for name, record in shipped.items()
               if record.get("retired") and name in checked}
    return checked, skipped, retired


def record_statuses(records: dict, shipped: dict) -> dict:
    """Does the tree ship the bytes each record names? match, partial, replaced (another record matches there)
    or not shipped; `differ` lists the record's other paths (other bytes, or absent), `by` the records matching there."""
    out = {}
    for name, files in sorted(records.items()):
        same = [card for card, digest in files.items() if shipped.get(card) == digest]
        entry = {"files": len(files), "status": "match" if len(same) == len(files) else "partial" if same else
                 "not shipped"}
        if entry["status"] != "match":
            entry["differ"] = {card: "absent" if shipped.get(card) is None else "other bytes"
                               for card in sorted(files) if card not in same}
        out[name] = entry
    for name, entry in out.items():
        if entry["status"] in ("partial", "not shipped"):
            by = sorted(other for other, files in records.items() if other != name and out[other]["status"] == "match"
                        and set(files) & set(entry["differ"]))
            if by:
                entry["by"] = by
                if entry["status"] == "not shipped":
                    entry["status"] = "replaced"
    return out


def cmd_spruce(args) -> int:
    repo = Repo()
    names = load_json(ROOT / "manifests/emulator-names.json")["names"]
    builds = standalone.buildable(standalone.load(repo))
    built_as = None
    if args.nightly:
        built_as = nightly(args.nightly)
        if args.rev and args.rev != built_as["commit"]:
            sys.exit(f"--rev {args.rev} is not nightly {built_as['tag']}'s commit {built_as['commit']}")
        args.rev = built_as["commit"]
    elif not args.rev:
        sys.exit("spruce: give --rev or --nightly")
    try:
        inv = inventory.generate(Path(args.spruceos), args.rev, names)
    except subprocess.CalledProcessError:
        sys.exit(f"spruceOS {args.rev} is not in {args.spruceos}: git -C {args.spruceos} fetch origin")
    sources = recipe_sources(repo, builds)
    files: dict = {}
    rows = inventory.coverage(inv, names, repo.cores, builds)
    unused = inventory.spare(rows)
    for row in rows:
        if not row["path"]:
            continue
        entry = files.setdefault(row["path"], {"sha256": inv["files"].get(row["path"]), "kind": row["kind"],
                                               "names": [], "status": row["status"], "recipes": row["recipes"],
                                               "families": []})
        entry["names"].append(row["name"])
        entry["families"] = sorted(set(entry["families"]) | set(row["families"]))
        if row["path"] in unused:
            entry["spare"] = True  # shipped, but no device loads it from this folder
        if row["status"] == "reproduces" and "pin" not in entry:
            recipe = row["recipes"][0].split(" (as ")[0]
            src = sources.get(recipe, {})
            entry["pin"] = {"recipe": recipe, "url": src.get("url"), "commit": src.get("commit")}
    records, skipped, retired = shipped_records(repo, builds)
    shipped = inventory.card_sha256(Path(args.spruceos), inv["spruceos"]["commit"],
                                    [card for files in records.values() for card in files])
    statuses = {**record_statuses(records, shipped), **skipped}
    for name, count in retired.items():
        statuses[name]["retired"] = count
    defined_by = {"repo": SPRUCEOS, "ref": args.rev, **inv["spruceos"]}
    if built_as:
        defined_by["nightly"] = {"tag": built_as["tag"], "run": built_as["run"], "built": built_as["built"]}
    data = {"note": "Generated by scripts/waves.py spruce (docs/waves.md); regenerate, don't edit.",
            "wave": args.name,
            "defined_by": defined_by,
            "files": carry(args.name, "files", dict(sorted(files.items()))),
            "records": dict(sorted(statuses.items()))}
    path = write(args.name, data)
    print(f"{path.relative_to(ROOT)}: spruceOS {inv['spruceos']['commit'][:9]}"
          + (f" (nightly {built_as['tag']})" if built_as else "") + f", {len(files)} files, "
          + ", ".join(f"{k} {v}" for k, v in Counter(f["status"] for f in files.values()).most_common())
          + f"; spare {len(unused)}; records "
          + ", ".join(f"{k} {v}" for k, v in Counter(r["status"] for r in data["records"].values()).most_common()))
    return 0


def label(defined_by: dict) -> str:
    night = defined_by.get("nightly", {}).get("tag")
    commit = (defined_by.get("commit") or "")[:9]
    return f"nightly {night} ({commit})" if night else commit or "nothing"


def diff(old: dict, new: dict) -> list[str]:
    """One line per change between two manifests of a wave: what defines it, its files' status or bytes, its records."""
    lines = []
    if old.get("defined_by") != new.get("defined_by"):
        lines.append(f"defined by: {label(old.get('defined_by', {}))} -> {label(new.get('defined_by', {}))}")
    before, after = old.get("files", {}), new.get("files", {})
    for path in sorted(set(before) | set(after)):
        a, b = before.get(path), after.get(path)
        if a is None:
            lines.append(f"+ {path}: {b['status']}")
        elif b is None:
            lines.append(f"- {path} (was {a['status']})")
        elif a["status"] != b["status"]:
            lines.append(f"~ {path}: {a['status']} -> {b['status']}")
        elif a.get("sha256") != b.get("sha256"):
            lines.append(f"~ {path}: new bytes, still {b['status']}")
    before, after = old.get("records", {}), new.get("records", {})
    for name in sorted(set(before) | set(after)):
        a, b = before.get(name, {}).get("status"), after.get(name, {}).get("status")
        if a != b:
            lines.append(f"record {name}: {a or 'none'} -> {b or 'none'}")
    return lines


def cmd_diff(args) -> int:
    rel = f"manifests/waves/{args.name}.json"
    shown = subprocess.run(["git", "-C", str(ROOT), "show", f"{args.rev}:{rel}"], capture_output=True, text=True)
    old = json.loads(shown.stdout) if shown.returncode == 0 else {}
    lines = diff(old, load_json(ROOT / rel))
    print("\n".join(lines) if lines else f"{args.name}: no change since {args.rev}")
    return 0


def cmd_twigui(args) -> int:
    import twigui_pins
    rec = twigui_pins.pins(args.twigui, args.rev, args.release, args.device, args.card, args.archive,
                           args.spruceos, args.spruce_rev)
    files = {}
    for path, entry in rec.pop("files").items():
        files[path] = {"sha256": entry.pop("sha256"), "kind": entry.pop("kind"), "status": "pinned", **entry}
    base = {}
    for item in args.base or []:
        path, digest, package = item.split(":", 2)
        base[path] = {"sha256": digest, "kind": "base image", "status": "pinned", "package": package}
    for item in args.verified or []:
        path, evidence = item.split("=", 1)
        target = files.get(path) or base.get(path)
        if target is None:
            sys.exit(f"--verified {path}: not in the wave")
        target["verified"] = evidence
    files, base = carry(args.name, "files", files), carry(args.name, "base", base)
    for entry in (*files.values(), *base.values()):
        if entry.get("verified"):  # only byte-for-byte evidence counts as reproduced
            entry["status"] = "reproduced" if entry["verified"].startswith("byte for byte") else "near"
    data = {"note": "Generated by scripts/waves.py twigui (docs/twigui-next.md); regenerate, don't edit.",
            "wave": args.name, "defined_by": rec.pop("twigui_next"), **rec, "files": files, "base": base}
    path = write(args.name, data)
    print(f"{path.relative_to(ROOT)}: {len(files)} card files ("
          + ", ".join(f"{k} {v}" for k, v in Counter(e["kind"] for e in files.values()).items())
          + f"), {len(base)} base files, "
          + ", ".join(f"{k} {v}" for k, v in Counter(e["status"] for e in (*files.values(), *base.values())).items()))
    return 0


def ls_remote(url: str) -> list[tuple[str, str]]:
    out = subprocess.run(["git", "ls-remote", url], capture_output=True, text=True, timeout=120).stdout
    return [tuple(line.split("\t", 1)) for line in out.splitlines() if "\t" in line]


def commit_date(url: str, commit: str) -> str | None:
    """Committer date of a commit, from GitHub's API (None for other hosts or on error)."""
    m = re.match(r"https://github\.com/([^/]+/[^/.]+?)(\.git)?$", url)
    if not m:
        return None
    r = subprocess.run(["gh", "api", f"repos/{m.group(1)}/commits/{commit}", "--jq", ".commit.committer.date"],
                       capture_output=True, text=True)
    return r.stdout.strip() or None


def version_key(tag: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", tag))


def edge_of(source: dict) -> dict:
    """The newest release tag if its commit is newer than the pin, else the requested branch's tip."""
    url, pin = source["url"], source["commit"]
    refs = ls_remote(url)
    peeled = {ref.removesuffix("^{}"): sha for sha, ref in refs if ref.endswith("^{}")}
    tags = {ref[len("refs/tags/"):]: peeled.get(ref, sha) for sha, ref in refs
            if ref.startswith("refs/tags/") and not ref.endswith("^{}")}
    release = sorted((t for t in tags if RELEASE_TAG.match(t)), key=version_key)
    requested = source.get("requested_ref", "").split()[0] if source.get("requested_ref") else ""
    branch = requested if requested.startswith("refs/heads/") else "HEAD"
    tip = next((sha for sha, ref in refs if ref == branch), None)
    pin_date = commit_date(url, pin)
    out = {"url": url, "pin": pin, "pin_date": pin_date}
    if release:
        tag = release[-1]
        tag_date = commit_date(url, tags[tag])
        out["newest_tag"] = {"tag": tag, "commit": tags[tag], "date": tag_date}
        if tag_date and pin_date and tag_date > pin_date:
            out["edge"] = {"kind": "tag", "tag": tag, "commit": tags[tag], "date": tag_date}
            return out
    out["edge"] = {"kind": "tip", "ref": branch, "commit": tip, "date": commit_date(url, tip) if tip else None,
                   "why": "no release tag" if not release else "newest tag is not newer than the pin"}
    return out


def cmd_edge(args) -> int:
    repo = Repo()
    builds = standalone.buildable(standalone.load(repo))
    sources = recipe_sources(repo, builds)
    seen: dict = {}
    entries = {}
    for name, src in sorted(sources.items()):
        key = (src["url"], src["commit"], src.get("requested_ref", ""))
        if key not in seen:
            seen[key] = edge_of(src)
            print(f"  {name:44} {seen[key]['edge']['kind']:4} {seen[key]['edge'].get('tag', '')}", flush=True)
        entries[name] = seen[key]
    data = {"note": "Generated by scripts/waves.py edge (docs/waves.md); regenerate, don't edit.",
            "wave": "edge",
            "rule": "each recipe source's newest release tag (vN.N... or rN) if its commit is newer than the recipe's "
                    "pin, else the requested branch's tip (HEAD for a tag-pinned recipe)",
            "sources": entries}
    path = write("edge", data)
    kinds = Counter(e["edge"]["kind"] for e in entries.values())
    print(f"{path.relative_to(ROOT)}: {len(entries)} recipes, " + ", ".join(f"{k} {v}" for k, v in kinds.items()))
    return 0


def cmd_custom(args) -> int:
    repo = Repo()
    builds = standalone.buildable(standalone.load(repo))
    sources = recipe_sources(repo, builds)
    builders = inventory.recipes_by_path(repo.cores, builds)  # every card path a recipe builds
    used = set()
    for path in sorted(WAVES.glob("*.json")):
        if path.stem in ("edge", "custom"):
            continue
        for card, entry in load_json(path).get("files", {}).items():
            used.update(r.split(" (as ")[0] for r in entry.get("recipes", []))
            used.update(name for name, _ in builders.get(card, []))
            if entry.get("pin", {}).get("recipe"):
                used.add(entry["pin"]["recipe"])
    entries = {name: {"url": src["url"], "commit": src["commit"]} for name, src in sorted(sources.items())
               if name not in used}
    data = {"note": "Generated by scripts/waves.py custom (docs/waves.md); regenerate, don't edit.",
            "wave": "custom", "rule": "recipes that build no file of spruce-nightly, spruce-stable46 or "
                                      "pixel2-twiguinext: experiments, variants and candidates", "recipes": entries}
    path = write("custom", data)
    print(f"{path.relative_to(ROOT)}: {len(entries)} recipes")
    return 0


def cmd_summary(args) -> int:
    for path in sorted(WAVES.glob("*.json")):
        data = load_json(path)
        if "files" in data:
            counts = Counter(e["status"] for e in (*data["files"].values(), *data.get("base", {}).values()))
            spare = sum(1 for e in data["files"].values() if e.get("spare"))
            records = Counter(r["status"] for r in data.get("records", {}).values())
            print(f"{path.stem:20} {sum(counts.values()):4} files  " + ", ".join(f"{k} {v}" for k, v in counts.most_common())
                  + (f"; spare {spare}" if spare else "")
                  + ("; records " + ", ".join(f"{k} {v}" for k, v in records.most_common()) if records else ""))
        elif "sources" in data:
            counts = Counter(e["edge"]["kind"] for e in data["sources"].values())
            print(f"{path.stem:20} {len(data['sources']):4} recipes  " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        else:
            print(f"{path.stem:20} {len(data['recipes']):4} recipes")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("spruce")
    p.add_argument("name"), p.add_argument("--spruceos", required=True), p.add_argument("--rev")
    p.add_argument("--nightly", help="a nightly's release tag, or latest: its Development commit, from the run log")
    p = sub.add_parser("diff")
    p.add_argument("name"), p.add_argument("--rev", default="HEAD")
    p = sub.add_parser("twigui")
    p.add_argument("name")
    for opt in ("--twigui", "--rev", "--release", "--archive", "--spruceos", "--spruce-rev"):
        p.add_argument(opt, required=True)
    p.add_argument("--card", required=True, help="the release's twigUI_SDCARD.7z, extracted (the card root)")
    p.add_argument("--device", default="RK3326S")
    p.add_argument("--base", action="append", help="PATH:SHA256:PACKAGE of a base-image file spruce uses")
    p.add_argument("--verified", action="append", help="PATH=EVIDENCE for a file reproduced byte for byte")
    sub.add_parser("edge"), sub.add_parser("custom"), sub.add_parser("summary")
    args = ap.parse_args()
    return {"spruce": cmd_spruce, "twigui": cmd_twigui, "edge": cmd_edge, "custom": cmd_custom,
            "summary": cmd_summary, "diff": cmd_diff}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
