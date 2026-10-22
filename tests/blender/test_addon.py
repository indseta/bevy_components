import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import bpy
import gpu
from mathutils import Matrix, Vector

from sample_level import COMPRESSED_FIXTURES, FIXTURE, add_component, add_empty, add_mesh, apply_lod_preset, build_sample_level, clear_scene, export_sample_level, install_addon, layers, read_gltf, select, uninstall_addon

LAYOUT = bpy.types.UILayout.bl_rna
ICONS = set(LAYOUT.functions["label"].parameters["icon"].enum_items.keys())
CHILD_LAYOUTS = {"row", "column", "box", "split", "grid_flow", "column_flow"}
DEFAULT_COLLIDER = {"size": [1.0, 1.0, 1.0], "radius": 0.5, "height": 1.0, "sensor": False, "friction": 0.5, "restitution": 0.0, "memberships": 1, "filters": 4294967295}
STATIC_BODY = {"type": "rigid_body", "kind": "static", "mass": None}
DYNAMIC_BODY = {"type": "rigid_body", "kind": "dynamic", "mass": None}
EXPECTED_COMPONENTS = {
    "ground": [
        {"type": "collider", "shape": "trimesh", **DEFAULT_COLLIDER},
        STATIC_BODY,
    ],
    "crate": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [2.0, 2.0, 2.0], "friction": 0.8, "restitution": 0.1}},
        DYNAMIC_BODY,
        {"type": "visibility_range", "start": [20.0, 25.0], "end": [80.0, 85.0], "use_aabb": False},
    ],
    "crate_copy": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [2.0, 2.0, 2.0], "friction": 0.8, "restitution": 0.1}},
        DYNAMIC_BODY,
        {"type": "visibility_range", "start": [20.0, 25.0], "end": [80.0, 85.0], "use_aabb": False},
    ],
    "ball": [
        {"type": "collider", "shape": "sphere", **DEFAULT_COLLIDER},
        {"type": "rigid_body", "kind": "kinematic", "mass": None},
    ],
    "pillar": [
        {"type": "collider", "shape": "capsule", **{**DEFAULT_COLLIDER, "radius": 0.4, "height": 1.2}},
    ],
    "rock": [
        {"type": "collider", "shape": "convex", **DEFAULT_COLLIDER},
        {**DYNAMIC_BODY, "mass": 25.0},
    ],
    "trigger_zone": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [1.0, 2.0, 3.0], "sensor": True, "memberships": 4, "filters": 2}},
    ],
    "pickup_zone": [
        {"type": "collider", "shape": "sphere", **{**DEFAULT_COLLIDER, "radius": 1.5, "sensor": True}},
    ],
    "player_spawn": [
        {"type": "custom", "type_path": "my_game::PlayerSpawn", "data": {}},
    ],
    "enemy_spawn": [
        {"type": "custom", "type_path": "my_game::EnemySpawn", "data": {}},
        {"type": "custom", "type_path": "my_game::Wave", "data": {"count": 3, "delay": 1.5}},
    ],
    "lamp": [
        {"type": "custom", "type_path": "my_game::Glow", "data": {"color": [1.0, 0.8, 0.6], "label": "Lamp ✦"}},
        {"type": "custom", "type_path": "my_game::Flicker", "data": 0.25},
    ],
    "house": [
        {"type": "visibility_range", "start": [80.0, 85.0], "end": [250.0, 260.0], "use_aabb": True},
        {"type": "collider", "shape": "trimesh", **DEFAULT_COLLIDER},
    ],
    "tree_lod0": [
        {"type": "visibility_range", "start": [0.0, 0.0], "end": [20.0, 25.0], "use_aabb": False},
    ],
    "tree_lod1": [
        {"type": "visibility_range", "start": [20.0, 25.0], "end": [100.0, 120.0], "use_aabb": False},
    ],
    "cart": [
        {**DYNAMIC_BODY, "mass": 12.0},
    ],
    "cart_shape": [
        {"type": "collider", "shape": "cuboid", **DEFAULT_COLLIDER},
    ],
    "cart_handle": [
        {"type": "collider", "shape": "sphere", **{**DEFAULT_COLLIDER, "radius": 0.25}},
    ],
    "bouncy_ball": [
        {"type": "collider", "shape": "sphere", **{**DEFAULT_COLLIDER, "radius": 0.3, "restitution": 1.0}},
        DYNAMIC_BODY,
    ],
    "ghost": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "memberships": 2, "filters": 2}},
        DYNAMIC_BODY,
    ],
    "ramp": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [6.0, 0.2, 2.0]}},
        STATIC_BODY,
    ],
    "ice_block": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [0.5, 0.5, 0.5], "friction": 0.0}},
        DYNAMIC_BODY,
    ],
    "rubber_block": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [0.5, 0.5, 0.5], "friction": 1.0}},
        DYNAMIC_BODY,
    ],
}

addon = None


def setUpModule():
    global addon
    addon = sys.modules[install_addon()]


def tearDownModule():
    uninstall_addon()
    if hasattr(bpy.types.Object, "bevy_component_data") or _operator_exists("bevy_components.add"):
        raise AssertionError("Bevy Components did not unregister cleanly")


def _encoder_available():
    spec = importlib.util.spec_from_file_location("bevy_encoder", Path(__file__).resolve().parents[2] / "addon" / "encoder.py")
    encoder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(encoder)
    try:
        encoder.check_encoder()
    except encoder.EncoderError:
        return False
    return True


def _operator_exists(idname):
    category, name = idname.split(".")
    try:
        getattr(getattr(bpy.ops, category), name).get_rna_type()
    except KeyError:
        return False
    return True


def _stored(obj):
    return json.loads(obj["bevy_components"])


def _rounded(value):
    if isinstance(value, float):
        return round(value, 5)
    if isinstance(value, list):
        return [_rounded(item) for item in value]
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    return value


def _node_summary(gltf):
    nodes = gltf["nodes"]
    summary = {}
    for node in nodes:
        summary[node["name"]] = {
            "extras": node.get("extras"),
            "children": sorted(nodes[index]["name"] for index in node.get("children", [])),
            "translation": _rounded(node.get("translation")),
            "rotation": _rounded(node.get("rotation")),
            "scale": _rounded(node.get("scale")),
            "mesh": "mesh" in node,
        }
    return summary


class FakeOperatorProperties:
    def __init__(self, test, idname):
        category, name = idname.split(".")
        object.__setattr__(self, "test", test)
        object.__setattr__(self, "properties", getattr(getattr(bpy.ops, category), name).get_rna_type().properties)

    def __setattr__(self, name, value):
        self.test.assertIn(name, self.properties.keys())
        if self.properties[name].type == "ENUM":
            self.test.assertIn(value, self.properties[name].enum_items.keys())
        object.__setattr__(self, name, value)


