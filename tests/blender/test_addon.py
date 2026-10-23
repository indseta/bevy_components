import hashlib
import importlib.util
import json
import math
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

from sample_level import COMPRESSED_FIXTURES, CUBEMAP, FIXTURE, IRRADIANCE_VOLUME, PROP, add_component, add_empty, add_light, add_mesh, animate, apply_lod_preset, build_sample_level, clear_scene, define_component, export_props, export_sample_level, install_addon, layers, pick_sound, read_gltf, select, set_fields, uninstall_addon

LAYOUT = bpy.types.UILayout.bl_rna
ICONS = set(LAYOUT.functions["label"].parameters["icon"].enum_items.keys())
CHILD_LAYOUTS = {"row", "column", "box", "split", "grid_flow", "column_flow"}
DEFAULT_COLLIDER = {"size": [1.0, 1.0, 1.0], "radius": 0.5, "height": 1.0, "sensor": False, "friction": 0.5, "restitution": 0.0, "memberships": 1, "filters": 4294967295}
STATIC_BODY = {"type": "rigid_body", "kind": "static", "mass": None, "gravity_scale": None, "linear_damping": None, "angular_damping": None, "lock_translation": None, "lock_rotation": None, "ccd": None, "linear_velocity": None, "angular_velocity": None}
KINEMATIC_BODY = {**STATIC_BODY, "kind": "kinematic", "linear_velocity": [0.0, 0.0, 0.0], "angular_velocity": [0.0, 0.0, 0.0]}
DYNAMIC_BODY = {**KINEMATIC_BODY, "kind": "dynamic", "gravity_scale": 1.0, "linear_damping": 0.0, "angular_damping": 0.0, "lock_translation": [False, False, False], "lock_rotation": [False, False, False], "ccd": "default"}
DEFAULT_JOINT = {"type": "joint", "kind": "revolute", "body1": None, "body2": None, "axis": [0.0, 1.0, 0.0], "angle_limits": None, "distance_limits": None, "swing_limit": None, "linear_damping": 0.0, "angular_damping": 0.0, "collide": False}
DEFAULT_AUDIO = {"type": "audio_player", "path": "", "volume": 1.0, "loop": False, "autoplay": True, "spatial": True, "distance": 5.0}
WINDMILL = {"type": "scene_reference", "path": "props/windmill.glb", "scene": 0}
DEFAULT_LIGHT = {"type": "light", "intensity": None, "radius": None, "range": None, "color": None, "size": None, "shadows": True, "contact_shadows": False, "volumetric": False, "baked": False, "depth_bias": None, "normal_bias": None, "near_clip": None, "cascades": None}
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
        KINEMATIC_BODY,
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
        {"type": "custom", "type_path": "my_game::Pickup", "data": {"item": "coin", "amount": 5, "respawn": True, "weight": 0.1, "spin": [0.0, 1.5, 0.0], "glow": {"Srgba": {"red": 1.0, "green": 0.8, "blue": 0.2, "alpha": 1.0}}}},
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
    "water": [
        {"type": "shadows", "cast": False, "receive": False},
    ],
    "bushes": [
        {"type": "shadows", "cast": False, "receive": True},
    ],
    "bush_b": [
        {"type": "shadows", "cast": True, "receive": True},
    ],
    "campfire": [
        {"type": "audio_player", "path": "sounds/campfire.ogg", "volume": 0.8, "loop": True, "autoplay": True, "spatial": True, "distance": 4.0},
    ],
    "jingle": [
        {"type": "audio_player", "path": "sounds/chime.ogg", "volume": 0.5, "loop": False, "autoplay": False, "spatial": False, "distance": 5.0},
    ],
    "door_frame": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [0.1, 2.2, 0.2]}},
    ],
    "door": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [1.0, 2.0, 0.1]}},
        {**DYNAMIC_BODY, "angular_velocity": [0.0, 6.0, 0.0]},
    ],
    "door_hinge": [
        {**DEFAULT_JOINT, "body1": "door_frame", "body2": "door", "angle_limits": [0.0, 1.5708]},
    ],
    "chain_link_1": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [0.15, 0.6, 0.15]}},
        DYNAMIC_BODY,
    ],
    "chain_link_2": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [0.15, 0.6, 0.15]}},
        {**DYNAMIC_BODY, "linear_velocity": [3.0, 0.0, 0.0]},
    ],
    "chain_top": [
        {**DEFAULT_JOINT, "kind": "spherical", "body2": "chain_link_1"},
    ],
    "chain_middle": [
        {**DEFAULT_JOINT, "kind": "spherical", "body1": "chain_link_1", "body2": "chain_link_2", "swing_limit": 0.7854},
    ],
    "drawer_cabinet": [
        {"type": "collider", "shape": "cuboid", **DEFAULT_COLLIDER},
        STATIC_BODY,
    ],
    "drawer": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [0.8, 0.3, 0.8]}},
        {**DYNAMIC_BODY, "linear_velocity": [2.0, 0.0, 0.0]},
        {**DEFAULT_JOINT, "kind": "prismatic", "body1": "drawer_cabinet", "body2": "drawer", "axis": [1.0, 0.0, 0.0], "distance_limits": [0.0, 0.4]},
    ],
    "barrel": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [0.8, 1.0, 0.8]}},
        DYNAMIC_BODY,
    ],
    "barrel_lid": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [0.9, 0.1, 0.9]}},
        DYNAMIC_BODY,
        {**DEFAULT_JOINT, "kind": "fixed", "body1": "barrel", "body2": "barrel_lid", "axis": None, "linear_damping": None, "angular_damping": None},
    ],
    "balloon": [
        {"type": "collider", "shape": "sphere", **{**DEFAULT_COLLIDER, "radius": 0.3}},
        {**DYNAMIC_BODY, "gravity_scale": -0.5, "linear_damping": 0.5, "angular_damping": 0.2},
    ],
    "spinner": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [1.5, 0.2, 0.2]}},
        {**KINEMATIC_BODY, "angular_velocity": [0.0, 1.5708, 0.0]},
    ],
    "puck": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [0.5, 0.1, 0.5]}},
        {**DYNAMIC_BODY, "lock_translation": [False, True, False], "lock_rotation": [True, True, True], "linear_velocity": [2.0, 0.0, 0.0], "angular_velocity": [0.0, 3.0, 0.0]},
    ],
    "bullet": [
        {"type": "collider", "shape": "sphere", **{**DEFAULT_COLLIDER, "radius": 0.05}},
        {**DYNAMIC_BODY, "gravity_scale": 0.0, "ccd": "all", "linear_velocity": [80.0, 0.0, 0.0]},
    ],
    "bullet_target": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [0.02, 1.0, 1.0]}},
        {**DYNAMIC_BODY, "gravity_scale": 0.0},
    ],
    "gate": [
        {"type": "animation", "clip": "gate_open", "repeat": False, "speed": 1.0},
    ],
    "windmill_a": [
        WINDMILL,
    ],
    "windmill_b": [
        WINDMILL,
    ],
    "fog_bank": [
        {"type": "fog_volume", "size": [6.0, 2.0, 6.0], "color": [0.8, 0.85, 1.0], "density": 0.2, "absorption": 0.3, "scattering": 0.3, "anisotropy": 0.6, "light_tint": [1.0, 1.0, 1.0], "light_intensity": 1.5},
    ],
    "room_probe": [
        {"type": "reflection_probe", "size": [24.0, 5.0, 24.0], "falloff": [0.25, 0.25, 0.25], "intensity": 2000.0, "parallax_correction": True, "texture": "probe_cubemap"},
    ],
    "gi_volume": [
        {"type": "irradiance_volume", "size": [24.0, 6.0, 24.0], "falloff": [0.1, 0.1, 0.1], "intensity": 500.0, "texture": "irradiance_volume"},
    ],
    "sun": [
        {**DEFAULT_LIGHT, "kind": "directional", "volumetric": True, "cascades": {"count": 3, "minimum_distance": 0.1, "first_cascade_far_bound": 8.0, "maximum_distance": 80.0, "overlap_proportion": 0.2}},
    ],
    "lamp_light": [
        {**DEFAULT_LIGHT, "kind": "point", "radius": 0.1, "baked": True, "depth_bias": 0.1, "normal_bias": 0.5, "near_clip": 0.05},
    ],
    "spot_light": [
        {**DEFAULT_LIGHT, "kind": "spot", "intensity": 2000.0, "radius": 0.0, "shadows": False, "contact_shadows": True},
    ],
    "window_light": [
        {**DEFAULT_LIGHT, "kind": "area", "intensity": 34150.0, "color": [1.0, 1.0, 1.0], "size": [2.0, 1.0], "shadows": False},
    ],
}
PROBE_IMAGES = {"probe_cubemap", "irradiance_volume"}

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
    if isinstance(value, tuple):
        return tuple(_rounded(item) for item in value)
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    return value


def _named_textures(gltf, components):
    return [{**component, "texture": gltf["images"][gltf["textures"][component["texture"]]["source"]]["name"]} if isinstance(component.get("texture"), int) else component for component in components]


def _extras(gltf, node):
    extras = node.get("extras")
    if not isinstance(extras, dict) or "bevy_components" not in extras:
        return extras
    data = json.loads(extras["bevy_components"])
    return {**data, "components": _named_textures(gltf, data["components"])}


