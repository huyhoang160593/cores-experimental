"""Unit tests for the build driver; run with `python3 -m unittest discover tests`."""

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from corebuild import build, inventory, recipe, release, standalone  # noqa: E402
from corebuild.catalog import Repo, known_good  # noqa: E402
from corebuild.variants import parse_flags, plan  # noqa: E402

REPO = Repo()


def builds(core, boards, profiles, flags=(), arch=None, runtimes=("shared",), strip=False):
    return plan(REPO.cores[core], REPO.boards, REPO.profiles, boards, profiles, flags, arch, runtimes, strip)


class CatalogTest(unittest.TestCase):
    def test_repository_is_consistent(self):
        self.assertEqual(REPO.check(), [])

    def test_every_core_renders_for_every_target(self):
        for core, spec in REPO.cores.items():
            for arch in spec["targets"]:
                with self.subTest(core=core, arch=arch):
                    script = recipe.render(core, spec, arch)
                    self.assertIn(f"/output/{spec['build']['artifact_name']}", script.text)
                    for host, _ in script.mounts:
                        self.assertTrue((ROOT / host).is_file(), host)

    def test_selection_rejects_unknown_names(self):
        with self.assertRaises(ValueError):
            REPO.select("np2kai nosuchcore")
        self.assertEqual(REPO.select("all"), sorted(REPO.cores))