class FakeLayout:
    def __init__(self, test, calls=None, parent=None):
        object.__setattr__(self, "test", test)
        object.__setattr__(self, "calls", [] if calls is None else calls)
        object.__setattr__(self, "parent", parent)
        object.__setattr__(self, "enabled", True)

    def __setattr__(self, name, value):
        self.test.assertIn(name, LAYOUT.properties.keys())
        object.__setattr__(self, name, value)

    def __getattr__(self, name):
        function = LAYOUT.functions.get(name)
        if function is None:
            raise AttributeError(f"UILayout has no function {name}")
        return lambda *args, **kwargs: self._call(name, function, args, kwargs)

    def _call(self, name, function, args, kwargs):
        parameters = [parameter.identifier for parameter in function.parameters if not parameter.is_output]
        self.test.assertLessEqual(len(args), len(parameters), f"Too many arguments to UILayout.{name}")
        unknown = set(kwargs) - set(parameters)
        self.test.assertFalse(unknown, f"Unknown arguments to UILayout.{name}: {unknown}")
        bound = {**dict(zip(parameters, args)), **kwargs}
        if "icon" in bound:
            self.test.assertIn(bound["icon"], ICONS)
        if name in {"prop", "panel_prop"}:
            self.test.assertIn(bound["property"], bound["data"].bl_rna.properties.keys())
        if name == "menu":
            self.test.assertTrue(hasattr(bpy.types, bound["menu"]), bound["menu"])
        self.calls.append((name, bound, self))
        if name == "operator":
            self.test.assertTrue(_operator_exists(bound["operator"]), bound["operator"])
            properties = FakeOperatorProperties(self.test, bound["operator"])
            bound["properties"] = properties
            return properties
        if name in CHILD_LAYOUTS:
            return FakeLayout(self.test, self.calls, self)
        if name == "panel_prop":
            return FakeLayout(self.test, self.calls, self), FakeLayout(self.test, self.calls, self) if getattr(bound["data"], bound["property"]) else None
        if name == "panel":
            return FakeLayout(self.test, self.calls, self), FakeLayout(self.test, self.calls, self)
        return None

    def is_enabled(self):
        return self.enabled and (self.parent is None or self.parent.is_enabled())

    def texts(self):
        return [bound.get("text", "") for name, bound, layout in self.calls]

    def props(self):
        return [bound["property"] for name, bound, layout in self.calls if name == "prop"]

    def alerts(self):
        return [bound.get("text", "") for name, bound, layout in self.calls if name == "label" and layout.is_alert()]

    def is_alert(self):
        return getattr(self, "alert", False) or (self.parent is not None and self.parent.is_alert())

    def menus(self):
        return [bound["menu"] for name, bound, layout in self.calls if name == "menu"]

    def operators(self):
        return [bound["operator"] for name, bound, layout in self.calls if name == "operator"]

    def buttons(self):
        return [(bound.get("text", ""), bound["properties"], layout.is_enabled()) for name, bound, layout in self.calls if name == "operator"]


def _prop_layout(layout, prop):
    return next(child for name, bound, child in layout.calls if name == "prop" and bound["property"] == prop)


class FakePanel:
    def __init__(self, test):
        self.layout = FakeLayout(test)
        self.bl_label = "Bevy Components"


def _menu_context(obj=None, item=None):
    return SimpleNamespace(object=obj, bevy_component=item, scene=bpy.context.scene, space_data=SimpleNamespace(overlay=SimpleNamespace(show_overlays=True)))


class TestRegistration(unittest.TestCase):
    def test_extension_registers_types_and_operators(self):
        self.assertTrue(hasattr(bpy.types.Object, "bevy_component_data"))
        self.assertTrue(hasattr(bpy.types.Scene, "bevy_component_previews"))
        for idname in ("bevy_components.add", "bevy_components.remove", "bevy_components.duplicate", "bevy_components.copy_component_to_selected", "bevy_components.reset", "bevy_components.move", "bevy_components.lod_preset", "bevy_components.set_collision_layers", "bevy_components.copy_to_selected", "bevy_components.validate", "export_scene.bevy_components_glb"):
            self.assertTrue(_operator_exists(idname), idname)
        for idname in ("BEVY_MT_component_add", "BEVY_MT_component_add_physics", "BEVY_MT_component_add_rendering", "BEVY_MT_component_context_menu", "BEVY_MT_object_context_menu", "BEVY_PT_object_properties", "BEVY_PT_view_sidebar", "BEVY_PT_overlay"):
            self.assertTrue(hasattr(bpy.types, idname), idname)
        self.assertEqual(bpy.types.BEVY_PT_overlay.bl_parent_id, "VIEW3D_PT_overlay")
        self.assertIn(addon.menu.export_menu, bpy.types.TOPBAR_MT_file_export._dyn_ui_initialize())
        self.assertIn(addon.system.save_sync, bpy.app.handlers.save_pre)
        self.assertEqual(bpy.context.preferences.addons[addon.__name__].preferences.ktx_path, "")

    def test_registers_with_restricted_blend_data(self):
        bpy.ops.preferences.addon_disable(module=addon.__name__)
        try:
            with mock.patch.object(bpy, "data", SimpleNamespace()), mock.patch.object(bpy, "context", SimpleNamespace()):
                addon.register()
            addon.unregister()
        finally:
            bpy.ops.preferences.addon_enable(module=addon.__name__)
        self.assertTrue(_operator_exists("bevy_components.add"))

    def test_add_menus_search_on_key_press(self):
        for menu in (addon.menu.BEVY_MT_component_add, addon.menu.BEVY_MT_component_add_physics, addon.menu.BEVY_MT_component_add_rendering):
            self.assertEqual(menu.bl_options, {"SEARCH_ON_KEY_PRESS"})

    def test_disable_and_enable_keeps_components(self):
        clear_scene()
        obj = add_mesh(bpy.ops.mesh.primitive_cube_add, "kept")
        add_component(obj, "CUSTOM", custom_type="game::Kept")
        bpy.ops.preferences.addon_disable(module=addon.__name__)
        self.assertFalse(hasattr(bpy.types.Object, "bevy_component_data"))
        self.assertFalse(_operator_exists("bevy_components.add"))
        bpy.ops.preferences.addon_enable(module=addon.__name__)
        self.assertEqual(obj.bevy_component_data.components[0].custom_type, "game::Kept")
        self.assertEqual(_stored(obj)["components"], [{"type": "custom", "type_path": "game::Kept", "data": {}}])


