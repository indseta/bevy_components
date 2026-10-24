import importlib
import json
import pathlib
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "importer" / "tests" / "assets" / "bevy_components_schema.json"
package = types.ModuleType("bevy_schema_addon")
package.__path__ = [str(ROOT / "addon")]
sys.modules.setdefault("bevy_schema_addon", package)
schema = importlib.import_module("bevy_schema_addon.schema")


def document(*components, version=1):
    return json.dumps({"version": version, "components": list(components)})


class TestSchema(unittest.TestCase):
    def test_reads_the_importer_fixture(self):
        types = schema.parse_schema(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(sorted(types), ["my_game::Patrol", "my_game::Reward"])
        patrol = types["my_game::Patrol"]
        self.assertEqual([(field.name, field.field_type, field.rust_type, field.default) for field in patrol.fields], [("speed", "FLOAT", "f32", 2.0), ("mode", "ENUM", "my_game::PatrolMode", "Loop"), ("offset", "VECTOR2", "glam::Vec2", (0.0, 0.0)), ("stops", "INT", "u8", 1)])
        self.assertEqual(patrol.fields[1].variants, "Loop, PingPong")
        self.assertEqual(patrol.others, [("timer", "bevy_time::timer::Timer")])
        self.assertTrue(patrol.has_default)
        self.assertEqual([(field.identifier, field.field_type) for field in types["my_game::Reward"].fields], [("0", "INT"), ("1", "FLOAT")])
        self.assertEqual((patrol.tuple_struct, types["my_game::Reward"].tuple_struct), (False, True))

    def test_missing_or_odd_defaults_fall_back(self):
        fields = [{"name": "tint", "type": "color"}, {"name": "mode", "type": "enum", "variants": ["Idle", "Run"], "default": "Fly"}, {"name": "count", "type": "int", "default": 2 ** 40}, {"name": "aim", "type": "vector2", "default": [1, "x"]}, {"name": "path", "type": "other", "rust_type": "alloc::vec::Vec<f32>"}]
        game_type = schema.parse_schema(document({"type_path": "game::Walker", "fields": fields}))["game::Walker"]
        self.assertEqual([field.default for field in game_type.fields], [(1.0, 1.0, 1.0, 1.0), "Idle", 0, (0.0, 0.0)])
        self.assertEqual(game_type.others, [("path", "alloc::vec::Vec<f32>")])
        self.assertFalse(game_type.has_default)

    def test_rejects_broken_files(self):
        for text, message in (("{", "not valid JSON"), ("[]", "lists no components"), (document(version=2), "has version 2"), (document({"fields": []}), "no type path"), (document({"type_path": "game::Tag", "fields": [1]}), "no type path or fields")):
            with self.assertRaisesRegex(schema.SchemaError, message):
                schema.parse_schema(text)

    def test_finds_the_schema_above_the_blend_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            scenes = root / "assets" / "scenes"
            scenes.mkdir(parents=True)
            self.assertIsNone(schema.find_schema(scenes))
            (root / schema.SCHEMA_FILE).write_text(document(), encoding="utf-8")
            self.assertEqual(schema.find_schema(scenes), root / schema.SCHEMA_FILE)

    def test_short_names(self):
        self.assertEqual(schema.short_name("my_game::stats::Health"), "Health")
        self.assertEqual(schema.short_name("my_game::Wrapper<my_game::Coin>"), "Wrapper<my_game::Coin>")
        self.assertEqual(schema.short_name("Marker"), "Marker")


if __name__ == "__main__":
    unittest.main()