class PlanTest(unittest.TestCase):
    def test_boards_with_identical_flags_share_a_build(self):
        variants = builds("np2kai", ["a523", "rk3566", "a33", "ssd202d"], ["max"])
        self.assertEqual(sorted((v.name, v.boards) for v in variants), [
            ("max-arm64-cortex-a55", ("a523", "rk3566")),
            ("max-armhf-cortex-a7-neon-vfpv4", ("a33", "ssd202d")),
        ])

    def test_universal_builds_every_target_and_boards_only_their_arch(self):
        self.assertEqual({v.arch for v in builds("np2kai", ["universal"], ["release"])}, {"arm64", "armhf"})
        self.assertEqual({v.arch for v in builds("np2kai", ["universal"], ["release"], arch="armhf")}, {"armhf"})
        arm64_only = next(c for c, s in REPO.cores.items() if s["targets"] == ["arm64"])
        self.assertEqual(builds(arm64_only, ["a33"], ["max"]), [])

    def test_baseline_is_the_catalog_build(self):
        (variant,) = builds("np2kai", ["universal"], ["release"], arch="arm64")
        self.assertTrue(variant.is_baseline)
        self.assertNotIn("cores-variant", recipe.render("np2kai", REPO.cores["np2kai"], "arm64", variant).text)

    def test_cargo_cores_take_profiles_but_not_board_flags(self):
        variants = builds("libgametank", ["a133p", "universal"], ["debug"], arch="arm64")
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0].flags, ())
        self.assertEqual(dict(variants[0].cargo), {"opt-level": "0", "debug": "true"})

    def test_extra_flags_are_validated_and_named(self):
        self.assertEqual(parse_flags("-O2 -fno-plt -DFOO=1"), ("-O2", "-fno-plt", "-DFOO=1"))
        for bad in ("-specs=/x", "--sysroot=/", "-I/tmp", "-O3;id", "-fplugin=../x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_flags(bad)
        (variant,) = builds("np2kai", ["a133p"], ["max"], ("-fno-plt",))
        self.assertRegex(variant.name, r"^max-arm64-cortex-a53-x[0-9a-f]{8}$")
        self.assertEqual(variant.flags, ("-mcpu=cortex-a53", "-O3", "-fno-plt"))

    def test_runtime_and_strip_make_named_builds(self):
        shared, static = builds("np2kai", ["universal"], ["release"], arch="armhf",
                                runtimes=("shared", "static"), strip=True)
        self.assertEqual((shared.name, static.name),
                         ("release-armhf-generic-stripped", "release-armhf-generic-static-stripped"))
        self.assertEqual(shared.flags, ())
        self.assertEqual(static.flags, ("-static-libstdc++", "-static-libgcc", "-Wl,--exclude-libs,ALL"))
        # Rust links its std statically anyway, so the runtime choice makes one build.
        (rust,) = builds("libgametank", ["universal"], ["release"], arch="arm64",
                         runtimes=("shared", "static"), strip=True)
        self.assertEqual((rust.name, rust.boards), ("release-arm64-generic-stripped", ("universal",)))


class RecipeTest(unittest.TestCase):
    def render(self, core, arch, boards=("universal",), profiles=("release",)):
        (variant,) = [v for v in builds(core, list(boards), list(profiles)) if v.arch == arch]
        return recipe.render(core, REPO.cores[core], arch, variant).text

    def test_variant_flags_are_appended_last_by_the_wrapper(self):
        text = self.render("np2kai", "arm64", ["a133p"], ["max"])
        self.assertLess(text.index('export PATH="/tmp/cores-variant:$PATH"'), text.index("./libretro-build.sh"))
        work = Path(tempfile.mkdtemp())
        compiler = work / "cc"
        compiler.write_text('#!/bin/sh\necho "$@"\n')
        compiler.chmod(0o755)
        body = text.split("<<'CORES_WRAPPER'\n", 1)[1].split("\nCORES_WRAPPER\n", 1)[0]
        wrapper = work / "wrapper"
        wrapper.write_text(body.replace("@REAL@", str(compiler))
                           .replace("/output/variant-calls.log", str(work / "calls.log")) + "\n")
        run = lambda *args: subprocess.run(["sh", str(wrapper), *args], capture_output=True, text=True).stdout.split()
        self.assertEqual(run("-c", "a.c", "-O2"), ["-c", "a.c", "-O2", "-mcpu=cortex-a53", "-O3"])
        # max never lowers a compile that already uses -Ofast; the board flags still apply.
        self.assertEqual(run("-c", "b.c", "-Ofast"), ["-c", "b.c", "-Ofast", "-mcpu=cortex-a53"])
        self.assertEqual((work / "calls.log").read_text().splitlines(), ["-c a.c -O2", "-c b.c -Ofast"])

    def test_static_runtime_survives_the_ofast_skip(self):
        (variant,) = builds("np2kai", ["a133p"], ["max"], runtimes=("static",))
        text = recipe.render("np2kai", REPO.cores["np2kai"], "arm64", variant).text
        self.assertIn('exec @REAL@ "$@" -mcpu=cortex-a53 -static-libstdc++ -static-libgcc -Wl,--exclude-libs,ALL ;;', text)

    def test_strip_runs_before_the_load_test(self):
        (variant,) = builds("np2kai", ["universal"], ["release"], arch="arm64", strip=True)
        text = recipe.render("np2kai", REPO.cores["np2kai"], "arm64", variant).text
        self.assertNotIn("cores-variant", text)
        self.assertLess(text.index('"$STRIP" --strip-unneeded /output/np2kai_libretro.so'), text.index("/tmp/smoke-loader"))
        (rust,) = builds("libgametank", ["universal"], ["release"], arch="arm64", strip=True)
        self.assertIn("export CARGO_PROFILE_RELEASE_STRIP=symbols",
                      recipe.render("libgametank", REPO.cores["libgametank"], "arm64", rust).text)

    def test_cargo_profile_is_set_through_cargo(self):
        text = self.render("libgametank", "arm64", profiles=["debug"])
        self.assertIn("export CARGO_PROFILE_RELEASE_OPT_LEVEL=0", text)
        self.assertNotIn("smoke", text)

    def test_commit_derived_values_follow_the_pinned_commit(self):
        self.assertIn("""export MAKEFLAGS='-- GIT_VERSION="\\ 9d3bcf2"'""", self.render("atari800", "arm64"))
        self.assertIn("export GIT_REVISION=-f0d4a011", self.render("picodrive", "arm64"))
        self.assertIn('export SOURCE_DATE_EPOCH="$(git -C libretro-fbneo show -s --format=%ct HEAD)"',
                      self.render("fbneo", "arm64"))

    def test_git_abbrev_pins_the_short_hash_length(self):
        text = self.render("hatari", "arm64")
        self.assertIn("export GIT_CONFIG_PARAMETERS=\"'core.abbrev=8'\"", text)
        self.assertLess(text.index("GIT_CONFIG_PARAMETERS"), text.index("./libretro-build.sh hatari"))

    def test_neon_switches_apply_only_to_neon_armhf_builds(self):
        self.assertIn("NOSSE=1 HAVE_NEON=1 CC=", self.render("km_parallel_n64_xtreme_amped_turbo", "armhf", ["a33"], ["max"]))
        self.assertNotIn("HAVE_NEON", self.render("km_parallel_n64_xtreme_amped_turbo", "armhf"))

    def test_neon_switches_reach_each_driver(self):
        (neon,) = builds("np2kai", ["a33"], ["release"])
        def render(core, entries):
            spec = json.loads(json.dumps(REPO.cores[core]))
            spec["build"]["neon"] = entries
            return recipe.render(core, spec, "armhf", neon).text
        self.assertIn("export MAKEFLAGS=HAVE_NEON=1", render("np2kai", ["HAVE_NEON=1"]))
        self.assertIn("GIT_VERSION=\"\\ {}\" HIDE= HAVE_NEON=1' ./libretro-build.sh".format(
            REPO.cores["mame2003_plus"]["source"]["commit"][:8]), render("mame2003_plus", ["HAVE_NEON=1"]))
        self.assertIn(" -DHAVE_NEON=ON", render("flycast", ["HAVE_NEON=ON"]))
        self.assertIn("export CFLAGS=-D__NEON_OPT\n", render("np2kai", ["-D__NEON_OPT"]))

    def test_special_recipes(self):
        self.assertIn("/usr/bin/gmake -f Makefile.libretro", self.render("picodrive", "armhf"))
        self.assertIn("MAKEFLAGS='-- GIT_VERSION=9d7716aa2 GIT_DATE=260503 HIDE=' ./libretro-build.sh fbneo",
                      self.render("fbneo", "arm64"))
        self.assertIn("apply -p4 --check", self.render("flycast", "armhf"))
        self.assertIn("timeout 300 qemu-arm /tmp/smoke-loader", self.render("np2kai", "armhf"))


class KnownGoodTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.spec = self.repo.cores["np2kai"]
        self.spec["known_good"] = {k: json.loads(json.dumps(self.spec[k])) for k in ("source", "build", "metadata")}
        self.spec["known_good"]["source"]["commit"] = "1" * 40

    def test_known_good_is_checked_like_the_current_recipe(self):
        self.assertEqual(self.repo.check(), [])
        self.spec["known_good"]["build"]["overlays"]["arm64"][0]["patch"] = "patches/missing.patch"
        self.assertIn("np2kai: known_good: missing patch patches/missing.patch", self.repo.check())

    def test_a_failed_build_falls_back_to_the_known_good_recipe(self):
        def fake(repo, core, variant, out, repeat=1, spec=None):
            out.mkdir(parents=True)
            commit = (spec or repo.cores[core])["source"]["commit"]
            rec = {"status": "usable" if commit == "1" * 40 else "failed", "seconds": 0,
                   "source": {"commit": commit}}
            (out / "record.json").write_text(json.dumps(rec))
            return rec

        original, build.build_one = build.build_one, fake
        try:
            out = Path(tempfile.mkdtemp())
            (variant,) = builds("np2kai", ["universal"], ["release"], arch="arm64")
            (rec,) = build.build_core(self.repo, "np2kai", [variant], out, fallback=True)
        finally:
            build.build_one = original
        self.assertEqual((rec["status"], rec["source"]["commit"]), ("usable", "1" * 40))
        self.assertEqual(rec["fallback"]["from_commit"], self.spec["source"]["commit"])
        self.assertTrue((out / "np2kai" / variant.name / "current-attempt" / "record.json").is_file())
        self.assertIsNone(known_good(Repo().cores["np2kai"]))


class ShippedTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.spec = self.repo.cores["np2kai"]
        self.spec["shipped"] = {"spruceos": "fac0c9424", "variant": "release-arm64-generic-stripped",
                                "files": {"RetroArch/.retroarch/cores64/np2kai_libretro.so": "a" * 64}}

    def test_a_shipped_record_is_checked(self):
        self.assertEqual(self.repo.check(), [])
        self.spec["shipped"].update(spruceos="Development", variant="release-x86-generic",
                                    files={"/mnt/SDCARD/np2kai_libretro.so": "abc"})
        problems = " | ".join(self.repo.check())
        for text in ("shipped.spruceos must be a commit id", "shipped.variant 'release-x86-generic' names no targeted arch",
                     "not a card-relative path", "sha256 must be 64 hex digits"):
            self.assertIn(text, problems)


def record(core, name, arch, boards, status="usable", sha="a" * 64, reproducible=None, profile="max", suffix=""):
    return {
        "core": core, "status": status, "source": {"commit": "c" * 40},
        "variant": {"name": name, "arch": arch, "profile": profile, "boards": boards, "flags": [], "suffix": suffix},
        "toolchain": {"image_id": "sha256:" + "0" * 64},
        "artifact": {"name": f"{core}_libretro.so", "sha256": sha, "size": 1} if status != "failed" else None,
        "metadata": {"name": f"{core}_libretro.info", "sha256": "b" * 64},
        "reproducible": reproducible,
    }


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.results = self.tmp / "results"

    def add(self, rec):
        directory = self.results / rec["core"] / rec["variant"]["name"]
        directory.mkdir(parents=True)
        (directory / "record.json").write_text(json.dumps(rec))
        if rec["artifact"]:
            (directory / rec["artifact"]["name"]).write_text("so")
            (directory / rec["metadata"]["name"]).write_text("info")

    def test_bundles_use_the_device_layout(self):
        self.add(record("yabasanshiro", "max-arm64-cortex-a53", "arm64", ["a133p", "h700"]))
        self.add(record("np2kai", "max-armhf-generic", "armhf", ["universal"]))
        self.add(record("broken", "max-arm64-cortex-a53", "arm64", ["a133p"], status="failed"))
        summary = release.bundle(self.results, self.tmp / "bundles")
        a133p = self.tmp / "bundles/a133p-max/RetroArch/.retroarch"
        self.assertTrue((a133p / "cores64/yabasanshiro_a133p_libretro.so").is_file())
        self.assertTrue((a133p / "info/yabasanshiro_libretro.info").is_file())
        self.assertTrue((self.tmp / "bundles/universal-max/RetroArch/.retroarch/cores/np2kai_libretro.so").is_file())
        self.assertEqual(summary["a133p-max"]["broken"]["arm64"]["status"], "failed")
        self.assertFalse((a133p / "cores64/broken_libretro.so").exists())

    def test_static_and_stripped_builds_get_their_own_bundle(self):
        self.add(record("np2kai", "release-armhf-generic-stripped", "armhf", ["universal"],
                        profile="release", suffix="-stripped"))
        self.add(record("np2kai", "release-armhf-generic-static-stripped", "armhf", ["universal"],
                        profile="release", suffix="-static-stripped"))
        summary = release.bundle(self.results, self.tmp / "bundles")
        self.assertEqual(sorted(summary), ["universal-release-static-stripped", "universal-release-stripped"])

    def test_freeze_requires_reproducible_builds_and_checks_a_manifest(self):
        self.add(record("np2kai", "release-arm64-generic", "arm64", ["universal"], reproducible=True))
        self.add(record("mgba", "release-arm64-generic", "arm64", ["universal"], reproducible=False))
        manifest, problems = release.freeze(self.results, "test", "f" * 40)
        self.assertEqual(len(manifest["builds"]), 2)
        self.assertEqual(problems, ["mgba release-arm64-generic: second build differs (None)"])
        frozen = self.tmp / "frozen.json"
        manifest["builds"][1]["artifact"]["sha256"] = "d" * 64
        frozen.write_text(json.dumps(manifest))
        _, problems = release.freeze(self.results, "test", "f" * 40, frozen)
        self.assertIn("np2kai release-arm64-generic: rebuilt bytes differ from the frozen release", problems)

    def test_a_failed_script_step_fails_the_build_even_with_an_artifact(self):
        rec = {"artifact": {"name": "x.so"}, "exit_code": 1, "usability": {"probed": False}}
        self.assertEqual(build.status(rec), "failed")
        rec["exit_code"] = 0
        self.assertEqual(build.status(rec), "built")

    def test_usability_needs_every_smoke_step(self):
        out = self.tmp / "smoke"
        out.mkdir()
        (out / "smoke.txt").write_text("".join(f"CHECK {s} pass\n" for s in build.SMOKE_STEPS))
        self.assertTrue(build.usability(out)["loaded"])
        (out / "smoke.txt").write_text("CHECK dlopen pass\nCHECK retro_api_version pass\nexit 139\n")
        self.assertFalse(build.usability(out)["loaded"])
        mid_line = "".join(f"core output without newline CHECK {s} pass\n" for s in build.SMOKE_STEPS)
        (out / "smoke.txt").write_text(mid_line)
        self.assertTrue(build.usability(out)["loaded"])


class StandaloneTest(unittest.TestCase):
    def setUp(self):
        self.spec = standalone.load(REPO)["flycast-standalone"]
        self.toolchain = REPO.toolchains[self.spec["toolchain"]]

    def steps_spec(self, **fields) -> dict:
        spec = {"source": dict(self.spec["source"]), "toolchain": "arm64", "source_date_epoch": 1,
                "steps": ["make -j1"], "output": {"files": [{"from": "/src/emu", "to": "emu", "strip": "-s"}]}}
        spec.update(fields)
        return spec

    def test_recipes_are_consistent(self):
        self.assertEqual(standalone.check(REPO), [])

    def test_toolchain_names_the_image_a_workflow_downloads(self):
        def toolchain(name):
            return subprocess.run([sys.executable, str(ROOT / "scripts/cores.py"), "standalone", "toolchain", name],
                                  capture_output=True, text=True)
        found = toolchain("mupen64plus-arm64-gliden64")  # inherits its toolchain through extends
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertEqual(found.stdout.split(), ["standalone-mupen64plus",
                                                REPO.toolchains["standalone-mupen64plus"]["archive"]["name"]])
        self.assertEqual(toolchain("ppsspp").returncode, 2)  # abstract: never built
        self.assertTrue((ROOT / ".github/workflows/standalone.yml").is_file())

    def test_script_pins_the_source_and_ships_the_libraries(self):
        text = standalone.render("flycast-standalone", self.spec, self.toolchain).text
        self.assertIn(f"checkout -q {self.spec['source']['commit']}", text)
        self.assertIn(self.spec["source"]["tree"], text)
        self.assertIn(f"SOURCE_DATE_EPOCH={self.spec['source_date_epoch']}", text)
        for item in self.spec["output"]["files"]:
            self.assertIn(f"/output/dist/{item['to']}", text)
        self.assertLess(text.index("cmake --build"), text.index("strip -s /output/dist/flycast"))
        self.assertLess(text.index("strip -s /output/dist/flycast"), text.index("/output/elf.tsv"))

    def test_contract_names_forbidden_and_unaccounted_libraries(self):
        elf = {"flycast": {"soname": None, "needed": ["libSDL2-2.0.so.0", "libcurl.so.4", "libc.so.6"]},
               "lib64/libcurl.so.4": {"soname": "libcurl.so.4", "needed": ["libssl.so.1.1", "libz.so.1"]},
               "lib64/libssl.so.1.1": {"soname": "libssl.so.1.1", "needed": []}}
        self.assertEqual(standalone.contract_problems(self.spec, elf), [])
        elf["flycast"]["needed"] += ["libvulkan.so.1", "libfoo.so.1"]
        self.assertEqual(standalone.contract_problems(self.spec, elf), [
            "libfoo.so.1 is neither on the device nor shipped (needed by flycast)",
            "libvulkan.so.1 is forbidden (needed by flycast)"])

    def test_extends_replaces_top_level_keys_and_drops_abstract(self):
        raw = {"base": {"abstract": True, "toolchain": "arm64", "steps": ["a"], "env": {"X": "1"}},
               "child": {"extends": "base", "steps": ["b"]}}
        child = standalone.resolve(raw, "child")
        self.assertEqual((child["steps"], child["env"], child.get("abstract")), (["b"], {"X": "1"}, None))
        self.assertEqual(list(standalone.buildable({n: standalone.resolve(raw, n) for n in raw})), ["child"])
        with self.assertRaises(ValueError):
            standalone.resolve({"a": {"extends": "b"}, "b": {"extends": "a"}}, "a")

    def test_problems_are_reported(self):
        self.assertEqual(standalone.spec_problems(REPO, self.steps_spec()), [])
        bad = self.steps_spec(cmake={}, toolchain="nope", downloads=[{"url": "u", "sha256": "x", "path": "p"}],
                              patches=[{"diff": "patches/standalone/none.patch"}],
                              shipped={"files": {"other": "0" * 64}})
        problems = standalone.spec_problems(REPO, bad)
        for fragment in ("unknown toolchain", "exactly one of cmake and steps", "download u",
                         "does not exist", "shipped file other is not an output"):
            self.assertTrue(any(fragment in problem for problem in problems), fragment)
        mail = "patches/standalone/vtree/0001-nintendo-button-labels.patch"
        good = {"mail": mail, "committer": "A <a@example.org>", "commit": "1" * 40}
        self.assertEqual(standalone.spec_problems(REPO, self.steps_spec(patches=[good])), [])
        for broken in ({"mail": mail, "committer": "A <a@example.org>"}, {"mail": mail, "committer": "A", "commit": "1" * 40},
                       {"mail": mail, "diff": mail, "committer": "A <a@example.org>", "commit": "1" * 40}):
            self.assertEqual(len(standalone.spec_problems(REPO, self.steps_spec(patches=[broken]))), 1, broken)

    def test_patches_and_downloads_are_checked_in_the_script(self):
        spec = self.steps_spec(patches=[{"diff": "patches/standalone/x/a.patch"}],
                               downloads=[{"url": "https://example.org/t.tar.gz", "sha256": "a" * 64, "path": "/dl/t.tar.gz"}])
        script = standalone.render("x", spec, REPO.toolchains["arm64"])
        self.assertIn("git -C /src apply --check /recipe/patches/standalone/x/a.patch", script.text)
        self.assertIn(f"echo '{'a' * 64}  /dl/t.tar.gz' | sha256sum -c -", script.text)
        self.assertEqual(script.mounts, [("patches", "/recipe/patches")])
        self.assertLess(script.text.index("sha256sum -c"), script.text.index("make -j1"))

    def test_mails_recreate_their_commits(self):
        spec = self.steps_spec(patches=[{"mail": "patches/standalone/x/m.patch", "committer": "A B <a@example.org>",
                                         "commit": "2" * 40}, {"diff": "patches/standalone/x/a.patch"}])
        text = standalone.render("x", spec, REPO.toolchains["arm64"]).text
        am = ("GIT_COMMITTER_NAME='A B' GIT_COMMITTER_EMAIL=a@example.org "
              "git -C /src am -q --committer-date-is-author-date /recipe/patches/standalone/x/m.patch")
        self.assertIn(am, text)
        self.assertIn(f'test "$(git -C /src rev-parse HEAD)" = {"2" * 40}', text)
        self.assertLess(text.index(am), text.index("apply --check /recipe/patches/standalone/x/a.patch"))

    def test_elf_listing_and_shipped_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            tsv = Path(tmp) / "elf.tsv"
            tsv.write_text("emu\tneeded\tlibc.so.6\nlib/x.so\tsoname\tlibx.so.1\nlib/x.so\tneeded\tlibm.so.6\n")
            self.assertEqual(standalone.read_elf(tsv), {"emu": {"soname": None, "needed": ["libc.so.6"]},
                                                        "lib/x.so": {"soname": "libx.so.1", "needed": ["libm.so.6"]}})
        spec = {"shipped": {"files": {"emu": "1" * 64, "lib/x.so": "2" * 64, "gone": "3" * 64}}}
        files = {"emu": {"sha256": "1" * 64}, "lib/x.so": {"sha256": "9" * 64}}
        self.assertEqual(standalone.compare_shipped(spec, files), {"emu": "match", "lib/x.so": "differs", "gone": "missing"})
        spec["shipped"]["differs"] = {"lib/x.so": "a build date in the image"}
        self.assertEqual(standalone.compare_shipped(spec, files)["lib/x.so"], "differs, as known")


# A docker stand-in: the classic store names an image by its config digest, the containerd store by another digest.
FAKE_DOCKER = r'''
import hashlib, io, json, os, sys, tarfile
state_path = os.environ["FAKE_DOCKER_STATE"]
state = json.load(open(state_path)) if os.path.exists(state_path) else {"images": {}, "tags": {}}
def save():
    json.dump(state, open(state_path, "w"))
def resolve(ref):
    return state["tags"].get(ref) or (ref if ref in state["images"] else None)
args = sys.argv[1:]
if args[0] == "load":
    tar = tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()))
    entry = json.loads(tar.extractfile("manifest.json").read())[0]
    config = tar.extractfile(entry["Config"]).read()
    digest = "sha256:" + hashlib.sha256(config).hexdigest()
    image = digest if os.environ["FAKE_DOCKER_STORE"] == "classic" else "sha256:" + hashlib.sha256(b"m" + config).hexdigest()
    layers = json.loads(config)["rootfs"]["diff_ids"]
    state["images"][image] = {"layers": ["sha256:" + "0" * 64] if os.environ.get("FAKE_DOCKER_BAD") else layers}
    for tag in entry["RepoTags"]:
        state["tags"][tag] = image
    save()
    print("Loaded image: " + entry["RepoTags"][0])
elif args[:2] == ["image", "inspect"]:
    image = resolve(args[4])
    if image is None:
        sys.exit(1)
    print(image if args[3] == "{{.Id}}" else json.dumps(state["images"][image]["layers"]))
elif args[0] == "tag":
    state["tags"][args[2]] = resolve(args[1])
    save()
elif args[0] == "run":
    open(state_path + ".run", "w").write(json.dumps(args))
'''


class ToolchainImageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "docker").write_text(f"#!{sys.executable}\n" + FAKE_DOCKER)
        (self.tmp / "docker").chmod(0o755)
        self.env = dict(os.environ)
        os.environ["PATH"] = f"{self.tmp}{os.pathsep}{os.environ['PATH']}"
        os.environ["FAKE_DOCKER_STATE"] = str(self.tmp / "state.json")
        layer = b"layer"
        self.config = json.dumps({"rootfs": {"type": "layers",
                                             "diff_ids": ["sha256:" + hashlib.sha256(layer).hexdigest()]}}).encode()
        self.image_id = "sha256:" + hashlib.sha256(self.config).hexdigest()
        self.archive = self.tmp / "toolchain.tar.gz"
        config_name = "blobs/sha256/" + self.image_id[7:]
        manifest = json.dumps([{"Config": config_name, "RepoTags": ["fake-toolchain:latest"],
                                "Layers": ["blobs/sha256/layer"]}]).encode()
        with tarfile.open(self.archive, "w:gz") as tar:
            for name, data in ((config_name, self.config), ("blobs/sha256/layer", layer), ("manifest.json", manifest)):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        shutil.rmtree(self.tmp)

    def run_one(self):
        script = recipe.Script(text="true", mounts=[])
        self.assertEqual(build.run_container(REPO, self.image_id, script, self.tmp / "out"), 0)
        return json.loads((self.tmp / "state.json.run").read_text())

    def test_classic_store_uses_the_config_digest(self):
        os.environ["FAKE_DOCKER_STORE"] = "classic"
        self.assertEqual(build.load_toolchain(self.archive, self.image_id), self.image_id)
        self.assertIn(self.image_id, self.run_one())
        self.assertNotIn(build.alias(self.image_id), json.loads((self.tmp / "state.json").read_text())["tags"])

    def test_containerd_store_is_reached_through_the_alias(self):
        os.environ["FAKE_DOCKER_STORE"] = "containerd"
        self.assertFalse(build.image_present(self.image_id))
        self.assertEqual(build.load_toolchain(self.archive, self.image_id), build.alias(self.image_id))
        self.assertTrue(build.image_present(self.image_id))
        self.assertIn(build.alias(self.image_id), self.run_one())

    def test_an_archive_of_another_image_is_refused(self):
        os.environ["FAKE_DOCKER_STORE"] = "containerd"
        with self.assertRaisesRegex(RuntimeError, "holds image"):
            build.load_toolchain(self.archive, "sha256:" + "1" * 64)
        self.assertFalse(build.image_present("sha256:" + "1" * 64))

    def test_a_loaded_image_without_the_archive_layers_is_refused(self):
        os.environ["FAKE_DOCKER_STORE"] = "containerd"
        os.environ["FAKE_DOCKER_BAD"] = "1"
        with self.assertRaisesRegex(RuntimeError, "does not have the layers"):
            build.load_toolchain(self.archive, self.image_id)
        self.assertFalse(build.image_present(self.image_id))

    def test_a_missing_image_stops_the_build(self):
        os.environ["FAKE_DOCKER_STORE"] = "containerd"
        with self.assertRaisesRegex(RuntimeError, "is not loaded"):
            build.run_container(REPO, self.image_id, recipe.Script(text="true", mounts=[]), self.tmp / "out")