class TestOperators(unittest.TestCase):
    def setUp(self):
        clear_scene()
        self.obj = add_mesh(bpy.ops.mesh.primitive_cube_add, "subject")

    def test_add_rejects_duplicates_except_custom(self):
        add_component(self.obj, "COLLIDER")
        self.assertEqual(bpy.ops.bevy_components.add(component_type="COLLIDER"), {"CANCELLED"})
        add_component(self.obj, "CUSTOM")
        add_component(self.obj, "CUSTOM")
        self.assertEqual([item["type"] for item in _stored(self.obj)["components"]], ["collider", "custom", "custom"])

    def test_property_changes_sync_custom_property(self):
        item = add_component(self.obj, "VISIBILITY_RANGE")
        item.fade_out_start = 30
        item.fade_out_end = 40
        self.assertEqual(_stored(self.obj)["components"][0]["end"], [30.0, 40.0])

    def test_remove(self):
        add_component(self.obj, "COLLIDER")
        add_component(self.obj, "RIGID_BODY")
        self.assertEqual(bpy.ops.bevy_components.remove(index=5), {"CANCELLED"})
        self.assertEqual(bpy.ops.bevy_components.remove(index=0), {"FINISHED"})
        self.assertEqual(_stored(self.obj)["components"], [STATIC_BODY])
        bpy.ops.bevy_components.remove(index=0)
        self.assertNotIn("bevy_components", self.obj.keys())

    def test_lod_presets(self):
        add_component(self.obj, "COLLIDER")
        add_component(self.obj, "VISIBILITY_RANGE")
        self.assertEqual(bpy.ops.bevy_components.lod_preset(index=0, preset="FAR"), {"CANCELLED"})
        for preset, start, end in (("NEAR", [0.0, 0.0], [20.0, 25.0]), ("MID", [20.0, 25.0], [80.0, 85.0]), ("FAR", [80.0, 85.0], [250.0, 260.0])):
            apply_lod_preset(self.obj, preset)
            stored = _stored(self.obj)["components"][1]
            self.assertEqual((stored["start"], stored["end"]), (start, end))

    def test_copy_to_selected_replaces_components(self):
        add_component(self.obj, "COLLIDER", collider_shape="CAPSULE", collider_radius=0.3, collider_height=1.7, collider_size=(1, 2, 3), collider_sensor=True, collider_friction=0.9, collider_restitution=0.4, collider_memberships=layers(3, 31), collider_filters=layers(0, 3))
        add_component(self.obj, "CUSTOM", custom_type="game::Tag", custom_json='{"a": 1}')
        first = add_mesh(bpy.ops.mesh.primitive_cube_add, "first")
        add_component(first, "RIGID_BODY")
        second = add_empty("second", (0, 0, 0))
        select(self.obj, first, second)
        self.assertEqual(bpy.ops.bevy_components.copy_to_selected(), {"FINISHED"})
        for obj in (first, second):
            self.assertEqual(_stored(obj), _stored(self.obj))
            self.assertEqual(tuple(obj.bevy_component_data.components[0].collider_size), (1.0, 2.0, 3.0))
            self.assertEqual(list(obj.bevy_component_data.components[0].collider_memberships), layers(3, 31))
            self.assertEqual((_stored(obj)["components"][0]["memberships"], _stored(obj)["components"][0]["filters"]), (2**3 + 2**31, 0b1001))

    def test_validate(self):
        add_component(self.obj, "VISIBILITY_RANGE")
        self.assertEqual(bpy.ops.bevy_components.validate(), {"FINISHED"})
        item = add_component(self.obj, "CUSTOM", custom_json="{broken")
        with self.assertRaises(RuntimeError):
            bpy.ops.bevy_components.validate()
        item.custom_json = "[1, 2]"
        self.assertEqual(bpy.ops.bevy_components.validate(), {"FINISHED"})

    def test_disabled_components_are_not_stored_or_validated(self):
        add_component(self.obj, "RIGID_BODY", rigid_body_kind="DYNAMIC")
        collider = add_component(self.obj, "COLLIDER")
        custom = add_component(self.obj, "CUSTOM", custom_json="{broken")
        collider.enabled = False
        self.assertNotIn("bevy_components", self.obj.keys())
        custom.enabled = False
        self.assertEqual(_stored(self.obj)["components"], [DYNAMIC_BODY])
        self.assertEqual(bpy.ops.bevy_components.validate(), {"FINISHED"})
        collider.enabled = True
        self.assertEqual([item["type"] for item in _stored(self.obj)["components"]], ["rigid_body", "collider"])

    def test_duplicate_only_custom_components(self):
        add_component(self.obj, "COLLIDER")
        add_component(self.obj, "CUSTOM", custom_type="game::First", custom_json='{"a": 1}')
        add_component(self.obj, "CUSTOM", custom_type="game::Last")
        self.assertEqual(bpy.ops.bevy_components.duplicate(index=0), {"CANCELLED"})
        self.assertEqual(bpy.ops.bevy_components.duplicate(index=1), {"FINISHED"})
        self.assertEqual([item["type_path"] for item in _stored(self.obj)["components"][1:]], ["game::First", "game::First", "game::Last"])
        self.assertEqual(_stored(self.obj)["components"][2]["data"], {"a": 1})

    def test_copy_component_to_selected_adds_or_replaces(self):
        add_component(self.obj, "COLLIDER", collider_shape="SPHERE", collider_radius=2)
        add_component(self.obj, "CUSTOM", custom_type="game::Tag", custom_json='{"a": 1}')
        first = add_mesh(bpy.ops.mesh.primitive_cube_add, "first")
        add_component(first, "RIGID_BODY")
        add_component(first, "COLLIDER", collider_shape="CUBOID")
        add_component(first, "CUSTOM", custom_type="game::Tag", custom_json='{"a": 0}')
        second = add_empty("second", (0, 0, 0))
        select(self.obj, first, second)
        self.assertEqual(bpy.ops.bevy_components.copy_component_to_selected(index=0), {"FINISHED"})
        self.assertEqual(bpy.ops.bevy_components.copy_component_to_selected(index=1), {"FINISHED"})
        self.assertEqual(_stored(first)["components"], [STATIC_BODY, *_stored(self.obj)["components"]])
        self.assertEqual(_stored(second), _stored(self.obj))

    def test_copy_needs_other_selected_objects(self):
        add_component(self.obj, "COLLIDER")
        select(self.obj)
        self.assertFalse(bpy.ops.bevy_components.copy_component_to_selected.poll())
        self.assertFalse(bpy.ops.bevy_components.copy_to_selected.poll())

    def test_set_collision_layers(self):
        collider = add_component(self.obj, "COLLIDER", collider_memberships=layers(4), collider_filters=layers(2))
        add_component(self.obj, "RIGID_BODY")
        self.assertEqual(bpy.ops.bevy_components.set_collision_layers(index=0, layers="MEMBERSHIPS", enable=True), {"FINISHED"})
        self.assertEqual(bpy.ops.bevy_components.set_collision_layers(index=0, layers="FILTERS", enable=False), {"FINISHED"})
        self.assertEqual(list(collider.collider_memberships), [True] * 32)
        self.assertEqual(list(collider.collider_filters), [False] * 32)
        self.assertEqual((_stored(self.obj)["components"][0]["memberships"], _stored(self.obj)["components"][0]["filters"]), (2**32 - 1, 0))
        self.assertEqual(bpy.ops.bevy_components.set_collision_layers(index=1, layers="FILTERS", enable=True), {"CANCELLED"})
        self.assertEqual(bpy.ops.bevy_components.set_collision_layers(index=2, layers="FILTERS", enable=True), {"CANCELLED"})

    def test_mass_is_stored_for_dynamic_bodies(self):
        body = add_component(self.obj, "RIGID_BODY", rigid_body_mass=40)
        body.rigid_body_use_mass = True
        self.assertIsNone(_stored(self.obj)["components"][0]["mass"])
        body.rigid_body_kind = "DYNAMIC"
        self.assertEqual(_stored(self.obj)["components"][0]["mass"], 40.0)
        body.rigid_body_use_mass = False
        self.assertIsNone(_stored(self.obj)["components"][0]["mass"])

    def test_reset_restores_physics_defaults(self):
        collider = add_component(self.obj, "COLLIDER", collider_friction=0.1, collider_restitution=0.9, collider_memberships=layers(5), collider_filters=layers(5), show_layers=True)
        body = add_component(self.obj, "RIGID_BODY", rigid_body_kind="DYNAMIC", rigid_body_use_mass=True, rigid_body_mass=3)
        bpy.ops.bevy_components.reset(index=0)
        bpy.ops.bevy_components.reset(index=1)
        self.assertEqual((collider.collider_friction, collider.collider_restitution, list(collider.collider_memberships), list(collider.collider_filters), collider.show_layers), (0.5, 0.0, layers(0), [True] * 32, True))
        self.assertEqual((body.rigid_body_kind, body.rigid_body_use_mass, body.rigid_body_mass), ("STATIC", False, 1.0))
        self.assertEqual(_stored(self.obj)["components"], [{"type": "collider", "shape": "trimesh", **DEFAULT_COLLIDER}, STATIC_BODY])

    def test_reset_restores_defaults(self):
        item = add_component(self.obj, "COLLIDER", collider_shape="CAPSULE", collider_radius=3, collider_sensor=True)
        item.show_expanded = False
        self.assertEqual(bpy.ops.bevy_components.reset(index=0), {"FINISHED"})
        self.assertEqual((item.component_type, item.collider_shape, item.collider_radius, item.collider_sensor, item.show_expanded), ("COLLIDER", "TRIMESH", 0.5, False, False))
        self.assertEqual(_stored(self.obj)["components"][0]["shape"], "trimesh")

    def test_move(self):
        for kind in ("COLLIDER", "RIGID_BODY", "VISIBILITY_RANGE"):
            add_component(self.obj, kind)
        order = lambda: [item.component_type for item in self.obj.bevy_component_data.components]
        self.assertEqual(bpy.ops.bevy_components.move(index=0, direction="UP"), {"CANCELLED"})
        bpy.ops.bevy_components.move(index=0, direction="DOWN")
        self.assertEqual(order(), ["RIGID_BODY", "COLLIDER", "VISIBILITY_RANGE"])
        bpy.ops.bevy_components.move(index=2, direction="FIRST")
        self.assertEqual(order(), ["VISIBILITY_RANGE", "RIGID_BODY", "COLLIDER"])
        bpy.ops.bevy_components.move(index=0, direction="LAST")
        self.assertEqual(order(), ["RIGID_BODY", "COLLIDER", "VISIBILITY_RANGE"])
        bpy.ops.bevy_components.move(index=2, direction="UP")
        self.assertEqual([item["type"] for item in _stored(self.obj)["components"]], ["rigid_body", "visibility_range", "collider"])

    def test_invalid_custom_json_is_not_stored(self):
        add_component(self.obj, "CUSTOM", custom_json="{broken")
        self.assertNotIn("bevy_components", self.obj.keys())

    def test_save_and_reload(self):
        add_component(self.obj, "COLLIDER", collider_shape="SPHERE", collider_radius=2, collider_friction=0.2, collider_memberships=layers(1, 7))
        add_component(self.obj, "RIGID_BODY", rigid_body_kind="DYNAMIC", rigid_body_use_mass=True, rigid_body_mass=7.5)
        self.obj["bevy_components"] = "stale"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "level.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(path))
            bpy.ops.wm.open_mainfile(filepath=str(path))
        obj = bpy.data.objects["subject"]
        self.assertEqual(obj.bevy_component_data.components[0].collider_radius, 2.0)
        self.assertEqual(_stored(obj)["components"][0]["radius"], 2.0)
        self.assertEqual(list(obj.bevy_component_data.components[0].collider_memberships), layers(1, 7))
        self.assertEqual(_rounded(_stored(obj)["components"]), [{"type": "collider", "shape": "sphere", **{**DEFAULT_COLLIDER, "radius": 2.0, "friction": 0.2, "memberships": 0b10000010}}, {**DYNAMIC_BODY, "mass": 7.5}])


