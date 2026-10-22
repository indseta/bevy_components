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

    def test_component_errors_leave_out_the_object_name(self):
        component = item(component_type="CUSTOM", custom_type=" ", custom_json="oops")
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

    def test_empty(self):
        self.assertEqual(json.loads(metadata.serialize_items([])), {"version": 1, "components": []})


if __name__ == "__main__":
    unittest.main()
