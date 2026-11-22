"""scripts/waves.py: the hand-kept facts that survive regeneration, and how edge picks a tag or a tip."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import waves  # noqa: E402


class WavesTest(unittest.TestCase):
    def test_carry_keeps_facts_only_while_the_file_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(waves, "WAVES", Path(d)):
            Path(d, "w.json").write_text(json.dumps({"files": {
                "a": {"sha256": "1", "pin": {"commit": "c"}, "verified": "byte for byte: run 1"},
                "b": {"sha256": "2", "pin": {"commit": "d"}}}}))
            out = waves.carry("w", "files", {"a": {"sha256": "1"}, "b": {"sha256": "3"}, "c": {"sha256": "4"}})
        self.assertEqual(out["a"]["pin"], {"commit": "c"})
        self.assertEqual(out["a"]["verified"], "byte for byte: run 1")
        self.assertNotIn("pin", out["b"])  # the file changed: its old pin no longer holds
        self.assertEqual(out["c"], {"sha256": "4"})

    def test_release_tags(self):
        for tag in ("v2.7", "1.53", "r24", "v1.0.0.02"):
            self.assertRegex(tag, waves.RELEASE_TAG)
        for tag in ("v0.3.0-beta", "1.52fix4", "latest", "nightly"):
            self.assertNotRegex(tag, waves.RELEASE_TAG)
        self.assertEqual(sorted(["v2.10", "v2.9", "v2.7"], key=waves.version_key)[-1], "v2.10")

    def test_edge_takes_a_tag_only_when_it_is_newer_than_the_pin(self):
        refs = [("t1", "refs/tags/v1.0"), ("t1c", "refs/tags/v1.0^{}"), ("tip", "refs/heads/master"), ("tip", "HEAD")]
        source = {"url": "https://github.com/o/r.git", "commit": "pin", "requested_ref": "refs/heads/master"}
        dates = {"pin": "2026-01-01T00:00:00Z", "t1c": "2026-06-01T00:00:00Z", "tip": "2026-11-01T00:00:00Z"}
        with mock.patch.object(waves, "ls_remote", return_value=refs), \
                mock.patch.object(waves, "commit_date", side_effect=lambda url, c: dates.get(c)):
            self.assertEqual(waves.edge_of(source)["edge"], {"kind": "tag", "tag": "v1.0", "commit": "t1c",
                                                             "date": dates["t1c"]})
            dates["t1c"] = "2025-01-01T00:00:00Z"  # the tag predates the pin: the branch tip it is
            edge = waves.edge_of(source)["edge"]
        self.assertEqual((edge["kind"], edge["commit"], edge["why"]), ("tip", "tip", "newest tag is not newer than the pin"))

    def test_nightly_log_gives_the_tag_and_the_development_commit(self):
        log = ("build\tRun\t2026-11-19T06:00:01Z Release tag for this run: v4.6.0-20261119\x1b[0m\n"
               "build\tRun\t2026-11-19T06:00:02Z Current Development commit: " + "d7ce3dc5" * 5 + "\n")
        self.assertEqual(waves.parse_nightly_log(log), ("v4.6.0-20261119", "d7ce3dc5" * 5))
        self.assertEqual(waves.parse_nightly_log("no such lines"), (None, None))

    def test_record_statuses(self):
        records = {"old": {"Emu/X/x": "1"}, "new": {"Emu/X/x": "2"}, "pair": {"a": "3", "b": "4"},
                   "gone": {"Emu/Y/y": "5"}, "half": {"Emu/X/x": "1", "lib": "6"}}
        out = waves.record_statuses(records, {"Emu/X/x": "2", "a": "3", "b": "9", "Emu/Y/y": None, "lib": "6"})
        self.assertEqual(out["half"], {"files": 2, "status": "partial", "differ": {"Emu/X/x": "other bytes"},
                                       "by": ["new"]})
        self.assertEqual(out["new"], {"files": 1, "status": "match"})
        self.assertEqual(out["old"], {"files": 1, "status": "replaced", "differ": {"Emu/X/x": "other bytes"},
                                      "by": ["new"]})
        self.assertEqual(out["pair"], {"files": 2, "status": "partial", "differ": {"b": "other bytes"}})
        self.assertEqual(out["gone"], {"files": 1, "status": "not shipped", "differ": {"Emu/Y/y": "absent"}})

    def test_shipped_records_leave_out_retired_files_and_other_packages(self):
        digest = "0" * 64
        raw = {"builds": {
            "gone": {"shipped": {"spruceos": "a", "files": {"x": digest}, "retired": {"x": "removed"}}},
            "some": {"shipped": {"spruceos": "a", "files": {"x": digest, "lib/y": digest}, "retired": {"lib/y": "gone"}}},
            "pkg": {"shipped": {"source": "a package", "files": {"x": digest}}}}}
        builds = {name: {"output": {"spruce": {"x": f"Emu/{name}/x", "lib/": f"Emu/{name}/lib/"}}} for name in raw["builds"]}
        repo = mock.Mock(cores={"core": {"shipped": {"spruceos": "a", "files": {"RetroArch/c.so": digest}}}})
        with mock.patch.object(waves, "load_json", return_value=raw):
            checked, skipped, retired = waves.shipped_records(repo, builds)
        self.assertEqual(checked, {"core": {"RetroArch/c.so": digest}, "standalone:some": {"Emu/some/x": digest}})
        self.assertEqual(skipped, {"standalone:gone": {"files": 1, "status": "retired"},
                                   "standalone:pkg": {"files": 1, "status": "elsewhere", "source": "a package"}})
        self.assertEqual(retired, {"standalone:some": 1})

    def test_diff_lists_each_change_once(self):
        old = {"defined_by": {"commit": "a" * 40}, "files": {"f": {"sha256": "1", "status": "recipe"},
                                                             "g": {"sha256": "2", "status": "reproduces"},
                                                             "h": {"sha256": "3", "status": "recipe"},
                                                             "s": {"sha256": "6", "status": "recipe", "spare": True}},
               "records": {"r": {"status": "match"}}}
        new = {"defined_by": {"commit": "b" * 40, "nightly": {"tag": "v4.6.0-20261120"}},
               "files": {"f": {"sha256": "1", "status": "reproduces"}, "g": {"sha256": "5", "status": "reproduces"},
                         "i": {"sha256": "4", "status": "no recipe"},
                         "s": {"sha256": "6", "status": "recipe", "families": ["MIYOO_A30"]}},
               "records": {"r": {"status": "replaced"}}}
        self.assertEqual(waves.diff(old, new), [
            "defined by: aaaaaaaaa -> nightly v4.6.0-20261120 (bbbbbbbbb)",
            "~ f: recipe -> reproduces", "~ g: new bytes, still reproduces", "- h (was recipe)", "+ i: no recipe",
            "~ s: no longer spare (MIYOO_A30)", "record r: match -> replaced"])
        self.assertEqual(waves.diff(new, new), [])


if __name__ == "__main__":
    unittest.main()