def _node_summary(gltf):
    nodes = gltf["nodes"]
    summary = {}
    for node in nodes:
        summary[node["name"]] = {
            "extras": _extras(gltf, node),
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


def _operator_icon(layout, properties):
    return next(bound.get("icon") for name, bound, child in layout.calls if name == "operator" and bound.get("properties") is properties)


def _prop_layouts(layout, prop):
    return [child for name, bound, child in layout.calls if name == "prop" and bound["property"] == prop]


def _extents(lines):
    return tuple(round(max(abs(point[axis]) for line in lines for point in line), 5) for axis in range(3))


class FakePanel:
    def __init__(self, test):
        self.layout = FakeLayout(test)
        self.bl_label = "Bevy Components"


def _collider_lines(obj, item, limit, batches=False):
    found = addon.overlay.collider_lines(obj, item, limit, addon.system.children_map(bpy.data.objects))
    return found if batches else [line for matrix, lines in found for line in lines]


def _line_keys(lines):
    return sorted(tuple(sorted(tuple(round(value, 5) for value in point) for point in line)) for line in lines)


def _menu_context(obj=None, item=None):
    return SimpleNamespace(object=obj, bevy_component=item, scene=bpy.context.scene, space_data=SimpleNamespace(overlay=SimpleNamespace(show_overlays=True)))


class TestRegistration(unittest.TestCase):
    def test_extension_registers_types_and_operators(self):
        self.assertTrue(hasattr(bpy.types.Object, "bevy_component_data"))
        self.assertTrue(hasattr(bpy.types.Scene, "bevy_component_previews"))
        self.assertTrue(hasattr(bpy.types.Scene, "bevy_component_definitions"))
        self.assertTrue(hasattr(bpy.types.World, "bevy_ambient_light"))
        for idname in ("bevy_components.add", "bevy_components.remove", "bevy_components.duplicate", "bevy_components.copy_component_to_selected", "bevy_components.reset", "bevy_components.move", "bevy_components.lod_preset", "bevy_components.set_collision_layers", "bevy_components.pick_sound", "bevy_components.define_fields", "bevy_components.definition_add", "bevy_components.definition_remove", "bevy_components.field_add", "bevy_components.field_remove", "bevy_components.field_move", "bevy_components.copy_to_selected", "bevy_components.validate", "bevy_components.cancel_export", "export_scene.bevy_components_glb"):
            self.assertTrue(_operator_exists(idname), idname)
        for idname in ("BEVY_MT_component_add", "BEVY_MT_component_add_physics", "BEVY_MT_component_add_rendering", "BEVY_MT_component_add_audio", "BEVY_MT_component_add_animation", "BEVY_MT_component_add_scene", "BEVY_MT_component_context_menu", "BEVY_MT_object_context_menu", "BEVY_PT_object_properties", "BEVY_PT_view_sidebar", "BEVY_PT_scene_definitions", "BEVY_PT_world_ambient_light", "BEVY_PT_overlay", "BEVY_UL_definitions", "BEVY_UL_fields"):
            self.assertTrue(hasattr(bpy.types, idname), idname)
        for idname in ("BEVY_GGT_collider_handles", "BEVY_GGT_audio_handles"):
            self.assertIsNotNone(bpy.types.GizmoGroup.bl_rna_get_subclass_py(idname), idname)
        self.assertEqual(bpy.types.BEVY_PT_overlay.bl_parent_id, "VIEW3D_PT_overlay")
        self.assertIn(addon.menu.export_menu, bpy.types.TOPBAR_MT_file_export._dyn_ui_initialize())
        self.assertIn(addon.menu.export_status, bpy.types.STATUSBAR_HT_header._dyn_ui_initialize())
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
        for menu in (addon.menu.BEVY_MT_component_add, addon.menu.BEVY_MT_component_add_physics, addon.menu.BEVY_MT_component_add_rendering, addon.menu.BEVY_MT_component_add_audio, addon.menu.BEVY_MT_component_add_animation, addon.menu.BEVY_MT_component_add_scene):
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

    def test_body_tuning_is_stored_for_moving_bodies(self):
        body = add_component(self.obj, "RIGID_BODY", rigid_body_gravity_scale=0.5, rigid_body_linear_damping=1, rigid_body_lock_rotation=(True, False, True), rigid_body_ccd="ALL", rigid_body_linear_velocity=(1, 2, 3), rigid_body_angular_velocity=(0, 4, 0))
        self.assertEqual(_stored(self.obj)["components"], [STATIC_BODY])
        body.rigid_body_kind = "KINEMATIC"
        self.assertEqual(_stored(self.obj)["components"], [{**KINEMATIC_BODY, "linear_velocity": [1.0, 2.0, 3.0], "angular_velocity": [0.0, 4.0, 0.0]}])
        body.rigid_body_kind = "DYNAMIC"
        self.assertEqual(_stored(self.obj)["components"], [{**DYNAMIC_BODY, "gravity_scale": 0.5, "linear_damping": 1.0, "lock_rotation": [True, False, True], "ccd": "all", "linear_velocity": [1.0, 2.0, 3.0], "angular_velocity": [0.0, 4.0, 0.0]}])

    def test_reset_keeps_open_sub_panels(self):
        body = add_component(self.obj, "RIGID_BODY", rigid_body_kind="DYNAMIC", rigid_body_gravity_scale=0, rigid_body_lock_translation=(True, True, True), show_velocity=True, show_dynamics=True)
        bpy.ops.bevy_components.reset(index=0)
        self.assertEqual((body.rigid_body_kind, body.rigid_body_gravity_scale, tuple(body.rigid_body_lock_translation)), ("STATIC", 1.0, (False, False, False)))
        self.assertEqual((body.show_velocity, body.show_dynamics), (True, True))

    def test_joints_start_on_the_body_they_are_added_to(self):
        hinge = add_empty("hinge", (0, 0, 0))
        joint = add_component(hinge, "JOINT")
        self.assertEqual((joint.joint_body1, joint.joint_body2), (None, None))
        self.assertEqual(_stored(hinge)["components"], [DEFAULT_JOINT])
        add_component(self.obj, "COLLIDER")
        joint = add_component(self.obj, "JOINT")
        self.assertEqual((joint.joint_body1, joint.joint_body2), (None, self.obj))
        self.assertEqual(_stored(self.obj)["components"][1]["body2"], "subject")

    def test_copied_joints_point_at_their_new_object(self):
        frame = add_mesh(bpy.ops.mesh.primitive_cube_add, "frame")
        add_component(frame, "COLLIDER")
        add_component(self.obj, "COLLIDER")
        joint = add_component(self.obj, "JOINT")
        joint.joint_body1 = frame
        other = add_mesh(bpy.ops.mesh.primitive_cube_add, "other")
        select(self.obj, other)
        self.assertEqual(bpy.ops.bevy_components.copy_component_to_selected(index=1), {"FINISHED"})
        copied = other.bevy_component_data.components[0]
        self.assertEqual((copied.joint_body1, copied.joint_body2), (frame, other))
        self.assertEqual((joint.joint_body1, joint.joint_body2), (frame, self.obj))
        third = add_mesh(bpy.ops.mesh.primitive_cube_add, "third")
        select(self.obj, third)
        self.assertEqual(bpy.ops.bevy_components.copy_to_selected(), {"FINISHED"})
        self.assertEqual([(item["body1"], item["body2"]) for item in _stored(third)["components"] if item["type"] == "joint"], [("frame", "third")])

    def test_reset_restores_defaults(self):
        item = add_component(self.obj, "COLLIDER", collider_shape="CAPSULE", collider_radius=3, collider_sensor=True)
        item.show_expanded = False
        self.assertEqual(bpy.ops.bevy_components.reset(index=0), {"FINISHED"})
        self.assertEqual((item.component_type, item.collider_shape, item.collider_radius, item.collider_sensor, item.show_expanded), ("COLLIDER", "TRIMESH", 0.5, False, False))
        self.assertEqual(_stored(self.obj)["components"][0]["shape"], "trimesh")
        add_component(self.obj, "CUSTOM", custom_type="game::Tag", custom_json='{"a": 1}')
        self.assertEqual(bpy.ops.bevy_components.reset(index=1), {"FINISHED"})
        self.assertEqual(_stored(self.obj)["components"][1], {"type": "custom", "type_path": "game::Tag", "data": {}})

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

    def test_shadows_are_stored(self):
        item = add_component(self.obj, "SHADOWS")
        self.assertEqual(_stored(self.obj)["components"], [{"type": "shadows", "cast": False, "receive": True}])
        item.shadows_cast = True
        item.shadows_receive = False
        self.assertEqual(_stored(self.obj)["components"], [{"type": "shadows", "cast": True, "receive": False}])
        self.assertEqual(bpy.ops.bevy_components.add(component_type="SHADOWS"), {"CANCELLED"})

    def test_audio_players_are_stored(self):
        item = add_component(self.obj, "AUDIO_PLAYER")
        self.assertEqual(_stored(self.obj)["components"], [DEFAULT_AUDIO])
        item.audio_path = " sounds/fire.ogg "
        item.audio_volume = 0.3
        item.audio_loop = True
        item.audio_autoplay = False
        item.audio_spatial = False
        item.audio_distance = 12.5
        self.assertEqual(_stored(self.obj)["components"], [{"type": "audio_player", "path": "sounds/fire.ogg", "volume": 0.3, "loop": True, "autoplay": False, "spatial": False, "distance": 12.5}])
        self.assertEqual(bpy.ops.bevy_components.add(component_type="AUDIO_PLAYER"), {"CANCELLED"})

    def test_reset_restores_shadow_and_audio_defaults(self):
        shadows = add_component(self.obj, "SHADOWS", shadows_cast=True, shadows_receive=False)
        audio = add_component(self.obj, "AUDIO_PLAYER", audio_path="sounds/fire.ogg", audio_volume=0.2, audio_loop=True, audio_spatial=False, audio_distance=30)
        bpy.ops.bevy_components.reset(index=0)
        bpy.ops.bevy_components.reset(index=1)
        self.assertEqual((shadows.shadows_cast, shadows.shadows_receive), (False, True))
        self.assertEqual((audio.audio_path, audio.audio_volume, audio.audio_loop, audio.audio_autoplay, audio.audio_spatial, audio.audio_distance), ("", 1.0, False, True, True, 5.0))
        self.assertEqual(_stored(self.obj)["components"], [{"type": "shadows", "cast": False, "receive": True}, DEFAULT_AUDIO])

    def test_pick_sound_stores_the_path_inside_assets(self):
        add_component(self.obj, "COLLIDER")
        audio = add_component(self.obj, "AUDIO_PLAYER")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "game").mkdir()
            (root / "game" / "Cargo.toml").write_text("[package]\n")
            cases = (
                (root / "game" / "assets" / "sounds" / "fire.ogg", "sounds/fire.ogg"),
                (root / "game" / "assets" / "packs" / "assets" / "wind.wav", "packs/assets/wind.wav"),
                (root / "assets" / "music" / "theme.mp3", "music/theme.mp3"),
                (root / "downloads" / "loose.flac", "loose.flac"),
            )
            for file, expected in cases:
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b"")
                self.assertEqual(pick_sound(self.obj, file), {"FINISHED"})
                self.assertEqual(audio.audio_path, expected)
            self.assertEqual(_stored(self.obj)["components"][1]["path"], "loose.flac")
            self.assertEqual(bpy.ops.bevy_components.pick_sound(index=0, filepath=str(cases[0][0])), {"CANCELLED"})
            self.assertEqual(audio.audio_path, "loose.flac")

    def test_scene_references_are_stored_relative_to_the_blend_file(self):
        holder = add_empty("holder", (0, 0, 0))
        item = add_component(holder, "SCENE_REFERENCE")
        self.assertEqual(_stored(holder)["components"], [{"type": "scene_reference", "path": "", "scene": 0}])
        self.assertEqual(bpy.ops.bevy_components.add(component_type="SCENE_REFERENCE"), {"CANCELLED"})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "levels").mkdir()
            bpy.ops.wm.save_as_mainfile(filepath=str(root / "levels" / "level.blend"))
            item.scene_file = "//props/tree.glb"
            item.scene_index = 2
            self.assertEqual(_stored(holder)["components"], [{"type": "scene_reference", "path": "props/tree.glb", "scene": 2}])
            item.scene_file = str(root / "shared" / "rock.gltf")
            self.assertEqual(_stored(holder)["components"][0]["path"], "../shared/rock.gltf")
            bpy.ops.wm.save_mainfile()
            bpy.ops.wm.open_mainfile(filepath=str(root / "levels" / "level.blend"))
            self.assertEqual(_stored(bpy.data.objects["holder"])["components"], [{"type": "scene_reference", "path": "../shared/rock.gltf", "scene": 2}])

    def test_animation_starts_with_the_objects_action(self):
        spin = animate(self.obj, "spin", "rotation_euler", 2, [(1, 0.0), (10, 1.0)])
        animate(add_mesh(bpy.ops.mesh.primitive_cube_add, "other"), "wave", "location", 0, [(1, 0.0), (10, 1.0)])
        select(self.obj)
        item = add_component(self.obj, "ANIMATION")
        self.assertEqual(_stored(self.obj)["components"], [{"type": "animation", "clip": "spin", "repeat": True, "speed": 1.0}])
        self.assertEqual(bpy.ops.bevy_components.add(component_type="ANIMATION"), {"CANCELLED"})
        item.animation_loop = False
        item.animation_speed = 0.30000001192092896
        self.assertEqual(_stored(self.obj)["components"][0], {"type": "animation", "clip": "spin", "repeat": False, "speed": 0.3})
        track = self.obj.animation_data.nla_tracks.new()
        track.strips.new("spin", 1, spin)
        self.obj.animation_data.action = None
        self.assertEqual(addon.system.default_clip(self.obj), "spin")
        self.assertEqual(addon.system.default_clip(add_empty("still", (0, 0, 0))), "")

    def test_reset_keeps_the_scene_file_and_clip(self):
        reference = add_component(self.obj, "SCENE_REFERENCE", scene_file="//props/tree.glb", scene_index=3)
        animation = add_component(self.obj, "ANIMATION", animation_clip="spin", animation_loop=False, animation_speed=2)
        bpy.ops.bevy_components.reset(index=0)
        bpy.ops.bevy_components.reset(index=1)
        self.assertEqual((reference.scene_file, reference.scene_index), ("//props/tree.glb", 0))
        self.assertEqual((animation.animation_clip, animation.animation_loop, animation.animation_speed), ("spin", True, 1.0))

    def test_fog_volumes_and_light_probes_are_stored(self):
        add_component(self.obj, "FOG_VOLUME", volume_size=(4, 2, 4), fog_density=0.25)
        probe = add_component(self.obj, "REFLECTION_PROBE", volume_falloff=0.5, probe_intensity=300, probe_parallax=False, probe_file=str(CUBEMAP))
        add_component(self.obj, "IRRADIANCE_VOLUME")
        fog, reflection, irradiance = _stored(self.obj)["components"]
        self.assertEqual(fog, {"type": "fog_volume", "size": [4.0, 2.0, 4.0], "color": [1.0, 1.0, 1.0], "density": 0.25, "absorption": 0.3, "scattering": 0.3, "anisotropy": 0.5, "light_tint": [1.0, 1.0, 1.0], "light_intensity": 1.0})
        self.assertEqual(reflection, {"type": "reflection_probe", "size": [10.0, 5.0, 10.0], "falloff": [0.5, 0.5, 0.5], "intensity": 300.0, "parallax_correction": False, "file": str(CUBEMAP)})
        self.assertEqual(irradiance, {"type": "irradiance_volume", "size": [10.0, 5.0, 10.0], "falloff": [0.0, 0.0, 0.0], "intensity": 1000.0, "file": None})
        self.assertEqual(bpy.ops.bevy_components.add(component_type="REFLECTION_PROBE"), {"CANCELLED"})
        self.assertEqual(bpy.ops.bevy_components.reset(index=1), {"FINISHED"})
        self.assertEqual((tuple(probe.volume_size), probe.volume_falloff, probe.probe_intensity, probe.probe_parallax, probe.probe_file), ((10.0, 5.0, 10.0), 0.0, 1000.0, True, ""))
        other = add_mesh(bpy.ops.mesh.primitive_cube_add, "other")
        probe.probe_file = str(CUBEMAP)
        select(self.obj, other)
        self.assertEqual(bpy.ops.bevy_components.copy_component_to_selected(index=1), {"FINISHED"})
        self.assertEqual(_stored(other)["components"], [_stored(self.obj)["components"][1]])

    def test_lights_are_stored(self):
        self.assertEqual(bpy.ops.bevy_components.add(component_type="LIGHT"), {"CANCELLED"})
        self.assertEqual(len(self.obj.bevy_component_data.components), 0)
        lamp = add_light("lamp", "POINT", (0, 0, 0), energy=10)
        item = add_component(lamp, "LIGHT")
        self.assertEqual(_stored(lamp)["components"], [{**DEFAULT_LIGHT, "kind": "point", "radius": 0.0}])
        lamp.data.shadow_soft_size = 0.2
        lamp.data.use_shadow = False
        item.light_contact_shadows = True
        item.light_volumetric = True
        item.light_baked = True
        self.assertEqual(_rounded(_stored(lamp)["components"]), [{**DEFAULT_LIGHT, "kind": "point", "radius": 0.2, "shadows": False, "contact_shadows": True, "volumetric": True, "baked": True}])
        self.assertEqual(bpy.ops.bevy_components.add(component_type="LIGHT"), {"CANCELLED"})

    def test_light_overrides_start_from_blender_and_bevy_values(self):
        lamp = add_light("lamp", "SPOT", (0, 0, 0), energy=10)
        item = add_component(lamp, "LIGHT")
        item.light_use_intensity = True
        self.assertEqual(item.light_intensity, 6830.0)
        item.light_intensity = 500
        item.light_use_intensity = False
        item.light_use_intensity = True
        self.assertEqual(_stored(lamp)["components"][0]["intensity"], 500.0)
        item.light_use_bias = True
        self.assertEqual(_rounded((item.light_depth_bias, item.light_normal_bias, item.light_near_clip)), (0.02, 1.8, 0.1))
        point = add_light("point", "POINT", (0, 0, 0))
        item = add_component(point, "LIGHT", light_use_bias=True)
        self.assertEqual(_rounded([_stored(point)["components"][0][key] for key in ("depth_bias", "normal_bias", "near_clip")]), [0.08, 0.6, 0.1])
        sun = add_light("sun", "SUN", (0, 0, 0), energy=3)
        item = add_component(sun, "LIGHT", light_use_intensity=True, light_use_bias=True, light_use_cascades=True)
        stored = _stored(sun)["components"][0]
        self.assertEqual(_rounded([stored[key] for key in ("kind", "intensity", "radius", "depth_bias", "normal_bias", "near_clip")]), ["directional", 2049.0, None, 0.02, 1.8, None])
        self.assertEqual(_rounded(stored["cascades"]), {"count": 4, "minimum_distance": 0.1, "first_cascade_far_bound": 10.0, "maximum_distance": 150.0, "overlap_proportion": 0.2})

    def test_area_lights_are_stored_as_rectangles(self):
        window = add_light("window", "AREA", (0, 0, 0), shape="ELLIPSE", size=2, size_y=0.5, energy=20, color=(1.0, 0.5, 0.25), use_custom_distance=True, cutoff_distance=8)
        item = add_component(window, "LIGHT", light_volumetric=True, light_use_bias=True)
        self.assertEqual(_rounded(_stored(window)["components"]), [{**DEFAULT_LIGHT, "kind": "area", "intensity": 13660.0, "range": 8.0, "color": [1.0, 0.5, 0.25], "size": [2.0, 0.5], "shadows": False}])
        window.data.shape = "SQUARE"
        if hasattr(window.data, "normalize"):
            window.data.normalize = False
            window.scale = (2, 1, 1)
            bpy.context.view_layer.update()
            self.assertEqual(addon.metadata.light_intensity(window.data, window), 20 * 683 * 2 * 2 * 2)
        item.light_use_intensity = True
        self.assertEqual(item.light_intensity, addon.metadata.light_intensity(window.data, window))

    def test_light_components_stay_on_lights(self):
        lamp = add_light("lamp", "POINT", (0, 0, 0))
        add_component(lamp, "LIGHT", light_baked=True)
        add_component(lamp, "CUSTOM", custom_type="game::Flicker")
        other = add_light("other", "SPOT", (1, 0, 0))
        select(lamp, self.obj, other)
        self.assertEqual(bpy.ops.bevy_components.copy_to_selected(), {"FINISHED"})
        self.assertEqual([item.component_type for item in self.obj.bevy_component_data.components], ["CUSTOM"])
        self.assertEqual([item.component_type for item in other.bevy_component_data.components], ["LIGHT", "CUSTOM"])
        self.obj.bevy_component_data.components.clear()
        other.bevy_component_data.components.clear()
        self.assertEqual(bpy.ops.bevy_components.copy_component_to_selected(index=0), {"FINISHED"})
        self.assertEqual(len(self.obj.bevy_component_data.components), 0)
        self.assertEqual(_stored(other)["components"][0]["baked"], True)

    def test_reset_restores_light_defaults(self):
        lamp = add_light("lamp", "POINT", (0, 0, 0))
        item = add_component(lamp, "LIGHT", light_use_intensity=True, light_intensity=5, light_baked=True, light_use_bias=True, light_depth_bias=0.3, show_shadows=True)
        bpy.ops.bevy_components.reset(index=0)
        self.assertEqual((item.light_use_intensity, item.light_baked, item.light_use_bias, item.show_shadows), (False, False, False, True))
        item.light_use_bias = True
        self.assertEqual(_rounded(item.light_depth_bias), 0.08)

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

    def test_save_and_reload_keeps_joint_bodies(self):
        add_component(self.obj, "COLLIDER")
        frame = add_mesh(bpy.ops.mesh.primitive_cube_add, "frame")
        add_component(frame, "COLLIDER")
        joint = add_component(self.obj, "JOINT", joint_kind="SPHERICAL", joint_use_swing=True)
        joint.joint_body1 = frame
        frame.name = "door_frame"
        self.assertEqual(_stored(self.obj)["components"][1]["body1"], "frame")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "level.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(path))
            bpy.ops.wm.open_mainfile(filepath=str(path))
        obj = bpy.data.objects["subject"]
        joint = obj.bevy_component_data.components[1]
        self.assertEqual((joint.joint_body1, joint.joint_body2), (bpy.data.objects["door_frame"], obj))
        self.assertEqual(_rounded(_stored(obj)["components"][1]), {**DEFAULT_JOINT, "kind": "spherical", "body1": "door_frame", "body2": "subject", "swing_limit": 0.7854})


