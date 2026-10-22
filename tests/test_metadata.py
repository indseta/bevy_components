import importlib.util
import json
import pathlib
import types
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "addon" / "metadata.py"
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
        component = item(component_type="COLLIDER", collider_shape="CONVEX", collider_size=(1, 2, 3), collider_radius=0.5, collider_height=1.0, collider_sensor=True, collider_friction=0.25, collider_restitution=0.75, collider_memberships=[index in {0, 3} for index in range(32)], collider_filters=[index != 1 for index in range(32)])
        result = json.loads(metadata.serialize_items([component]))
        self.assertEqual(result["components"][0], {"type": "collider", "shape": "convex", "size": [1, 2, 3], "radius": 0.5, "height": 1.0, "sensor": True, "friction": 0.25, "restitution": 0.75, "memberships": 0b1001, "filters": 0xFFFFFFFD})

    def test_collider_layer_extremes(self):
        component = item(component_type="COLLIDER", collider_shape="CUBOID", collider_size=(1, 1, 1), collider_radius=0.5, collider_height=1.0, collider_sensor=False, collider_friction=0.5, collider_restitution=0.0, collider_memberships=[False] * 32, collider_filters=[True] * 32)
        result = json.loads(metadata.serialize_items([component]))["components"][0]
        self.assertEqual((result["memberships"], result["filters"]), (0, 2**32 - 1))

    def test_rigid_body_mass(self):
        component = item(component_type="RIGID_BODY", rigid_body_kind="DYNAMIC", rigid_body_use_mass=False, rigid_body_mass=12.5)
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0], {"type": "rigid_body", "kind": "dynamic", "mass": None})
        component.rigid_body_use_mass = True
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0]["mass"], 12.5)
        for kind in ("STATIC", "KINEMATIC"):
            component.rigid_body_kind = kind
            self.assertIsNone(json.loads(metadata.serialize_items([component]))["components"][0]["mass"], kind)

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