class InventoryTest(unittest.TestCase):
    def test_generate_reads_systems_and_hashes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            config = {"default_emulator": "foo", "devices": ["A"],
                      "menuOptions": {"Emulator_64": {"devices": ["B"], "options": ["foo", "bar-standalone"]},
                                      "Governor": {"options": ["x"]}}}
            (repo / "Emu/SYS").mkdir(parents=True)
            (repo / "Emu/SYS/config.json").write_text(json.dumps(config))
            (repo / "Emu/SYS/bar").write_bytes(b"bar")
            (repo / "RetroArch/.retroarch/cores64").mkdir(parents=True)
            (repo / "RetroArch/.retroarch/cores64/foo_libretro.so").write_bytes(b"foo")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.org",
                            "commit", "-q", "-m", "x"], check=True)
            data = inventory.generate(repo, "HEAD", {"bar-standalone": {"paths": ["Emu/SYS/bar"]}})
        self.assertEqual(data["systems"]["SYS"], {"devices": ["A"], "default": "foo",
                                                  "options": {"Emulator_64": {"devices": ["B"],
                                                                              "options": ["foo", "bar-standalone"]}}})
        self.assertEqual(data["files"], {"Emu/SYS/bar": hashlib.sha256(b"bar").hexdigest(),
                                         "RetroArch/.retroarch/cores64/foo_libretro.so": hashlib.sha256(b"foo").hexdigest()})

    def test_coverage_classes_every_offered_file(self):
        sha = {name: hashlib.sha256(name.encode()).hexdigest() for name in ("a", "b", "c", "d")}
        inv = {"spruceos": {"commit": "0" * 40, "date": "2026-11-18"},
               "systems": {"S": {"devices": None, "default": "a", "options": {
                   "Emulator": {"devices": ["X"], "options": ["a", "b", "c-standalone", "mystery", "Flycast-libretro",
                                                              "d-standalone", "closed", "base"]}}}},
               "files": {"RetroArch/.retroarch/cores64/a_libretro.so": sha["a"],
                         "RetroArch/.retroarch/cores/b_libretro.so": sha["b"],
                         "Emu/S/c": sha["c"], "Emu/S/d": sha["d"]}}
        names = {"c-standalone": {"paths": ["Emu/S/c"]}, "d-standalone": {"paths": ["Emu/S/d"]},
                 "Flycast-libretro": {"core": "flycast"}, "closed": {"closed_source": "no source"},
                 "base": {"base_image": "a base OS package"}}
        catalog = {"a": {"targets": ["arm64"], "build": {"artifact_name": "a_libretro.so"},
                         "shipped": {"files": {"RetroArch/.retroarch/cores64/a_libretro.so": sha["a"]}}},
                   "b": {"targets": ["armhf"], "build": {"artifact_name": "b_libretro.so"}}}
        standalones = {"c-old": {"output": {"files": [{"to": "c"}], "spruce": {"c": "Emu/S/c-renamed"}},
                                 "shipped": {"files": {"c": sha["c"]}}}}
        rows = {(r["name"], r["path"]): r for r in inventory.coverage(inv, names, catalog, standalones)}
        self.assertEqual(rows[("a", "RetroArch/.retroarch/cores64/a_libretro.so")]["status"], "reproduces")
        self.assertEqual(rows[("b", "RetroArch/.retroarch/cores/b_libretro.so")]["status"], "recipe")
        self.assertEqual(rows[("c-standalone", "Emu/S/c")]["status"], "reproduces")  # recorded at a renamed path
        self.assertEqual(rows[("d-standalone", "Emu/S/d")]["status"], "no recipe")
        # A record no build has matched yet counts as a recipe, at its own path or a renamed one.
        standalones["d-new"] = {"output": {"files": [{"to": "d"}], "spruce": {"d": "Emu/S/d"}},
                                "shipped": {"unverified": True, "files": {"d": sha["d"]}}}
        standalones["c-old"]["shipped"]["unverified"] = True
        rows = {(r["name"], r["path"]): r for r in inventory.coverage(inv, names, catalog, standalones)}
        self.assertEqual(rows[("d-standalone", "Emu/S/d")]["status"], "recipe")
        self.assertEqual(rows[("c-standalone", "Emu/S/c")]["status"], "no recipe")
        # A file the record knows the build does not reproduce counts as a recipe, never as reproduced.
        standalones["d-new"]["shipped"] = {"differs": {"d": "a build date in the image"}, "files": {"d": sha["d"]}}
        rows = {(r["name"], r["path"]): r for r in inventory.coverage(inv, names, catalog, standalones)}
        self.assertEqual(rows[("d-standalone", "Emu/S/d")]["status"], "recipe")
        self.assertEqual(rows[("mystery", "")]["status"], "unresolved")
        self.assertEqual(rows[("Flycast-libretro", "")]["status"], "not shipped")
        self.assertEqual(rows[("closed", "")]["status"], "closed source")
        self.assertEqual(rows[("base", "")]["status"], "base image")
        self.assertEqual(rows[("base", "")]["note"], "a base OS package")
        self.assertIn("S (default)", rows[("a", "RetroArch/.retroarch/cores64/a_libretro.so")]["where"])

    def test_committed_inventory_and_names_are_consistent(self):
        names = json.loads((ROOT / "manifests/emulator-names.json").read_text())["names"]
        data = json.loads((ROOT / "manifests/emulator-inventory.json").read_text())
        self.assertEqual(inventory.check(names, data), [])
        self.assertRegex(data["spruceos"]["commit"], r"^[0-9a-f]{40}$")
        self.assertTrue(inventory.report(inventory.coverage(data, names, REPO.cores, standalone.buildable(
            standalone.load(REPO))), data).startswith("# Emulator inventory coverage"))


if __name__ == "__main__":
    unittest.main()