class TestPanels(unittest.TestCase):
    def setUp(self):
        clear_scene()
        self.obj = add_mesh(bpy.ops.mesh.primitive_cube_add, "subject")

    def test_object_panel_draws_every_component(self):
        for kind in ("VISIBILITY_RANGE", "COLLIDER", "RIGID_BODY", "CUSTOM", "SHADOWS", "AUDIO_PLAYER", "JOINT", "SCENE_REFERENCE", "ANIMATION"):
            add_component(self.obj, kind)
        collider = self.obj.bevy_component_data.components[1]
        for shape in ("TRIMESH", "CONVEX", "CUBOID", "SPHERE", "CAPSULE"):
            collider.collider_shape = shape
            panel = FakePanel(self)
            self.assertTrue(addon.panel.BEVY_PT_object_properties.poll(bpy.context))
            addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
            text, add_menu, enabled = panel.layout.buttons()[0]
            self.assertEqual((text, add_menu.name), ("Add Component", "BEVY_MT_component_add"))
            self.assertEqual(panel.layout.menus(), ["BEVY_MT_object_context_menu"] + ["BEVY_MT_component_context_menu"] * 9)
            self.assertEqual([bound["property"] for name, bound, layout in panel.layout.calls if name == "panel_prop"], ["show_expanded", "show_expanded", "show_layers", "show_expanded", "show_expanded", "show_expanded", "show_expanded", "show_expanded", "show_expanded", "show_expanded"])
            self.assertEqual(panel.layout.props().count("enabled"), 9)
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
        self.assertEqual(menu.layout.menus(), ["BEVY_MT_component_add_physics", "BEVY_MT_component_add_rendering", "BEVY_MT_component_add_audio", "BEVY_MT_component_add_animation", "BEVY_MT_component_add_scene"])
        found = {}
        for menu_type in (addon.menu.BEVY_MT_component_add, addon.menu.BEVY_MT_component_add_physics, addon.menu.BEVY_MT_component_add_rendering, addon.menu.BEVY_MT_component_add_audio, addon.menu.BEVY_MT_component_add_animation, addon.menu.BEVY_MT_component_add_scene):
            menu = FakePanel(self)
            menu_type.draw(menu, _menu_context(self.obj))
            found.update({properties.component_type: enabled for text, properties, enabled in menu.layout.buttons()})
        self.assertEqual(found, {"CUSTOM": True, "COLLIDER": False, "RIGID_BODY": True, "JOINT": True, "VISIBILITY_RANGE": True, "SHADOWS": True, "LIGHT": False, "FOG_VOLUME": True, "REFLECTION_PROBE": True, "IRRADIANCE_VOLUME": True, "AUDIO_PLAYER": True, "ANIMATION": True, "SCENE_REFERENCE": True})
        add_component(self.obj, "AUDIO_PLAYER")
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add_audio.draw(menu, _menu_context(self.obj))
        self.assertEqual([(text, enabled) for text, properties, enabled in menu.layout.buttons()], [("Audio Player", False)])
        lamp = add_light("lamp", "POINT", (0, 0, 0))
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add_rendering.draw(menu, _menu_context(lamp))
        self.assertTrue(dict((text, enabled) for text, properties, enabled in menu.layout.buttons())["Light"])
        add_component(lamp, "LIGHT")
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add_rendering.draw(menu, _menu_context(lamp))
        self.assertFalse(dict((text, enabled) for text, properties, enabled in menu.layout.buttons())["Light"])

    def test_component_context_menu_targets_its_component(self):
        add_component(self.obj, "COLLIDER")
        custom = add_component(self.obj, "CUSTOM")
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_context_menu.draw(menu, _menu_context(self.obj, custom))
        buttons = {text: (properties, enabled) for text, properties, enabled in menu.layout.buttons()}
        self.assertEqual(set(buttons), {"Duplicate", "Copy to Selected", "Define Fields", "Reset to Defaults", "Move to First", "Move Up", "Move Down", "Move to Last", "Remove"})
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
        self.assertEqual(panel.layout.props()[-4:], ["rigid_body_kind", "rigid_body_use_mass", "rigid_body_mass", "rigid_body_gravity_scale"])
        self.assertIn(("row", "Mass"), [(name, bound.get("heading")) for name, bound, layout in panel.layout.calls])
        self.assertFalse(_prop_layout(panel.layout, "rigid_body_mass").active)
        body.rigid_body_use_mass = True
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertTrue(_prop_layout(panel.layout, "rigid_body_mass").active)

    def test_rigid_body_card_tunes_moving_bodies(self):
        body = add_component(self.obj, "RIGID_BODY", show_velocity=True, show_dynamics=True)
        expected = {
            "STATIC": ["rigid_body_kind"],
            "KINEMATIC": ["rigid_body_kind", *["rigid_body_linear_velocity"] * 3, *["rigid_body_angular_velocity"] * 3],
            "DYNAMIC": ["rigid_body_kind", "rigid_body_use_mass", "rigid_body_mass", "rigid_body_gravity_scale", *["rigid_body_linear_velocity"] * 3, *["rigid_body_angular_velocity"] * 3, "rigid_body_linear_damping", "rigid_body_angular_damping", *["rigid_body_lock_translation"] * 3, *["rigid_body_lock_rotation"] * 3, "rigid_body_ccd"],
        }
        for kind, props in expected.items():
            body.rigid_body_kind = kind
            panel = FakePanel(self)
            addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
            self.assertEqual([prop for prop in panel.layout.props() if prop.startswith("rigid_body_")], props, kind)
        self.assertEqual([bound["property"] for name, bound, layout in panel.layout.calls if name == "panel_prop"], ["show_expanded", "show_velocity", "show_dynamics"])
        self.assertIn(("row", "Lock Position"), [(name, bound.get("heading")) for name, bound, layout in panel.layout.calls])
        toggles = [(bound["index"], bound["text"], bound["toggle"]) for name, bound, layout in panel.layout.calls if name == "prop" and bound["property"] == "rigid_body_lock_rotation"]
        self.assertEqual(toggles, [(0, "X", True), (1, "Y (Up)", True), (2, "Z", True)])
        self.assertEqual([bound["text"] for name, bound, layout in panel.layout.calls if name == "prop" and bound["property"] == "rigid_body_angular_velocity"], ["Spin X", "Y (Up)", "Z"])
        body.rigid_body_lock_rotation = (False, True, False)
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual([layout.active for name, bound, layout in panel.layout.calls if name == "prop" and bound["property"] == "rigid_body_angular_velocity"], [True, False, True])
        body.rigid_body_kind = "KINEMATIC"
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual([layout.active for name, bound, layout in panel.layout.calls if name == "prop" and bound["property"] == "rigid_body_angular_velocity"], [True, True, True])
        body.show_velocity = False
        body.show_dynamics = False
        body.rigid_body_kind = "DYNAMIC"
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props()[-1], "rigid_body_gravity_scale")
        self.assertIn("Initial Velocity", panel.layout.texts())
        self.assertIn("Dynamics", panel.layout.texts())

    def test_joint_card_follows_its_type(self):
        frame = add_mesh(bpy.ops.mesh.primitive_cube_add, "frame")
        add_component(frame, "COLLIDER")
        joint = add_component(self.obj, "JOINT")
        joint.joint_body1 = frame
        select(self.obj)
        expected = {
            "FIXED": ["joint_kind", "joint_body1", "joint_body2", "joint_collide"],
            "REVOLUTE": ["joint_kind", "joint_body1", "joint_body2", "joint_axis", "joint_use_limits", "joint_angle_min", "joint_angle_max", "joint_linear_damping", "joint_angular_damping", "joint_collide"],
            "PRISMATIC": ["joint_kind", "joint_body1", "joint_body2", "joint_axis", "joint_use_limits", "joint_distance_min", "joint_distance_max", "joint_linear_damping", "joint_angular_damping", "joint_collide"],
            "SPHERICAL": ["joint_kind", "joint_body1", "joint_body2", "joint_axis", "joint_use_swing", "joint_swing", "joint_use_limits", "joint_angle_min", "joint_angle_max", "joint_linear_damping", "joint_angular_damping", "joint_collide"],
        }
        for kind, props in expected.items():
            joint.joint_kind = kind
            panel = FakePanel(self)
            addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
            self.assertEqual([prop for prop in panel.layout.props() if prop.startswith("joint_")], props, kind)
            self.assertEqual([bound.get("placeholder") for name, bound, layout in panel.layout.calls if name == "prop" and bound["property"] in {"joint_body1", "joint_body2"}], ["World", "World"])
            self.assertIn("Pins frame to this spot in the level", panel.layout.texts())
        self.assertEqual([bound["text"] for name, bound, layout in panel.layout.calls if name == "prop" and bound["property"] == "joint_use_limits"], ["Twist Limits"])
        self.assertIn(("row", "Swing Limit"), [(name, bound.get("heading")) for name, bound, layout in panel.layout.calls])
        self.assertFalse(_prop_layout(panel.layout, "joint_swing").active)
        joint.joint_kind = "REVOLUTE"
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertFalse(_prop_layout(panel.layout, "joint_angle_min").active)
        self.assertEqual([bound["text"] for name, bound, layout in panel.layout.calls if name == "prop" and bound["property"] == "joint_use_limits"], ["Limits"])
        joint.joint_use_limits = True
        joint.joint_angle_min = 1
        joint.joint_angle_max = -1
        door = add_mesh(bpy.ops.mesh.primitive_cube_add, "door")
        add_component(door, "RIGID_BODY", rigid_body_kind="DYNAMIC")
        joint.joint_body2 = door
        select(self.obj)
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertTrue(_prop_layout(panel.layout, "joint_angle_min").active)
        self.assertTrue(_prop_layout(panel.layout, "joint_angle_min").is_alert())
        self.assertIn("Min must not be above Max", panel.layout.texts())
        self.assertIn(("", "CANCEL"), [(bound.get("text"), bound.get("icon")) for name, bound, layout in panel.layout.calls if name == "label"])
        self.assertNotIn("Pins frame to this spot in the level", panel.layout.texts())

    def test_joints_only_pick_bodies(self):
        joint = add_component(self.obj, "JOINT")
        poll = addon.property._is_body
        self.assertFalse(poll(joint, self.obj))
        add_component(self.obj, "COLLIDER")
        self.assertTrue(poll(joint, self.obj))
        holder = add_empty("holder", (0, 0, 0))
        add_component(holder, "RIGID_BODY")
        self.assertTrue(poll(joint, holder))

    def test_shadows_card(self):
        shadows = add_component(self.obj, "SHADOWS")
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props()[-2:], ["shadows_cast", "shadows_receive"])
        self.assertIn(("column", "Shadows"), [(name, bound.get("heading")) for name, bound, layout in panel.layout.calls])
        self.assertIn("Shadows", panel.layout.texts())
        self.assertNotIn("Casts and receives shadows", panel.layout.texts())
        shadows.shadows_cast = True
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertIn("Casts and receives shadows", panel.layout.texts())

    def test_audio_player_card(self):
        audio = add_component(self.obj, "AUDIO_PLAYER")
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props()[-6:], ["audio_path", "audio_volume", "audio_loop", "audio_autoplay", "audio_spatial", "audio_distance"])
        self.assertIn(("column", "Playback"), [(name, bound.get("heading")) for name, bound, layout in panel.layout.calls])
        self.assertEqual([(properties.index, enabled) for text, properties, enabled in panel.layout.buttons() if text == "" and _operator_icon(panel.layout, properties) == "FILEBROWSER"], [(0, True)])
        self.assertTrue(_prop_layout(panel.layout, "audio_path").alert)
        self.assertTrue(_prop_layout(panel.layout, "audio_distance").active)
        audio.audio_path = "sounds/fire.ogg"
        audio.audio_spatial = False
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertFalse(_prop_layout(panel.layout, "audio_path").alert)
        self.assertFalse(_prop_layout(panel.layout, "audio_distance").active)

    def test_scene_reference_card(self):
        reference = add_component(self.obj, "SCENE_REFERENCE")
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props()[-2:], ["scene_file", "scene_index"])
        self.assertTrue(_prop_layout(panel.layout, "scene_file").alert)
        reference.scene_file = "//props/tree.glb"
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertFalse(_prop_layout(panel.layout, "scene_file").alert)
        self.assertEqual(addon.property.BEVY_PG_component.bl_rna.properties["scene_file"].subtype, "FILE_PATH")

    def test_animation_card(self):
        add_component(self.obj, "ANIMATION")
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        searches = [(bound["property"], bound["search_data"], bound["search_property"]) for name, bound, layout in panel.layout.calls if name == "prop_search"]
        self.assertEqual(searches, [("animation_clip", bpy.data, "actions")])
        self.assertEqual(panel.layout.props()[-2:], ["animation_loop", "animation_speed"])

    def test_fog_volume_card(self):
        add_component(self.obj, "FOG_VOLUME")
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props()[1:], ["volume_size"] * 3 + ["fog_color", "fog_density", "fog_absorption", "fog_scattering", "fog_anisotropy", "fog_light_tint", "fog_light_intensity"])
        self.assertEqual([bound["text"] for name, bound, layout in panel.layout.calls if name == "prop" and bound["property"] == "volume_size"], ["Size X", "Y (Up)", "Z"])
        self.assertIn("Fog Volume", panel.layout.texts())

    def test_probe_cards_show_their_files(self):
        reflection = add_component(self.obj, "REFLECTION_PROBE")
        add_component(self.obj, "IRRADIANCE_VOLUME", probe_file=str(IRRADIANCE_VOLUME))
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props(), ["enabled", "volume_size", "volume_size", "volume_size", "volume_falloff", "probe_intensity", "probe_parallax", "probe_file", "enabled", "volume_size", "volume_size", "volume_size", "volume_falloff", "probe_intensity", "probe_file"])
        self.assertEqual([bound["text"] for name, bound, layout in panel.layout.calls if name == "prop" and bound["property"] == "probe_file"], ["Cubemap", "Voxels"])
        self.assertIn("2 × 2 × 2 voxels", panel.layout.texts())
        self.assertIn("No cubemap, so the probe adds no reflections", " ".join(panel.layout.texts()))
        self.assertFalse(any(layout.alert for layout in _prop_layouts(panel.layout, "probe_file")))
        reflection.probe_file = str(IRRADIANCE_VOLUME)
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual([layout.alert for layout in _prop_layouts(panel.layout, "probe_file")], [True, False])
        self.assertIn("irradiance_volume.ktx2 is not a cubemap", " ".join(panel.layout.texts()))
        reflection.probe_file = str(CUBEMAP)
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertIn("16 × 16 cubemap", panel.layout.texts())

    def _draw_card(self, obj):
        select(obj)
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        return panel.layout

    def test_light_card(self):
        lamp = add_light("lamp", "POINT", (0, 0, 0), energy=200)
        item = add_component(lamp, "LIGHT")
        layout = self._draw_card(lamp)
        self.assertEqual(layout.props()[-6:], ["light_use_intensity", "shadow_soft_size", "use_custom_distance", "light_baked", "light_volumetric", "use_shadow"])
        self.assertIn(("row", "Intensity"), [(name, bound.get("heading")) for name, bound, child in layout.calls])
        self.assertIn("136,600 lm", layout.texts())
        self.assertIn("20 m, Bevy's default", layout.texts())
        self.assertNotIn("light_contact_shadows", layout.props())
        item.light_use_intensity = True
        item.show_shadows = True
        lamp.data.use_custom_distance = True
        layout = self._draw_card(lamp)
        self.assertIn("light_intensity", layout.props())
        self.assertIn("lm", layout.texts())
        self.assertIn("cutoff_distance", layout.props())
        self.assertEqual(layout.props()[-3:], ["use_shadow", "light_contact_shadows", "light_use_bias"])
        self.assertTrue(_prop_layout(layout, "light_contact_shadows").active)
        item.light_use_bias = True
        lamp.data.use_shadow = False
        layout = self._draw_card(lamp)
        self.assertEqual(layout.props()[-3:], ["light_depth_bias", "light_normal_bias", "light_near_clip"])
        self.assertFalse(_prop_layout(layout, "light_contact_shadows").active)

    def test_sun_card_draws_cascades(self):
        sun = add_light("sun", "SUN", (0, 0, 0), energy=2)
        item = add_component(sun, "LIGHT", show_shadows=True, light_use_bias=True)
        layout = self._draw_card(sun)
        self.assertIn("1,366 lx", layout.texts())
        for prop in ("shadow_soft_size", "use_custom_distance", "light_near_clip", "light_cascade_count"):
            self.assertNotIn(prop, layout.props())
        self.assertEqual(layout.props()[-3:], ["light_depth_bias", "light_normal_bias", "light_use_cascades"])
        item.light_use_cascades = True
        layout = self._draw_card(sun)
        self.assertEqual(layout.props()[-5:], ["light_cascade_count", "light_cascade_near", "light_cascade_first", "light_cascade_far", "light_cascade_overlap"])
        self.assertFalse(_prop_layout(layout, "light_cascade_first").is_alert())
        item.light_cascade_first = 200
        layout = self._draw_card(sun)
        self.assertTrue(_prop_layout(layout, "light_cascade_first").is_alert())

    def test_area_light_card(self):
        window = add_light("window", "AREA", (0, 0, 0), energy=5)
        add_component(window, "LIGHT")
        layout = self._draw_card(window)
        self.assertEqual(layout.props()[-2:], ["light_use_intensity", "use_custom_distance"])
        self.assertIn("3,415 lm", layout.texts())
        self.assertIn("Bevy area lights cast no shadows", " ".join(layout.texts()))
        self.assertNotIn("light_baked", layout.props())

    def test_area_lights_without_a_light_component_explain_why(self):
        window = add_light("window", "AREA", (0, 0, 0))
        self.assertIn("glTF leaves out area lights", " ".join(self._draw_card(window).texts()))
        add_component(window, "LIGHT")
        self.assertNotIn("glTF leaves out area lights", " ".join(self._draw_card(window).texts()))

    def test_world_ambient_light_panel(self):
        panel_type = addon.panel.BEVY_PT_world_ambient_light
        world = bpy.data.worlds.new("ambient_test")
        try:
            if bpy.app.version < (5, 0, 0):
                world.use_nodes = True
            background = addon.system.world_background(world)
            background.inputs["Color"].default_value = (0.2, 0.4, 0.6, 1.0)
            background.inputs["Strength"].default_value = 2
            context = SimpleNamespace(world=world, region=None)
            self.assertTrue(panel_type.poll(context))
            self.assertFalse(panel_type.poll(SimpleNamespace(world=None)))
            panel = FakePanel(self)
            panel_type.draw_header(panel, context)
            self.assertEqual(panel.layout.props(), ["enabled"])
            panel = FakePanel(self)
            panel_type.draw(panel, context)
            self.assertFalse(panel.layout.active)
            self.assertEqual(panel.layout.props(), ["use_world_color", "default_value", "default_value", "baked"])
            self.assertIn("Bevy gets 1,366 cd/m²", panel.layout.texts())
            self.assertEqual(_rounded(addon.system.ambient_light(world)), ((0.2, 0.4, 0.6), 1366.0))
            world.bevy_ambient_light.enabled = True
            world.bevy_ambient_light.use_world_color = False
            panel = FakePanel(self)
            panel_type.draw(panel, context)
            self.assertTrue(panel.layout.active)
            self.assertEqual(panel.layout.props(), ["use_world_color", "color", "brightness", "baked"])
            self.assertEqual(addon.system.ambient_light(world), ((1.0, 1.0, 1.0), 80.0))
            world.bevy_ambient_light.use_world_color = True
            color = world.node_tree.nodes.new("ShaderNodeRGB")
            world.node_tree.links.new(color.outputs["Color"], background.inputs["Color"])
            panel = FakePanel(self)
            panel_type.draw(panel, context)
            self.assertEqual(panel.layout.props(), ["use_world_color", "color", "baked"])
            self.assertIn("The World color comes from a texture", " ".join(panel.layout.texts()))
            self.assertEqual(_rounded(addon.system.ambient_light(world)), (_rounded(tuple(world.color)), 683.0))
            if bpy.app.version < (5, 0, 0):
                world.use_nodes = False
                panel = FakePanel(self)
                panel_type.draw(panel, context)
                self.assertNotIn("The World color comes from a texture", " ".join(panel.layout.texts()))
        finally:
            bpy.data.worlds.remove(world)

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
        self.assertEqual(panel.layout.props(), ["scope", "colliders", "joints", "velocities", "visibility_ranges", "audio_ranges", "scene_references", "volumes", "lights", "labels", "xray", "edit_handles", "max_mesh_edges"])
        settings.enabled = False
        panel = FakePanel(self)
        addon.panel.BEVY_PT_overlay.draw(panel, _menu_context())
        self.assertFalse(panel.layout.active)
        settings.enabled = True

    def test_export_menu(self):
        panel = FakePanel(self)
        addon.menu.export_menu(panel, bpy.context)
        self.assertEqual(panel.layout.operators(), ["export_scene.bevy_components_glb"])

    def test_status_bar_shows_running_exports(self):
        header = FakePanel(self)
        addon.menu.export_status(header, bpy.context)
        self.assertEqual(header.layout.calls, [])
        self.assertTrue(bpy.ops.export_scene.bevy_components_glb.poll())
        self.assertFalse(bpy.ops.bevy_components.cancel_export.poll())
        task = mock.Mock(done=3, total=8)
        with mock.patch.dict(addon.operator._exports, {task: None}):
            addon.menu.export_status(header, bpy.context)
            self.assertFalse(bpy.ops.export_scene.bevy_components_glb.poll())
            bpy.ops.bevy_components.cancel_export()
        task.cancel.assert_called_once_with()
        self.assertEqual([bound for name, bound, layout in header.layout.calls if name == "progress"], [{"factor": 0.375, "type": "BAR", "text": "Compressing textures 3/8"}])
        self.assertEqual(header.layout.operators(), ["bevy_components.cancel_export"])
        self.assertTrue(bpy.ops.export_scene.bevy_components_glb.poll())

    def test_unregister_stops_running_exports(self):
        task = mock.Mock()
        directory = tempfile.TemporaryDirectory()
        addon.operator._exports[task] = (bpy.context.window_manager.event_timer_add(60.0, window=bpy.context.window), directory)
        addon.operator.stop_exports()
        task.cancel.assert_called_once_with()
        task.wait.assert_called_once_with()
        self.assertFalse(Path(directory.name).exists())
        self.assertEqual(addon.operator._exports, {})

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
            operator = SimpleNamespace(layout=FakeLayout(self), bl_rna=properties, filepath="", texture_compression=mode, selected_only=False, include_lights=True, include_cameras=False, include_animations=False, etc1s_quality=128, etc1s_effort=2, uastc_quality=2, uastc_zstd=18)
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


