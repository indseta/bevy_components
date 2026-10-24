import importlib.util
import pathlib
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bevy_release_notes", ROOT / "scripts" / "release_notes.py")
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)

CHANGELOG = "# Changelog\n\n## 0.5.0 (2026-10-24)\n\n### Added\n\n- Play\n\n## 0.4.0 (2026-10-23)\n\n- Lightmaps\n"


class TestLicenses(unittest.TestCase):
    def test_addon_is_gpl(self):
        manifest = tomllib.loads((ROOT / "addon" / "blender_manifest.toml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["license"], ["SPDX:GPL-3.0-or-later"])
        self.assertIn("GNU GENERAL PUBLIC LICENSE", (ROOT / "LICENSE").read_text(encoding="utf-8"))

    def test_importer_is_mit(self):
        cargo = tomllib.loads((ROOT / "importer" / "Cargo.toml").read_text(encoding="utf-8"))
        self.assertEqual(cargo["package"]["license"], "MIT")
        self.assertTrue((ROOT / "importer" / "LICENSE").read_text(encoding="utf-8").startswith("MIT License\n"))


class TestReleaseNotes(unittest.TestCase):
    def test_notes_hold_the_version_section(self):
        notes = release_notes.notes("0.5.0", CHANGELOG)
        self.assertTrue(notes.startswith("Download bevy_components_0_5_0.zip for the Blender addon and bevy_components_importer_0_5_0.zip"))
        self.assertIn("### Added\n\n- Play", notes)
        self.assertNotIn("Lightmaps", notes)

    def test_last_section_runs_to_the_end(self):
        self.assertTrue(release_notes.notes("0.4.0", CHANGELOG).endswith("\n\n- Lightmaps\n"))

    def test_links_point_at_the_release_tag(self):
        notes = release_notes.notes("0.5.0", "## 0.5.0\n\n- See [Play](docs/play.md), [Viewer](docs/play.md#viewer), [Bevy](https://bevy.org) and [below](#upgrading)\n")
        self.assertIn("[Play](https://github.com/indseta/bevy_components/blob/bevy_components_0_5_0/docs/play.md)", notes)
        self.assertIn("[Viewer](https://github.com/indseta/bevy_components/blob/bevy_components_0_5_0/docs/play.md#viewer)", notes)
        self.assertIn("[Bevy](https://bevy.org) and [below](#upgrading)", notes)

    def test_version_without_section_gets_download_line(self):
        self.assertEqual(release_notes.notes("0.4.1", CHANGELOG), "Download bevy_components_0_4_1.zip for the Blender addon and bevy_components_importer_0_4_1.zip for the Rust importer. See the README for installation.\n")


if __name__ == "__main__":
    unittest.main()
