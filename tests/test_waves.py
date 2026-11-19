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


if __name__ == "__main__":
    unittest.main()