class TestCustomFields(unittest.TestCase):
    def setUp(self):
        clear_scene()
        self.obj = add_mesh(bpy.ops.mesh.primitive_cube_add, "subject")
        self.other = add_empty("other", (0, 0, 0))
        self.library = bpy.context.scene.bevy_component_definitions

    def _definition(self, type_path):
        return next(definition for definition in self.library.definitions if definition.name == type_path)

    def _data(self, obj):
        return [component["data"] for component in _stored(obj)["components"]]

    def test_defined_components_start_with_defaults(self):
        define_component("game::Health", ("amount", "INT", 100), ("regen", "FLOAT", 0.5), ("tint", "COLOR", (1.0, 0.0, 0.0, 1.0)))
        item = add_component(self.obj, "CUSTOM", type_path="game::Health")
        self.assertEqual((item.custom_type, item.use_fields), ("game::Health", True))
        self.assertEqual([(field.name, field.field_type) for field in item.fields], [("amount", "INT"), ("regen", "FLOAT"), ("tint", "COLOR")])
        self.assertEqual(_stored(self.obj)["components"], [{"type": "custom", "type_path": "game::Health", "data": {"amount": 100, "regen": 0.5, "tint": {"Srgba": {"red": 1.0, "green": 0.0, "blue": 0.0, "alpha": 1.0}}}}])
        set_fields(item, amount=80)
        self.assertEqual(self._data(self.obj), [{"amount": 80, "regen": 0.5, "tint": {"Srgba": {"red": 1.0, "green": 0.0, "blue": 0.0, "alpha": 1.0}}}])
        self.assertEqual(bpy.ops.bevy_components.add(component_type="CUSTOM", type_path="game::Health"), {"CANCELLED"})
        self.assertEqual(len(self.obj.bevy_component_data.components), 1)

    def test_new_definitions_and_fields_get_unique_names(self):
        add_component(self.obj, "CUSTOM")
        bpy.ops.bevy_components.definition_add()
        bpy.ops.bevy_components.definition_add()
        self.assertEqual([definition.name for definition in self.library.definitions], ["my_game::MyComponent2", "my_game::MyComponent3"])
        self.assertFalse(self.obj.bevy_component_data.components[0].use_fields)
        self.library.definitions[1].name = "space::Ship"
        bpy.ops.bevy_components.definition_add()
        self.assertEqual(self.library.definitions[2].name, "space::MyComponent")
        bpy.ops.bevy_components.field_add()
        bpy.ops.bevy_components.field_add()
        fields = self.library.definitions[2].fields
        self.assertEqual([field.name for field in fields], ["field", "field_2"])
        self.assertEqual(len({field.identifier for field in fields}), 2)

    def test_definition_changes_reach_every_object(self):
        define_component("game::Mover", ("speed", "FLOAT", 2.0), ("axis", "VECTOR", (0.0, 1.0, 0.0)))
        first = set_fields(add_component(self.obj, "CUSTOM", type_path="game::Mover"), speed=4.6)
        add_component(self.other, "CUSTOM", type_path="game::Mover")
        definition = self._definition("game::Mover")
        definition.fields[0].name = "velocity"
        self.assertEqual(self._data(self.obj), [{"velocity": 4.6, "axis": [0.0, 1.0, 0.0]}])
        definition.fields[0].field_type = "INT"
        self.assertEqual([self._data(obj)[0]["velocity"] for obj in (self.obj, self.other)], [5, 2])
        definition.fields[0].field_type = "STRING"
        self.assertEqual(self._data(self.obj), [{"velocity": "", "axis": [0.0, 1.0, 0.0]}])
        definition.active_field = 1
        self.assertEqual(bpy.ops.bevy_components.field_move(direction="UP"), {"FINISHED"})
        self.assertEqual(bpy.ops.bevy_components.field_move(direction="UP"), {"CANCELLED"})
        self.assertEqual(list(self._data(self.obj)[0]), ["axis", "velocity"])
        bpy.ops.bevy_components.field_add()
        self.assertEqual(self._data(self.other), [{"axis": [0.0, 1.0, 0.0], "velocity": "", "field": 0.0}])
        definition.active_field = 1
        bpy.ops.bevy_components.field_remove()
        self.assertEqual(list(self._data(self.obj)[0]), ["axis", "field"])
        self.assertEqual([field.name for field in first.fields], ["axis", "field"])

    def test_renaming_a_definition_moves_its_components(self):
        define_component("game::Door", ("locked", "BOOL", True))
        item = add_component(self.obj, "CUSTOM", type_path="game::Door")
        gate = add_component(self.other, "CUSTOM", custom_type="game::Gate", custom_json='{"locked": false}')
        self.assertFalse(gate.use_fields)
        self._definition("game::Door").name = "game::Gate"
        self.assertEqual(item.custom_type, "game::Gate")
        self.assertTrue(gate.use_fields)
        self.assertEqual(self._data(self.other), [{"locked": False}])
        self._definition("game::Gate").name = ""
        self.assertEqual((item.custom_type, item.use_fields), ("game::Gate", True))
        self._definition("").name = "game::Portal"
        self.assertEqual([item.custom_type, gate.custom_type], ["game::Portal", "game::Portal"])
        self.assertEqual(_stored(self.obj)["components"][0]["type_path"], "game::Portal")

    def test_removing_a_definition_keeps_values_as_json(self):
        define_component("game::Door", ("locked", "BOOL", False), ("key", "STRING", ""))
        item = set_fields(add_component(self.obj, "CUSTOM", type_path="game::Door"), locked=True, key="red")
        self.assertEqual(bpy.ops.bevy_components.definition_remove(), {"FINISHED"})
        self.assertEqual((item.use_fields, len(item.fields), item.custom_type), (False, 0, "game::Door"))
        self.assertEqual(json.loads(item.custom_json), {"locked": True, "key": "red"})
        self.assertEqual(self._data(self.obj), [{"locked": True, "key": "red"}])
        self.assertFalse(bpy.ops.bevy_components.definition_remove.poll())

    def test_json_components_switch_to_fields_without_losing_data(self):
        item = add_component(self.obj, "CUSTOM", custom_type="game::Door", custom_json='{"locked": true, "key": "red", "note": "back door"}')
        define_component("game::Door", ("key", "STRING", ""), ("health", "INT", 0), ("locked", "INT", 0))
        self.assertTrue(item.use_fields)
        self.assertEqual(self._data(self.obj), [{"key": "red", "health": 0, "locked": 0}])
        self._definition("game::Door").fields[2].field_type = "BOOL"
        self.assertEqual(self._data(self.obj), [{"key": "red", "health": 0, "locked": True}])
        bpy.ops.bevy_components.definition_remove()
        self.assertEqual(json.loads(item.custom_json), {"key": "red", "health": 0, "locked": True, "note": "back door"})
        mover = add_component(self.other, "CUSTOM", custom_json='{"speed": 3}')
        define_component("game::Mover", ("speed", "FLOAT", 1.0))
        self.assertFalse(mover.use_fields)
        mover.custom_type = "game::Mover"
        self.assertTrue(mover.use_fields)
        self.assertEqual(self._data(self.other), [{"speed": 3.0}])

    def test_define_fields_from_json(self):
        wave = add_component(self.obj, "CUSTOM", custom_type="game::Wave", custom_json='{"count": 3, "delay": 1.5, "boss": "ogre", "spawn": [1, 0, 2]}')
        other = add_component(self.other, "CUSTOM", custom_type="game::Wave", custom_json='{"count": 7}')
        add_component(self.other, "CUSTOM", custom_type="game::Flicker", custom_json="0.25")
        select(self.obj)
        self.assertEqual(bpy.ops.bevy_components.define_fields(index=0), {"FINISHED"})
        definition = self._definition("game::Wave")
        self.assertEqual(self.library.active_index, 0)
        self.assertEqual([(field.name, field.field_type) for field in definition.fields], [("count", "INT"), ("delay", "FLOAT"), ("boss", "STRING"), ("spawn", "VECTOR")])
        self.assertEqual((definition.fields[0].int_value, tuple(definition.fields[3].vector_value)), (3, (1.0, 0.0, 2.0)))
        self.assertTrue(wave.use_fields and other.use_fields)
        self.assertEqual(self._data(self.obj), [{"count": 3, "delay": 1.5, "boss": "ogre", "spawn": [1.0, 0.0, 2.0]}])
        self.assertEqual(self._data(self.other)[0], {"count": 7, "delay": 1.5, "boss": "ogre", "spawn": [1.0, 0.0, 2.0]})
        select(self.other)
        with self.assertRaises(RuntimeError):
            bpy.ops.bevy_components.define_fields(index=1)
        self.assertFalse(self.other.bevy_component_data.components[1].use_fields)
        self.assertEqual(len(self.library.definitions), 1)

    def test_edit_fields_selects_the_definition(self):
        define_component("game::Tag")
        define_component("game::Mover", ("speed", "FLOAT", 1.0))
        add_component(self.obj, "CUSTOM", type_path="game::Tag")
        self.assertEqual(self.library.active_index, 1)
        self.assertEqual(bpy.ops.bevy_components.define_fields(index=0), {"FINISHED"})
        self.assertEqual((self.library.active_index, len(self.library.definitions)), (0, 2))

    def test_define_fields_restores_a_missing_definition(self):
        define_component("game::Tag", ("label", "STRING", "a"))
        item = set_fields(add_component(self.obj, "CUSTOM", type_path="game::Tag"), label="b")
        self.library.definitions.clear()
        self.assertTrue(item.use_fields)
        self.assertEqual(self._data(self.obj), [{"label": "b"}])
        self.assertEqual(bpy.ops.bevy_components.define_fields(index=0), {"FINISHED"})
        field = self._definition("game::Tag").fields[0]
        self.assertEqual((field.name, field.string_value, field.identifier), ("label", "b", item.fields[0].identifier))

    def test_copy_duplicate_and_reset_keep_fields(self):
        define_component("game::Health", ("amount", "INT", 100))
        set_fields(add_component(self.obj, "CUSTOM", type_path="game::Health"), amount=5)
        self.assertEqual(bpy.ops.bevy_components.duplicate(index=0), {"FINISHED"})
        self.assertEqual(self._data(self.obj), [{"amount": 5}, {"amount": 5}])
        select(self.obj, self.other)
        self.assertEqual(bpy.ops.bevy_components.copy_to_selected(), {"FINISHED"})
        self.assertEqual(self._data(self.other), [{"amount": 5}, {"amount": 5}])
        self.assertTrue(all(component.use_fields for component in self.other.bevy_component_data.components))
        select(self.obj)
        self.assertEqual(bpy.ops.bevy_components.reset(index=0), {"FINISHED"})
        item = self.obj.bevy_component_data.components[0]
        self.assertEqual((item.custom_type, item.use_fields), ("game::Health", True))
        self.assertEqual(self._data(self.obj), [{"amount": 100}, {"amount": 5}])

    def test_duplicate_field_names_block_export(self):
        define_component("game::Pair", ("value", "INT", 0), ("other", "INT", 0))
        add_component(self.obj, "CUSTOM", type_path="game::Pair")
        self.assertEqual(bpy.ops.bevy_components.validate(), {"FINISHED"})
        self._definition("game::Pair").fields[1].name = "value"
        with self.assertRaises(RuntimeError):
            bpy.ops.bevy_components.validate()

    def test_save_and_reload_keeps_definitions_and_fields(self):
        define_component("game::Glow", ("tint", "COLOR", (1.0, 0.5, 0.0, 1.0)))
        add_component(self.obj, "CUSTOM", type_path="game::Glow")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "level.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(path))
            bpy.ops.wm.open_mainfile(filepath=str(path))
        self.assertEqual([definition.name for definition in bpy.context.scene.bevy_component_definitions.definitions], ["game::Glow"])
        item = bpy.data.objects["subject"].bevy_component_data.components[0]
        self.assertEqual((item.use_fields, tuple(round(value, 5) for value in item.fields[0].color_value)), (True, (1.0, 0.5, 0.0, 1.0)))

    def test_custom_card_draws_fields(self):
        define_component("game::Mover", ("speed", "FLOAT", 1.0), ("axis", "VECTOR", (0.0, 1.0, 0.0)), ("tint", "COLOR", (1.0, 1.0, 1.0, 1.0)))
        define_component("game::Marker")
        add_component(self.obj, "CUSTOM", type_path="game::Mover")
        add_component(self.obj, "CUSTOM", type_path="game::Marker")
        add_component(self.obj, "CUSTOM", custom_type="game::Raw")
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual([(bound["property"], bound["text"]) for name, bound, layout in panel.layout.calls if name == "prop" and bound["property"].endswith("_value")], [("float_value", "speed"), ("vector_value", "axis"), ("color_value", "tint")])
        self.assertIn("No fields", panel.layout.texts())
        self.assertEqual([bound["property"] for name, bound, layout in panel.layout.calls if name == "prop_search"], ["custom_type"])
        self.assertEqual(panel.layout.props().count("custom_json"), 1)
        self.assertIn("game::Mover", panel.layout.texts())

    def test_scene_panel_lists_definitions_and_fields(self):
        panel = FakePanel(self)
        addon.panel.BEVY_PT_scene_definitions.draw(panel, bpy.context)
        lists = lambda: [bound["listtype_name"] for name, bound, layout in panel.layout.calls if name == "template_list"]
        self.assertEqual(lists(), ["BEVY_UL_definitions"])
        define_component("game::Mover", ("speed", "FLOAT", 1.0), ("axis", "VECTOR", (0.0, 1.0, 0.0)))
        panel = FakePanel(self)
        addon.panel.BEVY_PT_scene_definitions.draw(panel, bpy.context)
        self.assertEqual(lists(), ["BEVY_UL_definitions", "BEVY_UL_fields"])
        self.assertEqual(panel.layout.operators(), ["bevy_components.definition_add", "bevy_components.definition_remove", "bevy_components.field_add", "bevy_components.field_remove", "bevy_components.field_move", "bevy_components.field_move"])
        self.assertEqual(panel.layout.props(), ["field_type", "vector_value"])

    def test_lists_flag_repeated_names(self):
        define_component("game::Pair", ("value", "INT", 0), ("value", "FLOAT", 0.0))
        define_component("game::Pair")
        for index, definition in enumerate(self.library.definitions):
            layout = FakeLayout(self)
            addon.panel.BEVY_UL_definitions.draw_item(None, bpy.context, layout, self.library, definition, 0, self.library, "active_index", index)
            self.assertEqual(layout.props(), ["name"])
            self.assertTrue(layout.alert)
        definition = self.library.definitions[0]
        layout = FakeLayout(self)
        addon.panel.BEVY_UL_fields.draw_item(None, bpy.context, layout, definition, definition.fields[0], 0, definition, "active_field", 0)
        self.assertEqual([layout.is_alert() for name, bound, layout in layout.calls if name == "prop"], [True])
        self.assertIn("Integer", layout.texts())

    def test_add_menu_lists_defined_components(self):
        define_component("game::Health", ("amount", "INT", 100))
        define_component("game::Wave")
        add_component(self.obj, "CUSTOM", type_path="game::Health")
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add.draw(menu, _menu_context(self.obj))
        buttons = [(text, properties.component_type, getattr(properties, "type_path", ""), enabled) for text, properties, enabled in menu.layout.buttons()]
        self.assertEqual(buttons, [("Custom Component", "CUSTOM", "", True), ("game::Health", "CUSTOM", "game::Health", False), ("game::Wave", "CUSTOM", "game::Wave", True)])

    def test_component_context_menu_edits_defined_fields(self):
        define_component("game::Health", ("amount", "INT", 100))
        item = add_component(self.obj, "CUSTOM", type_path="game::Health")
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_context_menu.draw(menu, _menu_context(self.obj, item))
        self.assertIn("Edit Fields", [text for text, properties, enabled in menu.layout.buttons()])
        collider = add_component(self.obj, "COLLIDER")
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_context_menu.draw(menu, _menu_context(self.obj, collider))
        self.assertNotIn("bevy_components.define_fields", menu.layout.operators())


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

    def test_audio_handle_poll(self):
        gizmo = addon.gizmo.BEVY_GGT_audio_handles
        self.assertFalse(gizmo.poll(bpy.context))
        audio = add_component(self.obj, "AUDIO_PLAYER")
        self.assertTrue(gizmo.poll(bpy.context))
        self.assertFalse(addon.gizmo.BEVY_GGT_collider_handles.poll(bpy.context))
        audio.audio_spatial = False
        self.assertFalse(gizmo.poll(bpy.context))
        audio.audio_spatial = True
        for setting in ("audio_ranges", "edit_handles", "enabled"):
            setattr(self.settings, setting, False)
            self.assertFalse(gizmo.poll(bpy.context), setting)
            setattr(self.settings, setting, True)
        self.obj.select_set(False)
        self.assertFalse(gizmo.poll(bpy.context))

    def test_audio_handle_sets_the_reference_distance(self):
        audio = add_component(self.obj, "AUDIO_PLAYER", audio_distance=3)
        self.assertEqual(addon.gizmo._get_audio_distance(), 3.0)
        addon.gizmo._set_audio_distance((7.5,))
        self.assertEqual(audio.audio_distance, 7.5)
        self.assertEqual(_stored(self.obj)["components"][0]["distance"], 7.5)
        addon.gizmo._set_audio_distance(-1)
        self.assertAlmostEqual(audio.audio_distance, 0.01)

    def test_audio_range_preview_is_world_sized(self):
        self.obj.location = (1, 2, 3)
        self.obj.scale = (2, 0.5, 3)
        self.obj.rotation_euler = (0.3, 0.2, 0.1)
        bpy.context.view_layer.update()
        audio = add_component(self.obj, "AUDIO_PLAYER", audio_distance=4)
        select(self.obj)
        batches = addon.overlay.preview_batches(bpy.context, self.settings)
        self.assertEqual([(color, width) for matrix, lines, color, width in batches], [(addon.overlay.AUDIO_COLOR, 1.9), (addon.overlay.AUDIO_QUIET_COLOR, 1.1)])
        for (matrix, lines, color, width), radius in zip(batches, (4, 40)):
            self.assertEqual(tuple(matrix.translation), (1.0, 2.0, 3.0))
            distances = [(matrix @ Vector(point) - matrix.translation).length for line in lines for point in line]
            self.assertTrue(all(abs(distance - radius) < 1e-3 for distance in distances), radius)
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Audio · no sound · full volume within 4m, 1% at 40m"])
        audio.audio_distance = 3.5119462
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Audio · no sound · full volume within 3.51m, 1% at 35.12m"])
        audio.audio_spatial = False
        self.assertEqual(addon.overlay.preview_batches(bpy.context, self.settings), [])
        audio.audio_spatial = True
        self.settings.audio_ranges = False
        self.assertEqual(addon.overlay.preview_batches(bpy.context, self.settings), [])
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), [])
        self.settings.audio_ranges = True

    def test_shadow_and_audio_labels(self):
        shadows = add_component(self.obj, "SHADOWS")
        add_component(self.obj, "AUDIO_PLAYER", audio_path="sounds/ambience/wind.ogg", audio_loop=True, audio_autoplay=False, audio_spatial=False)
        labels = {(False, True): "no casting", (True, False): "no receiving", (False, False): "no casting or receiving", (True, True): "as usual"}
        for (cast, receive), label in labels.items():
            shadows.shadows_cast = cast
            shadows.shadows_receive = receive
            self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), [f"Shadows · {label}", "Audio · wind.ogg · loop · paused · same volume everywhere"])

    def test_scene_reference_preview_shows_the_scene_bounds(self):
        holder = add_empty("holder", (4, 5, 6))
        holder.rotation_euler = (0, 0, 0.5)
        holder.scale = (2, 2, 2)
        bpy.context.view_layer.update()
        reference = add_component(holder, "SCENE_REFERENCE", scene_file=str(FIXTURE.parent / PROP))
        select(holder)
        batches = addon.overlay.preview_batches(bpy.context, self.settings)
        self.assertEqual([(color, width) for matrix, lines, color, width in batches], [(addon.overlay.SCENE_COLOR, 1.5)])
        matrix, lines, color, width = batches[0]
        self.assertEqual(matrix, holder.matrix_world)
        points = [Vector(point) for line in lines for point in line]
        minimum = [min(point[axis] for point in points) for axis in range(3)]
        maximum = [max(point[axis] for point in points) for axis in range(3)]
        self.assertEqual(_rounded(minimum + maximum), [-1.2, -0.45, 0.0, 1.2, 0.3, 3.0])
        self.assertEqual(addon.overlay._label_lines(holder, self.settings, {}), ["Scene · windmill.glb#Scene0"])
        reference.scene_index = 1
        self.assertEqual(addon.overlay.preview_batches(bpy.context, self.settings), [])
        reference.scene_file = "//missing.glb"
        self.assertEqual(addon.overlay.preview_batches(bpy.context, self.settings), [])
        self.assertEqual(addon.overlay._label_lines(holder, self.settings, {}), ["Scene · missing.glb#Scene1"])
        reference.scene_file = ""
        self.assertEqual(addon.overlay._label_lines(holder, self.settings, {}), ["Scene · no file#Scene1"])
        reference.scene_file = str(FIXTURE.parent / PROP)
        reference.scene_index = 0
        self.settings.scene_references = False
        self.assertEqual(addon.overlay.preview_batches(bpy.context, self.settings), [])
        self.assertEqual(addon.overlay._label_lines(holder, self.settings, {}), [])
        self.settings.scene_references = True

    def test_animation_labels(self):
        animation = add_component(self.obj, "ANIMATION")
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Animation · no clip · loop · 1×"])
        animation.animation_clip = "door_open"
        animation.animation_loop = False
        animation.animation_speed = 0.5
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Animation · door_open · once · 0.5×"])

    def test_light_range_previews(self):
        lamp = add_light("lamp", "POINT", (1, 2, 3), energy=10, use_custom_distance=True, cutoff_distance=15)
        lamp.scale = (2, 2, 2)
        bpy.context.view_layer.update()
        add_component(lamp, "LIGHT")
        select(lamp)
        batches = addon.overlay.preview_batches(bpy.context, self.settings)
        self.assertEqual([(color, width) for matrix, lines, color, width in batches], [(addon.overlay.LIGHT_COLOR, 1.5)])
        matrix, lines, color, width = batches[0]
        self.assertEqual(tuple(matrix.translation), (1.0, 2.0, 3.0))
        self.assertTrue(all(abs((matrix @ Vector(point) - matrix.translation).length - 15) < 1e-3 for line in lines for point in line))
        self.assertEqual(addon.overlay._label_lines(lamp, self.settings, {}), ["Light · Point · 6,830 lm · shadows · range 15m"])
        self.settings.lights = False
        self.assertEqual(addon.overlay.preview_batches(bpy.context, self.settings), [])
        self.assertEqual(addon.overlay._label_lines(lamp, self.settings, {}), [])
        self.settings.lights = True

    def test_spot_light_preview_is_a_cone(self):
        spot = add_light("spot", "SPOT", (0, 0, 0), rotation=(math.radians(90), 0, 0), energy=10, spot_size=math.radians(60), use_shadow=False)
        add_component(spot, "LIGHT")
        select(spot)
        bpy.context.view_layer.update()
        matrix, lines, color, width = addon.overlay.preview_batches(bpy.context, self.settings)[0]
        points = [matrix @ Vector(point) for line in lines for point in line]
        self.assertAlmostEqual(max(point.length for point in points), 20, places=3)
        self.assertTrue(all(point.y > -1e-4 for point in points))
        self.assertTrue(all(point.angle(Vector((0, 1, 0))) < math.radians(30) + 1e-3 for point in points if point.length > 1e-3))
        self.assertEqual(addon.overlay._label_lines(spot, self.settings, {}), ["Light · Spot · 6,830 lm · range 20m"])

    def test_sun_and_area_light_labels(self):
        sun = add_light("sun", "SUN", (0, 0, 0))
        add_component(sun, "LIGHT", light_use_intensity=True, light_intensity=12.5)
        select(sun)
        self.assertEqual(addon.overlay.preview_batches(bpy.context, self.settings), [])
        self.assertEqual(addon.overlay._label_lines(sun, self.settings, {}), ["Light · Sun · 12.5 lx · shadows"])
        window = add_light("window", "AREA", (0, 0, 0), energy=1)
        add_component(window, "LIGHT")
        self.assertEqual(addon.overlay._label_lines(window, self.settings, {}), ["Light · Area · 683 lm · range 20m"])

    def test_preview_batches(self):
        add_component(self.obj, "COLLIDER", collider_sensor=True)
        add_component(self.obj, "VISIBILITY_RANGE")
        zone = add_empty("zone", (5, 0, 0))
        add_component(zone, "COLLIDER", collider_shape="SPHERE")
        select(self.obj)
        colors = [color for matrix, lines, color, width in addon.overlay.preview_batches(bpy.context, self.settings)]
        self.assertEqual(colors, [addon.overlay.SENSOR_COLOR, addon.overlay.LOD_OUT_COLOR, addon.overlay.LOD_OUT_COLOR])
        self.settings.scope = "ALL"
        self.assertEqual(len(addon.overlay.preview_batches(bpy.context, self.settings)), 4)
        self.settings.visibility_ranges = False
        self.assertEqual([matrix.translation.x for matrix, lines, color, width in addon.overlay.preview_batches(bpy.context, self.settings)], [0.0, 5.0])
        self.settings.colliders = False
        self.assertEqual(addon.overlay.preview_batches(bpy.context, self.settings), [])
        self.settings.colliders = True
        self.settings.visibility_ranges = True

    def test_joint_previews_follow_the_joint(self):
        frame = add_mesh(bpy.ops.mesh.primitive_cube_add, "frame", size=0.2)
        add_component(frame, "COLLIDER")
        door = add_mesh(bpy.ops.mesh.primitive_cube_add, "door", size=0.2, location=(1, 0, 0))
        add_component(door, "COLLIDER")
        add_component(door, "RIGID_BODY", rigid_body_kind="DYNAMIC")
        hinge = add_empty("hinge", (0.5, 0, 0))
        joint = add_component(hinge, "JOINT", joint_use_limits=True, joint_angle_min=0, joint_angle_max=math.radians(90))
        joint.joint_body1 = frame
        joint.joint_body2 = door
        select(hinge)
        batches = [batch for batch in addon.overlay.preview_batches(bpy.context, self.settings) if batch[2] == addon.overlay.JOINT_COLOR]
        self.assertEqual([(tuple(matrix.translation), width) for matrix, lines, color, width in batches], [((0.5, 0.0, 0.0), 2.0), ((0.0, 0.0, 0.0), 1.0)])
        points = {tuple(round(value, 5) for value in point) for line in batches[0][1] for point in line}
        self.assertTrue({(0.0, 0.0, 0.5), (0.0, 0.0, -0.5), (0.5, 0.0, 0.0), (0.0, 0.5, 0.0)} <= points)
        self.assertNotIn((0.0, -0.5, 0.0), points)
        self.assertEqual(batches[1][1], [((0.5, 0.0, 0.0), (0.0, 0.0, 0.0)), ((0.5, 0.0, 0.0), (1.0, 0.0, 0.0))])
        self.assertEqual(addon.overlay._label_lines(hinge, self.settings, {}), ["Joint · Hinge · frame – door"])
        joint.joint_body1 = None
        self.assertEqual(addon.overlay._label_lines(hinge, self.settings, {}), ["Joint · Hinge · World – door"])
        select(door)
        self.assertEqual(addon.overlay.joint_objects(bpy.context, self.settings, [door]), [hinge])
        select(frame)
        self.assertEqual(addon.overlay.joint_objects(bpy.context, self.settings, [frame]), [])
        self.settings.joints = False
        select(hinge)
        self.assertEqual([batch for batch in addon.overlay.preview_batches(bpy.context, self.settings) if batch[2] == addon.overlay.JOINT_COLOR], [])
        self.assertEqual(addon.overlay._label_lines(hinge, self.settings, {}), [])
        self.settings.joints = True

    def test_joint_previews_point_at_the_other_body(self):
        cabinet = add_mesh(bpy.ops.mesh.primitive_cube_add, "cabinet", location=(-2, 0, 0))
        add_component(cabinet, "COLLIDER")
        add_component(self.obj, "COLLIDER")
        add_component(self.obj, "RIGID_BODY", rigid_body_kind="DYNAMIC")
        for kind in ("FIXED", "REVOLUTE", "PRISMATIC", "SPHERICAL"):
            joint = add_component(self.obj, "JOINT", joint_kind=kind, joint_axis="X", joint_use_limits=True, joint_distance_min=0, joint_distance_max=1)
            joint.joint_body1 = cabinet
            select(self.obj)
            batches = addon.overlay.joint_batches(self.obj, joint)
            self.assertEqual(batches[1][1], [((0.0, 0.0, 0.0), (-2.0, 0.0, 0.0))], kind)
            self.assertTrue(batches[0][1], kind)
            bpy.ops.bevy_components.remove(index=2)
        joint = add_component(self.obj, "JOINT", joint_kind="PRISMATIC", joint_axis="X", joint_use_limits=True, joint_distance_min=0, joint_distance_max=1)
        joint.joint_body1 = cabinet
        self.assertEqual(addon.overlay.joint_batches(self.obj, joint)[0][1][0], ((-1.0, 0.0, 0.0), (0.0, 0.0, 0.0)))

    def test_velocity_previews_and_labels(self):
        body = add_component(self.obj, "RIGID_BODY", rigid_body_kind="DYNAMIC", rigid_body_linear_velocity=(4, 0, 0))
        select(self.obj)
        batches = [batch for batch in addon.overlay.preview_batches(bpy.context, self.settings) if batch[2] == addon.overlay.VELOCITY_COLOR]
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0][1][0], ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Velocity · 4 m/s"])
        body.rigid_body_linear_velocity = (0, 0, 4)
        self.assertEqual(tuple(round(value, 5) for value in addon.overlay.velocity_batches(self.obj, body)[0][1][0][1]), (0.0, -1.0, 0.0))
        body.rigid_body_angular_velocity = (0, math.pi, 0)
        lines = addon.overlay.velocity_batches(self.obj, body)[0][1]
        self.assertTrue(all(abs(point[2]) < 1e-5 for line in lines[5:-4] for point in line))
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Velocity · 4 m/s · 180 °/s"])
        body.rigid_body_lock_translation = (False, False, True)
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Velocity · 180 °/s"])
        body.rigid_body_kind = "KINEMATIC"
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Velocity · 4 m/s · 180 °/s"])
        self.settings.velocities = False
        self.assertEqual(addon.overlay.preview_batches(bpy.context, self.settings), [])
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), [])
        self.settings.velocities = True
        body.rigid_body_kind = "STATIC"
        self.assertEqual(addon.overlay.preview_batches(bpy.context, self.settings), [])

    def test_visibility_preview_is_world_sized(self):
        self.obj.scale = (2, 2, 2)
        bpy.context.view_layer.update()
        add_component(self.obj, "VISIBILITY_RANGE", fade_in_start=0, fade_in_end=0, fade_out_start=10, fade_out_end=10)
        select(self.obj)
        matrix, lines, color, width = addon.overlay.preview_batches(bpy.context, self.settings)[0]
        distances = [(matrix @ Vector(point) - matrix.translation).length for start, end in lines for point in (start, end)]
        self.assertTrue(all(abs(distance - 10) < 1e-4 for distance in distances))

    def test_mesh_previews_respect_edge_limit(self):
        collider = add_component(self.obj, "COLLIDER", collider_shape="TRIMESH")
        self.assertEqual(len(_collider_lines(self.obj, collider, 2000)), len(self.obj.data.edges))
        dense = add_mesh(bpy.ops.mesh.primitive_uv_sphere_add, "dense")
        add_component(dense, "COLLIDER", collider_shape="TRIMESH")
        self.assertEqual(len(_collider_lines(dense, collider, 64)), 12)
        self.assertEqual(addon.overlay._label_lines(dense, SimpleNamespace(colliders=True, visibility_ranges=False, volumes=False, max_mesh_edges=64), addon.system.children_map(bpy.data.objects)), ["Collider · Trimesh · AABB preview (mesh edge limit)"])

    def test_labels(self):
        add_component(self.obj, "COLLIDER", collider_shape="CAPSULE", collider_radius=0.25, collider_height=2)
        add_component(self.obj, "VISIBILITY_RANGE")
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Collider · Capsule · r=0.25, cylinder=2m", "LOD · in 0–0m · out 20–25m"])

    def test_fog_volume_and_probe_previews(self):
        add_component(self.obj, "FOG_VOLUME", volume_size=(2, 4, 6))
        add_component(self.obj, "REFLECTION_PROBE", volume_falloff=0.5)
        add_component(self.obj, "IRRADIANCE_VOLUME", volume_size=(4, 4, 4), probe_file=str(IRRADIANCE_VOLUME))
        select(self.obj)
        batches = addon.overlay.preview_batches(bpy.context, self.settings)
        colors = addon.overlay.VOLUME_COLORS
        self.assertEqual([color for matrix, lines, color, width in batches], [colors["FOG_VOLUME"], colors["REFLECTION_PROBE"], colors["REFLECTION_PROBE"], colors["IRRADIANCE_VOLUME"], colors["IRRADIANCE_VOLUME"]])
        self.assertEqual([_extents(lines) for matrix, lines, color, width in batches[:4]], [(1.0, 3.0, 2.0), (5.0, 5.0, 2.5), (2.5, 2.5, 1.25), (2.0, 2.0, 2.0)])
        voxels = batches[4][1]
        self.assertEqual(len(voxels), 8 * 3)
        self.assertEqual(sorted({tuple(round((start[axis] + end[axis]) / 2, 5) for axis in range(3)) for start, end in voxels}), sorted((x, y, z) for x in (-1.0, 1.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)))
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Fog Volume · 2 × 4 × 6 · density 0.1", "Reflection Probe · 10 × 5 × 10 · no cubemap", "Irradiance Volume · 4 × 4 × 4 · 2 × 2 × 2 voxels"])
        self.settings.volumes = False
        try:
            self.assertEqual(addon.overlay.preview_batches(bpy.context, self.settings), [])
            self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), [])
        finally:
            self.settings.volumes = True

    def test_gizmo_handles_resize_volumes(self):
        gizmo = addon.gizmo.BEVY_GGT_collider_handles
        collider = add_component(self.obj, "COLLIDER", collider_shape="TRIMESH")
        self.assertFalse(gizmo.poll(bpy.context))
        volume = add_component(self.obj, "IRRADIANCE_VOLUME", volume_size=(4, 6, 8))
        self.assertTrue(gizmo.poll(bpy.context))
        self.assertEqual([addon.gizmo._get_handle_value(index) for index in range(3)], [2.0, 3.0, 4.0])
        addon.gizmo._set_handle_value(2, 5)
        self.assertEqual(tuple(volume.volume_size), (4.0, 6.0, 10.0))
        self.assertEqual(_stored(self.obj)["components"][1]["size"], [4.0, 6.0, 10.0])
        self.settings.volumes = False
        try:
            self.assertFalse(gizmo.poll(bpy.context))
        finally:
            self.settings.volumes = True
        collider.collider_shape = "SPHERE"
        self.assertEqual(addon.gizmo._get_handle_value(0), 0.5)

    def test_convex_hull_preview_is_the_real_hull(self):
        collider = add_component(self.obj, "COLLIDER", collider_shape="CONVEX")
        self.assertEqual(_line_keys(_collider_lines(self.obj, collider, 2000)), _line_keys([(self.obj.data.vertices[start].co, self.obj.data.vertices[end].co) for start, end in self.obj.data.edge_keys]))
        rock = add_mesh(bpy.ops.mesh.primitive_ico_sphere_add, "rock", subdivisions=1)
        add_component(rock, "COLLIDER", collider_shape="CONVEX")
        self.assertEqual(len(_collider_lines(rock, collider, 2000)), 30)
        monkey = add_mesh(bpy.ops.mesh.primitive_monkey_add, "monkey")
        add_component(monkey, "COLLIDER", collider_shape="CONVEX")
        lines = _collider_lines(monkey, collider, 2000)
        corners = {tuple(round(value, 5) for value in point) for line in lines for point in line}
        vertices = {tuple(round(value, 5) for value in vertex.co) for vertex in monkey.data.vertices}
        self.assertTrue(corners < vertices)
        self.assertLess(len(corners), len(vertices) / 2)
        for axis in range(3):
            self.assertAlmostEqual(min(corner[axis] for corner in corners), min(vertex[axis] for vertex in vertices), places=4)
            self.assertAlmostEqual(max(corner[axis] for corner in corners), max(vertex[axis] for vertex in vertices), places=4)
        self.assertEqual(addon.overlay._label_lines(monkey, self.settings, {}), ["Collider · Convex · 1 hull"])

    def test_convex_hull_preview_has_one_hull_per_material(self):
        self.obj.data.materials.append(bpy.data.materials.new("first"))
        self.obj.data.materials.append(bpy.data.materials.new("second"))
        self.obj.data.polygons[0].material_index = 1
        collider = add_component(self.obj, "COLLIDER", collider_shape="CONVEX")
        self.assertEqual(len(_collider_lines(self.obj, collider, 2000)), 12 + 4)
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Collider · Convex · 2 hulls, one per mesh part"])

    def test_convex_hull_preview_follows_mesh_edits(self):
        collider = add_component(self.obj, "COLLIDER", collider_shape="CONVEX")
        before = _collider_lines(self.obj, collider, 2000)
        self.obj.data.vertices[0].co *= 3
        after = _collider_lines(self.obj, collider, 2000)
        self.assertNotEqual(_line_keys(before), _line_keys(after))
        self.assertIn(tuple(round(value, 5) for value in self.obj.data.vertices[0].co), {tuple(round(value, 5) for value in point) for line in after for point in line})

    def test_mesh_colliders_on_empties_preview_their_child_meshes(self):
        holder = add_empty("holder", (4, 0, 0))
        collider = add_component(holder, "COLLIDER", collider_shape="CONVEX")
        select(holder)
        self.assertEqual(addon.overlay.preview_batches(bpy.context, self.settings), [])
        self.assertEqual(addon.overlay._label_lines(holder, self.settings, {}), ["Collider · Convex · no mesh, so no collider"])
        child = add_mesh(bpy.ops.mesh.primitive_cube_add, "child", location=(1, 2, 3))
        separate = add_mesh(bpy.ops.mesh.primitive_cube_add, "separate")
        add_component(separate, "COLLIDER", collider_shape="SPHERE")
        for obj in (child, separate):
            obj.parent = holder
        bpy.context.view_layer.update()
        select(holder)
        batches = addon.overlay.preview_batches(bpy.context, self.settings)
        self.assertEqual([tuple(matrix.translation) for matrix, lines, color, width in batches], [tuple(child.matrix_world.translation)])
        self.assertEqual(len(batches[0][1]), 12)
        collider.collider_shape = "TRIMESH"
        self.assertEqual(len(addon.overlay.preview_batches(bpy.context, self.settings)[0][1]), 12)

    def test_mesh_colliders_preview_collection_instances(self):
        prop = bpy.data.collections.new("prop")
        rock = bpy.data.objects.new("prop_rock", bpy.data.meshes.new("prop_rock"))
        rock.data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)], [], [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)])
        rock.matrix_world = Matrix.Translation((0, 0, 1))
        prop.objects.link(rock)
        holder = add_empty("holder", (5, 0, 0))
        holder.instance_type = "COLLECTION"
        holder.instance_collection = prop
        collider = add_component(holder, "COLLIDER", collider_shape="CONVEX")
        bpy.context.view_layer.update()
        batches = _collider_lines(holder, collider, 2000, batches=True)
        self.assertEqual([tuple(matrix.translation) for matrix, lines in batches], [(5.0, 0.0, 1.0)])
        self.assertEqual(len(batches[0][1]), 6)
        self.assertEqual(addon.validation.check_object(holder, bpy.data.objects), [])
        bpy.data.objects.remove(rock)
        bpy.data.collections.remove(prop)

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
                    for matrix, lines, color, width in addon.overlay.preview_batches(bpy.context, self.settings):
                        addon.overlay._draw_lines(shader, matrix, lines, color, width=width)
                pixels = framebuffer.read_color(0, 0, 64, 64, 4, 0, "FLOAT")
        finally:
            offscreen.free()
        pixels.dimensions = 64 * 64 * 4
        self.assertTrue(any(value > 0.1 for value in pixels.to_list()[1::4]))


