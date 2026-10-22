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


def field(name, field_type, value):
    values = {"float_value": 0.0, "int_value": 0, "bool_value": False, "string_value": "", "vector_value": (0.0, 0.0, 0.0), "color_value": (1.0, 1.0, 1.0, 1.0)}
    values[metadata.FIELD_VALUES[field_type]] = value
    return item(name=name, field_type=field_type, **values)


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
        component = item(component_type="CUSTOM", custom_type="game::Marker", custom_json='{"value":42}', use_fields=False, fields=[])
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0]["data"]["value"], 42)
        component.custom_json = "oops"
        self.assertTrue(metadata.validate_items([component]))
        with self.assertRaises(ValueError):
            metadata.serialize_items([component])

    def test_component_errors_leave_out_the_object_name(self):
        component = item(component_type="CUSTOM", custom_type=" ", custom_json="oops", use_fields=False)
        self.assertEqual(metadata.component_errors(component), ["Custom Component needs a Rust type path", "invalid JSON in Custom Component"])
        self.assertEqual(metadata.validate_items([component], "lamp"), ["lamp: Custom Component needs a Rust type path", "lamp: invalid JSON in Custom Component"])

    def test_matching_levels_of_detail_crossfade(self):
        self.assertEqual(metadata.visibility_range_problems([("far", (80, 85, 250, 260)), ("near", (0, 0, 20, 25)), ("mid", (20, 25, 80, 85))]), [])

    def test_gaps_between_levels_of_detail(self):
        self.assertEqual(metadata.visibility_range_problems([("near", (0, 0, 20, 25)), ("far", (30, 35, 80, 85))]), [("far", "Gap after near: nothing shows from 25 to 30 m")])

    def test_overlapping_levels_of_detail(self):
        self.assertEqual(metadata.visibility_range_problems([("near", (0, 0, 20, 25)), ("far", (0, 0, 100, 120))]), [("far", "Shows together with near from 0 to 20 m")])

    def test_mismatched_fade_margins(self):
        self.assertEqual(metadata.visibility_range_problems([("near", (0, 0, 20, 25)), ("far", (22.5, 24, 80, 85))]), [("far", "Fades in over 22.5–24 m but near fades out over 20–25 m, so they do not crossfade")])

    def test_parts_of_one_level_of_detail_share_its_range(self):
        entries = [("trunk", (0, 0, 20, 25)), ("leaves", (0, 0, 20, 25)), ("far_trunk", (30, 35, 80, 85)), ("far_leaves", (30, 35, 80, 85))]
        self.assertEqual(metadata.visibility_range_problems(entries), [("far_trunk", "Gap after trunk: nothing shows from 25 to 30 m"), ("far_leaves", "Gap after trunk: nothing shows from 25 to 30 m")])

    def test_custom_fields(self):
        fields = [field("count", "INT", 3), field("delay", "FLOAT", 0.10000000149011612), field("label", "STRING", "Wave ✦"), field("boss", "BOOL", True), field("offset", "VECTOR", (0.0, 1.5, -2.0)), field("tint", "COLOR", (1.0, 0.800000011920929, 0.20000000298023224, 1.0))]
        component = item(component_type="CUSTOM", custom_type="game::Wave", custom_json="{broken", use_fields=True, fields=fields)
        self.assertEqual(metadata.validate_items([component]), [])
        data = json.loads(metadata.serialize_items([component]))["components"][0]
        self.assertEqual(data, {"type": "custom", "type_path": "game::Wave", "data": {"count": 3, "delay": 0.1, "label": "Wave ✦", "boss": True, "offset": [0.0, 1.5, -2.0], "tint": {"Srgba": {"red": 1.0, "green": 0.8, "blue": 0.2, "alpha": 1.0}}}})
        self.assertIsInstance(data["data"]["count"], int)

    def test_custom_fields_need_unique_names(self):
        for names in (["speed", "speed"], ["speed", " "]):
            component = item(component_type="CUSTOM", custom_type="game::Mover", use_fields=True, fields=[field(name, "FLOAT", 1.0) for name in names])
            self.assertEqual(metadata.validate_items([component], "car"), ["car: game::Mover needs a unique name for every field"])
        self.assertEqual(metadata.invalid_names(["a", "b", "a", ""]), {"a", ""})

    def test_float32_values_are_short(self):
        for value, expected in ((0.10000000149011612, 0.1), (1.0, 1.0), (16777217.0, 16777216.0), (3.4028234663852886e38, 3.4028235e38), (1e-45, 1e-45)):
            self.assertEqual(metadata._float32(value), expected)

    def test_convert_value(self):
        cases = [
            ("FLOAT", 3, 3.0),
            ("FLOAT", "3", None),
            ("FLOAT", True, None),
            ("INT", 2.6, 3),
            ("INT", 2 ** 31, None),
            ("INT", False, None),
            ("BOOL", True, True),
            ("BOOL", 1, None),
            ("STRING", "coin", "coin"),
            ("STRING", 5, None),
            ("VECTOR", [1, 2.5, 3], (1.0, 2.5, 3.0)),
            ("VECTOR", [1, 2], None),
            ("VECTOR", [1, "2", 3], None),
            ("COLOR", [1, 0.5, 0], (1.0, 0.5, 0.0, 1.0)),
            ("COLOR", [1, 0.5, 0, 0.25], (1.0, 0.5, 0.0, 0.25)),
            ("COLOR", {"Srgba": {"red": 1, "green": 0.5, "blue": 0, "alpha": 0.25}}, (1.0, 0.5, 0.0, 0.25)),
            ("COLOR", {"Srgba": {"red": 1, "green": 0.5, "blue": 0}}, (1.0, 0.5, 0.0, 1.0)),
            ("COLOR", {"Srgba": {"red": 1, "green": 0.5}}, None),
            ("COLOR", {"LinearRgba": {"red": 1, "green": 0.5, "blue": 0, "alpha": 1}}, None),
            ("FLOAT", float("inf"), None),
        ]
        for kind, value, expected in cases:
            self.assertEqual(metadata.convert_value(kind, value), expected, (kind, value))

    def test_infer_fields(self):
        data = {"count": 3, "delay": 1.5, "boss": False, "label": "x", "offset": [0, 1, 0], "tint": [1, 1, 1, 1], "glow": {"Srgba": {"red": 1, "green": 1, "blue": 1, "alpha": 1}}}
        self.assertEqual(metadata.infer_fields(data), [("count", "INT", 3), ("delay", "FLOAT", 1.5), ("boss", "BOOL", False), ("label", "STRING", "x"), ("offset", "VECTOR", (0.0, 1.0, 0.0)), ("tint", "COLOR", (1.0, 1.0, 1.0, 1.0)), ("glow", "COLOR", (1.0, 1.0, 1.0, 1.0))])
        with self.assertRaisesRegex(ValueError, "No field type fits target, path"):
            metadata.infer_fields({"count": 3, "target": None, "path": [[0, 0]]})
        with self.assertRaisesRegex(ValueError, "Only a JSON object"):
            metadata.infer_fields(0.25)

    def test_empty(self):
        self.assertEqual(json.loads(metadata.serialize_items([])), {"version": 1, "components": []})


if __name__ == "__main__":
    unittest.main()