class TestPanels(unittest.TestCase):
    def setUp(self):
        clear_scene()
        self.obj = add_mesh(bpy.ops.mesh.primitive_cube_add, "subject")

    def test_object_panel_draws_every_component(self):
        for kind in ("VISIBILITY_RANGE", "COLLIDER", "RIGID_BODY", "CUSTOM"):
            add_component(self.obj, kind)
        collider = self.obj.bevy_component_data.components[1]
        for shape in ("TRIMESH", "CONVEX", "CUBOID", "SPHERE", "CAPSULE"):
            collider.collider_shape = shape
            panel = FakePanel(self)
            self.assertTrue(addon.panel.BEVY_PT_object_properties.poll(bpy.context))
            addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
            text, add_menu, enabled = panel.layout.buttons()[0]
            self.assertEqual((text, add_menu.name), ("Add Component", "BEVY_MT_component_add"))
            self.assertEqual(panel.layout.menus(), ["BEVY_MT_object_context_menu"] + ["BEVY_MT_component_context_menu"] * 4)
            self.assertEqual([bound["property"] for name, bound, layout in panel.layout.calls if name == "panel_prop"], ["show_expanded", "show_expanded", "show_layers", "show_expanded", "show_expanded"])
            self.assertEqual(panel.layout.props().count("enabled"), 4)
        self.assertIn("collider_height", panel.layout.props())
        self.assertNotIn("Fade distances must increase from top to bottom", panel.layout.texts())

    def test_object_panel_flags_bad_ranges_and_collapsed_cards(self):
        add_component(self.obj, "VISIBILITY_RANGE", fade_in_end=50)
        add_component(self.obj, "COLLIDER", show_expanded=False)
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertIn("Fade distances must increase from top to bottom", panel.layout.texts())
        self.assertIn("Collider", panel.layout.texts())
        self.assertNotIn("collider_shape", panel.layout.props())

    def test_custom_component_card_shows_type_path(self):
        add_component(self.obj, "CUSTOM", custom_type="my_game::Health")
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertIn("my_game::Health", panel.layout.texts())

    def test_removed_component_types_are_skipped(self):
        add_component(self.obj, "COLLIDER")
        removed = add_component(self.obj, "RIGID_BODY")
        removed["component_type"] = 3
        addon.system.sync_object(self.obj)
        self.assertEqual([item["type"] for item in _stored(self.obj)["components"]], ["collider"])
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertIn("Removed Component", panel.layout.texts())
        self.assertIn("No longer exported", panel.layout.texts())

    def test_add_menu_disables_components_already_present(self):
        add_component(self.obj, "COLLIDER")
        add_component(self.obj, "CUSTOM")
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add.draw(menu, _menu_context(self.obj))
        self.assertEqual(menu.layout.menus(), ["BEVY_MT_component_add_physics", "BEVY_MT_component_add_rendering"])
        found = {}
        for menu_type in (addon.menu.BEVY_MT_component_add, addon.menu.BEVY_MT_component_add_physics, addon.menu.BEVY_MT_component_add_rendering):
            menu = FakePanel(self)
            menu_type.draw(menu, _menu_context(self.obj))
            found.update({properties.component_type: enabled for text, properties, enabled in menu.layout.buttons()})
        self.assertEqual(found, {"CUSTOM": True, "COLLIDER": False, "RIGID_BODY": True, "VISIBILITY_RANGE": True})

    def test_component_context_menu_targets_its_component(self):
        add_component(self.obj, "COLLIDER")
        custom = add_component(self.obj, "CUSTOM")
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_context_menu.draw(menu, _menu_context(self.obj, custom))
        buttons = {text: (properties, enabled) for text, properties, enabled in menu.layout.buttons()}
        self.assertEqual(set(buttons), {"Duplicate", "Copy to Selected", "Reset to Defaults", "Move to First", "Move Up", "Move Down", "Move to Last", "Remove"})
        self.assertTrue(all(properties.index == 1 for properties, enabled in buttons.values()))
        self.assertEqual({text for text, (properties, enabled) in buttons.items() if not enabled}, {"Move Down", "Move to Last"})
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_context_menu.draw(menu, _menu_context(self.obj, self.obj.bevy_component_data.components[0]))
        self.assertEqual({text for text, properties, enabled in menu.layout.buttons() if not enabled}, {"Duplicate", "Move to First", "Move Up"})

    def test_object_context_menu(self):
        menu = FakePanel(self)
        addon.menu.BEVY_MT_object_context_menu.draw(menu, _menu_context(self.obj))
        self.assertEqual(menu.layout.operators(), ["bevy_components.copy_to_selected", "bevy_components.validate", "export_scene.bevy_components_glb"])

    def test_sidebar_without_active_object(self):
        select()
        panel = FakePanel(self)
        addon.panel.BEVY_PT_view_sidebar.draw(panel, bpy.context)
        self.assertEqual(panel.layout.texts(), ["Select an object"])

    def test_collider_card_draws_surface_and_layers(self):
        collider = add_component(self.obj, "COLLIDER", collider_shape="CUBOID")
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props()[-3:], ["collider_sensor", "collider_friction", "collider_restitution"])
        self.assertIn("Collision Layers", panel.layout.texts())
        self.assertNotIn("collider_memberships", panel.layout.props())
        self.assertTrue(_prop_layout(panel.layout, "collider_friction").active)
        collider.show_layers = True
        collider.collider_sensor = True
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertFalse(_prop_layout(panel.layout, "collider_friction").active)
        toggles = [(bound["property"], bound["index"], bound["text"], bound["toggle"], layout.use_property_split) for name, bound, layout in panel.layout.calls if name == "prop" and bound["property"] in {"collider_memberships", "collider_filters"}]
        self.assertEqual(toggles, [(prop, index, str(index), True, False) for prop in ("collider_memberships", "collider_filters") for index in range(32)])
        buttons = [(text, properties.index, properties.layers, properties.enable) for text, properties, enabled in panel.layout.buttons() if text in {"All", "None"}]
        self.assertEqual(buttons, [("All", 0, "MEMBERSHIPS", True), ("None", 0, "MEMBERSHIPS", False), ("All", 0, "FILTERS", True), ("None", 0, "FILTERS", False)])
        self.assertIn("Belongs To", panel.layout.texts())
        self.assertIn("Collides With", panel.layout.texts())
        self.assertNotIn("Collides with nothing", panel.layout.texts())
        collider.collider_filters = [False] * 32
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertIn("Collides with nothing", panel.layout.texts())

    def test_rigid_body_card_shows_mass_for_dynamic_bodies(self):
        body = add_component(self.obj, "RIGID_BODY")
        for kind in ("STATIC", "KINEMATIC"):
            body.rigid_body_kind = kind
            panel = FakePanel(self)
            addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
            self.assertNotIn("rigid_body_mass", panel.layout.props(), kind)
        body.rigid_body_kind = "DYNAMIC"
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props()[-3:], ["rigid_body_kind", "rigid_body_use_mass", "rigid_body_mass"])
        self.assertIn(("row", "Mass"), [(name, bound.get("heading")) for name, bound, layout in panel.layout.calls])
        self.assertFalse(_prop_layout(panel.layout, "rigid_body_mass").active)
        body.rigid_body_use_mass = True
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertTrue(_prop_layout(panel.layout, "rigid_body_mass").active)

    def test_sidebar_draws_components(self):
        add_component(self.obj, "RIGID_BODY")
        select(self.obj)
        panel = FakePanel(self)
        addon.panel.BEVY_PT_view_sidebar.draw(panel, bpy.context)
        self.assertIn("rigid_body_kind", panel.layout.props())

    def test_overlay_popover(self):
        settings = bpy.context.scene.bevy_component_previews
        panel = FakePanel(self)
        addon.panel.BEVY_PT_overlay.draw_header(panel, _menu_context())
        self.assertEqual(panel.layout.props(), ["enabled"])
        panel = FakePanel(self)
        addon.panel.BEVY_PT_overlay.draw(panel, _menu_context())
        self.assertEqual(panel.layout.props(), ["scope", "colliders", "visibility_ranges", "labels", "xray", "edit_handles", "max_mesh_edges"])
        settings.enabled = False
        panel = FakePanel(self)
        addon.panel.BEVY_PT_overlay.draw(panel, _menu_context())
        self.assertFalse(panel.layout.active)
        settings.enabled = True

    def test_export_menu(self):
        panel = FakePanel(self)
        addon.menu.export_menu(panel, bpy.context)
        self.assertEqual(panel.layout.operators(), ["export_scene.bevy_components_glb"])

    def test_export_dialog_texture_compression(self):
        properties = bpy.ops.export_scene.bevy_components_glb.get_rna_type()
        include = ["selected_only", "include_lights", "include_cameras", "include_animations", "texture_compression"]
        expected = {
            "DISABLED": include,
            "ETC1S": include + ["etc1s_quality", "etc1s_effort"],
            "UASTC": include + ["uastc_quality", "uastc_zstd"],
            "AUTOMATIC": include + ["etc1s_quality", "etc1s_effort", "uastc_quality", "uastc_zstd"],
        }
        for mode, props in expected.items():
            operator = SimpleNamespace(layout=FakeLayout(self), bl_rna=properties, texture_compression=mode, selected_only=False, include_lights=True, include_cameras=False, include_animations=False, etc1s_quality=128, etc1s_effort=2, uastc_quality=2, uastc_zstd=18)
            addon.operator.BEVY_OT_export_glb.draw(operator, bpy.context)
            self.assertEqual(operator.layout.props(), props, mode)
            self.assertIn("Texture Compression", operator.layout.texts())
            self.assertEqual(any(text.startswith("KTX-Software") for text in operator.layout.texts()), mode != "DISABLED", mode)

    def test_preferences_show_encoder_status(self):
        preferences = bpy.context.preferences.addons[addon.__name__].preferences
        with tempfile.TemporaryDirectory() as directory:
            preferences.ktx_path = str(Path(directory) / "missing" / "ktx")
            try:
                panel = SimpleNamespace(layout=FakeLayout(self), bl_rna=preferences.bl_rna, ktx_path=preferences.ktx_path)
                addon.preferences.BEVY_AP_preferences.draw(panel, bpy.context)
            finally:
                preferences.ktx_path = ""
        self.assertEqual(panel.layout.props(), ["ktx_path"])
        self.assertTrue(panel.layout.alerts()[0].startswith("KTX-Software was not found at "))
        self.assertIn("Install KTX-Software 4.4 or newer", panel.layout.alerts()[1])
        if addon.encoder.find_encoder() is not None:
            panel = SimpleNamespace(layout=FakeLayout(self), bl_rna=preferences.bl_rna, ktx_path="")
            addon.preferences.BEVY_AP_preferences.draw(panel, bpy.context)
            self.assertEqual(panel.layout.alerts(), [])
            self.assertTrue(any(text.startswith("KTX-Software 4.") for text in panel.layout.texts()))