class TestValidation(unittest.TestCase):
    def setUp(self):
        clear_scene()

    def _messages(self, obj=None):
        issues = addon.validation.check_objects(bpy.data.objects) if obj is None else addon.validation.check_object(obj, bpy.data.objects)
        return [addon.validation.describe(issue) for issue in issues]

    def test_sample_level_is_clean(self):
        build_sample_level()
        self.assertEqual(self._messages(), [])

    def test_mesh_colliders_need_a_mesh(self):
        holder = add_empty("holder", (0, 0, 0))
        collider = add_component(holder, "COLLIDER", collider_shape="CONVEX")
        self.assertEqual(self._messages(), ["holder: No mesh on this object or under it, so no Convex Hull collider is built"])
        collider.collider_shape = "CUBOID"
        self.assertEqual(self._messages(), [])
        collider.collider_shape = "TRIMESH"
        child = add_mesh(bpy.ops.mesh.primitive_cube_add, "child")
        child.parent = holder
        self.assertEqual(self._messages(), [])
        add_component(child, "COLLIDER", collider_shape="SPHERE")
        self.assertEqual(self._messages(), ["holder: No mesh on this object or under it, so no Triangle Mesh collider is built"])
        curve = bpy.data.objects.new("rail", bpy.data.curves.new("rail", "CURVE"))
        bpy.context.scene.collection.objects.link(curve)
        curve.parent = holder
        self.assertEqual(self._messages(), [])

    def test_visibility_ranges_need_a_mesh(self):
        holder = add_empty("holder", (0, 0, 0))
        add_component(holder, "VISIBILITY_RANGE")
        self.assertEqual(self._messages(), ["holder: No mesh on this object or under it to show or hide"])
        child = add_mesh(bpy.ops.mesh.primitive_cube_add, "child")
        child.parent = holder
        self.assertEqual(self._messages(), [])

    def test_never_visible_range(self):
        obj = add_mesh(bpy.ops.mesh.primitive_cube_add, "hidden")
        add_component(obj, "VISIBILITY_RANGE", fade_out_start=0, fade_out_end=0)
        self.assertEqual(self._messages(), ["hidden: Never visible, because Fade Out End is 0 m"])

    def test_levels_of_detail_at_the_same_spot(self):
        lod0 = add_mesh(bpy.ops.mesh.primitive_cube_add, "lod0", location=(1, 2, 3))
        lod1 = add_mesh(bpy.ops.mesh.primitive_cube_add, "lod1", location=(1, 2, 3))
        lod2 = add_mesh(bpy.ops.mesh.primitive_cube_add, "lod2", location=(1, 2, 3))
        elsewhere = add_mesh(bpy.ops.mesh.primitive_cube_add, "elsewhere", location=(9, 2, 3))
        for obj, preset in ((lod0, "NEAR"), (lod1, "MID"), (lod2, "FAR"), (elsewhere, "FAR")):
            add_component(obj, "VISIBILITY_RANGE")
            apply_lod_preset(obj, preset)
        self.assertEqual(self._messages(), [])
        lod1.bevy_component_data.components[0].fade_in_start = 30
        lod1.bevy_component_data.components[0].fade_in_end = 35
        self.assertEqual(self._messages(), ["lod1: Gap after lod0: nothing shows from 25 to 30 m"])
        lod1.bevy_component_data.components[0].fade_in_start = 10
        lod1.bevy_component_data.components[0].fade_in_end = 12
        self.assertEqual(self._messages(), ["lod1: Shows together with lod0 from 12 to 20 m"])
        lod1.bevy_component_data.components[0].fade_in_start = 21
        lod1.bevy_component_data.components[0].fade_in_end = 24
        self.assertEqual(self._messages(), ["lod1: Fades in over 21–24 m but lod0 fades out over 20–25 m, so they do not crossfade"])
        self.assertEqual(self._messages(lod1), ["lod1: Fades in over 21–24 m but lod0 fades out over 20–25 m, so they do not crossfade"])
        self.assertEqual(self._messages(lod0), [])

    def test_dynamic_bodies_need_a_collider(self):
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate")
        add_component(crate, "RIGID_BODY", rigid_body_kind="DYNAMIC")
        self.assertEqual(self._messages(), ["crate: Dynamic body has no collider on it or under it, so it has no mass and collides with nothing"])
        handle = add_empty("handle", (0, 0, 0))
        handle.parent = crate
        add_component(handle, "COLLIDER", collider_shape="SPHERE")
        self.assertEqual(self._messages(), [])
        bpy.data.objects.remove(handle)
        cart = add_empty("cart", (0, 0, 0))
        add_component(cart, "COLLIDER", collider_shape="CONVEX")
        crate.parent = cart
        self.assertEqual(self._messages(), [])

    def test_nested_rigid_bodies(self):
        cart = add_empty("cart", (0, 0, 0))
        body = add_component(cart, "RIGID_BODY", rigid_body_kind="DYNAMIC")
        wheel = add_mesh(bpy.ops.mesh.primitive_cylinder_add, "wheel")
        wheel.parent = cart
        add_component(wheel, "COLLIDER", collider_shape="CONVEX")
        add_component(wheel, "RIGID_BODY", rigid_body_kind="DYNAMIC")
        self.assertEqual(self._messages(), ["cart: Dynamic body has no collider on it or under it, so it has no mass and collides with nothing", "wheel: Moves on its own instead of with cart. Remove this Rigid Body to make cart one compound body"])
        body.rigid_body_kind = "STATIC"
        self.assertEqual(self._messages(), [])

    def test_triangle_meshes_on_dynamic_bodies(self):
        rock = add_mesh(bpy.ops.mesh.primitive_ico_sphere_add, "rock")
        add_component(rock, "COLLIDER", collider_shape="TRIMESH")
        body = add_component(rock, "RIGID_BODY", rigid_body_kind="DYNAMIC")
        self.assertEqual(self._messages(), ["rock: Triangle meshes collide poorly on Dynamic bodies, use Convex Hull"])
        body.rigid_body_kind = "KINEMATIC"
        self.assertEqual(self._messages(), [])
        body.rigid_body_kind = "DYNAMIC"
        rock.bevy_component_data.components[0].collider_shape = "CONVEX"
        self.assertEqual(self._messages(), [])
        boulders = add_empty("boulders", (0, 0, 0))
        add_component(boulders, "COLLIDER", collider_shape="TRIMESH")
        rock.parent = boulders
        rock.bevy_component_data.components[0].enabled = False
        self.assertEqual(self._messages(), ["boulders: Triangle meshes collide poorly on Dynamic bodies such as rock, use Convex Hull"])

    def test_colliders_rotated_inside_uneven_scale(self):
        shelf = add_empty("shelf", (0, 0, 0))
        board = add_empty("board", (0, 0, 0))
        add_component(board, "COLLIDER", collider_shape="CUBOID")
        board.parent = shelf
        shelf.scale = (2, 1, 1)
        board.rotation_euler = (0, 0, 0.5)
        bpy.context.view_layer.update()
        self.assertEqual(self._messages(), ["board: This is rotated inside shelf, which is scaled unevenly, so the game sizes its collider wrong. Apply scale to shelf"])
        shelf.scale = (2, 2, 2)
        bpy.context.view_layer.update()
        self.assertEqual(self._messages(), [])
        shelf.scale = (2, 1, 1)
        board.rotation_euler = (0, 0, 0)
        shelf.rotation_euler = (0.3, 0.2, 0.1)
        bpy.context.view_layer.update()
        self.assertEqual(self._messages(), [])
        board.bevy_component_data.components[0].collider_shape = "CONVEX"
        plank = add_mesh(bpy.ops.mesh.primitive_cube_add, "plank", rotation=(0, 0, 0.5))
        plank.parent = board
        bpy.context.view_layer.update()
        self.assertEqual(self._messages(), ["board: plank is rotated inside shelf, which is scaled unevenly, so the game sizes its collider wrong. Apply scale to shelf"])

    def test_shadows_need_a_mesh(self):
        group = add_empty("group", (0, 0, 0))
        add_component(group, "SHADOWS")
        self.assertEqual(self._messages(), ["group: No mesh on this object or under it to cast or receive shadows"])
        child = add_mesh(bpy.ops.mesh.primitive_cube_add, "child")
        child.parent = group
        self.assertEqual(self._messages(), [])
        add_component(child, "SHADOWS", shadows_cast=True)
        self.assertEqual(self._messages(), ["group: No mesh on this object or under it to cast or receive shadows"])

    def test_audio_player_sound_paths(self):
        speaker = add_empty("speaker", (0, 0, 0))
        audio = add_component(speaker, "AUDIO_PLAYER")
        expected = {
            "": ["No sound file, so nothing plays"],
            "sounds/fire.ogg": [],
            "music/theme.MP3": [],
            "fire.flac": [],
            "sounds/fire.aiff": ["Bevy cannot play .aiff files, use .ogg, .wav, .mp3 or .flac"],
            "sounds/fire": ["The sound file has no extension, so Bevy cannot tell how to load it"],
            "//sounds/fire.ogg": ["\"//sounds/fire.ogg\" is not a path inside your game's assets folder, such as sounds/fire.ogg"],
            "C:/game/assets/fire.wav": ["\"C:/game/assets/fire.wav\" is not a path inside your game's assets folder, such as sounds/fire.ogg"],
            "sounds\\fire.ogg": ["\"sounds\\fire.ogg\" is not a path inside your game's assets folder, such as sounds/fire.ogg"],
            "../fire.ogg": ["\"../fire.ogg\" is not a path inside your game's assets folder, such as sounds/fire.ogg"],
        }
        for path, messages in expected.items():
            audio.audio_path = path
            self.assertEqual(self._messages(), [f"speaker: {message}" for message in messages], path)
        audio.audio_path = "sounds/fire.ogg"
        self.assertEqual(json.loads(speaker["bevy_components"])["components"][0]["path"], "sounds/fire.ogg")

    def test_joints_need_moving_bodies(self):
        hinge = add_empty("hinge", (0, 0, 0))
        joint = add_component(hinge, "JOINT")
        self.assertEqual(self._messages(), ["hinge: Connects nothing. Pick Body 1, Body 2 or both"])
        door = add_mesh(bpy.ops.mesh.primitive_cube_add, "door")
        joint.joint_body1 = door
        joint.joint_body2 = door
        self.assertEqual(self._messages(), ["hinge: Connects door to itself"])
        joint.joint_body2 = None
        self.assertEqual(self._messages(), ["hinge: door has no Rigid Body or Collider, so the joint holds nothing"])
        add_component(door, "COLLIDER", collider_shape="CUBOID")
        self.assertEqual(self._messages(), ["hinge: door is static, so pinning it does nothing"])
        body = add_component(door, "RIGID_BODY", rigid_body_kind="DYNAMIC")
        self.assertEqual(self._messages(), [])
        wall = add_mesh(bpy.ops.mesh.primitive_cube_add, "wall")
        add_component(wall, "COLLIDER")
        joint.joint_body2 = wall
        self.assertEqual(self._messages(), [])
        body.rigid_body_kind = "STATIC"
        self.assertEqual(self._messages(), ["hinge: Both ends are static, so the joint does nothing"])
        body.rigid_body_kind = "DYNAMIC"
        handle = add_mesh(bpy.ops.mesh.primitive_cube_add, "handle")
        add_component(handle, "COLLIDER", collider_shape="CUBOID")
        handle.parent = door
        joint.joint_body2 = handle
        self.assertEqual(self._messages(), ["hinge: handle is part of door's body, so pick door"])
        joint.joint_body2 = wall
        self.assertEqual([addon.validation.describe(issue) for issue in addon.validation.check_objects([hinge, door])], ["hinge: wall is not exported with this level, so the joint holds nothing"])
        joint.joint_use_limits = True
        joint.joint_angle_min = 1
        joint.joint_angle_max = 0
        self.assertEqual([(issue.level, addon.validation.describe(issue)) for issue in addon.validation.check_objects(bpy.data.objects)], [("ERROR", "hinge: Joint limit Min is above Max")])

    def test_fully_locked_bodies(self):
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate")
        add_component(crate, "COLLIDER", collider_shape="CUBOID")
        body = add_component(crate, "RIGID_BODY", rigid_body_kind="DYNAMIC", rigid_body_lock_translation=(True, True, True), rigid_body_lock_rotation=(True, True, False))
        self.assertEqual(self._messages(), [])
        body.rigid_body_lock_rotation = (True, True, True)
        self.assertEqual(self._messages(), ["crate: Every axis is locked, so the body never moves. Use a Static or Kinematic body instead"])
        body.rigid_body_kind = "KINEMATIC"
        self.assertEqual(self._messages(), [])

    def test_scene_reference_files(self):
        holder = add_empty("holder", (0, 0, 0))
        reference = add_component(holder, "SCENE_REFERENCE")
        self.assertEqual(self._messages(), ["holder: Scene Reference needs a glTF file"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "notes.txt").write_text("windmill")
            (root / "broken.glb").write_bytes(b"glTF broken")
            cases = (
                (str(FIXTURE.parent / PROP), 0, []),
                (str(FIXTURE.parent / PROP), 1, ["windmill.glb has 1 scene, numbered from 0"]),
                (str(root / "missing.glb"), 0, [f"No file at {root / 'missing.glb'}"]),
                (str(root / "notes.txt"), 0, ["notes.txt is not a .glb or .gltf file"]),
                (str(root / "broken.glb"), 0, ["broken.glb is not a valid glTF file"]),
            )
            for path, index, messages in cases:
                reference.scene_file = path
                reference.scene_index = index
                self.assertEqual(self._messages(), [f"holder: {message}" for message in messages], (path, index))
            reference.scene_file = str(root / "level.glb")
            (root / "level.glb").write_bytes((FIXTURE.parent / PROP).read_bytes())
            issues = addon.validation.check_objects(bpy.data.objects, level=root / "level.glb")
            self.assertEqual([addon.validation.describe(issue) for issue in issues], ["holder: Spawns the exported level inside itself, so the game skips it"])

    def test_scene_references_on_another_drive_block_export(self):
        holder = add_empty("holder", (0, 0, 0))
        add_component(holder, "SCENE_REFERENCE", scene_file=str(FIXTURE.parent / PROP))
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(addon.validation, "level_path", side_effect=ValueError("path is on mount 'D:', start on mount 'C:'")):
            path = Path(directory) / "level.glb"
            with self.assertRaisesRegex(RuntimeError, "Cannot export: holder: windmill.glb is on another drive than the level, so the game cannot load it"):
                bpy.ops.export_scene.bevy_components_glb(filepath=str(path))
            self.assertFalse(path.exists())

    def test_animation_clips(self):
        mill = add_empty("mill", (0, 0, 0))
        blade = add_mesh(bpy.ops.mesh.primitive_cube_add, "blade")
        blade.parent = mill
        animate(blade, "spin", "rotation_euler", 1, [(1, 0.0), (10, 1.0)])
        door = add_mesh(bpy.ops.mesh.primitive_cube_add, "door")
        animate(door, "open", "rotation_euler", 2, [(1, 0.0), (10, 1.0)])
        animation = add_component(mill, "ANIMATION", animation_clip="")
        self.assertEqual(self._messages(), ["mill: No clip picked, so nothing plays"])
        for clip, messages in (("spin", []), ("missing", ["No action named missing"]), ("open", ["open animates nothing on or under this object, so nothing plays"])):
            animation.animation_clip = clip
            self.assertEqual(self._messages(), [f"mill: {message}" for message in messages], clip)
        add_component(blade, "ANIMATION", animation_clip="spin")
        animation.animation_clip = "spin"
        self.assertEqual(self._messages(), [])
        blade.bevy_component_data.components[0].animation_clip = "open"
        self.assertEqual(self._messages(), ["blade: open animates nothing on or under mill, so nothing plays"])
        blade.bevy_component_data.components[0].animation_clip = "spin"
        issues = addon.validation.check_objects(bpy.data.objects, animations=False)
        self.assertEqual([addon.validation.describe(issue) for issue in issues], ["blade: Include Animations is off in the export, so nothing plays", "mill: Include Animations is off in the export, so nothing plays"])

    def test_light_probe_files(self):
        reflection = add_component(add_empty("probe", (0, 0, 0)), "REFLECTION_PROBE")
        irradiance = add_component(add_empty("volume", (0, 0, 0)), "IRRADIANCE_VOLUME")
        self.assertEqual(self._messages(), ["probe: No cubemap, so the probe adds no reflections", "volume: No voxel texture, so the volume adds no light"])
        reflection.probe_file = str(CUBEMAP)
        irradiance.probe_file = str(IRRADIANCE_VOLUME)
        self.assertEqual(self._messages(), [])
        reflection.probe_file = str(IRRADIANCE_VOLUME)
        irradiance.probe_file = str(CUBEMAP)
        self.assertEqual(self._messages(), ["probe: irradiance_volume.ktx2 is not a cubemap", "volume: probe_cubemap.ktx2 is not a 3D texture"])
        self.assertEqual({issue.level for issue in addon.validation.check_objects(bpy.data.objects)}, {"ERROR"})
        with tempfile.TemporaryDirectory() as directory:
            reflection.probe_file = str(Path(directory) / "missing.ktx2")
            irradiance.probe_file = str(Path(directory) / "plain.ktx2")
            (Path(directory) / "plain.ktx2").write_bytes(b"not a texture")
            self.assertEqual(self._messages(), ["probe: Cubemap file missing.ktx2 was not found", "volume: plain.ktx2 is not a KTX2 file"])
            self.assertEqual(bpy.ops.bevy_components.validate.poll(), True)
            with self.assertRaises(RuntimeError):
                bpy.ops.bevy_components.validate()

    def test_fog_needs_density(self):
        fog = add_component(add_empty("fog", (0, 0, 0)), "FOG_VOLUME", fog_density=0)
        self.assertEqual(self._messages(), ["fog: Density is 0, so the fog is invisible"])
        fog.fog_density = 0.01
        self.assertEqual(self._messages(), [])

    def test_light_warnings(self):
        lamp = add_light("lamp", "POINT", (0, 0, 0))
        add_component(lamp, "LIGHT", light_volumetric=True)
        self.assertEqual(self._messages(), [])
        lamp.data.use_shadow = False
        self.assertEqual(self._messages(), ["lamp: Volumetric needs Shadows, or the light makes no light shafts"])
        spot = add_light("spot", "SPOT", (0, 0, 0), use_square=True)
        add_component(spot, "LIGHT")
        self.assertEqual(self._messages(spot), ["spot: Bevy spot lights are round, so this square spot becomes round"])
        window = add_light("window", "AREA", (0, 0, 0), shape="DISK", size=1.5)
        self.assertEqual(self._messages(window), ["window: glTF leaves out area lights. Add a Light component to export this one as a Bevy rectangle light"])
        light = add_component(window, "LIGHT", light_volumetric=True)
        self.assertEqual(self._messages(window), ["window: Bevy area lights are rectangles, so this disk becomes a 1.5 × 1.5 m rectangle"])
        window.data.shape = "ELLIPSE"
        window.data.size_y = 0.5
        self.assertEqual(self._messages(window), ["window: Bevy area lights are rectangles, so this ellipse becomes a 1.5 × 0.5 m rectangle"])
        light.enabled = False
        self.assertEqual(self._messages(window), [])
        stray = add_mesh(bpy.ops.mesh.primitive_cube_add, "stray")
        stray.bevy_component_data.components.add().component_type = "LIGHT"
        self.assertEqual(self._messages(stray), ["stray: Only lights use this component, so it is not exported"])

    def test_invalid_shadow_cascades_block_export(self):
        sun = add_light("sun", "SUN", (0, 0, 0))
        item = add_component(sun, "LIGHT", light_use_cascades=True, light_cascade_first=200)
        message = "sun: Shadow cascades must satisfy near < first cascade < max distance"
        self.assertEqual(self._messages(), [message])
        item.light_cascade_count = 1
        self.assertEqual(self._messages(), [])
        item.light_cascade_near = 150
        self.assertEqual(self._messages(), [message])
        with self.assertRaisesRegex(RuntimeError, "1 problem blocks export"):
            bpy.ops.bevy_components.validate()
        item.light_use_cascades = False
        self.assertEqual(self._messages(), [])

    def test_custom_component_type_paths(self):
        marker = add_empty("marker", (0, 0, 0))
        add_component(marker, "CUSTOM", custom_type="my_game::Wrapper<f32>")
        add_component(marker, "CUSTOM", custom_type="my_game::Health ")
        add_component(marker, "CUSTOM", custom_type="my_game::Wrapper<f32>")
        self.assertEqual(self._messages(), ["marker: \"my_game::Health \" is not a Rust type path such as my_game::Health", "marker: Added more than once, but an entity holds only one my_game::Wrapper<f32>"])

    def test_errors_and_warnings_from_operators(self):
        holder = add_empty("holder", (0, 0, 0))
        add_component(holder, "COLLIDER", collider_shape="CONVEX")
        self.assertEqual(bpy.ops.bevy_components.validate(), {"FINISHED"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "level.glb"
            self.assertEqual(bpy.ops.export_scene.bevy_components_glb(filepath=str(path)), {"FINISHED"})
            self.assertEqual(json.loads(read_gltf(path)["nodes"][0]["extras"]["bevy_components"])["components"][0]["shape"], "convex")
            item = add_component(holder, "CUSTOM", custom_json="{broken")
            with self.assertRaisesRegex(RuntimeError, "1 problem blocks export: holder: invalid JSON in Custom Component"):
                bpy.ops.bevy_components.validate()
            path.unlink()
            with self.assertRaisesRegex(RuntimeError, "Cannot export: holder: invalid JSON in Custom Component"):
                bpy.ops.export_scene.bevy_components_glb(filepath=str(path))
            self.assertFalse(path.exists())
            item.enabled = False

    def test_select_object(self):
        first = add_mesh(bpy.ops.mesh.primitive_cube_add, "first")
        second = add_mesh(bpy.ops.mesh.primitive_cube_add, "second")
        select(first)
        self.assertEqual(bpy.ops.bevy_components.select_object(name="second"), {"FINISHED"})
        self.assertEqual((bpy.context.view_layer.objects.active, first.select_get(), second.select_get()), (second, False, True))
        self.assertEqual(bpy.ops.bevy_components.select_object(name="missing"), {"CANCELLED"})

    def test_panel_shows_warnings_on_their_component(self):
        holder = add_empty("holder", (0, 0, 0))
        add_component(holder, "RIGID_BODY", rigid_body_kind="DYNAMIC")
        add_component(holder, "COLLIDER", collider_shape="CONVEX")
        add_component(holder, "CUSTOM", custom_json="{broken")
        select(holder)
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        text = " ".join(panel.layout.texts())
        self.assertIn("No mesh on this object or under it, so no Convex Hull collider is built", text)
        self.assertNotIn("invalid JSON", text)
        icons = [bound.get("icon") for name, bound, layout in panel.layout.calls if name == "label" and bound.get("text") == ""]
        self.assertEqual(icons, ["ERROR", "CANCEL"])

    def test_export_dialog_lists_problems(self):
        properties = bpy.ops.export_scene.bevy_components_glb.get_rna_type()
        operator = SimpleNamespace(layout=FakeLayout(self), bl_rna=properties, filepath="", texture_compression="DISABLED", selected_only=False, include_lights=True, include_cameras=False, include_animations=False)
        addon.operator.BEVY_OT_export_glb.draw(operator, bpy.context)
        self.assertIn("No problems found", operator.layout.texts())
        for index in range(8):
            add_component(add_empty(f"holder_{index}", (index, 0, 0)), "VISIBILITY_RANGE")
        operator = SimpleNamespace(layout=FakeLayout(self), bl_rna=properties, filepath="", texture_compression="DISABLED", selected_only=False, include_lights=True, include_cameras=False, include_animations=False)
        addon.operator.BEVY_OT_export_glb.draw(operator, bpy.context)
        texts = operator.layout.texts()
        self.assertIn("8 warnings", texts)
        self.assertIn("2 more in Validate All Objects", texts)
        self.assertIn("holder_0: No mesh on this object or under it to show or hide", " ".join(texts))


class TestExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.props = export_props(cls.directory.name)
        build_sample_level(cls.directory.name)
        cls.gltf = export_sample_level(Path(cls.directory.name) / "sample_level.glb")
        cls.nodes = {node["name"]: node for node in cls.gltf["nodes"]}

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_every_object_is_exported(self):
        self.assertEqual(set(self.nodes), set(EXPECTED_COMPONENTS) | {"chimney", "cart_body", "bush_a"})
        self.assertEqual(self.nodes["house"].get("children"), [self.gltf["nodes"].index(self.nodes["chimney"])])
        self.assertEqual(sorted(self.gltf["nodes"][index]["name"] for index in self.nodes["cart"]["children"]), ["cart_body", "cart_handle", "cart_shape"])

    def test_component_extras(self):
        for name, expected in EXPECTED_COMPONENTS.items():
            extras = self.nodes[name]["extras"]
            self.assertEqual(list(extras), ["bevy_components"], name)
            exported = json.loads(extras["bevy_components"])
            self.assertEqual(exported["version"], 1)
            self.assertEqual(_rounded(_named_textures(self.gltf, exported["components"])), expected, name)

    def test_editor_state_is_not_exported(self):
        self.assertNotIn("extras", self.nodes["chimney"])
        self.assertNotIn("extras", self.nodes["cart_body"])
        self.assertNotIn("extras", self.nodes["bush_a"])
        self.assertEqual([list(scene.get("extras", {})) for scene in self.gltf["scenes"]], [["bevy_components"]])

    def test_ambient_light_is_exported_on_the_scene(self):
        self.assertEqual(json.loads(self.gltf["scenes"][0]["extras"]["bevy_components"]), {"version": 1, "components": [{"type": "ambient_light", "color": [0.9, 0.95, 1.0], "brightness": 120.0, "baked": False}]})
        ambient = bpy.context.scene.world.bevy_ambient_light
        path = Path(self.directory.name) / "no_ambient.glb"
        ambient.enabled = False
        try:
            self.assertTrue(all("extras" not in scene for scene in export_sample_level(path)["scenes"]))
        finally:
            ambient.enabled = True

    def test_light_data_is_read_at_export(self):
        window = bpy.data.objects["window_light"]
        path = Path(self.directory.name) / "dimmer.glb"
        window.data.energy = 10
        window.data.size = 3
        try:
            node = next(node for node in export_sample_level(path)["nodes"] if node["name"] == "window_light")
        finally:
            window.data.energy = 50
            window.data.size = 2
        self.assertEqual(json.loads(node["extras"]["bevy_components"])["components"][0]["intensity"], 6830.0)
        self.assertEqual(json.loads(node["extras"]["bevy_components"])["components"][0]["size"], [3.0, 1.0])

    def test_light_nodes_face_like_in_blender(self):
        self.assertEqual(_rounded(self.nodes["sun"]["rotation"]), [-0.70711, 0.0, 0.0, 0.70711])
        self.assertEqual([abs(value) for value in _rounded(self.nodes["window_light"]["rotation"])], [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(self.nodes["lamp_light"]["extensions"], {"KHR_lights_punctual": {"light": self.gltf["extensions"]["KHR_lights_punctual"]["lights"].index(next(light for light in self.gltf["extensions"]["KHR_lights_punctual"]["lights"] if light["name"] == "lamp_light"))}})
        self.assertNotIn("extensions", self.nodes["window_light"])

    def test_transforms_are_y_up(self):
        self.assertEqual(_rounded(self.nodes["crate"]["translation"]), [3.0, 1.0, 2.0])
        self.assertEqual(_rounded(self.nodes["crate"]["rotation"]), [0.0, 0.25882, 0.0, 0.96593])
        self.assertEqual(_rounded(self.nodes["trigger_zone"]["scale"]), [2.0, 1.0, 1.0])
        self.assertEqual(_rounded(self.nodes["player_spawn"]["translation"]), [2.0, 0.0, -3.0])
        self.assertEqual(_rounded(self.nodes["cart_handle"]["translation"]), [-0.75, 0.25, 0.0])

    def test_fixture_is_current(self):
        self.assertTrue(FIXTURE.is_file(), f"Missing {FIXTURE}, run tests/blender/sample_level.py to create it")
        self.assertEqual(_node_summary(read_gltf(FIXTURE)), _node_summary(self.gltf), "importer/tests/assets/sample_level.glb is out of date, run tests/blender/sample_level.py to regenerate it")

    def test_prop_fixture_is_current(self):
        path = FIXTURE.parent / PROP
        self.assertTrue(path.is_file(), f"Missing {path}, run tests/blender/sample_level.py to create it")
        self.assertEqual(_node_summary(read_gltf(path)), _node_summary(self.props), f"importer/tests/assets/{PROP.as_posix()} is out of date, run tests/blender/sample_level.py to regenerate it")

    def test_animations_start_at_zero(self):
        for gltf, name in ((self.gltf, "gate_open"), (self.props, "windmill_spin")):
            self.assertEqual([animation["name"] for animation in gltf["animations"]], [name])
            inputs = {gltf["accessors"][sampler["input"]]["min"][0] for sampler in gltf["animations"][0]["samplers"]}
            self.assertEqual(inputs, {0.0}, name)
        blades = json.loads(next(node for node in self.props["nodes"] if node["name"] == "windmill_blades")["extras"]["bevy_components"])
        self.assertEqual(blades["components"], [{"type": "animation", "clip": "windmill_spin", "repeat": True, "speed": 0.5}])

    def test_scene_reference_paths_follow_the_level(self):
        path = Path(self.directory.name) / "levels" / "level.glb"
        gltf = export_sample_level(path, include_animations=False)
        nodes = {node["name"]: node for node in gltf["nodes"]}
        self.assertEqual(json.loads(nodes["windmill_a"]["extras"]["bevy_components"])["components"], [{**WINDMILL, "path": "../props/windmill.glb"}])
        self.assertNotIn("animations", gltf)

    def test_plain_gltf_export_leaves_out_editor_state(self):
        path = Path(self.directory.name) / "plain.glb"
        bpy.context.scene.bevy_component_previews.scope = "ALL"
        bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", export_extras=True)
        gltf = read_gltf(path)
        self.assertTrue(all(set(node.get("extras", {})) <= {"bevy_components"} for node in gltf["nodes"]))
        self.assertTrue(all(set(scene.get("extras", {})) <= {"bevy_components"} for scene in gltf["scenes"]))

    def test_light_probe_files_are_embedded(self):
        gltf, binary = addon.compression.read_glb((Path(self.directory.name) / "sample_level.glb").read_bytes())
        for name, source in (("room_probe", CUBEMAP), ("gi_volume", IRRADIANCE_VOLUME)):
            component = json.loads(self.nodes[name]["extras"]["bevy_components"])["components"][0]
            self.assertNotIn("file", component)
            texture = gltf["textures"][component["texture"]]
            self.assertEqual(gltf["images"][texture["source"]], {"bufferView": gltf["images"][texture["source"]]["bufferView"], "mimeType": "image/ktx2", "name": source.stem})
            self.assertEqual(addon.compression.image_payload(gltf, binary, texture["source"])[0], source.read_bytes())
            self.assertEqual(gltf["samplers"][texture["sampler"]], {"magFilter": 9729, "minFilter": 9729, "wrapS": 33071, "wrapT": 33071})
            self.assertEqual(_stored(bpy.data.objects[name])["components"][0]["file"], str(source))

    def test_missing_light_probe_files_block_export(self):
        path = Path(self.directory.name) / "missing_probe.glb"
        probe = bpy.data.objects["room_probe"].bevy_component_data.components[0]
        probe.probe_file = str(Path(self.directory.name) / "missing.ktx2")
        try:
            with self.assertRaisesRegex(RuntimeError, "Cubemap file missing.ktx2 was not found"):
                bpy.ops.export_scene.bevy_components_glb(filepath=str(path))
        finally:
            probe.probe_file = str(CUBEMAP)
        self.assertFalse(path.exists())
        with mock.patch.object(addon.operator, "_read_file", side_effect=FileNotFoundError(2, "No such file or directory", str(CUBEMAP))):
            with self.assertRaisesRegex(RuntimeError, "Could not embed probe_cubemap.ktx2 in the level: No such file or directory"):
                bpy.ops.export_scene.bevy_components_glb(filepath=str(path))
        self.assertFalse(path.exists())

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
        cls.directory = tempfile.TemporaryDirectory()
        export_props(cls.directory.name)
        build_sample_level(cls.directory.name)
        cls.images = _image_state()
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
        self.assertEqual({image["mimeType"] for image in gltf["images"] if image["name"] not in PROBE_IMAGES}, {"image/png"})
        self.assertEqual({image["mimeType"] for image in gltf["images"] if image["name"] in PROBE_IMAGES}, {"image/ktx2"})
        self.assertIn(addon.compression.PNG_SIGNATURE, binary)

    def test_textures_reference_embedded_ktx2(self):
        for mode, (gltf, binary) in self.compressed.items():
            self.assertIn("KHR_texture_basisu", gltf["extensionsUsed"], mode)
            self.assertIn("KHR_texture_basisu", gltf["extensionsRequired"], mode)
            self.assertEqual(len(gltf["textures"]), 11, mode)
            for texture in gltf["textures"]:
                if "source" in texture:
                    self.assertIn(gltf["images"][texture["source"]]["name"], PROBE_IMAGES, mode)
                    self.assertNotIn("extensions", texture, mode)
                    continue
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
            self.assertEqual(names, ["ball_pixels", "irradiance_volume", "lamp_emissive", "metal_color", "pillar_gradient", "probe_cubemap", "wood_color", "wood_normal", "wood_orm", "wood_orm"], mode)
            sources = [texture["extensions"]["KHR_texture_basisu"]["source"] for texture in gltf["textures"] if "source" not in texture]
            self.assertEqual(len(sources) - len(set(sources)), 1, mode)

    def test_embedded_ktx2_files_pass_khronos_validation(self):
        path, _version = addon.encoder.check_encoder()
        for mode, (gltf, binary) in self.compressed.items():
            for index, image in enumerate(gltf["images"]):
                file = Path(self.directory.name) / f"{mode}_{index}.ktx2"
                file.write_bytes(addon.compression.image_payload(gltf, binary, index)[0])
                result = subprocess.run([str(path), "validate", *(() if image["name"] in PROBE_IMAGES else ("--gltf-basisu",)), str(file)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, f"{mode} {image['name']}: {result.stdout}{result.stderr}")

    def test_codecs_color_spaces_and_mipmaps(self):
        for mode, (gltf, binary) in self.compressed.items():
            usages = _usages(gltf)
            for index, (name, _mime_type, model, width, height, levels, transfer, primaries) in enumerate(_texture_summary(gltf, binary)):
                if name in PROBE_IMAGES:
                    continue
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
