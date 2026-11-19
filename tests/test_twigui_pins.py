"""scripts/twigui_pins.py: which package.mk TwigUI-Next's build picks, and the fields read from it."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import twigui_pins  # noqa: E402


class TwiguiPinsTest(unittest.TestCase):
    def test_package_dir_prefers_device_then_project_then_global(self):
        tree = ["packages/emulators/x-lr/package.mk", "projects/ROCKNIX/packages/x-lr/package.mk",
                "projects/twigUI/packages/emulators/x-lr/package.mk",
                "projects/twigUI/devices/RK3326S/packages/y-lr/package.mk", "packages/y-lr/package.mk",
                "packages/z-lr/package.mk"]
        self.assertEqual(twigui_pins.package_dir(tree, "x-lr", "RK3326S"), "projects/twigUI/packages/emulators/x-lr")
        self.assertEqual(twigui_pins.package_dir(tree, "y-lr", "RK3326S"), "projects/twigUI/devices/RK3326S/packages/y-lr")
        self.assertEqual(twigui_pins.package_dir(tree, "z-lr", "RK3326S"), "packages/z-lr")
        with self.assertRaises(SystemExit):  # two local package.mk files is the build system's own failure
            twigui_pins.package_dir(tree + ["projects/twigUI/packages/other/x-lr/package.mk"], "x-lr", "RK3326S")

    def test_fields_expand_site_and_version(self):
        text = 'PKG_NAME="a5200-lr"\nPKG_VERSION="23c1ea4"\nPKG_SITE="https://github.com/libretro/a5200"\n' \
               'PKG_URL="${PKG_SITE}/archive/${PKG_VERSION}.tar.gz"\nPKG_VERSION="ignored, the first wins"\n'
        self.assertEqual(twigui_pins.fields(text, "a5200-lr"),
                         {"PKG_VERSION": "23c1ea4", "PKG_SITE": "https://github.com/libretro/a5200",
                          "PKG_URL": "https://github.com/libretro/a5200/archive/23c1ea4.tar.gz"})

    def test_committed_pins_are_complete(self):
        data = json.loads((ROOT / "manifests/waves/pixel2-twiguinext.json").read_text())
        kinds = [entry["kind"] for entry in data["files"].values()]
        self.assertEqual(kinds.count("core"), 71)
        self.assertEqual(len(kinds) - kinds.count("core"), 13)  # standalones, their libraries and data
        for path, entry in data["files"].items():
            self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$", path)
            self.assertTrue(entry["version"] and entry["package_dir"].startswith("projects/twigUI/"), path)

    def test_a_folder_is_fingerprinted_by_its_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            Path(d, "a").write_text("1"); Path(d, "sub").mkdir(); Path(d, "sub", "b").write_text("2")
            digest, count = twigui_pins.tree_sha256(Path(d))
            self.assertEqual(count, 2)
            Path(d, "sub", "b").write_text("3")
            self.assertNotEqual(twigui_pins.tree_sha256(Path(d))[0], digest)


if __name__ == "__main__":
    unittest.main()