class TestViewport(unittest.TestCase):
    def setUp(self):
        clear_scene()
        self.settings = bpy.context.scene.bevy_component_previews
        self.settings.enabled = True
        self.settings.scope = "SELECTED"
        self.settings.edit_handles = True
        self.obj = add_mesh(bpy.ops.mesh.primitive_cube_add, "subject")

    def test_gizmo_poll(self):
        gizmo = addon.gizmo.BEVY_GGT_collider_handles
        self.assertFalse(gizmo.poll(bpy.context))
        collider = add_component(self.obj, "COLLIDER")
        for shape, expected in (("TRIMESH", False), ("CONVEX", False), ("CUBOID", True), ("SPHERE", True), ("CAPSULE", True)):
            collider.collider_shape = shape
            self.assertEqual(gizmo.poll(bpy.context), expected, shape)
        self.settings.edit_handles = False
        self.assertFalse(gizmo.poll(bpy.context))

    def test_gizmo_needs_selected_object(self):
        gizmo = addon.gizmo.BEVY_GGT_collider_handles
        add_component(self.obj, "COLLIDER", collider_shape="CUBOID")
        self.assertTrue(gizmo.poll(bpy.context))
        self.obj.select_set(False)
        self.assertEqual(bpy.context.object, self.obj)
        self.assertFalse(gizmo.poll(bpy.context))

    def test_collapsed_panel_hides_previews(self):
        gizmo = addon.gizmo.BEVY_GGT_collider_handles
        panel_type = addon.panel.BEVY_PT_object_properties
        add_component(self.obj, "COLLIDER", collider_shape="CUBOID")
        context = SimpleNamespace(region_data=object(), space_data=SimpleNamespace(overlay=SimpleNamespace(show_overlays=True)))
        panel = FakePanel(self)
        try:
            panel_type.draw_header(panel, bpy.context)
            self.assertTrue(bpy.app.timers.is_registered(addon.system._apply_panel_state))
            addon.system._apply_panel_state()
            self.assertFalse(addon.system.panel_expanded())
            self.assertFalse(addon.overlay._previews_shown(context))
            self.assertFalse(gizmo.poll(bpy.context))
        finally:
            panel_type.draw_header(panel, bpy.context)
            panel_type.draw(panel, bpy.context)
            addon.system._apply_panel_state()
        self.assertTrue(addon.system.panel_expanded())
        self.assertTrue(addon.overlay._previews_shown(context))
        self.assertTrue(gizmo.poll(bpy.context))

    def test_gizmo_handles_resize_colliders(self):
        collider = add_component(self.obj, "COLLIDER", collider_shape="CUBOID", collider_size=(2, 4, 6))
        self.assertEqual([addon.gizmo._get_handle_value(index) for index in range(3)], [1.0, 2.0, 3.0])
        addon.gizmo._set_handle_value(1, 1.5)
        self.assertEqual(tuple(collider.collider_size), (2.0, 3.0, 6.0))
        self.assertEqual(_stored(self.obj)["components"][0]["size"], [2.0, 3.0, 6.0])
        collider.collider_shape = "CAPSULE"
        collider.collider_radius = 0.5
        collider.collider_height = 2
        self.assertEqual(addon.gizmo._get_handle_value(1), 1.5)
        addon.gizmo._set_handle_value(1, (2.5,))
        self.assertAlmostEqual(collider.collider_height, 4.0)
        addon.gizmo._set_handle_value(0, -1)
        self.assertAlmostEqual(collider.collider_radius, 0.001)

    def test_preview_batches(self):
        add_component(self.obj, "COLLIDER", collider_sensor=True)
        add_component(self.obj, "VISIBILITY_RANGE")
        zone = add_empty("zone", (5, 0, 0))
        add_component(zone, "COLLIDER", collider_shape="SPHERE")
        select(self.obj)
        colors = [color for obj, lines, color, width in addon.overlay.preview_batches(bpy.context, self.settings)]
        self.assertEqual(colors, [addon.overlay.SENSOR_COLOR, addon.overlay.LOD_OUT_COLOR, addon.overlay.LOD_OUT_COLOR])
        self.settings.scope = "ALL"
        self.assertEqual(len(addon.overlay.preview_batches(bpy.context, self.settings)), 4)
        self.settings.visibility_ranges = False
        self.assertEqual([obj.name for obj, lines, color, width in addon.overlay.preview_batches(bpy.context, self.settings)], ["subject", "zone"])
        self.settings.colliders = False
        self.assertEqual(addon.overlay.preview_batches(bpy.context, self.settings), [])
        self.settings.colliders = True
        self.settings.visibility_ranges = True

    def test_visibility_preview_is_world_sized(self):
        self.obj.scale = (2, 2, 2)
        bpy.context.view_layer.update()
        add_component(self.obj, "VISIBILITY_RANGE", fade_in_start=0, fade_in_end=0, fade_out_start=10, fade_out_end=10)
        select(self.obj)
        obj, lines, color, width = addon.overlay.preview_batches(bpy.context, self.settings)[0]
        distances = [(obj.matrix_world @ Vector(point) - obj.matrix_world.translation).length for start, end in lines for point in (start, end)]
        self.assertTrue(all(abs(distance - 10) < 1e-4 for distance in distances))

    def test_mesh_previews_respect_edge_limit(self):
        collider = add_component(self.obj, "COLLIDER", collider_shape="TRIMESH")
        self.assertEqual(len(addon.overlay.collider_lines(self.obj, collider, 2000)), len(self.obj.data.edges))
        dense = add_mesh(bpy.ops.mesh.primitive_uv_sphere_add, "dense")
        self.assertEqual(len(addon.overlay.collider_lines(dense, collider, 64)), 12)
        collider.collider_shape = "CONVEX"
        self.assertEqual(len(addon.overlay.collider_lines(dense, collider, 2000)), 12)

    def test_labels(self):
        add_component(self.obj, "COLLIDER", collider_shape="CAPSULE", collider_radius=0.25, collider_height=2)
        add_component(self.obj, "VISIBILITY_RANGE")
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings), ["Collider · Capsule · r=0.25, cylinder=2m", "LOD · in 0–0m · out 20–25m"])

    def test_draws_lines_on_gpu(self):
        if not hasattr(gpu, "init"):
            self.skipTest("This Blender cannot draw on the GPU in background mode")
        try:
            gpu.init()
        except SystemError as error:
            self.skipTest(f"No GPU context available: {error}")
        add_component(self.obj, "COLLIDER", collider_shape="CUBOID", collider_size=(1, 1, 1))
        select(self.obj)
        self.obj.location = (0, 0, 0)
        bpy.context.view_layer.update()
        shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        offscreen = gpu.types.GPUOffScreen(64, 64)
        try:
            with offscreen.bind():
                framebuffer = gpu.state.active_framebuffer_get()
                framebuffer.clear(color=(0.0, 0.0, 0.0, 0.0))
                with gpu.matrix.push_pop():
                    gpu.matrix.load_matrix(Matrix.Identity(4))
                    gpu.matrix.load_projection_matrix(Matrix.Identity(4))
                    for obj, lines, color, width in addon.overlay.preview_batches(bpy.context, self.settings):
                        addon.overlay._draw_lines(shader, obj, lines, color, width=width)
                pixels = framebuffer.read_color(0, 0, 64, 64, 4, 0, "FLOAT")
        finally:
            offscreen.free()
        pixels.dimensions = 64 * 64 * 4
        self.assertTrue(any(value > 0.1 for value in pixels.to_list()[1::4]))


class TestExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_sample_level()
        cls.directory = tempfile.TemporaryDirectory()
        cls.gltf = export_sample_level(Path(cls.directory.name) / "sample_level.glb")
        cls.nodes = {node["name"]: node for node in cls.gltf["nodes"]}

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_every_object_is_exported(self):
        self.assertEqual(set(self.nodes), set(EXPECTED_COMPONENTS) | {"chimney", "sun", "cart_body"})
        self.assertEqual(self.nodes["house"].get("children"), [self.gltf["nodes"].index(self.nodes["chimney"])])
        self.assertEqual(sorted(self.gltf["nodes"][index]["name"] for index in self.nodes["cart"]["children"]), ["cart_body", "cart_handle", "cart_shape"])

    def test_component_extras(self):
        for name, expected in EXPECTED_COMPONENTS.items():
            extras = self.nodes[name]["extras"]
            self.assertEqual(list(extras), ["bevy_components"], name)
            exported = json.loads(extras["bevy_components"])
            self.assertEqual(exported["version"], 1)
            self.assertEqual(_rounded(exported["components"]), expected, name)

    def test_editor_state_is_not_exported(self):
        self.assertNotIn("extras", self.nodes["chimney"])
        self.assertNotIn("extras", self.nodes["cart_body"])
        self.assertNotIn("extras", self.nodes["sun"])
        self.assertTrue(all("extras" not in scene for scene in self.gltf["scenes"]))

    def test_transforms_are_y_up(self):
        self.assertEqual(_rounded(self.nodes["crate"]["translation"]), [3.0, 1.0, 2.0])
        self.assertEqual(_rounded(self.nodes["crate"]["rotation"]), [0.0, 0.25882, 0.0, 0.96593])
        self.assertEqual(_rounded(self.nodes["trigger_zone"]["scale"]), [2.0, 1.0, 1.0])
        self.assertEqual(_rounded(self.nodes["player_spawn"]["translation"]), [2.0, 0.0, -3.0])
        self.assertEqual(_rounded(self.nodes["cart_handle"]["translation"]), [-0.75, 0.25, 0.0])

    def test_fixture_is_current(self):
        self.assertTrue(FIXTURE.is_file(), f"Missing {FIXTURE}, run tests/blender/sample_level.py to create it")
        self.assertEqual(_node_summary(read_gltf(FIXTURE)), _node_summary(self.gltf), "importer/tests/assets/sample_level.glb is out of date, run tests/blender/sample_level.py to regenerate it")

    def test_plain_gltf_export_leaves_out_editor_state(self):
        path = Path(self.directory.name) / "plain.glb"
        bpy.context.scene.bevy_component_previews.scope = "ALL"
        bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", export_extras=True)
        gltf = read_gltf(path)
        self.assertTrue(all(set(node.get("extras", {})) <= {"bevy_components"} for node in gltf["nodes"]))
        self.assertTrue(all("extras" not in scene for scene in gltf["scenes"]))

    def test_selected_only(self):
        path = Path(self.directory.name) / "selected.glb"
        select(bpy.data.objects["ball"], bpy.data.objects["player_spawn"])
        bpy.ops.export_scene.bevy_components_glb(filepath=str(path), selected_only=True)
        self.assertEqual(sorted(node["name"] for node in read_gltf(path)["nodes"]), ["ball", "player_spawn"])

    def test_invalid_components_block_export(self):
        path = Path(self.directory.name) / "invalid.glb"
        item = add_component(bpy.data.objects["lamp"], "CUSTOM", custom_json="{broken")
        try:
            with self.assertRaises(RuntimeError):
                bpy.ops.export_scene.bevy_components_glb(filepath=str(path))
            self.assertFalse(path.exists())
        finally:
            select(bpy.data.objects["lamp"])
            bpy.ops.bevy_components.remove(index=list(bpy.data.objects["lamp"].bevy_component_data.components).index(item))


