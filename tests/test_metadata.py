import importlib.util
import json
import pathlib
import types
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "bevy_components" / "metadata.py"
spec = importlib.util.spec_from_file_location("bevy_metadata", MODULE)
metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata)


def item(**kwargs):
    return types.SimpleNamespace(**kwargs)


class TestMetadata(unittest.TestCase):
    def test_visibility(self):
        component = item(component_type="VISIBILITY_RANGE", fade_in_start=0, fade_in_end=0, fade_out_start=20, fade_out_end=25, use_aabb=False)
        result = json.loads(metadata.serialize_items([component]))
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["components"][0], {"type": "visibility_range", "start": [0, 0], "end": [20, 25], "use_aabb": False})
        self.assertEqual(metadata.validate_items([component]), [])

    def test_invalid_visibility(self):
        component = item(component_type="VISIBILITY_RANGE", fade_in_start=5, fade_in_end=20, fade_out_start=10, fade_out_end=25)
        self.assertTrue(metadata.validate_items([component]))

    def test_collider(self):
        component = item(component_type="COLLIDER", collider_shape="CONVEX", collider_size=(1, 2, 3), collider_radius=0.5, collider_height=1.0, collider_sensor=True)
        result = json.loads(metadata.serialize_items([component]))
        self.assertEqual(result["components"][0]["shape"], "convex")
        self.assertTrue(result["components"][0]["sensor"])

    def test_custom(self):
        component = item(component_type="CUSTOM", custom_type="game::Marker", custom_json='{"value":42}')
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0]["data"]["value"], 42)
        component.custom_json = "oops"
        self.assertTrue(metadata.validate_items([component]))
        with self.assertRaises(ValueError):
            metadata.serialize_items([component])

    def test_empty(self):
        self.assertEqual(json.loads(metadata.serialize_items([])), {"version": 1, "components": []})


if __name__ == "__main__":
    unittest.main()
