import ast
import pathlib
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestVersion(unittest.TestCase):
    def test_addon_and_importer_share_version(self):
        manifest = tomllib.loads((ROOT / "addon" / "blender_manifest.toml").read_text(encoding="utf-8"))["version"]
        cargo = tomllib.loads((ROOT / "importer" / "Cargo.toml").read_text(encoding="utf-8"))["package"]["version"]
        module = ast.parse((ROOT / "addon" / "__init__.py").read_text(encoding="utf-8"))
        bl_info = next(ast.literal_eval(node.value) for node in module.body if isinstance(node, ast.Assign) and node.targets[0].id == "bl_info")
        self.assertEqual(cargo, manifest)
        self.assertEqual(".".join(str(part) for part in bl_info["version"]), manifest)


if __name__ == "__main__":
    unittest.main()