def _image_state():
    return {image.name: (tuple(image.size), image.colorspace_settings.name, image.filepath, hashlib.sha256(image.packed_file.data).hexdigest() if image.packed_file else None) for image in bpy.data.images}


def _texture_summary(gltf, binary):
    images = []
    for index, image in enumerate(gltf["images"]):
        data, mime_type = addon.compression.image_payload(gltf, binary, index)
        info = addon.compression.ktx2_info(data) if mime_type == "image/ktx2" else {}
        images.append((image.get("name"), mime_type, *(info.get(key) for key in ("model", "width", "height", "levels", "transfer", "primaries"))))
    return images


def _sorted_texture_summary(gltf, binary):
    return sorted(_texture_summary(gltf, binary))


def _view_data(gltf, binary, index):
    view = gltf["bufferViews"][index]
    return binary[view.get("byteOffset", 0):view.get("byteOffset", 0) + view["byteLength"]]


def _usages(gltf):
    usages = {}
    for material in gltf["materials"]:
        for slot, info in addon.compression.texture_infos(material):
            texture = gltf["textures"][info["index"]]
            source = texture.get("source", texture.get("extensions", {}).get("KHR_texture_basisu", {}).get("source"))
            usages.setdefault(source, set()).add((material["name"], slot, addon.compression.slot_usage(slot)))
    return usages


def _material_summary(gltf):
    def resolve(value):
        if isinstance(value, dict):
            resolved = {key: resolve(child) for key, child in value.items()}
            if isinstance(value.get("index"), int):
                texture = gltf["textures"][value["index"]]
                source = texture.get("source", texture.get("extensions", {}).get("KHR_texture_basisu", {}).get("source"))
                resolved["index"] = (gltf["images"][source]["name"], gltf["samplers"][texture["sampler"]])
            return resolved
        if isinstance(value, list):
            return [resolve(child) for child in value]
        return value
    return [resolve(material) for material in gltf["materials"]]


@unittest.skipUnless(os.environ.get("BEVY_COMPONENTS_REQUIRE_KTX") or _encoder_available(), "KTX-Software is not installed")
class TestTextureCompression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_sample_level()
        cls.images = _image_state()
        cls.directory = tempfile.TemporaryDirectory()
        cls.cache = Path(cls.directory.name) / "texture_cache"
        cls.cache.mkdir()
        cls.cache_patch = mock.patch.object(addon.operator, "texture_cache", return_value=cls.cache)
        cls.cache_patch.start()
        cls.exports = {}
        for mode in ("DISABLED", "ETC1S", "UASTC", "AUTOMATIC"):
            path = Path(cls.directory.name) / f"level_{mode.lower()}.glb"
            export_sample_level(path, texture_compression=mode)
            cls.exports[mode] = addon.compression.read_glb(path.read_bytes())
        cls.compressed = {mode: cls.exports[mode] for mode in ("ETC1S", "UASTC", "AUTOMATIC")}

    @classmethod
    def tearDownClass(cls):
        cls.cache_patch.stop()
        cls.directory.cleanup()

    def test_compression_is_off_by_default(self):
        gltf, binary = self.exports["DISABLED"]
        self.assertNotIn("KHR_texture_basisu", gltf.get("extensionsUsed", []))
        self.assertEqual({image["mimeType"] for image in gltf["images"]}, {"image/png"})
        self.assertIn(addon.compression.PNG_SIGNATURE, binary)

    def test_textures_reference_embedded_ktx2(self):
        for mode, (gltf, binary) in self.compressed.items():
            self.assertIn("KHR_texture_basisu", gltf["extensionsUsed"], mode)
            self.assertIn("KHR_texture_basisu", gltf["extensionsRequired"], mode)
            self.assertEqual(len(gltf["textures"]), 9, mode)
            for texture in gltf["textures"]:
                self.assertNotIn("source", texture, mode)
                self.assertLess(texture["extensions"]["KHR_texture_basisu"]["source"], len(gltf["images"]), mode)
            for image in gltf["images"]:
                self.assertEqual(set(image), {"bufferView", "mimeType", "name"}, mode)
                self.assertEqual(image["mimeType"], "image/ktx2", mode)
                self.assertEqual(gltf["bufferViews"][image["bufferView"]]["byteOffset"] % 16, 0, mode)
            self.assertNotIn(addon.compression.PNG_SIGNATURE, binary, mode)
            self.assertEqual(gltf["buffers"], [{"byteLength": gltf["buffers"][0]["byteLength"]}], mode)

    def test_shared_images_are_embedded_once(self):
        for mode, (gltf, binary) in self.compressed.items():
            names = sorted(image["name"] for image in gltf["images"])
            self.assertEqual(names, ["ball_pixels", "lamp_emissive", "metal_color", "pillar_gradient", "wood_color", "wood_normal", "wood_orm", "wood_orm"], mode)
            sources = [texture["extensions"]["KHR_texture_basisu"]["source"] for texture in gltf["textures"]]
            self.assertEqual(len(sources) - len(set(sources)), 1, mode)

    def test_embedded_ktx2_files_pass_khronos_validation(self):
        path, _version = addon.encoder.check_encoder()
        for mode, (gltf, binary) in self.compressed.items():
            for index, image in enumerate(gltf["images"]):
                file = Path(self.directory.name) / f"{mode}_{index}.ktx2"
                file.write_bytes(addon.compression.image_payload(gltf, binary, index)[0])
                result = subprocess.run([str(path), "validate", "--gltf-basisu", str(file)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, f"{mode} {image['name']}: {result.stdout}{result.stderr}")

    def test_codecs_color_spaces_and_mipmaps(self):
        for mode, (gltf, binary) in self.compressed.items():
            usages = _usages(gltf)
            for index, (name, _mime_type, model, width, height, levels, transfer, primaries) in enumerate(_texture_summary(gltf, binary)):
                kinds = {usage for _material, _slot, usage in usages[index]}
                self.assertEqual(len(kinds), 1, f"{mode} {name}")
                usage = kinds.pop()
                expected = {"ETC1S": "etc1s", "UASTC": "uastc"}.get(mode, "etc1s" if usage == "color" and name != "ball_pixels" else "uastc")
                self.assertEqual(model, addon.compression.ETC1S_MODEL if expected == "etc1s" else addon.compression.UASTC_MODEL, f"{mode} {name}")
                self.assertEqual((transfer, primaries), (2, 1) if usage == "color" else (1, 0), f"{mode} {name}")
                self.assertEqual(levels, addon.compression.full_mip_count(width, height), f"{mode} {name}")
                self.assertEqual((width, height), (32, 20) if name == "pillar_gradient" else (8, 8) if name == "ball_pixels" else (32, 32) if name == "lamp_emissive" else (64, 64), f"{mode} {name}")

    def test_scene_matches_the_uncompressed_export(self):
        plain, plain_binary = self.exports["DISABLED"]
        for mode, (gltf, binary) in self.compressed.items():
            self.assertEqual(_node_summary(gltf), _node_summary(plain), mode)
            for key in ("scenes", "meshes", "accessors", "samplers", "extensions"):
                self.assertEqual(gltf.get(key), plain.get(key), f"{mode} {key}")
            self.assertEqual(_material_summary(gltf), _material_summary(plain), mode)
            self.assertIn("KHR_texture_transform", json.dumps(gltf["materials"]), mode)
            self.assertEqual(gltf["materials"][1]["occlusionTexture"]["texCoord"], 1, mode)
            for accessor in plain["accessors"]:
                self.assertEqual(_view_data(gltf, binary, accessor["bufferView"]), _view_data(plain, plain_binary, accessor["bufferView"]), mode)

    def test_blender_data_is_unchanged(self):
        self.assertEqual(_image_state(), self.images)
        self.assertEqual(bpy.data.images["wood_orm"].colorspace_settings.name, "Non-Color")

    def test_fixtures_are_current(self):
        for mode, path in COMPRESSED_FIXTURES.items():
            self.assertTrue(path.is_file(), f"Missing {path}, run tests/blender/sample_level.py to create it")
            gltf, binary = addon.compression.read_glb(path.read_bytes())
            fresh, fresh_binary = self.compressed[mode]
            self.assertEqual(_node_summary(gltf), _node_summary(fresh), f"{path.name} is out of date, run tests/blender/sample_level.py to regenerate it")
            self.assertEqual(_sorted_texture_summary(gltf, binary), _sorted_texture_summary(fresh, fresh_binary), f"{path.name} is out of date, run tests/blender/sample_level.py to regenerate it")


    def test_reexports_reuse_cached_textures(self):
        self.assertTrue(any(self.cache.glob("*.ktx2")))
        path = Path(self.directory.name) / "level_again.glb"
        with mock.patch.object(addon.encoder, "_run", side_effect=AssertionError("textures were encoded again")):
            export_sample_level(path, texture_compression="AUTOMATIC")
        self.assertEqual(addon.compression.read_glb(path.read_bytes()), self.exports["AUTOMATIC"])

    def test_texture_cache_is_in_the_extension_user_folder(self):
        self.cache_patch.stop()
        try:
            cache = Path(addon.preferences.texture_cache())
        finally:
            self.cache_patch.start()
        self.assertTrue(cache.is_dir())
        self.assertEqual(cache.name, "texture_cache")
        self.assertEqual(cache.parent.name, "bevy_components")


class TestTextureCompressionErrors(unittest.TestCase):
    def setUp(self):
        clear_scene()
        build_sample_level()
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "level.glb"
        self.preferences = bpy.context.preferences.addons[addon.__name__].preferences

    def tearDown(self):
        self.preferences.ktx_path = ""
        self.directory.cleanup()

    def test_missing_encoder_cancels_before_export(self):
        self.preferences.ktx_path = str(Path(self.directory.name) / "missing" / "ktx")
        with self.assertRaisesRegex(RuntimeError, "KTX-Software was not found at .*Install KTX-Software 4.4 or newer"):
            bpy.ops.export_scene.bevy_components_glb(filepath=str(self.path), texture_compression="AUTOMATIC")
        self.assertFalse(self.path.exists())

    def test_encoder_failures_keep_the_previous_file(self):
        self.path.write_bytes(b"previous level")
        with mock.patch.object(addon.operator, "check_encoder", return_value=(Path("ktx"), (4, 4, 0))), mock.patch.object(addon.operator, "encode", side_effect=addon.encoder.EncoderError("KTX-Software could not encode wood_color: broken input")):
            with self.assertRaisesRegex(RuntimeError, "Texture compression failed: KTX-Software could not encode wood_color: broken input"):
                bpy.ops.export_scene.bevy_components_glb(filepath=str(self.path), texture_compression="ETC1S")
        self.assertEqual(self.path.read_bytes(), b"previous level")
        self.assertEqual(sorted(path.name for path in Path(self.directory.name).iterdir()), ["level.glb"])

    def test_invalid_encoder_output_is_rejected(self):
        with mock.patch.object(addon.operator, "check_encoder", return_value=(Path("ktx"), (4, 4, 0))), mock.patch.object(addon.operator, "encode", side_effect=lambda path, jobs, *args, **options: [b"not ktx2"] * len(jobs)):
            with self.assertRaisesRegex(RuntimeError, "the encoder wrote an invalid KTX2 file"):
                bpy.ops.export_scene.bevy_components_glb(filepath=str(self.path), texture_compression="UASTC")
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
