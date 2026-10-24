import hashlib
import importlib.util
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest import mock

import bpy
import gpu
import numpy
from mathutils import Matrix, Quaternion, Vector

from sample_scene import COMPRESSED_FIXTURES, CUBEMAP, FIXTURE, IRRADIANCE_VOLUME, LIGHTMAP, PROP, SCHEMA, SOUNDS, add_component, add_empty, add_instance, add_light, add_material, add_mesh, add_prefab, animate, apply_lod_preset, build_sample_scene, clear_scene, define_component, export_props, export_sample_scene, install_addon, layers, move_to, pick_sound, read_gltf, select, set_fields, uninstall_addon, use_game_schema

LAYOUT = bpy.types.UILayout.bl_rna
ICONS = set(LAYOUT.functions["label"].parameters["icon"].enum_items.keys())
CHILD_LAYOUTS = {"row", "column", "box", "split", "grid_flow", "column_flow"}
DEFAULT_COLLIDER = {"size": [1.0, 1.0, 1.0], "radius": 0.5, "height": 1.0, "offset": [0.0, 0.0, 0.0], "sensor": False, "events": False, "collision_only": False, "friction": 0.5, "restitution": 0.0, "memberships": 1, "filters": 4294967295}
MESH_COLLIDER = {**DEFAULT_COLLIDER, "offset": None}
STATIC_BODY = {"type": "rigid_body", "kind": "static", "mass": None, "gravity_scale": None, "linear_damping": None, "angular_damping": None, "lock_translation": None, "lock_rotation": None, "ccd": None, "linear_velocity": None, "angular_velocity": None}
KINEMATIC_BODY = {**STATIC_BODY, "kind": "kinematic", "linear_velocity": [0.0, 0.0, 0.0], "angular_velocity": [0.0, 0.0, 0.0]}
DYNAMIC_BODY = {**KINEMATIC_BODY, "kind": "dynamic", "gravity_scale": 1.0, "linear_damping": 0.0, "angular_damping": 0.0, "lock_translation": [False, False, False], "lock_rotation": [False, False, False], "ccd": "default"}
DEFAULT_JOINT = {"type": "joint", "kind": "revolute", "body1": None, "body2": None, "axis": [0.0, 1.0, 0.0], "angle_limits": None, "distance_limits": None, "swing_limit": None, "linear_damping": 0.0, "angular_damping": 0.0, "collide": False}
DEFAULT_AUDIO = {"type": "audio_player", "path": "", "volume": 1.0, "loop": False, "autoplay": True, "spatial": True, "distance": 5.0}
WINDMILL = {"type": "scene_reference", "path": "props/windmill.glb", "scene": 0}
LAMP_POST = {"type": "scene_reference", "path": "props/lamp_post.glb", "scene": 0, "prefab": "lamp_post"}
OBSTACLE = {"type": "navigation", "kind": "obstacle", "cost": None}
DEFAULT_LIGHT = {"type": "light", "intensity": None, "radius": None, "range": None, "color": None, "size": None, "shadows": True, "contact_shadows": False, "volumetric": False, "baked": False, "depth_bias": None, "normal_bias": None, "near_clip": None, "cascades": None}
EXPECTED_COMPONENTS = {
    "ground": [
        {"type": "collider", "shape": "trimesh", **MESH_COLLIDER},
        STATIC_BODY,
        {"type": "lightmap", "bicubic": True, "texture": "ground_lightmap"},
        {"type": "navigation", "kind": "walkable", "cost": 1.0},
    ],
    "crate": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [2.0, 2.0, 2.0], "friction": 0.8, "restitution": 0.1}},
        DYNAMIC_BODY,
        {"type": "visibility_range", "start": [20.0, 25.0], "end": [80.0, 85.0], "use_aabb": False},
        OBSTACLE,
    ],
    "crate_copy": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [2.0, 2.0, 2.0], "friction": 0.8, "restitution": 0.1}},
        DYNAMIC_BODY,
        {"type": "visibility_range", "start": [20.0, 25.0], "end": [80.0, 85.0], "use_aabb": False},
        OBSTACLE,
    ],
    "ball": [
        {"type": "collider", "shape": "sphere", **DEFAULT_COLLIDER},
        KINEMATIC_BODY,
    ],
    "pillar": [
        {"type": "collider", "shape": "capsule", **{**DEFAULT_COLLIDER, "radius": 0.4, "height": 1.2}},
    ],
    "rock": [
        {"type": "collider", "shape": "convex", **MESH_COLLIDER},
        {**DYNAMIC_BODY, "mass": 25.0},
    ],
    "trigger_zone": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [1.0, 2.0, 3.0], "sensor": True, "events": True, "memberships": 4, "filters": 2}},
    ],
    "pickup_zone": [
        {"type": "collider", "shape": "sphere", **{**DEFAULT_COLLIDER, "radius": 1.5, "sensor": True, "events": True}},
        {"type": "custom", "type_path": "my_game::Pickup", "data": {"item": "coin", "amount": 5, "respawn": True, "weight": 0.1, "spin": [0.0, 1.5, 0.0], "glow": {"Srgba": {"red": 1.0, "green": 0.8, "blue": 0.2, "alpha": 1.0}}}},
    ],
    "player_spawn": [
        {"type": "custom", "type_path": "my_game::PlayerSpawn", "data": {}},
    ],
    "enemy_spawn": [
        {"type": "custom", "type_path": "my_game::EnemySpawn", "data": {}},
        {"type": "custom", "type_path": "my_game::Wave", "data": {"count": 3, "delay": 1.5}},
        {"type": "custom", "type_path": "my_game::Patrol", "data": {"speed": 2.5, "mode": "PingPong", "offset": [1.0, -0.5], "stops": 3}},
        {"type": "custom", "type_path": "my_game::Reward", "data": [7, 1.5]},
    ],
    "lamp": [
        {"type": "custom", "type_path": "my_game::Glow", "data": {"color": [1.0, 0.8, 0.6], "label": "Lamp ✦"}},
        {"type": "custom", "type_path": "my_game::Flicker", "data": 0.25},
    ],
    "house": [
        {"type": "visibility_range", "start": [80.0, 85.0], "end": [250.0, 260.0], "use_aabb": True},
        {"type": "collider", "shape": "trimesh", **MESH_COLLIDER},
        OBSTACLE,
    ],
    "tree_lod0": [
        {"type": "visibility_range", "start": [0.0, 0.0], "end": [20.0, 25.0], "use_aabb": False},
    ],
    "tree_lod1": [
        {"type": "visibility_range", "start": [20.0, 25.0], "end": [100.0, 120.0], "use_aabb": False},
    ],
    "cart": [
        {**DYNAMIC_BODY, "mass": 12.0},
        OBSTACLE,
    ],
    "cart_shape": [
        {"type": "collider", "shape": "cuboid", **DEFAULT_COLLIDER},
    ],
    "cart_handle": [
        {"type": "collider", "shape": "sphere", **{**DEFAULT_COLLIDER, "radius": 0.25}},
    ],
    "bouncy_ball": [
        {"type": "collider", "shape": "sphere", **{**DEFAULT_COLLIDER, "radius": 0.3, "restitution": 1.0, "events": True}},
        DYNAMIC_BODY,
    ],
    "ghost": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "memberships": 2, "filters": 2}},
        DYNAMIC_BODY,
    ],
    "signpost": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [0.3, 1.5, 0.3], "offset": [0.0, 0.75, 0.0]}},
        DYNAMIC_BODY,
    ],
    "invisible_wall": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [0.2, 2.0, 4.0], "collision_only": True}},
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
        {"type": "navigation", "kind": "walkable", "cost": 3.0},
    ],
    "bushes": [
        {"type": "shadows", "cast": False, "receive": True},
        OBSTACLE,
    ],
    "bush_b": [
        {"type": "shadows", "cast": True, "receive": True},
        {"type": "navigation", "kind": "ignored", "cost": None},
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
    "lamp_post_a": [
        LAMP_POST,
    ],
    "lamp_post_b": [
        LAMP_POST,
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
LIGHTING_IMAGES = {"probe_cubemap", "irradiance_volume", "ground_lightmap"}
BEVY_FROM_BLENDER = Matrix(((1, 0, 0), (0, 0, 1), (0, -1, 0)))
SIDE_COLORS = {
    (1, 0, 0): (1.0, 0.0, 0.0),
    (-1, 0, 0): (0.0, 1.0, 1.0),
    (0, 1, 0): (0.0, 1.0, 0.0),
    (0, -1, 0): (1.0, 0.0, 1.0),
    (0, 0, 1): (0.0, 0.0, 1.0),
    (0, 0, -1): (1.0, 1.0, 0.0),
}
FAKE_BLENDER = """#!{python}
import os
import sys
import traceback

import bpy

arguments = sys.argv[1:]
bpy.ops.wm.open_mainfile(filepath=arguments[arguments.index("--background") + 1])
try:
    exec(arguments[arguments.index("--python-expr") + 1])
except Exception:
    traceback.print_exc()
    code = 1
else:
    code = 0
sys.stdout.flush()
os._exit(code)
"""

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
    return {"version": addon.metadata.SCHEMA_VERSION, "components": addon.system.object_components(obj)}


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


class RemovedGizmo:
    @property
    def is_modal(self):
        raise ReferenceError("StructRNA of type Gizmo has been removed")


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


@contextmanager
def _remembered_exports(glb=""):
    settings = bpy.context.scene.bevy_glb_export
    before = settings.filepath
    settings.filepath = glb
    try:
        yield
    finally:
        settings.filepath = before


def _open_dialog(operator_class, **values):
    operator = SimpleNamespace(again=False, collection="", filepath="", filename_ext=operator_class.filename_ext, _settings=operator_class._settings, _target=operator_class._target, remembered=operator_class.remembered, properties=SimpleNamespace(is_property_set=lambda name: name in values))
    for name, value in {**{name: None for name in addon.property.EXPORT_OPTIONS}, **values}.items():
        setattr(operator, name, value)
    operator._recall = MethodType(operator_class._recall, operator)
    with mock.patch.object(addon.operator.ExportHelper, "invoke", return_value={"RUNNING_MODAL"}) as invoke:
        operator_class.invoke(operator, bpy.context, None)
    invoke.assert_called_once()
    return operator


def _resolved(path):
    return Path(os.path.abspath(bpy.path.abspath(path)))


def _dialog(test, operator_class, **values):
    properties = getattr(bpy.ops.export_scene, operator_class.bl_idname.partition(".")[2]).get_rna_type()
    defaults = {name: properties.properties[name].default for name in addon.property.EXPORT_OPTIONS}
    return SimpleNamespace(layout=FakeLayout(test), bl_rna=properties, **{"filepath": "", "collection": "", **defaults, **values})


def _again_buttons(layout):
    return [(text, getattr(properties, "again", False)) for text, properties, enabled in layout.buttons()]


def _execute(operator_class, context, **values):
    reports = []
    operator = SimpleNamespace(report=lambda kinds, message: reports.append((set(kinds), message)), **values)
    for name in dir(operator_class):
        if name.startswith("_") and not name.startswith("__") and callable(getattr(operator_class, name)):
            setattr(operator, name, MethodType(getattr(operator_class, name), operator))
    return operator_class.execute(operator, context), reports


def _clipboard_context(obj, *selected, clipboard=None):
    return SimpleNamespace(object=obj, selected_objects=list(selected), scene=bpy.context.scene, window_manager=clipboard or SimpleNamespace(clipboard=""))


def _shown_in_overview(ui_list):
    scene = bpy.context.scene
    flags, order = addon.panel.BEVY_UL_objects.filter_items(ui_list, bpy.context, scene, "objects")
    return sorted(obj.name for obj, flag in zip(scene.objects, flags) if flag)


def _operator_calls(layout):
    return [(bound.get("text", ""), bound.get("icon")) for name, bound, child in layout.calls if name == "operator"]


class TestRegistration(unittest.TestCase):
    def test_extension_registers_types_and_operators(self):
        self.assertTrue(hasattr(bpy.types.Object, "bevy_component_data"))
        self.assertTrue(hasattr(bpy.types.Scene, "bevy_component_previews"))
        self.assertTrue(hasattr(bpy.types.Scene, "bevy_component_definitions"))
        self.assertTrue(hasattr(bpy.types.World, "bevy_ambient_light"))
        self.assertTrue(hasattr(bpy.types.World, "bevy_sky"))
        self.assertTrue(hasattr(bpy.types.Scene, "bevy_bake_settings"))
        self.assertTrue(hasattr(bpy.types.Scene, "bevy_glb_export"))
        self.assertFalse(hasattr(bpy.types.Scene, "bevy_bsn_export"))
        self.assertFalse(_operator_exists("export_scene.bevy_components_bsn"))
        self.assertTrue(hasattr(bpy.types.Scene, "bevy_game"))
        self.assertTrue(hasattr(bpy.types.Scene, "bevy_collision_layers"))
        self.assertTrue(hasattr(bpy.types.Scene, "bevy_component_overview"))
        self.assertTrue(hasattr(bpy.types.Collection, "bevy_prefab"))
        self.assertTrue(hasattr(bpy.types.Collection, "bevy_component_data"))
        for idname in ("bevy_components.fit_collider", "bevy_components.add", "bevy_components.remove", "bevy_components.duplicate", "bevy_components.copy_component_to_selected", "bevy_components.reset", "bevy_components.move", "bevy_components.lod_preset", "bevy_components.set_collision_layers", "bevy_components.pick_sound", "bevy_components.pick_file", "bevy_components.define_fields", "bevy_components.definition_add", "bevy_components.definition_remove", "bevy_components.field_add", "bevy_components.field_remove", "bevy_components.field_move", "bevy_components.copy_to_selected", "bevy_components.validate", "bevy_components.cancel_export", "bevy_components.unwrap_lightmap", "bevy_components.bake_lighting", "bevy_components.play", "bevy_components.stop_game", "bevy_components.show_game_output", "bevy_components.cancel_bake", "bevy_components.export_all_scenes", "export_scene.bevy_components_glb", "export_scene.bevy_gltf", "bevy_components.copy_component", "bevy_components.copy_components", "bevy_components.paste_components", "bevy_components.save_preset", "bevy_components.apply_preset", "bevy_components.remove_preset", "bevy_components.edit_as_text", "bevy_components.apply_text", "bevy_components.select_by_component", "bevy_components.show_collection", "bevy_components.copy_physics"):
            self.assertTrue(_operator_exists(idname), idname)
        for idname in ("BEVY_MT_component_add", "BEVY_MT_component_add_physics", "BEVY_MT_component_add_advanced", "BEVY_MT_component_add_presets", "BEVY_MT_component_remove_presets", "BEVY_MT_component_context_menu", "BEVY_MT_object_context_menu", "BEVY_MT_object_menu", "BEVY_MT_select_by_component", "BEVY_PT_object_properties", "BEVY_PT_view_sidebar", "BEVY_PT_view_overview", "BEVY_PT_view_export", "BEVY_PT_view_play", "BEVY_PT_scene_definitions", "BEVY_PT_scene_collision_layers", "BEVY_PT_collection_components", "BEVY_PT_collection_prefab", "BEVY_PT_world_sky", "BEVY_PT_world_ambient_light", "BEVY_PT_overlay", "BEVY_UL_definitions", "BEVY_UL_fields", "BEVY_UL_objects"):
            self.assertTrue(hasattr(bpy.types, idname), idname)
        for idname in ("BEVY_GGT_collider_handles", "BEVY_GGT_range_handles", "BEVY_GGT_light_handles", "BEVY_GGT_audio_handles"):
            self.assertIsNotNone(bpy.types.GizmoGroup.bl_rna_get_subclass_py(idname), idname)
        for idname in ("BEVY_FH_glb", "BEVY_FH_gltf"):
            self.assertIsNotNone(bpy.types.FileHandler.bl_rna_get_subclass_py(idname), idname)
        self.assertEqual(bpy.types.BEVY_PT_overlay.bl_parent_id, "VIEW3D_PT_overlay")
        self.assertEqual((bpy.types.BEVY_PT_object_properties.bl_label, bpy.types.BEVY_PT_object_properties.bl_context), ("Game Components", "object"))
        self.assertIn(addon.menu.export_menu, bpy.types.TOPBAR_MT_file_export._dyn_ui_initialize())
        self.assertIn(addon.menu.export_status, bpy.types.STATUSBAR_HT_header._dyn_ui_initialize())
        self.assertIn(addon.menu.bake_status, bpy.types.STATUSBAR_HT_header._dyn_ui_initialize())
        self.assertIn(addon.menu.play_status, bpy.types.STATUSBAR_HT_header._dyn_ui_initialize())
        self.assertIn(addon.system.save_cleanup, bpy.app.handlers.save_pre)
        self.assertIn(addon.operator.export_on_save, bpy.app.handlers.save_post)
        for menu in (bpy.types.VIEW3D_MT_object, bpy.types.VIEW3D_MT_object_context_menu):
            self.assertIn(addon.menu.object_menu, menu._dyn_ui_initialize())
        self.assertIn(addon.menu.select_menu, bpy.types.VIEW3D_MT_select_object._dyn_ui_initialize())
        self.assertIn(addon.menu.rigid_body_menu, bpy.types.VIEW3D_MT_object_rigid_body._dyn_ui_initialize())
        self.assertIn(addon.menu.text_header, bpy.types.TEXT_HT_header._dyn_ui_initialize())
        for name in ("depsgraph_update_post", "undo_post", "redo_post", "load_post"):
            self.assertIn(addon.system.problems_changed, getattr(bpy.app.handlers, name))
        for name in ("depsgraph_update_post", "frame_change_post"):
            self.assertIn(addon.changes.depsgraph_changed, getattr(bpy.app.handlers, name))
        for name in ("undo_post", "redo_post", "load_post"):
            self.assertIn(addon.changes.forget_revisions, getattr(bpy.app.handlers, name))
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
        for menu in (addon.menu.BEVY_MT_component_add, addon.menu.BEVY_MT_component_add_physics, addon.menu.BEVY_MT_component_add_advanced, addon.menu.BEVY_MT_component_add_presets):
            self.assertEqual(menu.bl_options, {"SEARCH_ON_KEY_PRESS"})

    def test_disable_and_enable_keeps_components(self):
        clear_scene()
        obj = add_mesh(bpy.ops.mesh.primitive_cube_add, "kept")
        add_component(obj, "CUSTOM", custom_type="game::Kept")
        bpy.ops.preferences.addon_disable(module=addon.__name__)
        self.assertFalse(hasattr(bpy.types.Object, "bevy_component_data"))
        self.assertFalse(_operator_exists("bevy_components.add"))
        self.assertFalse(any(getattr(handler, "__name__", "") == "export_on_save" for handler in bpy.app.handlers.save_post))
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

    def test_property_changes_reach_the_serialized_components(self):
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
        self.assertEqual(_stored(self.obj)["components"], [DYNAMIC_BODY])
        with self.assertRaises(RuntimeError):
            bpy.ops.bevy_components.validate()
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
        collider = add_component(self.obj, "COLLIDER", collider_friction=0.1, collider_restitution=0.9, collider_memberships=layers(5), collider_filters=layers(5), collider_offset=(1, 2, 3), collider_events=True, collider_collision_only=True, show_layers=True)
        body = add_component(self.obj, "RIGID_BODY", rigid_body_kind="DYNAMIC", rigid_body_use_mass=True, rigid_body_mass=3)
        bpy.ops.bevy_components.reset(index=0)
        bpy.ops.bevy_components.reset(index=1)
        self.assertEqual((collider.collider_friction, collider.collider_restitution, list(collider.collider_memberships), list(collider.collider_filters), collider.show_layers), (0.5, 0.0, layers(0), [True] * 32, True))
        self.assertEqual((tuple(collider.collider_offset), collider.collider_events, collider.collider_collision_only), ((0.0, 0.0, 0.0), False, False))
        self.assertEqual((body.rigid_body_kind, body.rigid_body_use_mass, body.rigid_body_mass), ("STATIC", False, 1.0))
        self.assertEqual(_stored(self.obj)["components"], [{"type": "collider", "shape": "trimesh", **MESH_COLLIDER}, STATIC_BODY])
        collider.collider_sensor = True
        self.assertTrue(collider.collider_events)

    def test_collision_events_follow_the_sensor_until_set(self):
        collider = add_component(self.obj, "COLLIDER", collider_shape="CUBOID")
        self.assertFalse(collider.collider_events)
        collider.collider_sensor = True
        self.assertEqual((collider.collider_events, _stored(self.obj)["components"][0]["events"]), (True, True))
        collider.collider_events = False
        collider.collider_sensor = False
        collider.collider_sensor = True
        self.assertEqual((collider.collider_events, _stored(self.obj)["components"][0]["events"]), (False, False))
        solid = add_mesh(bpy.ops.mesh.primitive_cube_add, "solid")
        item = add_component(solid, "COLLIDER", collider_events=True)
        self.assertEqual(_stored(solid)["components"][0]["events"], True)
        select(solid, self.obj)
        self.assertEqual(bpy.ops.bevy_components.copy_component_to_selected(index=0), {"FINISHED"})
        self.assertTrue(self.obj.bevy_component_data.components[0].collider_events)
        self.assertFalse(self.obj.bevy_component_data.components[0].collider_sensor)
        item.collider_events = False
        self.assertEqual(_stored(solid)["components"][0]["events"], False)

    def test_fit_to_mesh_sets_size_and_offset_on_bevy_axes(self):
        self.obj.data.transform(Matrix.Translation((1, 0, 0.75)) @ Matrix.Diagonal((0.25, 0.15, 0.75, 1)))
        self.obj.scale = (2, 2, 2)
        collider = add_component(self.obj, "COLLIDER", collider_shape="CUBOID")
        self.assertEqual(bpy.ops.bevy_components.fit_collider(index=0), {"FINISHED"})
        self.assertEqual(_rounded(tuple(collider.collider_size)), (0.5, 1.5, 0.3))
        self.assertEqual(_rounded(tuple(collider.collider_offset)), (1.0, 0.75, 0.0))
        self.assertEqual(_rounded(_stored(self.obj)["components"][0]["offset"]), [1.0, 0.75, 0.0])
        collider.collider_shape = "CAPSULE"
        self.assertEqual(bpy.ops.bevy_components.fit_collider(index=0), {"FINISHED"})
        self.assertEqual(_rounded((collider.collider_radius, collider.collider_height)), _rounded((math.hypot(0.25, 0.15), 1.5 - 2 * math.hypot(0.25, 0.15))))
        collider.collider_shape = "SPHERE"
        self.assertEqual(bpy.ops.bevy_components.fit_collider(index=0), {"FINISHED"})
        self.assertAlmostEqual(collider.collider_radius, math.sqrt(0.25 ** 2 + 0.75 ** 2 + 0.15 ** 2), places=5)
        collider.collider_shape = "CONVEX"
        self.assertEqual(bpy.ops.bevy_components.fit_collider(index=0), {"CANCELLED"})
        self.assertEqual(_stored(self.obj)["components"][0]["offset"], None)

    def test_fit_to_mesh_reads_child_meshes_and_modifiers(self):
        holder = add_empty("holder", (5, 0, 0))
        add_component(holder, "COLLIDER", collider_shape="CUBOID")
        select(holder)
        self.assertEqual(bpy.ops.bevy_components.fit_collider(index=0), {"CANCELLED"})
        self.obj.parent = holder
        self.obj.location = (0, 2, 0)
        self.obj.modifiers.new("Array", "ARRAY").count = 3
        bystander = add_mesh(bpy.ops.mesh.primitive_cube_add, "bystander", location=(5, 0, 10))
        add_component(bystander, "COLLIDER")
        bystander.parent = holder
        bystander.matrix_parent_inverse = holder.matrix_world.inverted()
        bpy.context.view_layer.update()
        select(holder)
        self.assertEqual(bpy.ops.bevy_components.fit_collider(index=0), {"FINISHED"})
        collider = holder.bevy_component_data.components[0]
        self.assertEqual(_rounded(tuple(collider.collider_size)), (6.0, 2.0, 2.0))
        self.assertEqual(_rounded(tuple(collider.collider_offset)), (2.0, 0.0, -2.0))

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

    def test_navigation_is_stored(self):
        item = add_component(self.obj, "NAVIGATION")
        self.assertEqual(_stored(self.obj)["components"], [{"type": "navigation", "kind": "walkable", "cost": 1.0}])
        item.navigation_cost = 3
        self.assertEqual(_stored(self.obj)["components"], [{"type": "navigation", "kind": "walkable", "cost": 3.0}])
        item.navigation_kind = "OBSTACLE"
        self.assertEqual(_stored(self.obj)["components"], [{"type": "navigation", "kind": "obstacle", "cost": None}])
        item.navigation_kind = "IGNORED"
        self.assertEqual(_stored(self.obj)["components"], [{"type": "navigation", "kind": "ignored", "cost": None}])
        self.assertEqual(bpy.ops.bevy_components.add(component_type="NAVIGATION"), {"CANCELLED"})

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
            (root / "scenes").mkdir()
            bpy.ops.wm.save_as_mainfile(filepath=str(root / "scenes" / "scene.blend"))
            item.scene_file = "//props/tree.glb"
            item.scene_index = 2
            self.assertEqual(_stored(holder)["components"], [{"type": "scene_reference", "path": "props/tree.glb", "scene": 2}])
            item.scene_file = str(root / "shared" / "rock.gltf")
            self.assertEqual(_stored(holder)["components"][0]["path"], "../shared/rock.gltf")
            bpy.ops.wm.save_mainfile()
            bpy.ops.wm.open_mainfile(filepath=str(root / "scenes" / "scene.blend"))
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
        self.assertEqual(irradiance, {"type": "irradiance_volume", "size": [10.0, 5.0, 10.0], "falloff": [0.0, 0.0, 0.0], "intensity": 683.0, "file": None})
        self.assertEqual(bpy.ops.bevy_components.add(component_type="REFLECTION_PROBE"), {"CANCELLED"})
        self.assertEqual(bpy.ops.bevy_components.reset(index=1), {"FINISHED"})
        self.assertEqual((tuple(probe.volume_size), probe.volume_falloff, probe.probe_intensity, probe.probe_parallax, probe.probe_file), ((10.0, 5.0, 10.0), 0.0, 683.0, True, ""))
        other = add_mesh(bpy.ops.mesh.primitive_cube_add, "other")
        probe.probe_file = str(CUBEMAP)
        select(self.obj, other)
        self.assertEqual(bpy.ops.bevy_components.copy_component_to_selected(index=1), {"FINISHED"})
        self.assertEqual(_stored(other)["components"], [_stored(self.obj)["components"][1]])

    def test_lightmaps_are_stored_on_meshes(self):
        item = add_component(self.obj, "LIGHTMAP")
        self.assertEqual(_stored(self.obj)["components"], [{"type": "lightmap", "bicubic": False, "file": None}])
        item.lightmap_bicubic = True
        item.probe_file = str(LIGHTMAP)
        self.assertEqual(_stored(self.obj)["components"], [{"type": "lightmap", "bicubic": True, "file": str(LIGHTMAP)}])
        self.assertEqual(bpy.ops.bevy_components.reset(index=0), {"FINISHED"})
        self.assertEqual((item.lightmap_resolution, item.lightmap_bicubic, item.probe_file), ("512", False, ""))
        for obj in (add_empty("holder", (0, 0, 0)), add_light("lamp", "POINT", (0, 0, 0))):
            select(obj)
            self.assertEqual(bpy.ops.bevy_components.add(component_type="LIGHTMAP"), {"CANCELLED"})
            self.assertEqual(len(obj.bevy_component_data.components), 0)
        holder = bpy.data.objects["holder"]
        holder.bevy_component_data.components.add().component_type = "LIGHTMAP"
        self.assertEqual(_stored(holder)["components"], [])

    def test_unwrap_lightmap_fills_the_second_uv_map(self):
        mesh = self.obj.data
        mesh.uv_layers.new(name="second")
        mesh.uv_layers.new(name="detail")
        first, detail = (numpy.array([tuple(loop.uv) for loop in mesh.uv_layers[name].data]) for name in ("UVMap", "detail"))
        mesh.polygons[0].hide = True
        mesh.polygons[1].select = False
        flags = [(polygon.hide, polygon.select) for polygon in mesh.polygons]
        add_component(self.obj, "LIGHTMAP", lightmap_resolution="128")
        select(self.obj)
        self.assertEqual(bpy.ops.bevy_components.unwrap_lightmap(), {"FINISHED"})
        self.assertEqual(([layer.name for layer in mesh.uv_layers], mesh.uv_layers.active_index, mesh.uv_layers["UVMap"].active_render), (["UVMap", "second", "detail"], 0, True))
        self.assertTrue(numpy.array_equal(first, [tuple(loop.uv) for loop in mesh.uv_layers["UVMap"].data]))
        self.assertTrue(numpy.array_equal(detail, [tuple(loop.uv) for loop in mesh.uv_layers["detail"].data]))
        self.assertEqual([(polygon.hide, polygon.select) for polygon in mesh.polygons], flags)
        islands = [numpy.array([tuple(mesh.uv_layers["second"].data[index].uv) for index in polygon.loop_indices]) for polygon in mesh.polygons]
        self.assertTrue(all(0.0 <= island.min() and island.max() <= 1.0 for island in islands))
        boxes = [(island.min(axis=0), island.max(axis=0)) for island in islands]
        gaps = [max((low_b - high_a).max(), (low_a - high_b).max()) for index, (low_a, high_a) in enumerate(boxes) for low_b, high_b in boxes[index + 1:]]
        self.assertGreaterEqual(min(gaps), 3.5 / 128)
        bare = bpy.data.objects.new("bare", bpy.data.meshes.new("bare"))
        bare.data.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
        bpy.context.scene.collection.objects.link(bare)
        select(bare)
        self.assertEqual(bpy.ops.bevy_components.unwrap_lightmap(), {"FINISHED"})
        self.assertEqual([layer.name for layer in bare.data.uv_layers], ["UVMap", "lightmap"])
        self.assertEqual(addon.system.lightmap_uv_map(bare).name, "lightmap")
        select(add_empty("holder", (0, 0, 0)))
        self.assertFalse(bpy.ops.bevy_components.unwrap_lightmap.poll())
        select(bare)
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            self.assertFalse(bpy.ops.bevy_components.unwrap_lightmap.poll())
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")

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
        add_component(self.obj, "SHADOWS")
        self.assertEqual([component["type"] for component in _stored(self.obj)["components"]], ["shadows"])

    def test_save_and_reload(self):
        add_component(self.obj, "COLLIDER", collider_shape="SPHERE", collider_radius=2, collider_friction=0.2, collider_memberships=layers(1, 7))
        add_component(self.obj, "RIGID_BODY", rigid_body_kind="DYNAMIC", rigid_body_use_mass=True, rigid_body_mass=7.5)
        self.obj["bevy_components"] = "stale"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scene.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(path))
            bpy.ops.wm.open_mainfile(filepath=str(path))
        obj = bpy.data.objects["subject"]
        self.assertNotIn("bevy_components", obj)
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
        self.assertEqual(_stored(self.obj)["components"][1]["body1"], "door_frame")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scene.blend"
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
        for shape in ("TRIMESH", "CONVEX", "CUBOID", "SPHERE", "CAPSULE", "CYLINDER", "CONE"):
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
        add_component(self.obj, "CUSTOM", custom_type="my_game::enemies::Health")
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertIn("Health", panel.layout.texts())
        self.assertNotIn("my_game::enemies::Health", panel.layout.texts())
        fields = [layout for name, bound, layout in panel.layout.calls if name in {"prop", "prop_search"} and bound["property"] in {"custom_type", "custom_json"}]
        self.assertEqual(len(fields), 2)
        self.assertTrue(all(layout.parent.use_property_split is False for layout in fields))
        self.assertIn("bevy_components.edit_as_text", panel.layout.operators())

    def test_removed_component_types_are_skipped(self):
        add_component(self.obj, "COLLIDER")
        removed = add_component(self.obj, "RIGID_BODY")
        removed["component_type"] = 3
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
        self.assertEqual(menu.layout.menus(), ["BEVY_MT_component_add_physics", "BEVY_MT_component_add_advanced", "BEVY_MT_component_add_presets"])
        self.assertEqual([text for text, properties, enabled in menu.layout.buttons()], ["Custom Component", "Navigation", "Visibility Range", "Lightmap", "Scene Reference"])
        found = {}
        for menu_type, kinds in ((addon.menu.BEVY_MT_component_add, None), (addon.menu.BEVY_MT_component_add_advanced, ["COLLIDER", "RIGID_BODY", "JOINT", "LIGHT", "SHADOWS", "FOG_VOLUME", "REFLECTION_PROBE", "IRRADIANCE_VOLUME", "AUDIO_PLAYER", "ANIMATION"])):
            menu = FakePanel(self)
            menu_type.draw(menu, _menu_context(self.obj))
            buttons = {properties.component_type: enabled for text, properties, enabled in menu.layout.buttons() if hasattr(properties, "component_type")}
            if kinds is not None:
                self.assertEqual(list(buttons), kinds)
            found.update(buttons)
        self.assertEqual(found, {"CUSTOM": True, "COLLIDER": False, "RIGID_BODY": True, "JOINT": True, "VISIBILITY_RANGE": True, "SHADOWS": True, "LIGHT": False, "FOG_VOLUME": True, "REFLECTION_PROBE": True, "IRRADIANCE_VOLUME": True, "LIGHTMAP": True, "AUDIO_PLAYER": True, "ANIMATION": True, "SCENE_REFERENCE": True, "NAVIGATION": True})
        add_component(self.obj, "AUDIO_PLAYER")
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add_advanced.draw(menu, _menu_context(self.obj))
        self.assertFalse(dict((text, enabled) for text, properties, enabled in menu.layout.buttons())["Audio Player"])
        self.assertEqual(menu.layout.texts()[0], "In place of Blender's settings")
        lamp = add_light("lamp", "POINT", (0, 0, 0))
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add_advanced.draw(menu, _menu_context(lamp))
        self.assertTrue(dict((text, enabled) for text, properties, enabled in menu.layout.buttons())["Light"])
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add.draw(menu, _menu_context(lamp))
        self.assertFalse(dict((text, enabled) for text, properties, enabled in menu.layout.buttons())["Lightmap"])
        add_component(lamp, "LIGHT")
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add_advanced.draw(menu, _menu_context(lamp))
        self.assertFalse(dict((text, enabled) for text, properties, enabled in menu.layout.buttons())["Light"])

    def test_component_context_menu_targets_its_component(self):
        add_component(self.obj, "COLLIDER")
        custom = add_component(self.obj, "CUSTOM")
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_context_menu.draw(menu, _menu_context(self.obj, custom))
        buttons = {text: (properties, enabled) for text, properties, enabled in menu.layout.buttons()}
        self.assertEqual(set(buttons), {"Duplicate", "Copy", "Copy to Selected", "Define Fields", "Edit as Text", "Reset to Defaults", "Move to First", "Move Up", "Move Down", "Move to Last", "Remove"})
        self.assertTrue(all(properties.index == 1 for properties, enabled in buttons.values()))
        self.assertEqual({text for text, (properties, enabled) in buttons.items() if not enabled}, {"Move Down", "Move to Last"})
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_context_menu.draw(menu, _menu_context(self.obj, self.obj.bevy_component_data.components[0]))
        self.assertEqual({text for text, properties, enabled in menu.layout.buttons() if not enabled}, {"Duplicate", "Move to First", "Move Up"})

    def test_object_context_menu(self):
        menu = FakePanel(self)
        with _remembered_exports():
            addon.menu.BEVY_MT_object_context_menu.draw(menu, _menu_context(self.obj))
        self.assertEqual(menu.layout.operators(), ["bevy_components.copy_to_selected", "bevy_components.copy_components", "bevy_components.paste_components", "bevy_components.validate", "bevy_components.convert_to_native", "bevy_components.bake_lighting", "export_scene.bevy_components_glb"])
        menu = FakePanel(self)
        with _remembered_exports(glb="//level.glb"):
            addon.menu.BEVY_MT_object_context_menu.draw(menu, _menu_context(self.obj))
        self.assertEqual(_again_buttons(menu.layout)[-2:], [("Export Bevy Scene (.glb)...", False), ("Export Again (level.glb)", True)])

    def test_sidebar_without_active_object(self):
        select()
        panel = FakePanel(self)
        addon.panel.BEVY_PT_view_sidebar.draw(panel, bpy.context)
        self.assertEqual(panel.layout.texts(), ["Select an object"])

    def test_collider_card_draws_surface_and_layers(self):
        collider = add_component(self.obj, "COLLIDER", collider_shape="CUBOID")
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props()[-8:], ["collider_offset"] * 3 + ["collider_sensor", "collider_events", "collider_collision_only", "collider_friction", "collider_restitution"])
        self.assertIn("bevy_components.fit_collider", panel.layout.operators())
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
        collider.collider_shape = "TRIMESH"
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertNotIn("collider_offset", panel.layout.props())
        self.assertNotIn("bevy_components.fit_collider", panel.layout.operators())

    def test_named_collision_layers_show_in_the_collider_card(self):
        names = bpy.context.scene.bevy_collision_layers
        names.layer_1 = "Player"
        names.layer_4 = " Enemies "
        try:
            add_component(self.obj, "COLLIDER", show_layers=True)
            panel = FakePanel(self)
            addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
            toggles = [(bound["index"], bound["text"]) for name, bound, layout in panel.layout.calls if name == "prop" and bound["property"] == "collider_memberships"]
            self.assertEqual(toggles[:2], [(1, "1 Player"), (4, "4 Enemies")])
            self.assertEqual(toggles[2:], [(index, str(index)) for index in range(32) if index not in {1, 4}])
            grids = [bound["columns"] for name, bound, layout in panel.layout.calls if name == "grid_flow"]
            self.assertEqual(grids, [2, 8, 2, 8])
            panel = FakePanel(self)
            addon.panel.BEVY_PT_scene_collision_layers.draw(panel, bpy.context)
            self.assertEqual(panel.layout.props(), [f"layer_{index}" for index in range(32)])
            self.assertEqual(addon.system.layer_names(bpy.context.scene)[:5], ["", "Player", "", "", "Enemies"])
        finally:
            names.layer_1 = ""
            names.layer_4 = ""

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
            self.assertIn("Pins frame to this spot in the scene", panel.layout.texts())
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
        self.assertIn(("Joint", "CANCEL"), [(bound.get("text"), bound.get("icon")) for name, bound, layout in panel.layout.calls if name == "label"])
        self.assertNotIn("Pins frame to this spot in the scene", panel.layout.texts())

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

    def test_navigation_card(self):
        navigation = add_component(self.obj, "NAVIGATION")
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props()[-2:], ["navigation_kind", "navigation_cost"])
        self.assertIn("Navigation", panel.layout.texts())
        navigation.navigation_kind = "OBSTACLE"
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props()[-1], "navigation_kind")
        self.assertNotIn("navigation_cost", panel.layout.props())

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
        self.assertEqual([(properties.index, properties.target) for text, properties, enabled in panel.layout.buttons() if hasattr(properties, "target")], [(0, "scene_file")])

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
        self.assertEqual(panel.layout.props(), ["enabled", "volume_size", "volume_size", "volume_size", "volume_falloff", "probe_intensity", "probe_parallax", "probe_file", "bake_resolution", "enabled", "volume_size", "volume_size", "volume_size", "volume_falloff", "probe_intensity", "probe_file", "bake_voxels", "bake_voxels", "bake_voxels"])
        self.assertEqual([bound["text"] for name, bound, layout in panel.layout.calls if name == "prop" and bound["property"] == "probe_file"], ["Cubemap", "Voxels"])
        self.assertEqual([(bound["index"], bound["text"]) for name, bound, layout in panel.layout.calls if name == "prop" and bound["property"] == "bake_voxels"], [(0, "Bake Voxels X"), (1, "Y (Up)"), (2, "Z")])
        self.assertEqual([(text, properties.object_name, properties.index) for text, properties, enabled in panel.layout.buttons() if text == "Bake"], [("Bake", "subject", 0), ("Bake", "subject", 1)])
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

    def test_lightmap_card(self):
        item = add_component(self.obj, "LIGHTMAP")
        layout = self._draw_card(self.obj)
        self.assertEqual(layout.props(), ["enabled", "probe_file", "lightmap_resolution", "lightmap_bicubic"])
        self.assertEqual([bound["text"] for name, bound, child in layout.calls if name == "prop" and bound["property"] == "probe_file"], ["Lightmap"])
        self.assertEqual(layout.operators()[-2:], ["bevy_components.unwrap_lightmap", "bevy_components.bake_lighting"])
        self.assertEqual([(properties.object_name, properties.index) for text, properties, enabled in layout.buttons() if text == "Bake"], [("subject", 0)])
        self.assertIn("None", layout.alerts())
        self.assertIn("No second UV map, which Bevy reads lightmaps with. Click Unwrap Lightmap UVs", " ".join(layout.texts()))
        self.assertIn("No lightmap baked yet, so the mesh gets no baked light", " ".join(layout.texts()))
        bpy.ops.bevy_components.unwrap_lightmap()
        item.probe_file = str(LIGHTMAP)
        layout = self._draw_card(self.obj)
        self.assertEqual(layout.alerts(), [])
        self.assertIn("lightmap", layout.texts())
        self.assertIn("16 × 16 lightmap", layout.texts())

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

    def test_lights_without_a_light_component_use_their_light_settings(self):
        window = add_light("window", "AREA", (0, 0, 0))
        self.assertIn("Light from Light Properties", self._draw_card(window).texts())
        add_component(window, "LIGHT")
        self.assertNotIn("Light from Light Properties", self._draw_card(window).texts())

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

    def test_world_sky_panel(self):
        panel_type = addon.panel.BEVY_PT_world_sky
        world = bpy.data.worlds.new("sky_test")
        try:
            context = SimpleNamespace(world=world, region=None)
            self.assertTrue(panel_type.poll(context))
            self.assertFalse(panel_type.poll(SimpleNamespace(world=None)))
            panel = FakePanel(self)
            panel_type.draw_header(panel, context)
            self.assertEqual(panel.layout.props(), ["enabled"])
            panel = FakePanel(self)
            panel_type.draw(panel, context)
            self.assertFalse(panel.layout.active)
            self.assertEqual(panel.layout.props(), ["sky_file", "bake_resolution", "brightness", "environment_light", "environment_intensity"])
            self.assertEqual([(text, properties.sky) for text, properties, enabled in panel.layout.buttons()], [("Bake", True)])
            self.assertIn("No cubemap baked yet, so Bevy shows no sky", " ".join(panel.layout.texts()))
            world.bevy_sky.enabled = True
            world.bevy_sky.sky_file = str(CUBEMAP)
            panel = FakePanel(self)
            panel_type.draw(panel, context)
            self.assertTrue(panel.layout.active)
            self.assertIn("16 × 16 cubemap", panel.layout.texts())
            self.assertNotIn("twice", " ".join(panel.layout.texts()))
            ambient = FakePanel(self)
            addon.panel.BEVY_PT_world_ambient_light.draw(ambient, context)
            self.assertIn("Off, so the export sets Bevy's ambient light to 0 and the Bevy Sky's environment light lights the scene alone", " ".join(ambient.layout.texts()))
            world.bevy_ambient_light.enabled = True
            for drawn in (panel_type, addon.panel.BEVY_PT_world_ambient_light):
                panel = FakePanel(self)
                drawn.draw(panel, context)
                self.assertIn("Bevy Ambient Light takes the World color, which the Bevy Sky's environment light already gives, so meshes get the World's light twice", " ".join(panel.layout.texts()))
            world.bevy_ambient_light.use_world_color = False
            for drawn in (panel_type, addon.panel.BEVY_PT_world_ambient_light):
                panel = FakePanel(self)
                drawn.draw(panel, context)
                self.assertNotIn("twice", " ".join(panel.layout.texts()))
            world.bevy_ambient_light.use_world_color = True
            world.bevy_sky.environment_light = False
            for drawn in (panel_type, addon.panel.BEVY_PT_world_ambient_light):
                panel = FakePanel(self)
                drawn.draw(panel, context)
                self.assertNotIn("twice", " ".join(panel.layout.texts()))
            world.bevy_sky.sky_file = str(IRRADIANCE_VOLUME)
            panel = FakePanel(self)
            panel_type.draw(panel, context)
            self.assertIn("irradiance_volume.ktx2 is not a cubemap", " ".join(panel.layout.texts()))
            self.assertTrue(_prop_layout(panel.layout, "sky_file").alert)
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
        self.assertEqual(panel.layout.props(), ["scope", "colliders", "joints", "velocities", "visibility_ranges", "audio_ranges", "scene_references", "volumes", "lights", "navigation", "labels", "xray", "edit_handles", "max_mesh_edges"])
        settings.enabled = False
        panel = FakePanel(self)
        addon.panel.BEVY_PT_overlay.draw(panel, _menu_context())
        self.assertFalse(panel.layout.active)
        settings.enabled = True

    def test_export_menu(self):
        panel = FakePanel(self)
        with _remembered_exports():
            addon.menu.export_menu(panel, bpy.context)
        self.assertEqual(panel.layout.operators(), ["export_scene.bevy_gltf", "export_scene.bevy_components_glb"])
        panel = FakePanel(self)
        with _remembered_exports(glb="//level.glb"):
            addon.menu.export_menu(panel, bpy.context)
        self.assertEqual(panel.layout.operators(), ["export_scene.bevy_gltf", "export_scene.bevy_components_glb", "export_scene.bevy_components_glb"])
        self.assertEqual(_again_buttons(panel.layout), [("Bevy glTF (.glb/.gltf)", False), ("Bevy Scene (.glb)", False), ("Export Again (level.glb)", True)])

    def test_sidebar_export_panel(self):
        panel = FakePanel(self)
        with _remembered_exports():
            addon.panel.BEVY_PT_view_export.draw(panel, bpy.context)
        self.assertEqual(_again_buttons(panel.layout), [("Bevy Scene (.glb)...", False)])
        self.assertEqual([name for name, bound, layout in panel.layout.calls if name == "prop"], [])
        panel = FakePanel(self)
        with _remembered_exports(glb="//level.glb"):
            addon.panel.BEVY_PT_view_export.draw(panel, bpy.context)
        self.assertEqual(_again_buttons(panel.layout), [("Export Again (level.glb)", True), ("Bevy Scene (.glb)...", False)])
        self.assertEqual(panel.layout.operators()[0], "export_scene.bevy_components_glb")
        self.assertEqual([(bound["data"], bound["text"]) for name, bound, layout in panel.layout.calls if name == "prop"], [(bpy.context.scene.bevy_glb_export, "Export on Save")])

    def test_export_all_scenes_needs_more_than_one_scene(self):
        menu = FakePanel(self)
        panel = FakePanel(self)
        with _remembered_exports():
            addon.menu.BEVY_MT_object_context_menu.draw(menu, _menu_context(self.obj))
            addon.panel.BEVY_PT_view_export.draw(panel, bpy.context)
        self.assertNotIn("bevy_components.export_all_scenes", menu.layout.operators() + panel.layout.operators())
        other = bpy.data.scenes.new("other")
        try:
            menu = FakePanel(self)
            panel = FakePanel(self)
            with _remembered_exports():
                addon.menu.BEVY_MT_object_context_menu.draw(menu, _menu_context(self.obj))
                addon.panel.BEVY_PT_view_export.draw(panel, bpy.context)
        finally:
            bpy.data.scenes.remove(other)
        self.assertEqual(menu.layout.operators()[-1], "bevy_components.export_all_scenes")
        self.assertEqual(_again_buttons(panel.layout)[0], ("Export All Scenes (.glb)", False))

    def test_export_again_describes_where_it_exports(self):
        glb = addon.operator.BEVY_OT_export_glb
        self.assertEqual(glb.description(bpy.context, SimpleNamespace(again=False, collection="")), glb.bl_description)
        with _remembered_exports(glb="//level.glb"):
            self.assertEqual(glb.description(bpy.context, SimpleNamespace(again=True, collection="")), "Export the scene again to //level.glb with the settings the last export used, without the file dialog")
        with _remembered_exports():
            self.assertEqual(glb.description(bpy.context, SimpleNamespace(again=True, collection="")), "Export the scene once with File > Export > Bevy Scene (.glb), then export it again here with one click")
        self.assertEqual(glb.description(bpy.context, SimpleNamespace(again=False, collection="lamp_post", filepath="/game/assets/props/lamp_post.glb")), "Export lamp_post to lamp_post.glb, with the prefabs inside it, using the scene's export settings")
        again = bpy.ops.export_scene.bevy_components_glb.get_rna_type().properties["again"]
        self.assertTrue(again.is_hidden and again.is_skip_save)

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

    def test_status_bar_shows_running_bakes(self):
        header = FakePanel(self)
        addon.menu.bake_status(header, bpy.context)
        self.assertEqual(header.layout.calls, [])
        self.assertTrue(bpy.ops.bevy_components.bake_lighting.poll())
        self.assertFalse(bpy.ops.bevy_components.cancel_bake.poll())
        task = mock.Mock(done=1, total=4, fraction=0.5)
        with mock.patch.dict(addon.operator._bakes, {task: None}):
            addon.menu.bake_status(header, bpy.context)
            self.assertFalse(bpy.ops.bevy_components.bake_lighting.poll())
            bpy.ops.bevy_components.cancel_bake()
        task.cancel.assert_called_once_with()
        self.assertEqual([bound for name, bound, layout in header.layout.calls if name == "progress"], [{"factor": 0.375, "type": "BAR", "text": "Baking lighting 1/4"}])
        self.assertEqual(header.layout.operators(), ["bevy_components.cancel_bake"])
        self.assertTrue(bpy.ops.bevy_components.bake_lighting.poll())

    def test_unregister_stops_running_bakes(self):
        task = mock.Mock()
        directory = tempfile.TemporaryDirectory()
        addon.operator._bakes[task] = (bpy.context.window_manager.event_timer_add(60.0, window=bpy.context.window), directory)
        addon.operator.stop_bakes()
        task.cancel.assert_called_once_with()
        task.wait.assert_called_once_with()
        self.assertFalse(Path(directory.name).exists())
        self.assertEqual(addon.operator._bakes, {})

    def test_unregister_stops_running_exports(self):
        task = mock.Mock()
        directory = tempfile.TemporaryDirectory()
        addon.operator._exports[task] = (bpy.context.window_manager.event_timer_add(60.0, window=bpy.context.window), directory)
        addon.operator.stop_exports()
        task.cancel.assert_called_once_with()
        task.wait.assert_called_once_with()
        self.assertFalse(Path(directory.name).exists())
        self.assertEqual(addon.operator._exports, {})

    def test_cancelled_dialogs_have_nothing_to_stop(self):
        for operator_class in (addon.operator.BEVY_OT_export_glb, addon.operator.BEVY_OT_bake_lighting):
            self.assertIsNone(operator_class.cancel(SimpleNamespace(_task=None), bpy.context))

    def test_export_dialog_texture_compression(self):
        properties = bpy.ops.export_scene.bevy_components_glb.get_rna_type()
        include = ["export_on_save", "selected_only", "visible_only", "renderable_only", "include_lights", "include_cameras", "include_animations", "apply_modifiers", "texture_compression"]
        expected = {
            "DISABLED": include,
            "ETC1S": include + ["etc1s_quality", "etc1s_effort"],
            "UASTC": include + ["uastc_quality", "uastc_zstd"],
            "AUTOMATIC": include + ["etc1s_quality", "etc1s_effort", "uastc_quality", "uastc_zstd"],
        }
        for mode, props in expected.items():
            operator = _dialog(self, addon.operator.BEVY_OT_export_glb, texture_compression=mode)
            addon.operator.BEVY_OT_export_glb.draw(operator, bpy.context)
            self.assertEqual(operator.layout.props(), props, mode)
            self.assertIn("Texture Compression", operator.layout.texts())
            self.assertEqual(any(text.startswith("KTX-Software") for text in operator.layout.texts()), mode != "DISABLED", mode)

    def test_preferences_show_encoder_status(self):
        preferences = bpy.context.preferences.addons[addon.__name__].preferences
        with tempfile.TemporaryDirectory() as directory:
            preferences.ktx_path = str(Path(directory) / "missing" / "ktx")
            try:
                panel = SimpleNamespace(layout=FakeLayout(self), bl_rna=preferences.bl_rna, ktx_path=preferences.ktx_path, schema_path="", game_folder="", run_command="cargo run", viewer_folder="")
                addon.preferences.BEVY_AP_preferences.draw(panel, bpy.context)
            finally:
                preferences.ktx_path = ""
        self.assertEqual(panel.layout.props(), ["ktx_path", "schema_path", "game_folder", "run_command", "viewer_folder"])
        self.assertTrue(panel.layout.alerts()[0].startswith("KTX-Software was not found at "))
        self.assertIn("Install KTX-Software 4.4 or newer", panel.layout.alerts()[1])
        if addon.encoder.find_encoder() is not None:
            panel = SimpleNamespace(layout=FakeLayout(self), bl_rna=preferences.bl_rna, ktx_path="", schema_path="", game_folder="", run_command="cargo run", viewer_folder="")
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

    def test_define_fields_keeps_enum_variants_and_rust_types(self):
        definition = define_component("game::Team", ("side", "STRING", ""))
        definition.fields[0].field_type = "ENUM"
        definition.fields[0].variants = "Red, Blue"
        definition.fields[0].rust_type = "game::Side"
        item = add_component(self.obj, "CUSTOM", type_path="game::Team")
        item.fields[0].enum_value = "Blue"
        self.library.definitions.clear()
        self.assertEqual(bpy.ops.bevy_components.define_fields(index=0), {"FINISHED"})
        field = self._definition("game::Team").fields[0]
        self.assertEqual((field.field_type, field.variants, field.rust_type, field.string_value), ("ENUM", "Red, Blue", "game::Side", "Blue"))
        self.assertEqual(addon.validation.check_object(self.obj, bpy.data.objects), [])

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
            path = Path(directory) / "scene.blend"
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
        self.assertEqual([bound["property"] for name, bound, layout in panel.layout.calls if name == "prop_search"], [])
        self.assertIn("custom_type", panel.layout.props())
        self.assertEqual(panel.layout.props().count("custom_json"), 1)
        self.assertIn("Mover", panel.layout.texts())

    def test_scene_panel_lists_definitions_and_fields(self):
        panel = FakePanel(self)
        addon.panel.BEVY_PT_scene_definitions.draw(panel, bpy.context)
        lists = lambda: [bound["listtype_name"] for name, bound, layout in panel.layout.calls if name == "template_list"]
        self.assertEqual(lists(), ["BEVY_UL_definitions"])
        define_component("game::Mover", ("speed", "FLOAT", 1.0), ("axis", "VECTOR", (0.0, 1.0, 0.0)))
        panel = FakePanel(self)
        addon.panel.BEVY_PT_scene_definitions.draw(panel, bpy.context)
        self.assertEqual(lists(), ["BEVY_UL_definitions", "BEVY_UL_fields"])
        self.assertEqual(panel.layout.operators(), ["bevy_components.reload_schema", "bevy_components.definition_add", "bevy_components.definition_remove", "bevy_components.field_add", "bevy_components.field_remove", "bevy_components.field_move", "bevy_components.field_move"])
        self.assertEqual(panel.layout.props(), ["field_type", "vector_value"])
        self.assertIn("No game components found", panel.layout.texts())

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
        self.assertEqual(buttons[:3], [("Custom Component", "CUSTOM", "", True), ("game::Health", "CUSTOM", "game::Health", False), ("game::Wave", "CUSTOM", "game::Wave", True)])
        self.assertEqual([button[1] for button in buttons[3:]], ["NAVIGATION", "VISIBILITY_RANGE", "LIGHTMAP", "SCENE_REFERENCE"])

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


class TestGameComponents(unittest.TestCase):
    def setUp(self):
        clear_scene()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(use_game_schema, None)
        self.obj = add_mesh(bpy.ops.mesh.primitive_cube_add, "subject")
        self.other = add_empty("other", (0, 0, 0))

    def _schema(self, *components):
        path = Path(self.directory.name) / "bevy_components_schema.json"
        path.write_text(json.dumps({"version": 1, "components": list(components)}), encoding="utf-8")
        use_game_schema(path)
        return path

    def _data(self, obj):
        return [component["data"] for component in _stored(obj)["components"]]

    def test_game_components_come_from_the_schema_file(self):
        use_game_schema()
        self.assertEqual(sorted(addon.system.game_types()), ["my_game::Patrol", "my_game::Reward"])
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add.draw(menu, _menu_context(self.obj))
        self.assertIn(("BEVY_MT_component_add_game", "my_game"), [(bound["menu"], bound.get("text")) for name, bound, layout in menu.layout.calls if name == "menu"])
        item = add_component(self.obj, "CUSTOM", type_path="my_game::Patrol")
        self.assertEqual([(field.name, field.field_type, field.rust_type) for field in item.fields], [("speed", "FLOAT", "f32"), ("mode", "ENUM", "my_game::PatrolMode"), ("offset", "VECTOR2", "glam::Vec2"), ("stops", "INT", "u8")])
        self.assertEqual(_stored(self.obj)["components"], [{"type": "custom", "type_path": "my_game::Patrol", "data": {"speed": 2.0, "mode": "Loop", "offset": [0.0, 0.0], "stops": 1}}])
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add_game.draw(menu, _menu_context(self.obj))
        self.assertEqual([(text, properties.type_path, enabled) for text, properties, enabled in menu.layout.buttons()], [("Patrol", "my_game::Patrol", False), ("Reward", "my_game::Reward", True)])
        self.assertEqual(addon.operator.BEVY_OT_add_component.description(bpy.context, SimpleNamespace(type_path="my_game::Reward")), "Add my_game::Reward to the active object")
        define_component("my_game::Wave")
        self.assertEqual(addon.system.type_path_suggestions(None, bpy.context, ""), ["my_game::Patrol", "my_game::Reward", "my_game::Wave"])

    def test_enum_fields_pick_a_variant(self):
        use_game_schema()
        mode = add_component(self.obj, "CUSTOM", type_path="my_game::Patrol").fields[1]
        self.assertEqual([identifier for identifier, *_rest in addon.system.variant_items(mode, bpy.context)], ["Loop", "PingPong"])
        mode.enum_value = "PingPong"
        self.assertEqual((mode.string_value, self._data(self.obj)[0]["mode"]), ("PingPong", "PingPong"))
        with self.assertRaises(TypeError):
            mode.enum_value = "Hover"
        self.assertEqual(addon.validation.check_object(self.obj, bpy.data.objects), [])

    def test_tuple_structs_need_every_field(self):
        with tempfile.TemporaryDirectory() as folder:
            schema = Path(folder) / "bevy_components_schema.json"
            fields = [{"name": "0", "type": "float", "rust_type": "f32", "default": 1.0}, {"name": "1", "type": "other", "rust_type": "bevy_asset::handle::Handle<bevy_image::image::Image>"}]
            schema.write_text(json.dumps({"version": 1, "components": [{"type_path": "my_game::Spawn", "kind": "tuple_struct", "has_default": True, "fields": fields}]}), encoding="utf-8")
            use_game_schema(schema)
            self.addCleanup(use_game_schema, None)
            add_component(self.obj, "CUSTOM", type_path="my_game::Spawn")
            self.assertEqual([issue.message for issue in addon.validation.check_object(self.obj, bpy.data.objects)], ["Blender cannot set field 1, and a tuple struct cannot leave fields out, so the game cannot insert my_game::Spawn. Name its fields, or skip that one with #[reflect(skip_serializing)]"])

    def test_tuple_structs_export_their_values_in_order(self):
        use_game_schema()
        item = set_fields(add_component(self.obj, "CUSTOM", type_path="my_game::Reward"), **{"0": 7, "1": 1.5})
        self.assertEqual(self._data(self.obj), [[7, 1.5]])
        item.custom_type = "my_game::Loot"
        self.assertEqual((item.use_fields, json.loads(item.custom_json)), (False, [7, 1.5]))
        item.custom_type = "my_game::Reward"
        self.assertEqual((item.use_fields, self._data(self.obj)), (True, [[7, 1.5]]))

    def test_json_components_switch_to_game_fields(self):
        item = add_component(self.obj, "CUSTOM", custom_type="my_game::Patrol")
        item.custom_json = json.dumps({"speed": 4, "mode": "PingPong", "offset": [1, 2], "note": "kept"})
        reward = add_component(self.other, "CUSTOM", custom_type="my_game::Reward")
        reward.custom_json = "[3, 2.5]"
        self.assertFalse(item.use_fields or reward.use_fields)
        use_game_schema()
        self.assertTrue(item.use_fields and reward.use_fields)
        self.assertEqual(self._data(self.obj), [{"speed": 4.0, "mode": "PingPong", "offset": [1.0, 2.0], "stops": 1}])
        self.assertEqual(json.loads(item.custom_json), {"note": "kept"})
        self.assertEqual(self._data(self.other), [[3, 2.5]])

    def test_schema_changes_reach_every_object(self):
        self._schema({"type_path": "game::Mover", "has_default": True, "fields": [{"name": "speed", "type": "float", "rust_type": "f32", "default": 1.0}]})
        first = set_fields(add_component(self.obj, "CUSTOM", type_path="game::Mover"), speed=3.0)
        add_component(self.other, "CUSTOM", type_path="game::Mover")
        self._schema({"type_path": "game::Mover", "has_default": True, "fields": [{"name": "speed", "type": "int", "rust_type": "u8", "default": 2}, {"name": "team", "type": "enum", "rust_type": "game::Team", "variants": ["Red", "Blue"], "default": "Blue"}]})
        self.assertEqual([self._data(obj) for obj in (self.obj, self.other)], [[{"speed": 3, "team": "Blue"}], [{"speed": 1, "team": "Blue"}]])
        self._schema()
        self.assertTrue(first.use_fields)
        self.assertEqual(self._data(self.obj), [{"speed": 3, "team": "Blue"}])

    def test_game_types_win_over_scene_definitions(self):
        define_component("my_game::Patrol", ("speed", "FLOAT", 9.0))
        item = add_component(self.obj, "CUSTOM", type_path="my_game::Patrol")
        use_game_schema()
        self.assertEqual([field.name for field in item.fields], ["speed", "mode", "offset", "stops"])
        self.assertEqual(self._data(self.obj)[0]["speed"], 9.0)
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add.draw(menu, _menu_context(self.obj))
        self.assertNotIn("my_game::Patrol", [getattr(properties, "type_path", "") for text, properties, enabled in menu.layout.buttons()])
        select(self.obj)
        self.assertEqual(bpy.ops.bevy_components.define_fields(index=0), {"CANCELLED"})
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_context_menu.draw(menu, _menu_context(self.obj, item))
        self.assertNotIn("bevy_components.define_fields", menu.layout.operators())
        library = bpy.context.scene.bevy_component_definitions
        library.definitions[0].name = "my_game::Other"
        self.assertEqual(item.custom_type, "my_game::Patrol")
        library.definitions[0].name = "my_game::Patrol"
        self.assertEqual(bpy.ops.bevy_components.definition_remove(), {"FINISHED"})
        self.assertEqual((item.use_fields, len(item.fields)), (True, 4))

    def test_checks_follow_the_rust_types(self):
        self._schema({"type_path": "game::Spawner", "has_default": False, "fields": [{"name": "count", "type": "int", "rust_type": "u8", "default": 1}, {"name": "timer", "type": "other", "rust_type": "bevy_time::timer::Timer"}]})
        set_fields(add_component(self.obj, "CUSTOM", type_path="game::Spawner"), count=300)
        issues = addon.validation.check_object(self.obj, bpy.data.objects)
        self.assertEqual([(issue.level, issue.message) for issue in issues], [("ERROR", "count must be from 0 to 255 to fit u8"), ("WARNING", "Blender cannot set timer, so the game needs #[reflect(Default)] on game::Spawner to fill them in")])

    def test_scene_definition_enums_export_the_variant(self):
        definition = define_component("game::Door", ("side", "STRING", "Left"))
        field = definition.fields[0]
        field.variants = "Left, Right"
        field.field_type = "ENUM"
        item = add_component(self.obj, "CUSTOM", type_path="game::Door")
        self.assertEqual((item.fields[0].field_type, item.fields[0].string_value), ("ENUM", "Left"))
        self.assertEqual(addon.validation.check_object(self.obj, bpy.data.objects), [])
        self.assertEqual(_stored(self.obj)["components"], [{"type": "custom", "type_path": "game::Door", "data": {"side": "Left"}}])
        panel = FakePanel(self)
        addon.panel.BEVY_PT_scene_definitions.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props(), ["field_type", "variants", "enum_value"])

    def test_schema_is_found_above_the_saved_blend_file(self):
        root = Path(self.directory.name)
        (root / "assets").mkdir()
        add_component(self.obj, "CUSTOM", custom_type="my_game::Reward", custom_json="[3, 2.5]")
        blend = root / "assets" / "level.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
        (root / "bevy_components_schema.json").write_bytes(SCHEMA.read_bytes())
        bpy.ops.wm.open_mainfile(filepath=str(blend))
        item = bpy.data.objects["subject"].bevy_component_data.components[0]
        self.assertTrue(item.use_fields)
        self.assertEqual(_stored(bpy.data.objects["subject"])["components"][0]["data"], [3, 2.5])
        self.assertEqual(addon.system.game_schema()["path"], root / "bevy_components_schema.json")

    def test_broken_schemas_show_an_error(self):
        path = Path(self.directory.name) / "bevy_components_schema.json"
        path.write_text("{", encoding="utf-8")
        use_game_schema(path)
        self.assertTrue(addon.system.game_schema()["error"].startswith("bevy_components_schema.json cannot be read. It is not valid JSON"))
        self.assertEqual(addon.system.game_types(), {})
        panel = FakePanel(self)
        addon.panel.BEVY_PT_scene_definitions.draw(panel, bpy.context)
        self.assertTrue(" ".join(panel.layout.alerts()).startswith("bevy_components_schema.json cannot be read. It is not valid JSON"))
        preferences = bpy.context.preferences.addons[addon.__name__].preferences
        panel = SimpleNamespace(layout=FakeLayout(self), bl_rna=preferences.bl_rna, ktx_path="", schema_path=str(path), game_folder="", run_command="cargo run", viewer_folder="")
        addon.preferences.BEVY_AP_preferences.draw(panel, bpy.context)
        self.assertIn("bevy_components_schema.json cannot be read. It is not valid JSON", " ".join(panel.layout.alerts()))
        use_game_schema(path.with_name("missing.json"))
        self.assertEqual(addon.system.game_schema()["error"], "missing.json was not found")

    def test_cards_and_preferences_show_game_components(self):
        use_game_schema()
        add_component(self.obj, "CUSTOM", type_path="my_game::Patrol")
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertEqual([(bound["property"], bound["text"]) for name, bound, layout in panel.layout.calls if name == "prop" and bound["property"].endswith("_value")], [("float_value", "speed"), ("enum_value", "mode"), ("vector2_value", "offset"), ("int_value", "stops")])
        self.assertIn("Game default (Timer)", panel.layout.texts())
        preferences = bpy.context.preferences.addons[addon.__name__].preferences
        panel = SimpleNamespace(layout=FakeLayout(self), bl_rna=preferences.bl_rna, ktx_path="", schema_path=str(SCHEMA), game_folder="", run_command="cargo run", viewer_folder="")
        addon.preferences.BEVY_AP_preferences.draw(panel, bpy.context)
        self.assertIn(f"2 game components from {SCHEMA}", panel.layout.texts())
        self.assertIn("schema_path", panel.layout.props())


class TestChanges(unittest.TestCase):
    def setUp(self):
        clear_scene()

    def test_revisions_follow_real_changes_only(self):
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate")
        rock = add_mesh(bpy.ops.mesh.primitive_ico_sphere_add, "rock", location=(3, 0, 0))
        objects = (crate, rock)
        bpy.context.view_layer.update()
        seen = {obj.session_uid: addon.changes.revision(obj) for obj in objects}

        def changed():
            bpy.context.view_layer.update()
            found = sorted(obj.name for obj in objects if addon.changes.revision(obj) != seen[obj.session_uid])
            seen.update({obj.session_uid: addon.changes.revision(obj) for obj in objects})
            return found

        self.assertEqual(changed(), [])
        helper = bpy.data.objects.new("helper", None)
        bpy.context.scene.collection.objects.link(helper)
        self.assertEqual(changed(), [])
        rock.location.x = 5
        self.assertEqual(changed(), ["rock"])
        crate.name = "box"
        self.assertEqual(changed(), ["box"])
        rock.data.materials.append(bpy.data.materials.new("stone"))
        self.assertEqual(changed(), ["rock"])
        group = bpy.data.collections.new("group")
        bpy.context.scene.collection.children.link(group)
        group.objects.link(crate)
        self.assertEqual(changed(), ["box"])
        rock.parent = crate
        self.assertEqual(changed(), ["box", "rock"])
        crate.visible_shadow = False
        self.assertEqual(changed(), ["box", "rock"])
        bpy.data.objects.remove(helper)
        self.assertEqual(changed(), [])
        addon.system.touch_object(rock)
        self.assertEqual(changed(), ["box", "rock"])
        epoch = addon.changes.change_count()[0]
        addon.changes.forget_revisions()
        self.assertEqual(addon.changes.change_count()[0], epoch + 1)
        self.assertEqual(changed(), ["box", "rock"])


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

    def test_collider_offset_moves_the_preview_and_handles(self):
        self.obj.location = (1, 2, 3)
        self.obj.scale = (2, 2, 2)
        bpy.context.view_layer.update()
        collider = add_component(self.obj, "COLLIDER", collider_shape="CUBOID", collider_size=(2, 2, 2), collider_offset=(0.5, 1, -0.25))
        (matrix, _lines), = addon.overlay.collider_lines(self.obj, collider, 2000, {})
        self.assertEqual(_rounded(tuple(matrix.translation)), (2.0, 2.5, 5.0))
        self.assertEqual(_rounded(addon.gizmo._get_offset()), (1.0, 0.5, 2.0))
        addon.gizmo._set_offset((2.0, -1.0, 0.0))
        self.assertEqual(_rounded(tuple(collider.collider_offset)), (1.0, 0.0, 0.5))
        self.assertEqual(_rounded(_stored(self.obj)["components"][0]["offset"]), [1.0, 0.0, 0.5])
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Collider · Cuboid · 2 × 2 × 2 · offset 1, 0, 0.5"])
        collider.collider_shape = "TRIMESH"
        self.assertEqual(_rounded(tuple(addon.overlay.collider_lines(self.obj, collider, 2000, {})[0][0].translation)), (1.0, 2.0, 3.0))
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Collider · Trimesh · mesh edges"])

    def test_collision_only_colliders_preview_in_their_own_color(self):
        collider = add_component(self.obj, "COLLIDER", collider_shape="SPHERE", collider_collision_only=True, collider_events=True)
        select(self.obj)
        self.assertEqual({color for _matrix, _lines, color, _width in addon.overlay.preview_batches(bpy.context, self.settings)}, {addon.overlay.COLLISION_ONLY_COLOR})
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Collider · Sphere · r=0.5m · events · collision only"])
        collider.collider_sensor = True
        self.assertEqual({color for _matrix, _lines, color, _width in addon.overlay.preview_batches(bpy.context, self.settings)}, {addon.overlay.SENSOR_COLOR})

    def test_visibility_range_handles_keep_the_fades_in_order(self):
        gizmo = addon.gizmo.BEVY_GGT_range_handles
        self.assertFalse(gizmo.poll(bpy.context))
        item = add_component(self.obj, "VISIBILITY_RANGE")
        self.assertTrue(gizmo.poll(bpy.context))
        self.assertEqual([addon.gizmo._get_range(index) for index in range(4)], [0.0, 0.0, 20.0, 25.0])
        for index, value, expected in ((2, 30, [0.0, 0.0, 30.0, 30.0]), (1, (5,), [0.0, 5.0, 30.0, 30.0]), (3, 3, [0.0, 3.0, 3.0, 3.0]), (0, -2, [0.0, 3.0, 3.0, 3.0])):
            addon.gizmo._set_range(index, value)
            self.assertEqual([item.fade_in_start, item.fade_in_end, item.fade_out_start, item.fade_out_end], expected, (index, value))
        self.assertEqual(_stored(self.obj)["components"][0]["end"], [3.0, 3.0])
        for setting in ("visibility_ranges", "edit_handles", "enabled"):
            setattr(self.settings, setting, False)
            self.assertFalse(gizmo.poll(bpy.context), setting)
            setattr(self.settings, setting, True)

    def test_light_range_handle_sets_a_custom_distance(self):
        gizmo = addon.gizmo.BEVY_GGT_light_handles
        self.assertFalse(gizmo.poll(bpy.context))
        lamp = add_light("lamp", "POINT", (0, 0, 0))
        select(lamp)
        self.assertTrue(gizmo.poll(bpy.context))
        self.assertEqual(addon.gizmo._get_light_range(), 20.0)
        addon.gizmo._set_light_range((7.5,))
        self.assertEqual((lamp.data.use_custom_distance, lamp.data.cutoff_distance), (True, 7.5))
        self.assertEqual(addon.gizmo._get_light_range(), 7.5)
        self.settings.lights = False
        try:
            self.assertFalse(gizmo.poll(bpy.context))
        finally:
            self.settings.lights = True
        sun = add_light("sun", "SUN", (0, 0, 5))
        add_component(sun, "LIGHT")
        select(sun)
        self.assertFalse(gizmo.poll(bpy.context))

    def test_handle_drags_push_one_undo_step(self):
        add_component(self.obj, "COLLIDER", collider_shape="CUBOID")
        drag = SimpleNamespace(is_modal=True)
        try:
            with mock.patch.object(addon.gizmo, "push_undo") as push:
                addon.gizmo.watch_drag(drag, "Resize Collider")
                self.assertTrue(bpy.app.timers.is_registered(addon.gizmo._finish_drag))
                self.assertEqual(addon.gizmo._finish_drag(), addon.gizmo.DRAG_INTERVAL)
                addon.gizmo._set_handle_value(0, 2)
                drag.is_modal = False
                self.assertIsNone(addon.gizmo._finish_drag())
                push.assert_called_once_with("Resize Collider")
                addon.gizmo.watch_drag(drag, "Resize Collider")
                self.assertIsNone(addon.gizmo._finish_drag())
                push.assert_called_once()
                addon.gizmo.watch_drag(RemovedGizmo(), "Move Collider")
                addon.gizmo._set_offset((1.0, 0.0, 0.0))
                self.assertIsNone(addon.gizmo._finish_drag())
                push.assert_called_with("Move Collider")
        finally:
            addon.gizmo.stop_drag_tracking()
        self.assertFalse(bpy.app.timers.is_registered(addon.gizmo._finish_drag))
        addon.gizmo.push_undo("Resize Collider")

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

    def test_lightmap_labels(self):
        item = add_component(self.obj, "LIGHTMAP")
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Lightmap · not baked"])
        item.probe_file = str(LIGHTMAP)
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Lightmap · 16 × 16"])
        item.probe_file = str(CUBEMAP)
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Lightmap · file problem, see its card"])

    def test_shadow_and_audio_labels(self):
        shadows = add_component(self.obj, "SHADOWS")
        add_component(self.obj, "AUDIO_PLAYER", audio_path="sounds/ambience/wind.ogg", audio_loop=True, audio_autoplay=False, audio_spatial=False)
        labels = {(False, True): "no casting", (True, False): "no receiving", (False, False): "no casting or receiving", (True, True): "as usual"}
        for (cast, receive), label in labels.items():
            shadows.shadows_cast = cast
            shadows.shadows_receive = receive
            self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), [f"Shadows · {label}", "Audio · wind.ogg · loop · paused · same volume everywhere"])

    def test_navigation_previews_walkable_faces_and_obstacle_bounds(self):
        walkable = addon.overlay.NAVIGATION_COLORS["WALKABLE"]
        obstacle = addon.overlay.NAVIGATION_COLORS["OBSTACLE"]
        navigation = add_component(self.obj, "NAVIGATION", navigation_cost=3)
        select(self.obj)
        batches = addon.overlay.preview_batches(bpy.context, self.settings)
        self.assertEqual([(color, len(lines)) for matrix, lines, color, width in batches], [(walkable, 4)])
        self.assertEqual({round(point[2], 4) for line in batches[0][1] for point in line}, {1.0})
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Navigation · Walkable · cost 3"])
        self.obj.rotation_euler = (math.pi, 0, 0)
        bpy.context.view_layer.update()
        self.assertEqual({round(point[2], 4) for line in addon.overlay.preview_batches(bpy.context, self.settings)[0][1] for point in line}, {-1.0})
        self.obj.rotation_euler = (math.radians(50), 0, 0)
        bpy.context.view_layer.update()
        self.assertEqual({round(point[1], 4) for line in addon.overlay.preview_batches(bpy.context, self.settings)[0][1] for point in line}, {1.0})
        navigation.navigation_kind = "OBSTACLE"
        batches = addon.overlay.preview_batches(bpy.context, self.settings)
        self.assertEqual([(color, len(lines)) for matrix, lines, color, width in batches], [(obstacle, 12)])
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Navigation · Obstacle"])
        navigation.navigation_kind = "IGNORED"
        self.assertEqual(addon.overlay.preview_batches(bpy.context, self.settings), [])
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), ["Navigation · Ignored"])
        navigation.navigation_kind = "WALKABLE"
        self.settings.navigation = False
        self.assertEqual(addon.overlay.preview_batches(bpy.context, self.settings), [])
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings, {}), [])
        self.settings.navigation = True

    def test_navigation_previews_child_meshes_and_big_meshes(self):
        group = add_empty("group", (0, 0, 0))
        navigation = add_component(group, "NAVIGATION")
        terrain = add_mesh(bpy.ops.mesh.primitive_grid_add, "terrain", x_subdivisions=10, y_subdivisions=10, size=4)
        prop = add_mesh(bpy.ops.mesh.primitive_cube_add, "prop", location=(3, 0, 0))
        add_component(prop, "NAVIGATION", navigation_kind="IGNORED")
        for obj in (terrain, prop):
            obj.parent = group
        bpy.context.view_layer.update()
        select(group)
        batches = addon.overlay.preview_batches(bpy.context, self.settings)
        self.assertEqual([(tuple(matrix.translation), len(lines)) for matrix, lines, color, width in batches], [((0.0, 0.0, 0.0), len(terrain.data.edges))])
        self.settings.max_mesh_edges = 64
        self.assertEqual(len(addon.overlay.preview_batches(bpy.context, self.settings)[0][1]), 12)
        self.settings.max_mesh_edges = 2000
        navigation.navigation_kind = "OBSTACLE"
        self.assertEqual(len(addon.overlay.preview_batches(bpy.context, self.settings)[0][1]), 12)

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

    def test_mesh_previews_follow_apply_modifiers(self):
        collider = add_component(self.obj, "COLLIDER", collider_shape="TRIMESH")
        self.obj.modifiers.new("Array", "ARRAY").count = 3
        settings = addon.system.export_settings(bpy.context.scene)
        self.assertEqual(len(_collider_lines(self.obj, collider, 2000)), 36)
        self.assertEqual(_extents(_collider_lines(self.obj, collider, 2000)), (5.0, 1.0, 1.0))
        self.assertTrue(addon.overlay.exceeds_edge_limit(self.obj, 20))
        settings.apply_modifiers = False
        try:
            self.assertEqual(len(_collider_lines(self.obj, collider, 2000)), 12)
            self.assertFalse(addon.overlay.exceeds_edge_limit(self.obj, 20))
        finally:
            settings.apply_modifiers = True

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

    def test_preview_cache_reuses_batches_until_something_changes(self):
        collider = add_component(self.obj, "COLLIDER", collider_shape="CUBOID")
        select(self.obj)
        first = addon.overlay.preview_entries(bpy.context, self.settings)[0]
        self.assertIs(addon.overlay.preview_entries(bpy.context, self.settings)[0], first)
        collider.collider_size = (2, 2, 2)
        resized = addon.overlay.preview_entries(bpy.context, self.settings)[0]
        self.assertIsNot(resized, first)
        self.assertEqual(_extents(resized["batches"][0][1]), (1.0, 1.0, 1.0))
        self.obj.location = (3, 0, 0)
        bpy.context.view_layer.update()
        moved = addon.overlay.preview_entries(bpy.context, self.settings)[0]
        self.assertIsNot(moved, resized)
        self.assertEqual(tuple(moved["batches"][0][0].translation), (3.0, 0.0, 0.0))
        self.settings.colliders = False
        try:
            self.assertEqual(addon.overlay.preview_entries(bpy.context, self.settings)[0]["batches"], [])
        finally:
            self.settings.colliders = True
        self.assertEqual(len(addon.overlay.preview_entries(bpy.context, self.settings)[0]["batches"]), 1)

    def test_preview_cache_follows_meshes_and_lights(self):
        add_component(self.obj, "COLLIDER", collider_shape="CONVEX")
        lamp = add_light("lamp", "POINT", (4, 0, 0))
        add_component(lamp, "LIGHT")
        select(self.obj, lamp)
        first = addon.overlay.preview_entries(bpy.context, self.settings)
        self.assertEqual([entry is again for entry, again in zip(first, addon.overlay.preview_entries(bpy.context, self.settings))], [True, True])
        self.obj.data.vertices[0].co *= 3
        lamp.data.use_custom_distance = True
        lamp.data.cutoff_distance = 6
        bpy.context.view_layer.update()
        second = addon.overlay.preview_entries(bpy.context, self.settings)
        self.assertEqual([entry is again for entry, again in zip(first, second)], [False, False])
        self.assertEqual(_extents(second[1]["batches"][0][1]), (6.0, 6.0, 6.0))

    def test_preview_cache_keeps_objects_that_did_not_change(self):
        add_component(self.obj, "COLLIDER", collider_shape="CUBOID")
        other = add_mesh(bpy.ops.mesh.primitive_cube_add, "other", location=(4, 0, 0))
        add_component(other, "COLLIDER", collider_shape="SPHERE")
        other.keyframe_insert("location", frame=1)
        other.location = (4, 0, 6)
        other.keyframe_insert("location", frame=11)
        bpy.context.scene.frame_set(1)
        select(self.obj, other)
        bpy.context.view_layer.update()
        entry = lambda obj: addon.overlay.PREVIEW_CACHE[("OBJECT", obj.session_uid)]
        addon.overlay.preview_entries(bpy.context, self.settings)
        first, moving = entry(self.obj), entry(other)
        try:
            bpy.context.scene.frame_set(6)
            addon.overlay.preview_entries(bpy.context, self.settings)
            self.assertIs(entry(self.obj), first)
            self.assertIsNot(entry(other), moving)
            self.assertEqual(round(entry(other)["batches"][0][0].translation.z, 4), 3.0)
            other.location = (4, 0, 0)
            other.animation_data_clear()
            bpy.context.view_layer.update()
            addon.overlay.preview_entries(bpy.context, self.settings)
            self.assertEqual(round(entry(other)["batches"][0][0].translation.z, 4), 0.0)
        finally:
            bpy.context.scene.frame_set(1)

    def test_preview_cache_starts_over_after_undo(self):
        add_component(self.obj, "COLLIDER", collider_shape="CUBOID")
        select(self.obj)
        first = addon.overlay.preview_entries(bpy.context, self.settings)[0]
        self.assertIs(addon.overlay.preview_entries(bpy.context, self.settings)[0], first)
        addon.changes.forget_revisions()
        again = addon.overlay.preview_entries(bpy.context, self.settings)[0]
        self.assertIsNot(again, first)
        self.assertEqual(len(again["batches"]), 1)

    def test_preview_cache_follows_navigation_meshes(self):
        navigation = add_component(self.obj, "NAVIGATION")
        select(self.obj)
        first = addon.overlay.preview_entries(bpy.context, self.settings)[0]
        self.assertTrue(first["batches"])
        self.assertIs(addon.overlay.preview_entries(bpy.context, self.settings)[0], first)
        next(vertex for vertex in self.obj.data.vertices if vertex.co.z > 0).co.z += 1
        self.obj.data.update()
        bpy.context.view_layer.update()
        edited = addon.overlay.preview_entries(bpy.context, self.settings)[0]
        self.assertIsNot(edited, first)
        navigation.navigation_kind = "OBSTACLE"
        obstacle = addon.overlay.preview_entries(bpy.context, self.settings)[0]
        self.assertIsNot(obstacle, edited)
        self.assertIs(addon.overlay.preview_entries(bpy.context, self.settings)[0], obstacle)

    def test_joint_preview_cache_follows_the_bodies(self):
        frame = add_mesh(bpy.ops.mesh.primitive_cube_add, "frame", size=0.2)
        add_component(frame, "COLLIDER")
        hinge = add_empty("hinge", (0.5, 0, 0))
        joint = add_component(hinge, "JOINT")
        joint.joint_body1 = frame
        select(hinge)
        first = addon.overlay.preview_entries(bpy.context, self.settings)[-1]
        self.assertIs(addon.overlay.preview_entries(bpy.context, self.settings)[-1], first)
        frame.location = (0, 2, 0)
        bpy.context.view_layer.update()
        moved = addon.overlay.preview_entries(bpy.context, self.settings)[-1]
        self.assertIsNot(moved, first)
        self.assertEqual(moved["batches"][-1][1], [((0.5, 0.0, 0.0), (0.0, 2.0, 0.0))])

    def test_labels_show_details_only_for_selected_objects(self):
        add_component(self.obj, "CUSTOM", type_path="my_game::enemies::Enemy")
        add_component(self.obj, "COLLIDER", collider_shape="SPHERE")
        other = add_mesh(bpy.ops.mesh.primitive_cube_add, "other", location=(5, 0, 0))
        add_component(other, "COLLIDER", collider_shape="CUBOID")
        add_component(other, "CUSTOM", type_path="my_game::Health")
        plain = add_mesh(bpy.ops.mesh.primitive_cube_add, "plain", location=(9, 0, 0))
        add_component(plain, "COLLIDER")
        self.settings.scope = "ALL"
        select(other)
        rows = addon.overlay.label_rows(bpy.context, self.settings)
        self.assertEqual([(obj.name, lines, details) for obj, lines, details in rows], [("other", ["other", "Health", "Collider · Cuboid · 1 × 1 × 1"], True), ("subject", ["subject · Enemy"], False), ("plain", ["plain"], False)])
        self.settings.scope = "SELECTED"
        select(self.obj)
        self.assertEqual([(obj.name, lines, details) for obj, lines, details in addon.overlay.label_rows(bpy.context, self.settings)], [("subject", ["subject", "Enemy", "Collider · Sphere · r=0.5m"], True)])

    def test_label_boxes_overlap(self):
        self.assertTrue(addon.overlay._overlaps((0, 0, 10, 10), (5, 5, 15, 15)))
        self.assertTrue(addon.overlay._overlaps((0, 0, 10, 10), (2, 2, 4, 4)))
        self.assertFalse(addon.overlay._overlaps((0, 0, 10, 10), (10, 0, 20, 10)))
        self.assertFalse(addon.overlay._overlaps((0, 0, 10, 10), (0, 11, 10, 20)))

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
                    entries = addon.overlay.preview_entries(bpy.context, self.settings)
                    addon.overlay.draw_entries(shader, entries)
                    drawables = [entry["drawables"] for entry in entries]
                    addon.overlay.draw_entries(shader, addon.overlay.preview_entries(bpy.context, self.settings))
                    self.assertEqual([entry["drawables"] for entry in addon.overlay.preview_entries(bpy.context, self.settings)], drawables)
                pixels = framebuffer.read_color(0, 0, 64, 64, 4, 0, "FLOAT")
        finally:
            offscreen.free()
        pixels.dimensions = 64 * 64 * 4
        self.assertTrue(any(value > 0.1 for value in pixels.to_list()[1::4]))


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        clear_scene()
        for text in list(bpy.data.texts):
            bpy.data.texts.remove(text)
        bpy.context.view_layer.update()
        self.obj = add_mesh(bpy.ops.mesh.primitive_cube_add, "subject")

    def tearDown(self):
        for text in list(bpy.data.texts):
            bpy.data.texts.remove(text)

    def test_copy_and_paste_components_between_files(self):
        define_component("my_game::Health", ("amount", "INT", 3), ("armor", "FLOAT", 0.5))
        add_component(self.obj, "COLLIDER", collider_shape="SPHERE", collider_radius=2, collider_friction=0.9)
        set_fields(add_component(self.obj, "CUSTOM", type_path="my_game::Health"), amount=7)
        add_component(self.obj, "RIGID_BODY", rigid_body_kind="DYNAMIC", rigid_body_lock_rotation=(True, False, False))
        clipboard = SimpleNamespace(clipboard="")
        self.assertEqual(_execute(addon.operator.BEVY_OT_copy_components, _clipboard_context(self.obj, self.obj, clipboard=clipboard)), ({"FINISHED"}, [({"INFO"}, "Copied 3 components")]))
        self.assertEqual(json.loads(clipboard.clipboard)["type"], "bevy_components")
        expected = _stored(self.obj)["components"]
        clear_scene()
        target = add_mesh(bpy.ops.mesh.primitive_cube_add, "target")
        add_component(target, "COLLIDER", collider_shape="CUBOID")
        add_component(target, "VISIBILITY_RANGE")
        other = add_mesh(bpy.ops.mesh.primitive_cube_add, "other")
        result = _execute(addon.operator.BEVY_OT_paste_components, _clipboard_context(target, target, other, clipboard=clipboard))
        self.assertEqual(result, ({"FINISHED"}, [({"INFO"}, "Added 3 components from the clipboard to 2 objects")]))
        for obj in (target, other):
            self.assertEqual([component for component in _stored(obj)["components"] if component["type"] != "visibility_range"], expected, obj.name)
        self.assertEqual([item.component_type for item in target.bevy_component_data.components], ["COLLIDER", "VISIBILITY_RANGE", "CUSTOM", "RIGID_BODY"])
        health = target.bevy_component_data.components[2]
        self.assertTrue(health.use_fields)
        self.assertEqual([(field.name, field.field_type) for field in health.fields], [("amount", "INT"), ("armor", "FLOAT")])
        definition = define_component("my_game::Health", ("amount", "INT", 1), ("armor", "FLOAT", 0.0))
        fresh = add_mesh(bpy.ops.mesh.primitive_cube_add, "fresh")
        _execute(addon.operator.BEVY_OT_paste_components, _clipboard_context(fresh, fresh, clipboard=clipboard))
        pasted = fresh.bevy_component_data.components[1]
        self.assertEqual([field.identifier for field in pasted.fields], [field.identifier for field in definition.fields])
        self.assertEqual(_stored(fresh)["components"], expected)

    def test_pasting_keeps_collision_events(self):
        add_component(self.obj, "COLLIDER", collider_shape="SPHERE", collider_sensor=True, collider_events=False)
        clipboard = SimpleNamespace(clipboard="")
        _execute(addon.operator.BEVY_OT_copy_components, _clipboard_context(self.obj, self.obj, clipboard=clipboard))
        door = add_mesh(bpy.ops.mesh.primitive_cube_add, "door")
        _execute(addon.operator.BEVY_OT_paste_components, _clipboard_context(door, door, clipboard=clipboard))
        pasted = door.bevy_component_data.components[0]
        self.assertEqual((pasted.collider_sensor, pasted.collider_events), (True, False))
        self.assertEqual(_stored(door)["components"], _stored(self.obj)["components"])

    def test_pasting_skips_components_that_do_not_fit(self):
        lamp = add_light("lamp", "POINT", (0, 0, 0))
        add_component(lamp, "LIGHT")
        clipboard = SimpleNamespace(clipboard="")
        _execute(addon.operator.BEVY_OT_copy_component, _clipboard_context(lamp, lamp, clipboard=clipboard), index=0)
        self.assertEqual(_execute(addon.operator.BEVY_OT_paste_components, _clipboard_context(self.obj, self.obj, clipboard=clipboard)), ({"CANCELLED"}, [({"WARNING"}, "None of the components in the clipboard fit the selected objects")]))
        self.assertEqual(len(self.obj.bevy_component_data.components), 0)
        clipboard.clipboard = "not components"
        self.assertEqual(_execute(addon.operator.BEVY_OT_paste_components, _clipboard_context(self.obj, self.obj, clipboard=clipboard)), ({"CANCELLED"}, [({"WARNING"}, "The clipboard holds no Bevy components. Copy some with Copy Components first")]))

    def test_pasted_joints_keep_their_bodies(self):
        frame = add_mesh(bpy.ops.mesh.primitive_cube_add, "frame")
        joint = add_component(self.obj, "JOINT", joint_kind="SPHERICAL")
        joint.joint_body1 = frame
        joint.joint_body2 = self.obj
        clipboard = SimpleNamespace(clipboard="")
        self.assertEqual(_execute(addon.operator.BEVY_OT_copy_component, _clipboard_context(self.obj, self.obj, clipboard=clipboard), index=0), ({"FINISHED"}, [({"INFO"}, "Copied Joint")]))
        door = add_mesh(bpy.ops.mesh.primitive_cube_add, "door")
        _execute(addon.operator.BEVY_OT_paste_components, _clipboard_context(door, door, clipboard=clipboard))
        pasted = door.bevy_component_data.components[0]
        self.assertEqual((pasted.joint_kind, pasted.joint_body1, pasted.joint_body2), ("SPHERICAL", frame, door))
        bpy.data.objects.remove(frame)
        hatch = add_mesh(bpy.ops.mesh.primitive_cube_add, "hatch")
        _execute(addon.operator.BEVY_OT_paste_components, _clipboard_context(hatch, hatch, clipboard=clipboard))
        self.assertEqual((hatch.bevy_component_data.components[0].joint_body1, hatch.bevy_component_data.components[0].joint_body2), (None, hatch))

    def test_presets_save_apply_and_remove(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(addon.system, "preset_folder", lambda create=False: Path(folder)), mock.patch.object(addon.menu, "preset_folder", lambda create=False: Path(folder)):
            menu = FakePanel(self)
            addon.menu.BEVY_MT_component_add_presets.draw(menu, bpy.context)
            self.assertEqual(menu.layout.texts(), ["", "No presets yet", "", "Save Components as Preset..."])
            frame = add_mesh(bpy.ops.mesh.primitive_cube_add, "frame")
            add_component(self.obj, "COLLIDER", collider_shape="CAPSULE", collider_radius=0.25)
            add_component(self.obj, "JOINT").joint_body1 = frame
            select(self.obj)
            self.assertEqual(bpy.ops.bevy_components.save_preset(name="Crate Kit"), {"FINISHED"})
            path = Path(folder) / "crate_kit.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual((data["name"], [component["component_type"] for component in data["components"]]), ("Crate Kit", ["COLLIDER", "JOINT"]))
            self.assertIsNone(data["components"][1].get("joint_body1"))
            self.assertEqual(addon.system.presets(), [("Crate Kit", path)])
            menu = FakePanel(self)
            addon.menu.BEVY_MT_component_add_presets.draw(menu, bpy.context)
            buttons = menu.layout.buttons()
            self.assertEqual([text for text, properties, enabled in buttons], ["Crate Kit", "Save Components as Preset...", "Open Presets Folder"])
            self.assertEqual(buttons[0][1].filepath, str(path))
            self.assertEqual(menu.layout.menus(), ["BEVY_MT_component_remove_presets"])
            crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate")
            add_component(crate, "COLLIDER")
            self.assertEqual(bpy.ops.bevy_components.apply_preset(filepath=str(path)), {"FINISHED"})
            self.assertEqual([item.component_type for item in crate.bevy_component_data.components], ["COLLIDER", "JOINT"])
            self.assertEqual((crate.bevy_component_data.components[0].collider_shape, crate.bevy_component_data.components[0].collider_radius), ("CAPSULE", 0.25))
            self.assertIsNone(crate.bevy_component_data.components[1].joint_body1)
            stray = Path(folder) / "notes.json"
            stray.write_text("{}", encoding="utf-8")
            self.assertEqual(addon.system.presets(), [("Crate Kit", path)])
            with self.assertRaisesRegex(RuntimeError, "notes.json is not a Bevy Components preset"):
                bpy.ops.bevy_components.apply_preset(filepath=str(stray))
            self.assertEqual(bpy.ops.bevy_components.remove_preset(filepath=str(path)), {"FINISHED"})
            self.assertFalse(path.exists())
            self.assertEqual(addon.system.presets(), [])

    def test_copy_paste_and_presets_carry_blender_settings(self):
        crate = self.obj
        _rigid_body(crate, shape="BOX")
        crate.rigid_body.mass = 4.0
        crate.rigid_body.friction = 0.9
        crate.bevy_physics.gravity_scale = 0.5
        crate.bevy_physics.sensor = True
        crate.bevy_physics.events = False
        crate.visible_shadow = False
        add_component(crate, "CUSTOM", type_path="my_game::Crate", custom_json="{}")
        expected = _native(crate)
        clipboard = SimpleNamespace(clipboard="")
        self.assertEqual(_execute(addon.operator.BEVY_OT_copy_components, _clipboard_context(crate, crate, clipboard=clipboard)), ({"FINISHED"}, [({"INFO"}, "Copied 3 components")]))
        self.assertEqual(sorted(json.loads(clipboard.clipboard)["blender"]), ["bevy_physics", "rigid_body", "shadows"])
        target = add_mesh(bpy.ops.mesh.primitive_cube_add, "target", location=(3, 0, 0))
        _rigid_body(target, "PASSIVE", "SPHERE")
        target.bevy_physics.ccd = "ALL"
        marker = add_empty("marker", (6, 0, 0))
        result = _execute(addon.operator.BEVY_OT_paste_components, _clipboard_context(target, target, marker, clipboard=clipboard))
        self.assertEqual(result, ({"FINISHED"}, [({"INFO"}, "Added 3 components from the clipboard to 2 objects")]))
        self.assertEqual((target.rigid_body.type, target.rigid_body.collision_shape, target.rigid_body.mass), ("ACTIVE", "BOX", 4.0))
        self.assertEqual((target.bevy_physics.ccd, target.bevy_physics.sensor, target.bevy_physics.events), ("DEFAULT", True, False))
        self.assertFalse(target.visible_shadow)
        self.assertEqual(_native(target), expected)
        self.assertIsNone(marker.rigid_body)
        self.assertEqual(_stored(marker)["components"], [{"type": "custom", "type_path": "my_game::Crate", "data": {}}])
        rocks = [add_mesh(bpy.ops.mesh.primitive_cube_add, f"rock_{index}", location=(index * 3, 4, 0)) for index in range(2)]
        context = SimpleNamespace(object=crate, selected_objects=[crate, *rocks], mode="OBJECT")
        self.assertTrue(addon.operator.BEVY_OT_copy_physics.poll(context))
        self.assertEqual(_execute(addon.operator.BEVY_OT_copy_physics, context), ({"FINISHED"}, [({"INFO"}, "Copied subject's Rigid Body to 2 objects")]))
        for rock in rocks:
            self.assertEqual((rock.rigid_body.mass, rock.bevy_physics.gravity_scale, rock.bevy_physics.sensor), (4.0, 0.5, True))
            self.assertTrue(rock.visible_shadow)
            self.assertEqual(len(rock.bevy_component_data.components), 0)
        frame = add_mesh(bpy.ops.mesh.primitive_cube_add, "frame", location=(0, 8, 0))
        _rigid_body(frame, "PASSIVE", "BOX")
        hinge = add_empty("hinge", (0, 10, 0))
        constraint = _constraint(hinge, "HINGE", frame, hinge)
        constraint.use_limit_ang_z = True
        hinge.bevy_physics.joint_angular_damping = 2.0
        door = add_empty("door", (0, 12, 0))
        select(hinge, door)
        bpy.context.view_layer.objects.active = hinge
        self.assertEqual(bpy.ops.bevy_components.copy_to_selected(), {"FINISHED"})
        self.assertEqual((door.rigid_body_constraint.type, door.rigid_body_constraint.object1, door.rigid_body_constraint.object2, door.rigid_body_constraint.use_limit_ang_z), ("HINGE", frame, door, True))
        self.assertEqual(door.bevy_physics.joint_angular_damping, 2.0)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(addon.system, "preset_folder", lambda create=False: Path(folder)):
            select(hinge)
            self.assertEqual(bpy.ops.bevy_components.save_preset(name="Hinge"), {"FINISHED"})
            data = json.loads((Path(folder) / "hinge.json").read_text(encoding="utf-8"))
            self.assertEqual((data["components"], data["blender"]["rigid_body_constraint"]["object1"]), ([], None))
            gate = add_empty("gate", (0, 14, 0))
            select(gate)
            self.assertEqual(bpy.ops.bevy_components.apply_preset(filepath=str(Path(folder) / "hinge.json")), {"FINISHED"})
            self.assertEqual((gate.rigid_body_constraint.type, gate.rigid_body_constraint.object1, gate.bevy_physics.joint_angular_damping), ("HINGE", None, 2.0))

    def test_copy_and_paste_carry_light_settings(self):
        lamp = add_light("lamp", "POINT", (0, 0, 3))
        lamp.data.bevy_light.light_volumetric = True
        clipboard = SimpleNamespace(clipboard="")
        self.assertEqual(_execute(addon.operator.BEVY_OT_copy_components, _clipboard_context(lamp, lamp, clipboard=clipboard)), ({"FINISHED"}, [({"INFO"}, "Copied 1 component")]))
        other = add_light("other", "SPOT", (4, 0, 3))
        twin = bpy.data.objects.new("twin", other.data)
        bpy.context.scene.collection.objects.link(twin)
        self.assertEqual(_execute(addon.operator.BEVY_OT_paste_components, _clipboard_context(other, other, clipboard=clipboard)), ({"FINISHED"}, [({"INFO"}, "Added 1 component from the clipboard to 1 object")]))
        self.assertTrue(other.data.bevy_light.light_volumetric)
        self.assertTrue(_by_type(_stored(twin)["components"])["light"]["volumetric"])
        self.assertEqual(_execute(addon.operator.BEVY_OT_paste_components, _clipboard_context(self.obj, self.obj, clipboard=clipboard)), ({"CANCELLED"}, [({"WARNING"}, "None of the components in the clipboard fit the selected objects")]))

    def test_preset_names_become_snake_case_files(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(addon.system, "preset_folder", lambda create=False: Path(folder)):
            self.assertEqual(addon.system.preset_file("  Enemy Spawner 2 ").name, "enemy_spawner_2.json")
            self.assertEqual(addon.system.preset_file("???").name, "preset.json")

    def test_edit_custom_component_as_text(self):
        custom = add_component(self.obj, "CUSTOM", type_path="my_game::Tag", custom_json='{"speed": 2}')
        self.assertEqual(bpy.ops.bevy_components.edit_as_text(index=0), {"FINISHED"})
        text = bpy.data.texts["subject Tag.json"]
        self.assertEqual(text.as_string(), '{\n  "speed": 2\n}\n')
        self.assertEqual(text["bevy_object"], self.obj)
        self.assertEqual(text["bevy_component"], custom.text_link)
        context = SimpleNamespace(space_data=SimpleNamespace(text=text))
        self.assertTrue(addon.operator.BEVY_OT_apply_text.poll(context))
        text.from_string('{"speed": 5, "name": "fast"}')
        self.assertEqual(_execute(addon.operator.BEVY_OT_apply_text, context), ({"FINISHED"}, [({"INFO"}, "Applied subject Tag.json to subject")]))
        self.assertEqual(json.loads(custom.custom_json), {"speed": 5, "name": "fast"})
        self.assertEqual(_stored(self.obj)["components"][0]["data"], {"speed": 5, "name": "fast"})
        text.from_string('{"speed": }')
        self.assertEqual(_execute(addon.operator.BEVY_OT_apply_text, context), ({"CANCELLED"}, [({"ERROR"}, "Cannot apply subject Tag.json: Line 1, column 11: Expecting value")]))
        self.assertEqual(bpy.ops.bevy_components.edit_as_text(index=0), {"FINISHED"})
        self.assertEqual(len(bpy.data.texts), 1)
        self.assertEqual(json.loads(text.as_string()), {"speed": 5, "name": "fast"})
        self.assertEqual(bpy.ops.bevy_components.duplicate(index=0), {"FINISHED"})
        self.assertEqual(self.obj.bevy_component_data.components[1].text_link, "")
        bpy.ops.bevy_components.remove(index=0)
        self.assertEqual(_execute(addon.operator.BEVY_OT_apply_text, context), ({"CANCELLED"}, [({"ERROR"}, "The component subject Tag.json was opened from is gone")]))
        self.assertFalse(addon.operator.BEVY_OT_apply_text.poll(SimpleNamespace(space_data=SimpleNamespace(text=bpy.data.texts.new("notes")))))
        self.assertFalse(addon.operator.BEVY_OT_apply_text.poll(SimpleNamespace(space_data=None)))

    def test_edit_typed_component_as_text(self):
        define_component("my_game::Health", ("amount", "INT", 3), ("label", "STRING", "hp"))
        health = add_component(self.obj, "CUSTOM", type_path="my_game::Health")
        bpy.ops.bevy_components.edit_as_text(index=0)
        text = bpy.data.texts["subject Health.json"]
        self.assertEqual(json.loads(text.as_string()), {"amount": 3, "label": "hp"})
        context = SimpleNamespace(space_data=SimpleNamespace(text=text))
        text.from_string('{"amount": 9}')
        self.assertEqual(_execute(addon.operator.BEVY_OT_apply_text, context)[0], {"FINISHED"})
        self.assertEqual([(field.name, field.int_value, field.string_value) for field in health.fields], [("amount", 9, ""), ("label", 0, "hp")])
        self.assertEqual(_stored(self.obj)["components"][0]["data"], {"amount": 9, "label": "hp"})
        text.from_string('{"amount": 4, "boss": true, "speed": 2}')
        self.assertEqual(_execute(addon.operator.BEVY_OT_apply_text, context)[1], [({"ERROR"}, "Cannot apply subject Health.json: boss, speed are not fields of my_game::Health. Its fields are set in Properties > Scene > Bevy Custom Components")])
        text.from_string('{"amount": "lots"}')
        self.assertEqual(_execute(addon.operator.BEVY_OT_apply_text, context)[1], [({"ERROR"}, "Cannot apply subject Health.json: amount needs a value of type Integer")])
        text.from_string("[1, 2]")
        self.assertEqual(_execute(addon.operator.BEVY_OT_apply_text, context)[1], [({"ERROR"}, "Cannot apply subject Health.json: my_game::Health has fields, so its data must be a JSON object")])
        self.assertEqual(health.fields[0].int_value, 9)

    def test_edit_game_component_as_text(self):
        use_game_schema()
        self.addCleanup(use_game_schema, None)
        patrol = add_component(self.obj, "CUSTOM", type_path="my_game::Patrol")
        add_component(self.obj, "CUSTOM", type_path="my_game::Reward")
        bpy.ops.bevy_components.edit_as_text(index=0)
        bpy.ops.bevy_components.edit_as_text(index=1)
        text = bpy.data.texts["subject Patrol.json"]
        self.assertEqual(json.loads(text.as_string()), {"speed": 2.0, "mode": "Loop", "offset": [0.0, 0.0], "stops": 1})
        context = SimpleNamespace(space_data=SimpleNamespace(text=text))
        text.from_string('{"mode": "PingPong", "offset": [1, 2]}')
        self.assertEqual(_execute(addon.operator.BEVY_OT_apply_text, context)[0], {"FINISHED"})
        self.assertEqual(_stored(self.obj)["components"][0]["data"], {"speed": 2.0, "mode": "PingPong", "offset": [1.0, 2.0], "stops": 1})
        text.from_string('{"mode": "Hover"}')
        self.assertEqual(_execute(addon.operator.BEVY_OT_apply_text, context)[1], [({"ERROR"}, "Cannot apply subject Patrol.json: mode needs one of Loop, PingPong")])
        text.from_string('{"timer": 3}')
        self.assertEqual(_execute(addon.operator.BEVY_OT_apply_text, context)[1], [({"ERROR"}, "Cannot apply subject Patrol.json: timer is not a field of my_game::Patrol. Its fields are set in your game's schema")])
        self.assertEqual(patrol.fields[1].string_value, "PingPong")
        text = bpy.data.texts["subject Reward.json"]
        text.from_string("[7, 1.5]")
        self.assertEqual(_execute(addon.operator.BEVY_OT_apply_text, SimpleNamespace(space_data=SimpleNamespace(text=text)))[0], {"FINISHED"})
        self.assertEqual(_stored(self.obj)["components"][1]["data"], [7, 1.5])
        clipboard = SimpleNamespace(clipboard="")
        _execute(addon.operator.BEVY_OT_copy_components, _clipboard_context(self.obj, self.obj, clipboard=clipboard))
        copy = add_mesh(bpy.ops.mesh.primitive_cube_add, "copy")
        _execute(addon.operator.BEVY_OT_paste_components, _clipboard_context(copy, copy, clipboard=clipboard))
        self.assertEqual(_stored(copy)["components"], _stored(self.obj)["components"])

    def test_text_editor_header_applies_linked_texts(self):
        add_component(self.obj, "CUSTOM", type_path="my_game::Tag")
        bpy.ops.bevy_components.edit_as_text(index=0)
        header = FakePanel(self)
        addon.menu.text_header(header, SimpleNamespace(space_data=SimpleNamespace(text=bpy.data.texts["subject Tag.json"])))
        self.assertEqual(header.layout.operators(), ["bevy_components.apply_text"])
        header = FakePanel(self)
        addon.menu.text_header(header, SimpleNamespace(space_data=SimpleNamespace(text=bpy.data.texts.new("notes"))))
        self.assertEqual(header.layout.operators(), [])

    def test_select_by_component(self):
        add_component(self.obj, "COLLIDER")
        enemy = add_mesh(bpy.ops.mesh.primitive_cube_add, "enemy")
        add_component(enemy, "CUSTOM", type_path="my_game::Enemy")
        hidden = add_mesh(bpy.ops.mesh.primitive_cube_add, "hidden")
        add_component(hidden, "COLLIDER")
        hidden.hide_set(True)
        plain = add_mesh(bpy.ops.mesh.primitive_cube_add, "plain")
        select(plain)
        self.assertEqual(bpy.ops.bevy_components.select_by_component(component_type="COLLIDER"), {"FINISHED"})
        self.assertEqual((bpy.context.selected_objects, bpy.context.object), ([self.obj], self.obj))
        self.assertEqual(bpy.ops.bevy_components.select_by_component(component_type="CUSTOM", type_path="my_game::Enemy", extend=True), {"FINISHED"})
        self.assertEqual({obj.name for obj in bpy.context.selected_objects}, {"subject", "enemy"})
        self.assertEqual(bpy.ops.bevy_components.select_by_component(component_type="CUSTOM", type_path="my_game::Boss"), {"CANCELLED"})
        select(plain)
        self.assertEqual(bpy.ops.bevy_components.select_by_component(component_type="ALL"), {"FINISHED"})
        self.assertEqual({obj.name for obj in bpy.context.selected_objects}, {"subject", "enemy"})
        menu = FakePanel(self)
        addon.menu.BEVY_MT_select_by_component.draw(menu, bpy.context)
        buttons = menu.layout.buttons()
        self.assertEqual([text for text, properties, enabled in buttons], ["Any Component", "Collider", "Custom Component", "my_game::Enemy"])
        self.assertEqual([(properties.component_type, getattr(properties, "type_path", "")) for text, properties, enabled in buttons], [("ALL", ""), ("COLLIDER", ""), ("CUSTOM", ""), ("CUSTOM", "my_game::Enemy")])
        clear_scene()
        bpy.context.view_layer.update()
        menu = FakePanel(self)
        addon.menu.BEVY_MT_select_by_component.draw(menu, bpy.context)
        self.assertEqual(menu.layout.texts(), ["", "No objects with Bevy components"])

    def test_viewport_object_menu(self):
        add_component(self.obj, "COLLIDER")
        menu = FakePanel(self)
        with _remembered_exports():
            addon.menu.BEVY_MT_object_menu.draw(menu, _menu_context(self.obj))
        self.assertEqual(menu.layout.menus(), ["BEVY_MT_component_add"])
        self.assertEqual([(text, enabled) for text, properties, enabled in menu.layout.buttons()], [("Copy All to Selected", True), ("Copy Components", True), ("Paste Components", True), ("Validate All Objects", True), ("Convert Components to Blender", True), ("Export Again", False)])
        menu = FakePanel(self)
        with _remembered_exports(glb="//level.glb"):
            addon.menu.BEVY_MT_object_menu.draw(menu, _menu_context(self.obj))
        self.assertEqual(_again_buttons(menu.layout)[-1], ("Export Again (level.glb)", True))
        for draw, expected in ((addon.menu.object_menu, "BEVY_MT_object_menu"), (addon.menu.select_menu, "BEVY_MT_select_by_component")):
            menu = FakePanel(self)
            draw(menu, bpy.context)
            self.assertEqual(menu.layout.menus(), [expected])

    def test_scene_overview_lists_objects_with_components(self):
        add_component(self.obj, "COLLIDER")
        enemy = add_mesh(bpy.ops.mesh.primitive_cube_add, "enemy")
        add_component(enemy, "CUSTOM", type_path="my_game::Enemy")
        add_component(enemy, "COLLIDER")
        add_mesh(bpy.ops.mesh.primitive_cube_add, "plain")
        overview = bpy.context.scene.bevy_component_overview
        ui_list = SimpleNamespace(filter_name="", use_filter_invert=False, use_filter_sort_alpha=False, bitflag_filter_item=1 << 30)
        self.assertEqual(_shown_in_overview(ui_list), ["enemy", "subject"])
        overview.filter = "CUSTOM"
        try:
            self.assertEqual(_shown_in_overview(ui_list), ["enemy"])
        finally:
            overview.filter = "ALL"
        ui_list.filter_name = "My_Game"
        self.assertEqual(_shown_in_overview(ui_list), ["enemy"])
        ui_list.use_filter_invert = True
        self.assertEqual(_shown_in_overview(ui_list), ["subject"])
        select(enemy)
        index = list(bpy.context.scene.objects).index(self.obj)
        overview.active = index
        self.assertEqual((bpy.context.selected_objects, bpy.context.object, overview.active), ([self.obj], self.obj, index))
        overview.active = 99
        self.assertEqual(bpy.context.object, self.obj)
        panel = FakePanel(self)
        addon.panel.BEVY_PT_view_overview.draw(panel, bpy.context)
        self.assertEqual([bound["listtype_name"] for name, bound, layout in panel.layout.calls if name == "template_list"], ["BEVY_UL_objects"])
        self.assertEqual(panel.layout.buttons()[0][1].component_type, "ALL")
        row = FakeLayout(self)
        addon.panel.BEVY_UL_objects.draw_item(ui_list, bpy.context, row, bpy.context.scene, enemy, 0, overview, "active")
        self.assertEqual([bound.get("icon") for name, bound, layout in row.calls if name == "label"], [addon.property.COMPONENT_LABELS["CUSTOM"][1], addon.property.COMPONENT_LABELS["COLLIDER"][1]])
        for kind in ("RIGID_BODY", "SHADOWS", "AUDIO_PLAYER", "ANIMATION"):
            add_component(enemy, kind)
        row = FakeLayout(self)
        addon.panel.BEVY_UL_objects.draw_item(ui_list, bpy.context, row, bpy.context.scene, enemy, 0, overview, "active")
        self.assertEqual([(bound.get("text", ""), bound.get("icon", "NONE")) for name, bound, layout in row.calls if name == "label"][4:], [("+2", "NONE")])

    def test_problem_count_follows_changes(self):
        scene = bpy.context.scene
        addon.validation.stop_problem_counts()
        try:
            self.assertIsNone(addon.validation.problem_count(scene))
            self.assertTrue(bpy.app.timers.is_registered(addon.validation._recount_problems))
            bpy.app.timers.unregister(addon.validation._recount_problems)
            addon.system.PROBLEM_CHANGES[1] = 0.0
            self.assertIsNone(addon.validation._recount_problems())
            self.assertEqual(addon.validation.problem_count(scene), (0, 0))
            self.assertFalse(bpy.app.timers.is_registered(addon.validation._recount_problems))
            holder = add_empty("holder", (0, 0, 0))
            add_component(holder, "VISIBILITY_RANGE")
            self.assertEqual(addon.validation.problem_count(scene), (0, 0))
            self.assertTrue(bpy.app.timers.is_registered(addon.validation._recount_problems))
            bpy.app.timers.unregister(addon.validation._recount_problems)
            self.assertGreater(addon.validation._recount_problems(), 0)
            addon.system.PROBLEM_CHANGES[1] = 0.0
            self.assertIsNone(addon.validation._recount_problems())
            self.assertEqual(addon.validation.problem_count(scene), (0, 1))
            add_component(self.obj, "CUSTOM", custom_json="{broken")
            addon.system.PROBLEM_CHANGES[1] = 0.0
            addon.validation._recount_problems()
            self.assertEqual(addon.validation.problem_count(scene), (1, 1))
            self.addCleanup(scene.world.property_unset, "bevy_sky")
            scene.world.bevy_sky.enabled = True
            addon.system.PROBLEM_CHANGES[1] = 0.0
            addon.validation._recount_problems()
            self.assertEqual(addon.validation.problem_count(scene), (1, 2))
        finally:
            addon.validation.stop_problem_counts()
        self.assertFalse(bpy.app.timers.is_registered(addon.validation._recount_problems))

    def test_property_changes_mark_problems_changed(self):
        collider = add_component(self.obj, "COLLIDER")
        before = addon.system.problem_changes()[0]
        collider.collider_shape = "SPHERE"
        bpy.context.view_layer.update()
        self.assertGreater(addon.system.problem_changes()[0], before)
        before = addon.system.problem_changes()[0]
        bpy.ops.bevy_components.remove(index=0)
        self.assertGreater(addon.system.problem_changes()[0], before)

    def test_headers_show_the_problem_count(self):
        for counted, expected in ((None, []), ((0, 0), [("", "CHECKMARK")]), ((2, 0), [("2", "CANCEL")]), ((2, 3), [("2", "CANCEL"), ("3", "ERROR")])):
            for panel_type in (addon.panel.BEVY_PT_object_properties, addon.panel.BEVY_PT_view_sidebar):
                panel = FakePanel(self)
                with mock.patch.object(addon.validation, "problem_count", return_value=counted):
                    panel_type.draw_header_preset(panel, bpy.context)
                self.assertEqual(_operator_calls(panel.layout), expected, (panel_type.__name__, counted))
                self.assertEqual(set(panel.layout.operators()), {"bevy_components.validate"} if counted else set())


NATIVE_COLLIDER = {**DEFAULT_COLLIDER, "filters": 1, "own_mesh": True}
BLENDER_BODY = {**DYNAMIC_BODY, "mass": 1.0, "linear_damping": 0.04, "angular_damping": 0.1}


def _rigid_body(obj, kind="ACTIVE", shape=None):
    select(obj)
    bpy.ops.rigidbody.object_add(type=kind)
    if shape is not None:
        obj.rigid_body.collision_shape = shape
    return obj.rigid_body


def _constraint(obj, kind, first=None, second=None):
    select(obj)
    if "FINISHED" not in bpy.ops.bevy_components.add_constraint():
        raise RuntimeError(f"Could not add a constraint to {obj.name}")
    constraint = obj.rigid_body_constraint
    constraint.type = kind
    constraint.object1 = first
    constraint.object2 = second
    return constraint


def _native(obj):
    return _rounded(addon.system.object_components(obj))


def _by_type(components):
    return {component["type"]: {key: value for key, value in component.items() if key != "own_mesh"} for component in components}


def _shaped(name, operator, matrix=None, **options):
    obj = add_mesh(operator, name, **options)
    if matrix is not None:
        obj.data.transform(matrix)
        obj.data.update()
    bpy.context.view_layer.update()
    return obj


class TestNativePhysics(unittest.TestCase):
    def setUp(self):
        clear_scene()

    def tearDown(self):
        clear_scene()

    def _messages(self):
        bpy.context.view_layer.update()
        return [addon.validation.describe(issue) for issue in addon.validation.check_objects(bpy.data.objects)]

    def test_rigid_bodies_export_as_bodies_and_colliders(self):
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=2, location=(0, 0, 5))
        body = _rigid_body(crate)
        body.mass = 3.0
        body.friction = 0.8
        body.restitution = 0.25
        self.assertEqual(_native(crate), [{**BLENDER_BODY, "mass": 3.0}, {"type": "collider", "shape": "convex", **NATIVE_COLLIDER, "offset": None, "friction": 0.8, "restitution": 0.25}])
        body.collision_collections[0] = False
        body.collision_collections[3] = True
        self.assertEqual([(component.get("memberships"), component.get("filters")) for component in _native(crate)][1], (8, 8))
        body.kinematic = True
        self.assertEqual(_native(crate)[0], KINEMATIC_BODY)
        body.kinematic = False
        body.enabled = False
        self.assertEqual(_native(crate)[0], STATIC_BODY)
        body.enabled = True
        body.type = "PASSIVE"
        self.assertEqual(_native(crate)[0], STATIC_BODY)
        select(crate)
        bpy.ops.rigidbody.object_remove()
        self.assertEqual(addon.system.components_for(crate), [])

    def test_shapes_follow_the_mesh(self):
        cases = (
            (_shaped("box", bpy.ops.mesh.primitive_cube_add, Matrix.Diagonal((1.0, 1.5, 2.0, 1.0)), size=2), "BOX", {"shape": "cuboid", "size": [2.0, 4.0, 3.0]}),
            (_shaped("ball", bpy.ops.mesh.primitive_uv_sphere_add, radius=0.75), "SPHERE", {"shape": "sphere", "radius": 0.75}),
            (_shaped("capsule", bpy.ops.mesh.primitive_cube_add, Matrix.Diagonal((0.5, 0.5, 1.5, 1.0)), size=2), "CAPSULE", {"shape": "capsule", "radius": 0.5, "height": 2.0}),
            (_shaped("pillar", bpy.ops.mesh.primitive_cylinder_add, radius=0.5, depth=3), "CYLINDER", {"shape": "cylinder", "radius": 0.5, "height": 3.0}),
            (_shaped("cone", bpy.ops.mesh.primitive_cone_add, radius1=1, depth=2), "CONE", {"shape": "cone", "radius": 1.0, "height": 2.0}),
            (_shaped("hull", bpy.ops.mesh.primitive_ico_sphere_add, radius=1), "CONVEX_HULL", {"shape": "convex", "offset": None}),
            (_shaped("floor", bpy.ops.mesh.primitive_plane_add, size=4), "MESH", {"shape": "trimesh", "offset": None}),
        )
        for obj, shape, expected in cases:
            _rigid_body(obj, "PASSIVE", shape)
            collider = _by_type(_native(obj))["collider"]
            self.assertEqual({key: collider[key] for key in expected}, expected, obj.name)
            self.assertEqual(collider.get("offset", [0.0, 0.0, 0.0]) or [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], obj.name)
        self.assertEqual(self._messages(), [])

    def test_bevy_settings_fill_in_what_blender_lacks(self):
        ball = add_mesh(bpy.ops.mesh.primitive_uv_sphere_add, "ball", radius=0.5)
        _rigid_body(ball, shape="SPHERE")
        physics = ball.bevy_physics
        physics.auto_mass = True
        physics.gravity_scale = 0.5
        physics.ccd = "ALL"
        physics.lock_translation = (True, False, False)
        physics.lock_rotation = (False, True, False)
        physics.linear_velocity = (1.0, 2.0, 3.0)
        physics.angular_velocity = (0.0, 0.0, 1.0)
        physics.events = True
        physics.collision_only = True
        physics.use_layers = True
        physics.memberships = [index == 1 for index in range(addon.property.LAYER_COUNT)]
        physics.filters = [index == 2 for index in range(addon.property.LAYER_COUNT)]
        self.assertEqual(_native(ball), [{**BLENDER_BODY, "mass": None, "gravity_scale": 0.5, "ccd": "all", "lock_translation": [True, False, False], "lock_rotation": [False, False, True], "linear_velocity": [1.0, 3.0, -2.0], "angular_velocity": [0.0, 1.0, 0.0]}, {"type": "collider", "shape": "sphere", **NATIVE_COLLIDER, "events": True, "collision_only": True, "memberships": 2, "filters": 4}])
        zone = add_mesh(bpy.ops.mesh.primitive_cube_add, "zone", size=2)
        _rigid_body(zone, "PASSIVE", "BOX")
        zone.bevy_physics.sensor = True
        self.assertEqual(_by_type(_native(zone))["collider"], {"type": "collider", "shape": "cuboid", **{key: value for key, value in NATIVE_COLLIDER.items() if key != "own_mesh"}, "size": [2.0, 2.0, 2.0], "sensor": True, "events": True})
        zone.bevy_physics.events = False
        self.assertFalse(_by_type(_native(zone))["collider"]["events"])

    def test_compound_parents_join_their_children(self):
        cart = add_mesh(bpy.ops.mesh.primitive_cube_add, "cart", size=1)
        _rigid_body(cart, shape="COMPOUND")
        wheel = add_mesh(bpy.ops.mesh.primitive_cylinder_add, "wheel", radius=0.5, depth=0.2, location=(0, 0, -0.5))
        wheel.parent = cart
        _rigid_body(wheel, shape="CYLINDER")
        self.assertEqual([component["type"] for component in _native(cart)], ["rigid_body"])
        self.assertEqual([component["type"] for component in _native(wheel)], ["collider"])
        self.assertEqual(self._messages(), [])
        wheel.parent = None
        self.assertEqual(self._messages(), ["cart: Dynamic body has no collider on it or under it, so it has no mass and collides with nothing"])
        wheel.parent = cart
        cart.rigid_body.collision_shape = "BOX"
        self.assertEqual(self._messages(), ["wheel: Moves on its own instead of with cart. Set cart's Shape to Compound Parent to make them one body"])

    def test_constraints_export_as_joints(self):
        door = add_mesh(bpy.ops.mesh.primitive_cube_add, "door", size=1, location=(1, 0, 0))
        _rigid_body(door, shape="BOX")
        frame = add_mesh(bpy.ops.mesh.primitive_cube_add, "frame", size=1, location=(-1, 0, 0))
        _rigid_body(frame, "PASSIVE", "BOX")
        hinge = add_empty("hinge", (0, 0, 0))
        constraint = _constraint(hinge, "HINGE", frame, door)
        constraint.use_limit_ang_z = True
        constraint.limit_ang_z_lower = -1.0
        constraint.limit_ang_z_upper = 1.5
        hinge.bevy_physics.joint_angular_damping = 2.0
        self.assertEqual(_native(hinge), [{**DEFAULT_JOINT, "body1": "frame", "body2": "door", "angle_limits": [-1.0, 1.5], "angular_damping": 2.0}])
        constraint.type = "SLIDER"
        constraint.use_limit_lin_x = True
        constraint.limit_lin_x_lower = -0.5
        constraint.limit_lin_x_upper = 2.0
        self.assertEqual(_native(hinge), [{**DEFAULT_JOINT, "kind": "prismatic", "body1": "frame", "body2": "door", "axis": [1.0, 0.0, 0.0], "distance_limits": [-0.5, 2.0], "angular_damping": 2.0}])
        constraint.type = "POINT"
        hinge.bevy_physics.joint_use_swing = True
        hinge.bevy_physics.joint_swing = 0.5
        self.assertEqual(_native(hinge), [{**DEFAULT_JOINT, "kind": "spherical", "body1": "frame", "body2": "door", "swing_limit": 0.5, "angular_damping": 2.0}])
        constraint.type = "FIXED"
        constraint.disable_collisions = False
        self.assertEqual(_native(hinge), [{**DEFAULT_JOINT, "kind": "fixed", "body1": "frame", "body2": "door", "axis": None, "linear_damping": None, "angular_damping": None, "collide": True}])
        self.assertEqual(self._messages(), [])
        constraint.type = "GENERIC"
        self.assertEqual(addon.system.components_for(hinge), [])
        self.assertEqual(self._messages(), ["hinge: Bevy has no Generic joint, so the game leaves this Rigid Body Constraint out. Use Fixed, Point, Hinge or Slider"])
        constraint.type = "HINGE"
        constraint.enabled = False
        self.assertEqual(addon.system.components_for(hinge), [])

    def test_components_override_blender_physics(self):
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=2)
        _rigid_body(crate)
        add_component(crate, "COLLIDER", collider_shape="SPHERE", collider_radius=2.0)
        self.assertEqual(_by_type(_native(crate))["collider"], {"type": "collider", "shape": "sphere", **DEFAULT_COLLIDER, "radius": 2.0})
        self.assertEqual(_native(crate)[1], BLENDER_BODY)
        select(crate)
        panel = FakePanel(self)
        addon.panel.BEVY_PT_physics_collisions.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props(), [])
        self.assertIn("The Collider component in Object > Game Components replaces these settings in Bevy", " ".join(panel.layout.texts()))

    def test_scene_gravity_is_exported_when_it_changes(self):
        scene = bpy.context.scene
        scene.gravity = (0.0, 0.0, -3.0)
        self.assertEqual(addon.native.physics_components(scene), [])
        bpy.ops.rigidbody.world_add()
        self.assertEqual(addon.native.physics_components(scene), [{"type": "gravity", "value": [0.0, -3.0, 0.0]}])
        scene.rigidbody_world.effector_weights.gravity = 0.5
        self.assertEqual(addon.native.physics_components(scene), [{"type": "gravity", "value": [0.0, -1.5, 0.0]}])
        scene.use_gravity = False
        self.assertEqual(addon.native.physics_components(scene), [{"type": "gravity", "value": [0.0, 0.0, 0.0]}])
        scene.use_gravity = True
        scene.rigidbody_world.effector_weights.gravity = 1.0
        scene.gravity = (0.0, 0.0, -9.81)
        self.assertEqual(addon.native.physics_components(scene), [])
        with tempfile.TemporaryDirectory() as directory:
            scene.gravity = (1.0, 0.0, -3.0)
            gltf = export_sample_scene(Path(directory) / "gravity.glb")
            self.assertEqual(json.loads(gltf["scenes"][0]["extras"]["bevy_components"])["components"], [{"type": "gravity", "value": [1.0, -3.0, 0.0]}])

    def test_plain_gltf_export_reads_blender_physics_when_it_runs(self):
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=2)
        add_component(crate, "SHADOWS", shadows_cast=False)
        _rigid_body(crate, "PASSIVE", "BOX")
        crate.rigid_body.friction = 0.9

        def exported():
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "plain.glb"
                bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", export_extras=True)
                node = read_gltf(path)["nodes"][0]
            return _rounded(json.loads(node["extras"]["bevy_components"])["components"])

        components = exported()
        self.assertEqual([component["type"] for component in components], ["shadows", "rigid_body", "collider"])
        self.assertEqual(components[2]["friction"], 0.9)
        select(crate)
        bpy.ops.rigidbody.object_remove()
        self.assertEqual([component["type"] for component in exported()], ["shadows"])

    def test_bevy_gltf_export_acts_like_the_gltf_export_with_components(self):
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=2)
        add_component(crate, "COLLIDER", collider_shape="SPHERE", collider_radius=1.5)
        add_component(crate, "CUSTOM", custom_type="game::Loot", custom_json='{"gold": 3}')
        broken = add_component(crate, "CUSTOM", custom_type="game::Broken", custom_json="{")
        crate["note"] = "left out"
        rock = add_mesh(bpy.ops.mesh.primitive_ico_sphere_add, "rock", location=(4, 0, 0))
        add_component(rock, "VISIBILITY_RANGE")
        select(crate)
        operator = addon.gltf.BEVY_OT_export_gltf
        self.assertEqual(operator.bl_idname, "export_scene.bevy_gltf")
        self.assertTrue(issubclass(operator, sys.modules["io_scene_gltf2"].ExportGLTF2_Base))
        self.assertEqual(addon.gltf.BEVY_FH_gltf.bl_export_operator, operator.bl_idname)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crate.glb"
            reference = add_component(crate, "SCENE_REFERENCE", scene_file=str(Path(directory) / "props" / "tree.glb"))
            self.assertEqual(bpy.ops.export_scene.bevy_gltf(filepath=str(path), use_selection=True), {"FINISHED"})
            gltf = read_gltf(path)
            bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True)
            plain = read_gltf(path)
        self.assertEqual(addon.gltf._skipped_message(["crate: invalid JSON in Custom Component"]), "Left out 1 Bevy component that cannot export: crate: invalid JSON in Custom Component. See Validate All Objects")
        self.assertEqual(addon.gltf._skipped_message([f"crate: problem {index}" for index in range(5)]), "Left out 5 Bevy components that cannot export: crate: problem 0; crate: problem 1; crate: problem 2 and 2 more. See Validate All Objects")
        with addon.system.bevy_export() as skipped:
            addon.system.object_components(crate, None, addon.system._skipped[0])
        self.assertEqual([message.split(":")[:2] for message in skipped], [["crate", " Custom JSON for game"]])
        self.assertEqual([node["name"] for node in gltf["nodes"]], ["crate"])
        extras = gltf["nodes"][0]["extras"]
        self.assertEqual(list(extras), ["bevy_components"])
        components = _rounded(json.loads(extras["bevy_components"])["components"])
        self.assertEqual([component["type"] for component in components], ["collider", "custom", "scene_reference"])
        self.assertEqual((components[0]["radius"], components[1]["data"], components[2]["path"]), (1.5, {"gold": 3}, "props/tree.glb"))
        self.assertNotIn("extras", plain["nodes"][0])
        self.assertTrue(reference.enabled and broken.enabled)
        self.assertNotIn("bevy_components", crate)

    def test_export_puts_bodies_back_where_they_start(self):
        scene = bpy.context.scene
        ground = add_mesh(bpy.ops.mesh.primitive_plane_add, "ground", size=20)
        _rigid_body(ground, "PASSIVE", "MESH")
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=1, location=(0, 0, 5))
        _rigid_body(crate, shape="BOX")
        scene.rigidbody_world.point_cache.frame_end = 100
        for frame in range(1, 41):
            scene.frame_set(frame)
        self.assertLess(crate.matrix_world.translation.z, 4.0)
        try:
            with tempfile.TemporaryDirectory() as directory:
                gltf = export_sample_scene(Path(directory) / "rest.glb")
            nodes = {node["name"]: node for node in gltf["nodes"]}
            self.assertEqual(_rounded(nodes["crate"]["translation"]), [0.0, 5.0, 0.0])
            self.assertEqual(scene.frame_current, 40)
            self.assertLess(crate.matrix_world.translation.z, 4.0)
        finally:
            scene.frame_set(1)

    def test_convert_replaces_components_with_blender_physics(self):
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=2)
        add_component(crate, "COLLIDER", collider_shape="CUBOID", collider_size=(2, 2, 2), collider_friction=0.8)
        add_component(crate, "RIGID_BODY", rigid_body_kind="DYNAMIC", rigid_body_use_mass=True, rigid_body_mass=4.0, rigid_body_lock_rotation=(False, True, False), rigid_body_linear_velocity=(0.0, 0.0, 2.0))
        add_component(crate, "SHADOWS", shadows_cast=False)
        ground = add_mesh(bpy.ops.mesh.primitive_plane_add, "ground", size=10, location=(0, 0, -2))
        add_component(ground, "COLLIDER", collider_shape="TRIMESH")
        trigger = add_mesh(bpy.ops.mesh.primitive_cube_add, "trigger", size=2, location=(4, 0, 0))
        add_component(trigger, "COLLIDER", collider_shape="CUBOID", collider_size=(2, 2, 2), collider_sensor=True, collider_memberships=layers(3), collider_filters=layers(3))
        ghost = add_mesh(bpy.ops.mesh.primitive_cube_add, "ghost", size=2, location=(8, 0, 0))
        add_component(ghost, "COLLIDER", collider_shape="CUBOID", collider_size=(2, 2, 2), collider_memberships=layers(1), collider_filters=layers(2))
        cart = add_mesh(bpy.ops.mesh.primitive_cube_add, "cart", size=1, location=(0, 6, 0))
        add_component(cart, "RIGID_BODY", rigid_body_kind="DYNAMIC")
        wheel = add_mesh(bpy.ops.mesh.primitive_cylinder_add, "wheel", radius=0.5, depth=0.2, location=(0, 6, -0.5))
        wheel.parent = cart
        wheel.matrix_parent_inverse = cart.matrix_world.inverted()
        add_component(wheel, "COLLIDER", collider_shape="CYLINDER", collider_radius=0.5, collider_height=0.2)
        hinge = add_empty("hinge", (0, 0, 2))
        add_component(hinge, "JOINT", joint_kind="REVOLUTE", joint_body1=crate, joint_use_limits=True, joint_angle_min=-0.5, joint_angle_max=0.5)
        offset = add_mesh(bpy.ops.mesh.primitive_cube_add, "offset", size=2, location=(0, -6, 0))
        add_component(offset, "COLLIDER", collider_shape="CUBOID", collider_size=(2, 2, 2), collider_offset=(0.0, 1.0, 0.0))
        holder = add_empty("holder", (0, -10, 0))
        add_component(holder, "RIGID_BODY", rigid_body_kind="DYNAMIC")
        slide = add_empty("slide", (0, -12, 0))
        add_component(slide, "JOINT", joint_kind="PRISMATIC", joint_body1=crate)
        house = add_mesh(bpy.ops.mesh.primitive_cube_add, "house", size=2, location=(0, -16, 0))
        add_component(house, "COLLIDER", collider_shape="TRIMESH")
        chimney = add_mesh(bpy.ops.mesh.primitive_cube_add, "chimney", size=0.5, location=(0, -16, 1.5))
        chimney.parent = house
        chimney.matrix_parent_inverse = house.matrix_world.inverted()
        bpy.context.view_layer.update()
        before = {obj.name: _by_type(_native(obj)) for obj in bpy.data.objects if obj.bevy_component_data.components}
        converted, kept = addon.convert.convert_objects(bpy.context, bpy.context.scene.objects)
        self.assertEqual(sorted(obj.name for obj in converted), ["cart", "crate", "ghost", "ground", "hinge", "trigger", "wheel"])
        self.assertEqual(sorted((obj.name, reason) for obj, reason in kept), [
            ("holder", "Blender only gives meshes a Rigid Body"),
            ("house", "its collider also covers the meshes of child objects"),
            ("offset", "its collider's size or offset differs from the mesh, which Blender's shape always fits"),
            ("slide", "its axis is Y, while Blender's Slider moves along X"),
        ])
        self.assertEqual(([item.component_type for item in crate.bevy_component_data.components], crate.visible_shadow), ([], False))
        self.assertEqual((crate.rigid_body.type, crate.rigid_body.collision_shape, cart.rigid_body.collision_shape, wheel.rigid_body.collision_shape, hinge.rigid_body_constraint.type), ("ACTIVE", "BOX", "COMPOUND", "CYLINDER", "HINGE"))
        self.assertTrue(ghost.bevy_physics.use_layers)
        self.assertEqual(list(trigger.rigid_body.collision_collections)[:4], [False, False, False, True])
        self.assertIsNone(offset.rigid_body)
        self.assertEqual([item.component_type for item in offset.bevy_component_data.components], ["COLLIDER"])
        for obj in converted:
            after = _by_type(_native(obj))
            expected = before[obj.name]
            if obj in (crate, ground, wheel):
                self.assertEqual((expected["collider"]["filters"], after["collider"]["filters"]), (4294967295, 1), obj.name)
                expected["collider"]["filters"] = 1
            if obj in (ground, trigger, ghost):
                expected["rigid_body"] = STATIC_BODY
            self.assertEqual(after, expected, obj.name)
        self.assertEqual(bpy.ops.bevy_components.convert_to_native(), {"FINISHED"})
        self.assertEqual([item.component_type for item in offset.bevy_component_data.components], ["COLLIDER"])
        clear_scene()
        self.assertEqual(bpy.ops.bevy_components.convert_to_native(), {"CANCELLED"})

    def test_convert_keeps_default_layers_that_other_colliders_rely_on(self):
        wall = add_mesh(bpy.ops.mesh.primitive_cube_add, "wall", size=2)
        add_component(wall, "COLLIDER", collider_shape="CUBOID", collider_size=(2, 2, 2))
        probe = add_empty("probe", (5, 0, 0))
        add_component(probe, "COLLIDER", collider_shape="SPHERE", collider_memberships=layers(4), collider_filters=layers(0))
        converted, kept = addon.convert.convert_objects(bpy.context, [wall])
        self.assertEqual(converted, [wall])
        self.assertTrue(wall.bevy_physics.use_layers)
        self.assertEqual((_by_type(_native(wall))["collider"]["memberships"], _by_type(_native(wall))["collider"]["filters"]), (1, 4294967295))

    def test_checks_for_blender_physics(self):
        shifted = _shaped("shifted", bpy.ops.mesh.primitive_cube_add, Matrix.Translation((0.0, 0.0, 1.0)), size=1)
        _rigid_body(shifted, "PASSIVE", "BOX")
        self.assertEqual(self._messages(), ["shifted: The mesh is not centered on its origin, but Blender and Bevy center the Box shape on it. Use Set Origin > Origin to Geometry, or add a Collider component with an offset"])
        shifted.rigid_body.collision_shape = "CONVEX_HULL"
        self.assertEqual(self._messages(), [])
        floor = add_mesh(bpy.ops.mesh.primitive_plane_add, "floor", size=4)
        _rigid_body(floor, "ACTIVE", "MESH")
        self.assertEqual(self._messages(), ["floor: Triangle meshes collide poorly on Dynamic bodies, use Convex Hull"])
        floor.rigid_body.type = "PASSIVE"
        edges = bpy.data.objects.new("edges", bpy.data.meshes.new("edges"))
        bpy.context.scene.collection.objects.link(edges)
        edges.data.from_pydata([(0, 0, 0), (1, 0, 0)], [(0, 1)], [])
        _rigid_body(edges, "PASSIVE", "CONVEX_HULL")
        self.assertEqual(self._messages(), ["edges: The mesh has no faces, so no Convex Hull collider is built"])

    def test_bevy_subpanels_sit_under_blender_physics(self):
        self.assertEqual([panel.bl_parent_id for panel in (addon.panel.BEVY_PT_physics_rigid_body, addon.panel.BEVY_PT_physics_collisions, addon.panel.BEVY_PT_physics_joint)], ["PHYSICS_PT_rigid_body", "PHYSICS_PT_rigid_body_collisions", "PHYSICS_PT_rigid_body_constraint"])
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=1)
        self.assertFalse(addon.panel.BEVY_PT_physics_rigid_body.poll(bpy.context))
        _rigid_body(crate, shape="COMPOUND")
        self.assertTrue(addon.panel.BEVY_PT_physics_rigid_body.poll(bpy.context))
        self.assertFalse(addon.panel.BEVY_PT_physics_collisions.poll(bpy.context))
        panel = FakePanel(self)
        addon.panel.BEVY_PT_physics_rigid_body.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props(), ["auto_mass", "gravity_scale", "ccd", *["lock_translation"] * 3, *["lock_rotation"] * 3, "linear_velocity", "angular_velocity"])
        self.assertIn("Dynamic body in Bevy", panel.layout.texts())
        crate.rigid_body.type = "PASSIVE"
        panel = FakePanel(self)
        addon.panel.BEVY_PT_physics_rigid_body.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props(), [])
        part = add_mesh(bpy.ops.mesh.primitive_cube_add, "part", size=0.5)
        part.parent = crate
        _rigid_body(part, shape="BOX")
        self.assertFalse(addon.panel.BEVY_PT_physics_rigid_body.poll(bpy.context))
        self.assertTrue(addon.panel.BEVY_PT_physics_collisions.poll(bpy.context))
        panel = FakePanel(self)
        addon.panel.BEVY_PT_physics_collisions.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props(), ["sensor", "events", "collision_only", "use_layers"])
        part.bevy_physics.use_layers = True
        panel = FakePanel(self)
        addon.panel.BEVY_PT_physics_collisions.draw(panel, bpy.context)
        self.assertEqual((panel.layout.props().count("memberships"), panel.layout.props().count("filters")), (addon.property.LAYER_COUNT, addon.property.LAYER_COUNT))
        hinge = add_empty("hinge", (0, 0, 0))
        select(hinge)
        self.assertFalse(addon.panel.BEVY_PT_physics_joint.poll(bpy.context))
        constraint = _constraint(hinge, "POINT", crate, part)
        panel = FakePanel(self)
        addon.panel.BEVY_PT_physics_joint.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props(), ["joint_use_swing", "joint_swing", "joint_linear_damping", "joint_angular_damping"])
        constraint.type = "FIXED"
        panel = FakePanel(self)
        addon.panel.BEVY_PT_physics_joint.draw(panel, bpy.context)
        self.assertEqual(panel.layout.props(), [])
        constraint.type = "MOTOR"
        panel = FakePanel(self)
        addon.panel.BEVY_PT_physics_joint.draw(panel, bpy.context)
        self.assertIn("Bevy has no Motor joint, so the game leaves this constraint out. Use Fixed, Point, Hinge or Slider", " ".join(panel.layout.texts()))
        select(crate)
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertIn("Rigid Body from Physics", panel.layout.texts())

    def test_physics_menu_offers_blender_physics_first(self):
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=1)
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add_physics.draw(menu, _menu_context(crate))
        self.assertEqual(menu.layout.operators(), ["rigidbody.object_add", "bevy_components.add_constraint"])
        self.assertEqual([enabled for text, properties, enabled in menu.layout.buttons()][:2], [True, True])
        _rigid_body(crate)
        _constraint(crate, "FIXED")
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add_physics.draw(menu, _menu_context(crate))
        self.assertEqual([enabled for text, properties, enabled in menu.layout.buttons()][:2], [False, False])
        empty = add_empty("empty", (0, 0, 0))
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add_physics.draw(menu, _menu_context(empty))
        self.assertEqual([enabled for text, properties, enabled in menu.layout.buttons()][:2], [False, True])

    def test_viewport_draws_blender_physics(self):
        pillar = add_mesh(bpy.ops.mesh.primitive_cylinder_add, "pillar", radius=0.5, depth=2)
        _rigid_body(pillar, "PASSIVE", "CYLINDER")
        self.assertEqual(_extents(_collider_lines(pillar, addon.system.component_of(pillar, "COLLIDER"), 1000)), (0.5, 0.5, 1.0))
        pillar.rigid_body.collision_shape = "CONE"
        self.assertEqual(_extents(_collider_lines(pillar, addon.system.component_of(pillar, "COLLIDER"), 1000)), (0.5, 0.5, 1.0))
        settings = bpy.context.scene.bevy_component_previews
        self.assertEqual(addon.system.component_kinds(pillar), {"RIGID_BODY", "COLLIDER"})
        self.assertIsNone(addon.gizmo.handle_item(pillar, settings))
        hinge = add_empty("hinge", (0, 0, 3))
        _constraint(hinge, "HINGE", pillar)
        settings.scope = "SELECTED"
        try:
            select(pillar)
            self.assertIn(hinge, addon.overlay.joint_objects(bpy.context, settings, addon.overlay.preview_objects(bpy.context, settings)))
        finally:
            settings.property_unset("scope")


POINT_LIGHT = {**DEFAULT_LIGHT, "kind": "point", "radius": 0.25}


def _volume_material(name, values):
    material = bpy.data.materials.new(name)
    if bpy.app.version < (5, 0, 0):
        material.use_nodes = True
    nodes = material.node_tree.nodes
    for node in [node for node in nodes if node.bl_idname != "ShaderNodeOutputMaterial"]:
        nodes.remove(node)
    output = next((node for node in nodes if node.bl_idname == "ShaderNodeOutputMaterial"), None) or nodes.new("ShaderNodeOutputMaterial")
    volume = nodes.new("ShaderNodeVolumePrincipled")
    material.node_tree.links.new(volume.outputs["Volume"], output.inputs["Volume"])
    for key, value in values.items():
        volume.inputs[key].default_value = value
    return material, volume


def _add_object(operator, **options):
    operator(**options)
    return bpy.context.object


class TestNativeLighting(unittest.TestCase):
    def setUp(self):
        clear_scene()

    def tearDown(self):
        clear_scene()

    def _messages(self):
        bpy.context.view_layer.update()
        return [addon.validation.describe(issue) for issue in addon.validation.check_objects(bpy.data.objects)]

    def _panel(self, panel_type, context):
        panel = FakePanel(self)
        panel_type.draw(panel, context)
        return panel.layout

    def test_lights_export_their_bevy_settings(self):
        lamp = add_light("lamp", "POINT", (0, 0, 3), shadow_soft_size=0.25, energy=10)
        self.assertEqual(_native(lamp), [POINT_LIGHT])
        twin = bpy.data.objects.new("twin", lamp.data)
        bpy.context.scene.collection.objects.link(twin)
        lamp.data.bevy_light.light_volumetric = True
        lamp.data.bevy_light.light_use_intensity = True
        self.assertEqual(_stored(twin)["components"], [{**POINT_LIGHT, "intensity": 6830.0, "volumetric": True}])
        lamp.data.use_shadow = False
        self.assertEqual(self._messages(), ["lamp: Volumetric needs Shadows, or the light makes no light shafts", "twin: Volumetric needs Shadows, or the light makes no light shafts"])
        window = add_light("window", "AREA", (0, 4, 3), size=2, size_y=1, shape="RECTANGLE", energy=5)
        self.assertEqual({key: value for key, value in _native(window)[0].items() if key in {"kind", "intensity", "size"}}, {"kind": "area", "intensity": 3415.0, "size": [2.0, 1.0]})
        select(lamp)
        context = SimpleNamespace(object=lamp, scene=bpy.context.scene, region=None, space_data=None, view_layer=bpy.context.view_layer, selected_objects=[])
        self.assertTrue(addon.panel.BEVY_PT_light.poll(context))
        layout = self._panel(addon.panel.BEVY_PT_light, context)
        self.assertIn("light_volumetric", layout.props())
        self.assertIn("Volumetric needs Shadows, or the light makes no light shafts", " ".join(layout.texts()))
        add_component(lamp, "LIGHT")
        self.assertIn("The Light component in Object > Game Components replaces these settings in Bevy", " ".join(self._panel(addon.panel.BEVY_PT_light, context).texts()))
        with tempfile.TemporaryDirectory() as directory:
            gltf = export_sample_scene(Path(directory) / "lights.glb")
        lights = gltf["extensions"]["KHR_lights_punctual"]["lights"]
        self.assertFalse(any("bevy_light" in light.get("extras", {}) for light in lights))
        self.assertFalse(any("bevy_object" in node.get("extras", {}) for node in gltf["nodes"]))
        self.assertTrue(_by_type(_extras(gltf, next(node for node in gltf["nodes"] if node["name"] == "twin"))["components"])["light"]["volumetric"])

    def test_shadows_follow_ray_visibility(self):
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=1)
        self.assertEqual(_native(crate), [])
        crate.visible_shadow = False
        self.assertEqual(_native(crate), [{"type": "shadows", "cast": False, "receive": True, "own_mesh": True}])
        crate.visible_shadow = True
        crate.bevy_object.receive_shadows = False
        self.assertEqual(_stored(crate)["components"], [{"type": "shadows", "cast": True, "receive": False, "own_mesh": True}])
        marker = add_empty("marker", (0, 0, 2))
        marker.visible_shadow = False
        self.assertEqual(_native(marker), [])
        self.assertEqual(self._messages(), [])
        context = SimpleNamespace(object=crate)
        panel = FakePanel(self)
        addon.panel.draw_visibility(panel, context)
        self.assertEqual(panel.layout.props(), ["receive_shadows"])
        room = add_empty("room", (0, 0, 0))
        add_component(room, "SHADOWS", shadows_cast=True, shadows_receive=False)
        chest = add_mesh(bpy.ops.mesh.primitive_cube_add, "chest", size=1)
        chest.parent = room
        chest.visible_shadow = False
        lid = add_mesh(bpy.ops.mesh.primitive_cube_add, "lid", size=0.5, location=(0, 0, 1))
        lid.parent = chest
        self.assertEqual([source.name for source, _matrix in addon.system.mesh_sources(room, addon.system.children_map(bpy.data.objects), "SHADOWS")], ["lid"])

    def test_speakers_export_as_audio_players(self):
        speaker = _add_object(bpy.ops.object.speaker_add, location=(0, 0, 1))
        speaker.name = "bell"
        self.assertEqual(_native(speaker), [])
        self.assertEqual(self._messages(), ["bell: No sound picked, so nothing plays"])
        speaker.data.sound = bpy.data.sounds.load(str(SOUNDS / "chime.ogg"))
        speaker.data.volume = 0.5
        speaker.data.pitch = 1.5
        speaker.data.distance_reference = 3.0
        speaker.data.bevy_speaker.audio_loop = True
        self.assertEqual(_native(speaker), [{**DEFAULT_AUDIO, "path": "sounds/chime.ogg", "volume": 0.5, "loop": True, "distance": 3.0, "speed": 1.5}])
        self.assertEqual(self._messages(), [])
        context = SimpleNamespace(object=speaker, speaker=speaker.data, scene=bpy.context.scene, region=None, space_data=None, view_layer=bpy.context.view_layer, selected_objects=[])
        self.assertTrue(addon.panel.BEVY_PT_speaker.poll(context))
        layout = self._panel(addon.panel.BEVY_PT_speaker, context)
        self.assertIn("sounds/chime.ogg", layout.texts())
        self.assertEqual(layout.props(), ["audio_loop", "audio_autoplay", "audio_spatial"])
        speaker.data.muted = True
        self.assertEqual(_native(speaker), [])
        self.assertEqual(self._messages(), [])
        self.assertEqual(" ".join(self._panel(addon.panel.BEVY_PT_speaker, context).texts()).strip(), "Muted, so the game leaves the sound out")
        speaker.data.muted = False
        with tempfile.TemporaryDirectory() as directory:
            loose = Path(directory) / "bell.ogg"
            loose.write_bytes((SOUNDS / "chime.ogg").read_bytes())
            speaker.data.sound = bpy.data.sounds.load(str(loose))
            self.assertEqual(self._messages(), ["bell: bell.ogg is not in an assets folder, so the game looks for it at the top of its assets folder"])
            speaker.data.sound.pack()
            self.assertEqual(self._messages(), ["bell: The sound is packed into the .blend, but the game loads it from its assets folder. Unpack it there"])

    def test_light_probes_export_as_probes(self):
        sphere = _add_object(bpy.ops.object.lightprobe_add, type="SPHERE", location=(0, 0, 1))
        sphere.name = "room"
        sphere.data.influence_distance = 2.0
        sphere.data.falloff = 0.25
        sphere.data.bevy_probe.intensity = 2.0
        self.assertEqual(_native(sphere), [{"type": "reflection_probe", "size": [4.0, 4.0, 4.0], "falloff": [0.25, 0.25, 0.25], "intensity": 1366.0, "parallax_correction": True, "file": None}])
        volume = _add_object(bpy.ops.object.lightprobe_add, type="VOLUME", location=(0, 6, 1))
        volume.name = "hall"
        volume.data.resolution_x, volume.data.resolution_y, volume.data.resolution_z = 4, 6, 3
        volume.data.bevy_probe.falloff = 0.5
        self.assertEqual(_native(volume), [{"type": "irradiance_volume", "size": [2.0, 2.0, 2.0], "falloff": [0.5, 0.5, 0.5], "intensity": 683.0, "file": None}])
        plane = _add_object(bpy.ops.object.lightprobe_add, type="PLANE", location=(0, 12, 1))
        plane.name = "mirror"
        self.assertEqual(_native(plane), [])
        self.assertEqual(self._messages(), ["hall: No voxel texture, so the volume adds no light", "mirror: Bevy has no planar reflections, so the game leaves this Light Probe out", "room: No cubemap, so the probe adds no reflections"])
        jobs = addon.bake.lighting_jobs(bpy.data.objects, "//lighting")
        self.assertEqual([(job["object"], job["index"], job["kind"]) for job in jobs], [("hall", -1, "VOXELS"), ("room", -1, "CUBEMAP")])
        self.assertEqual(jobs[0]["counts"], [4, 3, 6])
        context = SimpleNamespace(object=sphere, lightprobe=sphere.data, scene=bpy.context.scene, region=None, space_data=None, view_layer=bpy.context.view_layer, selected_objects=[])
        layout = self._panel(addon.panel.BEVY_PT_light_probe, context)
        self.assertEqual([prop for prop in layout.props() if prop != "probe_file"], ["intensity", "parallax", "bake_resolution"])
        self.assertIn("Bevy's reflection probes are boxes, so this one reflects in the box around its sphere", " ".join(layout.texts()))
        context.object, context.lightprobe = plane, plane.data
        self.assertEqual(" ".join(self._panel(addon.panel.BEVY_PT_light_probe, context).texts()).strip(), "Bevy has no planar reflections, so the game leaves this Light Probe out")

    def test_volume_boxes_export_as_fog(self):
        fog = add_mesh(bpy.ops.mesh.primitive_cube_add, "fog", size=2, location=(0, 0, 1))
        fog.data.transform(Matrix.Diagonal((2.0, 3.0, 1.0, 1.0)))
        fog.data.update()
        bpy.context.view_layer.update()
        material, volume = _volume_material("mist", {"Color": (0.25, 0.5, 0.5, 1.0), "Density": 0.2, "Absorption Color": (0.25, 0.25, 0.25, 1.0), "Anisotropy": 0.3})
        fog.data.materials.append(material)
        material.bevy_fog.fog_light_intensity = 2.0
        self.assertEqual(_native(fog), [{"type": "fog_volume", "size": [4.0, 2.0, 6.0], "color": [0.73536, 1.0, 1.0], "density": 0.2, "absorption": 0.29167, "scattering": 0.5, "anisotropy": 0.3, "light_tint": [1.0, 1.0, 1.0], "light_intensity": 2.0}])
        self.assertEqual(self._messages(), [])
        context = SimpleNamespace(object=fog, material=material, scene=bpy.context.scene, region=None, space_data=None, view_layer=bpy.context.view_layer, selected_objects=[])
        self.assertTrue(addon.panel.BEVY_PT_material_fog.poll(context))
        self.assertEqual(self._panel(addon.panel.BEVY_PT_material_fog, context).props(), ["fog_light_tint", "fog_light_intensity"])
        self.assertFalse(addon.panel.BEVY_PT_material_fog.poll(SimpleNamespace(material=add_material("wood"))))
        with tempfile.TemporaryDirectory() as directory:
            gltf = export_sample_scene(Path(directory) / "fog.glb")
        node = next(node for node in gltf["nodes"] if node["name"] == "fog")
        self.assertNotIn("mesh", node)
        self.assertEqual([component["type"] for component in _extras(gltf, node)["components"]], ["fog_volume"])
        self.assertNotIn("mist", [material["name"] for material in gltf.get("materials", [])])
        noise = material.node_tree.nodes.new("ShaderNodeTexNoise")
        material.node_tree.links.new(noise.outputs["Fac"], volume.inputs["Density"])
        volume.inputs["Emission Strength"].default_value = 1.0
        fog.data.transform(Matrix.Translation((0.0, 0.0, 1.0)))
        fog.data.update()
        self.assertEqual(self._messages(), [
            "fog: Bevy fog is even throughout, so the game takes the Density value and ignores what is plugged in",
            "fog: Bevy fog does not glow, so the game leaves out Emission and Blackbody",
            "fog: The mesh is not centered on its origin, but Bevy centers the fog box on it. Use Set Origin > Origin to Geometry",
        ])
        scatter = material.node_tree.nodes.new("ShaderNodeVolumeScatter")
        material.node_tree.links.new(scatter.outputs["Volume"], next(node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeOutputMaterial").inputs["Volume"])
        self.assertEqual(_native(fog), [])
        self.assertEqual(self._messages(), ["fog: Bevy fog reads only the Principled Volume shader, so the game leaves out mist"])

    def test_active_actions_autoplay(self):
        ball = add_mesh(bpy.ops.mesh.primitive_uv_sphere_add, "ball", radius=0.5)
        animate(ball, "bounce", "location", 2, [(1, 0.0), (20, 2.0)])
        self.assertEqual(_native(ball), [])
        select(ball)
        layout = self._panel(addon.panel.BEVY_PT_object_properties, bpy.context)
        self.assertIn("Autoplay bounce", layout.texts())
        self.assertNotIn("speed", layout.props())
        ball.bevy_object.autoplay = True
        self.assertEqual(_stored(ball)["components"], [{"type": "animation", "clip": "bounce", "repeat": False, "speed": 1.0}])
        ball.animation_data.action.use_cyclic = True
        ball.bevy_object.speed = 2.0
        self.assertEqual(_native(ball), [{"type": "animation", "clip": "bounce", "repeat": True, "speed": 2.0}])
        layout = self._panel(addon.panel.BEVY_PT_object_properties, bpy.context)
        self.assertEqual([prop for prop in layout.props() if prop in {"autoplay", "use_cyclic", "speed"}], ["autoplay", "use_cyclic", "speed"])
        self.assertEqual(self._messages(), [])

    def test_convert_replaces_lighting_components(self):
        lamp = add_light("lamp", "POINT", (0, 0, 3))
        twin = bpy.data.objects.new("twin", lamp.data)
        bpy.context.scene.collection.objects.link(twin)
        add_component(lamp, "LIGHT", light_volumetric=True)
        spot = add_light("spot", "SPOT", (2, 0, 3))
        add_component(spot, "LIGHT", light_contact_shadows=True, light_use_intensity=True, light_intensity=500.0)
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=1, location=(0, 3, 0))
        add_component(crate, "SHADOWS", shadows_cast=False)
        room = add_empty("room", (0, 6, 0))
        add_component(room, "SHADOWS", shadows_receive=False)
        stool = add_mesh(bpy.ops.mesh.primitive_cube_add, "stool", size=1, location=(0, 6, 0))
        stool.parent = room
        add_component(stool, "SHADOWS", shadows_cast=True)
        ball = add_mesh(bpy.ops.mesh.primitive_uv_sphere_add, "ball", radius=0.5, location=(3, 3, 0))
        animate(ball, "bounce", "location", 2, [(1, 0.0), (20, 2.0)])
        add_component(ball, "ANIMATION", animation_clip="bounce", animation_loop=True, animation_speed=1.5)
        bell = add_empty("bell", (3, 6, 1))
        add_component(bell, "AUDIO_PLAYER", audio_path="sounds/chime.ogg", audio_volume=0.5, audio_loop=True, audio_distance=3.0)
        loud = add_empty("loud", (3, 7, 1))
        add_component(loud, "AUDIO_PLAYER", audio_path="sounds/chime.ogg", audio_volume=2.0)
        missing = add_empty("missing", (3, 8, 1))
        add_component(missing, "AUDIO_PLAYER", audio_path="sounds/none.ogg")
        mist = add_empty("mist", (6, 0, 1))
        add_component(mist, "FOG_VOLUME", volume_size=(4.0, 2.0, 6.0), fog_color=(0.5, 0.8, 1.0), fog_density=0.2, fog_absorption=0.9, fog_scattering=0.7, fog_anisotropy=0.3, fog_light_intensity=1.5)
        cellar = add_empty("cellar", (6, 6, 1))
        add_component(cellar, "REFLECTION_PROBE", volume_size=(8.0, 3.0, 5.0), volume_falloff=0.2, probe_intensity=1000.0, probe_file=str(CUBEMAP))
        hall = add_empty("hall", (12, 0, 1))
        add_component(hall, "IRRADIANCE_VOLUME", volume_size=(10.0, 4.0, 6.0), bake_voxels=(10, 4, 6))
        bpy.context.scene.bevy_glb_export.filepath = str(FIXTURE)
        bpy.context.view_layer.update()
        before = {obj.name: _by_type(_native(obj)) for obj in bpy.data.objects}
        converted, kept = addon.convert.convert_objects(bpy.context, bpy.context.scene.objects)
        self.assertEqual(sorted(obj.name for obj in converted), ["ball", "bell", "cellar", "crate", "hall", "mist", "spot"])
        self.assertEqual(sorted((obj.name, reason) for obj, reason in kept), [
            ("lamp", "twin shares its light data and would get these Light settings too"),
            ("loud", "its Audio Player volume is above 1, the most a Speaker allows"),
            ("missing", "its Audio Player sound sounds/none.ogg is not in the game's assets folder, so a Speaker cannot load it"),
            ("room", "its Shadows component covers the meshes of child objects, while Blender sets shadows on each mesh object"),
            ("stool", "room's Shadows component would reach its mesh"),
        ])
        self.assertEqual((spot.data.bevy_light.light_intensity, crate.visible_shadow, ball.bevy_object.autoplay, ball.animation_data.action.use_cyclic), (500.0, False, True, True))
        self.assertFalse(lamp.data.bevy_light.light_volumetric)
        for obj in (spot, crate, ball):
            self.assertEqual(_by_type(_native(obj)), before[obj.name], obj.name)
        children = {child.parent.name: child for child in bpy.data.objects if child.parent is not None and child.parent.name in {"bell", "mist", "cellar", "hall"}}
        self.assertEqual({name: (child.name, child.type) for name, child in children.items()}, {"bell": ("bell_speaker", "SPEAKER"), "mist": ("mist_fog", "MESH"), "cellar": ("cellar_probe", "LIGHT_PROBE"), "hall": ("hall_probe", "LIGHT_PROBE")})
        self.assertEqual(_native(children["bell"]), [before["bell"]["audio_player"]])
        self.assertEqual(_native(children["cellar"]), [{**before["cellar"]["reflection_probe"], "size": [2.0, 2.0, 2.0]}])
        self.assertEqual(_rounded(tuple(children["cellar"].scale)), (4.0, 2.5, 1.5))
        self.assertEqual((children["hall"].data.resolution_x, children["hall"].data.resolution_y, children["hall"].data.resolution_z), (10, 6, 4))
        fog = _native(children["mist"])[0]
        self.assertEqual({key: fog[key] for key in ("size", "color", "anisotropy", "light_intensity")}, {key: before["mist"]["fog_volume"][key] for key in ("size", "color", "anisotropy", "light_intensity")})
        self.assertAlmostEqual(fog["density"] * (fog["absorption"] + fog["scattering"]), 0.2 * (0.9 + 0.7), places=4)
        self.assertAlmostEqual(fog["density"] * fog["scattering"], 0.2 * 0.7, places=4)
        for obj in (bell, mist, cellar, hall, spot, crate, ball):
            self.assertEqual(len(obj.bevy_component_data.components), 0, obj.name)
        self.assertEqual(bpy.ops.bevy_components.convert_to_native(), {"FINISHED"})
        self.assertEqual(len([obj for obj in bpy.data.objects if obj.parent == bell]), 1)


WALKABLE = {"type": "navigation", "kind": "walkable", "cost": 2.0}


def _collection(name, *objects, parent=None):
    collection = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(collection)
    for obj in objects:
        collection.objects.link(obj)
    return collection


def _add_to(collection, kind, type_path="", **values):
    with bpy.context.temp_override(bevy_collection=collection):
        if "FINISHED" not in bpy.ops.bevy_components.add(component_type=kind, type_path=type_path):
            raise RuntimeError(f"Could not add {kind} to {collection.name}")
    item = collection.bevy_component_data.components[-1]
    for name, value in values.items():
        setattr(item, name, value)
    return item


def _components(obj):
    return [addon.metadata.serialize_component(item) for item in addon.system.components_for(obj)]


class TestCollectionComponents(unittest.TestCase):
    def setUp(self):
        clear_scene()
        for library in list(bpy.data.libraries):
            bpy.data.libraries.remove(library)

    def tearDown(self):
        clear_scene()
        for library in list(bpy.data.libraries):
            bpy.data.libraries.remove(library)

    def _messages(self):
        bpy.context.view_layer.update()
        return [addon.validation.describe(issue) for issue in addon.validation.check_objects(bpy.context.scene.objects)]

    def _context(self, obj, **values):
        return SimpleNamespace(**{"object": obj, "scene": bpy.context.scene, "region": None, "space_data": None, "view_layer": bpy.context.view_layer, "selected_objects": [], **values})

    def test_overview_and_select_include_blender_and_collection_components(self):
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=1)
        _rigid_body(crate)
        rock = add_mesh(bpy.ops.mesh.primitive_cube_add, "rock", size=1, location=(3, 0, 0))
        add_mesh(bpy.ops.mesh.primitive_cube_add, "plain", size=1, location=(6, 0, 0))
        _add_to(_collection("Ground", rock), "CUSTOM", type_path="my_game::Ground")
        bpy.context.view_layer.update()
        ui_list = SimpleNamespace(filter_name="", use_filter_invert=False, use_filter_sort_alpha=False, bitflag_filter_item=1 << 30)
        self.assertEqual(_shown_in_overview(ui_list), ["crate", "rock"])
        ui_list.filter_name = "ground"
        self.assertEqual(_shown_in_overview(ui_list), ["rock"])
        row = FakeLayout(self)
        addon.panel.BEVY_UL_objects.draw_item(ui_list, bpy.context, row, bpy.context.scene, crate, 0, bpy.context.scene.bevy_component_overview, "active")
        self.assertIn(addon.property.COMPONENT_LABELS["RIGID_BODY"][1], [bound.get("icon") for name, bound, layout in row.calls if name == "label"])
        self.assertEqual(bpy.ops.bevy_components.select_by_component(component_type="RIGID_BODY"), {"FINISHED"})
        self.assertEqual(bpy.context.selected_objects, [crate])
        self.assertEqual(bpy.ops.bevy_components.select_by_component(component_type="CUSTOM", type_path="my_game::Ground"), {"FINISHED"})
        self.assertEqual(bpy.context.selected_objects, [rock])
        menu = FakePanel(self)
        addon.menu.BEVY_MT_select_by_component.draw(menu, bpy.context)
        self.assertIn(("CUSTOM", "my_game::Ground"), [(properties.component_type, getattr(properties, "type_path", "")) for text, properties, enabled in menu.layout.buttons()])

    def test_collections_give_their_components_to_every_member(self):
        rock = add_mesh(bpy.ops.mesh.primitive_cube_add, "rock", size=1)
        pebble = add_mesh(bpy.ops.mesh.primitive_cube_add, "pebble", size=1, location=(3, 0, 0))
        lamp = add_light("lamp", "POINT", (0, 0, 3))
        ground = _collection("Ground", rock, pebble, lamp)
        _add_to(ground, "NAVIGATION", navigation_kind="WALKABLE", navigation_cost=2.0)
        _add_to(ground, "CUSTOM", type_path="my_game::Ground", custom_json='{"slip": 1}')
        ground_tag = {"type": "custom", "type_path": "my_game::Ground", "data": {"slip": 1}}
        self.assertEqual(_stored(rock)["components"], [WALKABLE, ground_tag])
        self.assertEqual(_stored(lamp)["components"][1:], [ground_tag])
        self.assertEqual(self._messages(), [])
        with bpy.context.temp_override(bevy_collection=ground):
            self.assertEqual(bpy.ops.bevy_components.add(component_type="COLLIDER"), {"CANCELLED"})
        mud = _collection("Mud", pebble, parent=ground)
        _add_to(mud, "NAVIGATION", navigation_kind="WALKABLE", navigation_cost=4.0)
        self.assertEqual(_stored(pebble)["components"], [{**WALKABLE, "cost": 4.0}, ground_tag])
        add_component(rock, "NAVIGATION", navigation_kind="OBSTACLE")
        self.assertEqual(_stored(rock)["components"], [OBSTACLE, ground_tag])
        rock.bevy_component_data.components[0].enabled = False
        self.assertEqual(_stored(rock)["components"], [WALKABLE, ground_tag])
        boulder = add_mesh(bpy.ops.mesh.primitive_cube_add, "boulder", size=1, location=(6, 0, 0))
        ground.objects.link(boulder)
        bpy.context.view_layer.update()
        self.assertEqual(_components(boulder), [WALKABLE, ground_tag])
        ground.bevy_component_data.components[0].navigation_cost = 3.0
        self.assertEqual(_stored(boulder)["components"][0]["cost"], 3.0)
        with tempfile.TemporaryDirectory() as directory:
            gltf = export_sample_scene(Path(directory) / "ground.glb")
        nodes = {node["name"]: node for node in gltf["nodes"]}
        self.assertEqual(_extras(gltf, nodes["boulder"])["components"], [{**WALKABLE, "cost": 3.0}, ground_tag])
        self.assertEqual(_extras(gltf, nodes["pebble"])["components"], [{**WALKABLE, "cost": 4.0}, ground_tag])
        self.assertFalse(any("bevy_component_data" in json.dumps(element.get("extras", {})) for key in ("nodes", "scenes") for element in gltf[key]))
        with bpy.context.temp_override(bevy_collection=ground):
            self.assertEqual(bpy.ops.bevy_components.remove(index=1), {"FINISHED"})
        self.assertEqual(_stored(boulder)["components"], [{**WALKABLE, "cost": 3.0}])
        bpy.data.collections.remove(mud)
        self.assertEqual(_components(pebble), [{**WALKABLE, "cost": 3.0}])

    def test_collections_that_disagree_warn_and_nesting_picks_the_winner(self):
        rock = add_mesh(bpy.ops.mesh.primitive_cube_add, "rock", size=1)
        ground = _collection("Ground", rock)
        swamp = _collection("Swamp", rock)
        _add_to(ground, "NAVIGATION", navigation_kind="WALKABLE", navigation_cost=2.0)
        _add_to(swamp, "NAVIGATION", navigation_kind="WALKABLE", navigation_cost=2.0)
        self.assertEqual(self._messages(), [])
        swamp.bevy_component_data.components[0].navigation_cost = 5.0
        self.assertEqual(self._messages(), ["rock: Ground and Swamp both give it Navigation with different settings, so it uses Ground's. Put one collection inside the other to choose"])
        self.assertEqual(_stored(rock)["components"], [WALKABLE])
        bpy.context.scene.collection.children.unlink(swamp)
        ground.children.link(swamp)
        self.assertEqual(self._messages(), [])
        self.assertEqual(_components(rock), [{**WALKABLE, "cost": 5.0}])
        add_component(rock, "NAVIGATION", navigation_kind="OBSTACLE")
        self.assertEqual(_components(rock), [OBSTACLE])

    def test_collection_cards_report_problems_once(self):
        stones = [add_mesh(bpy.ops.mesh.primitive_cube_add, f"stone_{index}", size=1, location=(index * 2, 0, 0)) for index in range(3)]
        marker = add_empty("marker", (0, 4, 0))
        rubble = _collection("Rubble", *stones, marker)
        custom = _add_to(rubble, "CUSTOM", type_path="my_game::Rubble", custom_json="{")
        _add_to(rubble, "VISIBILITY_RANGE", fade_in_start=10.0, fade_in_end=5.0)
        self.assertEqual(sorted(self._messages()), [
            "marker: No mesh on this object or under it to show or hide",
            "stone_0: Visibility Range must satisfy 0 <= in.start <= in.end <= out.start <= out.end, in collection Rubble",
            "stone_0: invalid JSON in Custom Component, in collection Rubble",
        ])
        self.assertEqual([(issue.level, issue.message) for issue in addon.validation.collection_issues(rubble)], [("ERROR", "invalid JSON in Custom Component"), ("ERROR", "Visibility Range must satisfy 0 <= in.start <= in.end <= out.start <= out.end")])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "invalid JSON in Custom Component, in collection Rubble"):
                export_sample_scene(Path(directory) / "rubble.glb")
        custom.custom_json = '{"weight": 2}'
        with bpy.context.temp_override(bevy_collection=rubble):
            self.assertEqual(bpy.ops.bevy_components.lod_preset(index=1, preset="MID"), {"FINISHED"})
        self.assertEqual(_stored(stones[2])["components"][1], {"type": "visibility_range", "start": [20.0, 25.0], "end": [80.0, 85.0], "use_aabb": False})
        with bpy.context.temp_override(bevy_collection=rubble):
            self.assertEqual(bpy.ops.bevy_components.edit_as_text(index=0), {"FINISHED"})
        text = bpy.data.texts["Rubble Rubble.json"]
        self.assertEqual(text["bevy_object"], rubble)
        text.from_string('{"weight": 7}')
        self.assertEqual(_execute(addon.operator.BEVY_OT_apply_text, SimpleNamespace(space_data=SimpleNamespace(text=text))), ({"FINISHED"}, [({"INFO"}, "Applied Rubble Rubble.json to Rubble")]))
        self.assertEqual(_stored(stones[1])["components"][0]["data"], {"weight": 7})
        bpy.data.texts.remove(text)
        rubble.bevy_component_data.components.add().component_type = "COLLIDER"
        self.assertEqual(addon.validation.collection_issues(rubble)[-1].message, "Collections only pass on game and custom components, Navigation and Visibility Range, so its objects do not get this one")
        self.assertNotIn("collider", json.dumps(_stored(stones[0])))

    def test_typed_collection_components_follow_their_definition(self):
        define_component("my_game::Loot", ("gold", "INT", 5))
        chest = add_mesh(bpy.ops.mesh.primitive_cube_add, "chest", size=1)
        loot = _collection("Loot", chest)
        item = _add_to(loot, "CUSTOM", type_path="my_game::Loot")
        self.assertTrue(item.use_fields)
        self.assertEqual(_stored(chest)["components"], [{"type": "custom", "type_path": "my_game::Loot", "data": {"gold": 5}}])
        set_fields(item, gold=9)
        self.assertEqual(_stored(chest)["components"][0]["data"], {"gold": 9})
        library = bpy.context.scene.bevy_component_definitions
        library.definitions[0].name = "my_game::Treasure"
        self.assertEqual(item.custom_type, "my_game::Treasure")
        self.assertEqual(_stored(chest)["components"][0]["type_path"], "my_game::Treasure")
        library.active_index = 0
        self.assertEqual(bpy.ops.bevy_components.definition_remove(), {"FINISHED"})
        self.assertFalse(item.use_fields)
        self.assertEqual(_stored(chest)["components"][0]["data"], {"gold": 9})

    def test_collection_panel_and_inherited_rows(self):
        rock = add_mesh(bpy.ops.mesh.primitive_cube_add, "rock", size=1)
        pebble = add_mesh(bpy.ops.mesh.primitive_cube_add, "pebble", size=1, location=(3, 0, 0))
        ground = _collection("Ground", rock, pebble)
        context = self._context(rock, collection=ground)
        self.assertTrue(addon.panel.BEVY_PT_collection_components.poll(context))
        self.assertFalse(addon.panel.BEVY_PT_collection_components.poll(self._context(rock, collection=bpy.context.scene.collection)))
        panel = FakePanel(self)
        addon.panel.BEVY_PT_collection_components.draw(panel, context)
        self.assertEqual(panel.layout.menus(), ["BEVY_MT_component_add"])
        self.assertIn("Link objects to it with Ctrl+L > Link to Collection", " ".join(panel.layout.texts()))
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_add.draw(menu, SimpleNamespace(bevy_collection=ground, object=rock, scene=bpy.context.scene))
        self.assertEqual([text for text, properties, enabled in menu.layout.buttons()], ["Custom Component", "Navigation", "Visibility Range"])
        self.assertEqual(menu.layout.menus(), [])
        self.assertIn(("context_pointer_set", "bevy_collection"), [(name, bound.get("name")) for name, bound, layout in menu.layout.calls])
        _add_to(ground, "NAVIGATION", navigation_kind="WALKABLE")
        panel = FakePanel(self)
        addon.panel.BEVY_PT_collection_components.draw(panel, context)
        self.assertIn("2 objects get these components, unless the object or a collection inside this one sets its own", " ".join(panel.layout.texts()))
        self.assertIn("Navigation", panel.layout.texts())
        self.assertIn("navigation_kind", panel.layout.props())
        menu = FakePanel(self)
        addon.menu.BEVY_MT_component_context_menu.draw(menu, SimpleNamespace(bevy_collection=ground, object=rock, bevy_component=ground.bevy_component_data.components[0], scene=bpy.context.scene))
        self.assertNotIn("Copy to Selected", menu.layout.texts())
        self.assertIn("Remove", menu.layout.texts())
        panel = FakePanel(self)
        addon.panel.draw_components(panel.layout, self._context(rock), rock)
        self.assertIn("Navigation from Ground", panel.layout.texts())
        button = next(properties for text, properties, enabled in panel.layout.buttons() if getattr(properties, "collection", None) == "Ground")
        add_component(rock, "NAVIGATION", navigation_kind="OBSTACLE")
        panel = FakePanel(self)
        addon.panel.draw_components(panel.layout, self._context(rock), rock)
        self.assertIn("Replaced by the Navigation on this object", " ".join(panel.layout.texts()))
        bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection
        space = SimpleNamespace(type="PROPERTIES", context="OBJECT")
        self.assertEqual(_execute(addon.operator.BEVY_OT_show_collection, self._context(rock, space_data=space), collection=button.collection), ({"FINISHED"}, []))
        self.assertEqual(space.context, "COLLECTION")
        self.assertEqual(bpy.context.view_layer.active_layer_collection.collection, ground)

    def test_linked_collections_carry_their_components(self):
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=1)
        props = _collection("Props", crate)
        _add_to(props, "CUSTOM", type_path="my_game::Prop", custom_json="{}")
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "props.blend"
            bpy.data.libraries.write(str(library), {props})
            clear_scene()
            with bpy.data.libraries.load(str(library), link=True) as (source, target):
                target.collections = ["Props"]
            linked = target.collections[0]
            bpy.context.scene.collection.children.link(linked)
            crate = next(obj for obj in bpy.data.objects if obj.library is not None)
            _add_to(_collection("Loot", crate), "NAVIGATION", navigation_kind="OBSTACLE")
            self.assertEqual(_components(crate), [OBSTACLE, {"type": "custom", "type_path": "my_game::Prop", "data": {}}])
            panel = FakePanel(self)
            addon.panel.BEVY_PT_collection_components.draw(panel, self._context(crate, collection=linked))
            self.assertIn("Linked from props.blend, so edit its components in that file", " ".join(panel.layout.texts()))
            gltf = export_sample_scene(Path(directory) / "level.glb")
        node = next(node for node in gltf["nodes"] if node["name"] == "crate")
        self.assertEqual(_extras(gltf, node)["components"], [OBSTACLE, {"type": "custom", "type_path": "my_game::Prop", "data": {}}])

    def test_prefabs_change_with_their_collection_components(self):
        box = add_mesh(bpy.ops.mesh.primitive_cube_add, "box", size=1)
        crate = _collection("Crate", box)
        settings = addon.prefab.prefab_settings(bpy.context.scene.bevy_glb_export)
        before = addon.prefab.prefab_fingerprint(crate, settings, bpy.context.scene)
        _add_to(_collection("Breakable", box), "CUSTOM", type_path="my_game::Breakable", custom_json="{}")
        self.assertNotEqual(addon.prefab.prefab_fingerprint(crate, settings, bpy.context.scene), before)


class TestLeaveOut(unittest.TestCase):
    def setUp(self):
        clear_scene()

    def tearDown(self):
        clear_scene()

    def _messages(self):
        bpy.context.view_layer.update()
        return [addon.validation.describe(issue) for issue in addon.validation.check_objects(bpy.data.objects)]

    def _context(self, obj, **values):
        return SimpleNamespace(**{"object": obj, "scene": bpy.context.scene, "region": None, "space_data": None, "view_layer": bpy.context.view_layer, "selected_objects": [], **values})

    def _texts(self, obj):
        panel = FakePanel(self)
        addon.panel.draw_components(panel.layout, self._context(obj), obj)
        return panel.layout

    def test_objects_left_out_export_only_their_own_components(self):
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=1)
        _rigid_body(crate, shape="BOX")
        crate.visible_shadow = False
        add_component(crate, "CUSTOM", type_path="my_game::Helper", custom_json="{}")
        _add_to(_collection("Ground", crate), "NAVIGATION", navigation_kind="WALKABLE", navigation_cost=2.0)
        self.assertEqual([component["type"] for component in _native(crate)], ["custom", "rigid_body", "collider", "shadows", "navigation"])
        self.assertNotIn("leave_out", self._texts(add_mesh(bpy.ops.mesh.primitive_cube_add, "plain", size=1, location=(4, 0, 0))).props())
        layout = self._texts(crate)
        self.assertIn("leave_out", layout.props())
        self.assertIn("Collider from Physics", layout.texts())
        crate.bevy_component_data.leave_out = True
        self.assertEqual(_stored(crate)["components"], [{"type": "custom", "type_path": "my_game::Helper", "data": {}}])
        layout = self._texts(crate)
        self.assertIn("leave_out", layout.props())
        self.assertNotIn("Collider from Physics", layout.texts())
        self.assertNotIn("Navigation from Ground", layout.texts())
        self.assertIn("Exports as plain glTF, without components from Blender's settings or collections", " ".join(layout.texts()))
        self.assertIn("Helper", layout.texts())
        panel = FakePanel(self)
        addon.panel.BEVY_PT_physics_rigid_body.draw(panel, self._context(crate))
        self.assertIn("Left out of Bevy in Object > Game Components, so the game gets none of these settings", " ".join(panel.layout.texts()))
        self.assertNotIn("gravity_scale", panel.layout.props())
        panel = FakePanel(self)
        addon.panel.draw_visibility(panel, SimpleNamespace(object=crate))
        self.assertFalse(_prop_layout(panel.layout, "receive_shadows").active)
        self.assertEqual(self._messages(), [])
        with tempfile.TemporaryDirectory() as directory:
            gltf = export_sample_scene(Path(directory) / "left_out.glb")
        node = next(node for node in gltf["nodes"] if node["name"] == "crate")
        self.assertEqual(_extras(gltf, node)["components"], [{"type": "custom", "type_path": "my_game::Helper", "data": {}}])
        crate.bevy_component_data.leave_out = False
        self.assertEqual(len(_stored(crate)["components"]), 5)

    def test_left_out_data_objects_export_as_plain_glTF(self):
        fog = add_mesh(bpy.ops.mesh.primitive_cube_add, "fog", size=2)
        fog.data.materials.append(_volume_material("haze", {"Density": 0.5})[0])
        lamp = add_light("lamp", "POINT", (0, 0, 3))
        mirror = _add_object(bpy.ops.object.lightprobe_add, type="PLANE", location=(4, 0, 0))
        speaker = _add_object(bpy.ops.object.speaker_add, location=(0, 4, 0))
        hinge = add_empty("hinge", (0, 0, 0))
        _constraint(hinge, "MOTOR")
        self.assertEqual(sorted(self._messages()), sorted([
            "hinge: Bevy has no Motor joint, so the game leaves this Rigid Body Constraint out. Use Fixed, Point, Hinge or Slider",
            f"{mirror.name}: Bevy has no planar reflections, so the game leaves this Light Probe out",
            f"{speaker.name}: No sound picked, so nothing plays",
        ]))
        for obj in (fog, lamp, mirror, speaker, hinge):
            obj.bevy_component_data.leave_out = True
        self.assertEqual(self._messages(), [])
        self.assertEqual(_native(fog), [])
        self.assertEqual(_native(lamp), [])
        with tempfile.TemporaryDirectory() as directory:
            gltf = export_sample_scene(Path(directory) / "plain.glb")
        nodes = {node["name"]: node for node in gltf["nodes"]}
        self.assertIn("mesh", nodes["fog"])
        self.assertNotIn("bevy_components", nodes["fog"].get("extras") or {})
        self.assertNotIn("bevy_components", nodes["lamp"].get("extras") or {})
        fog.bevy_component_data.leave_out = False
        self.assertEqual([component["type"] for component in _native(fog)], ["fog_volume"])

    def test_collections_leave_out_every_member(self):
        rock = add_mesh(bpy.ops.mesh.primitive_cube_add, "rock", size=1)
        _rigid_body(rock, "PASSIVE", "MESH")
        pebble = add_mesh(bpy.ops.mesh.primitive_cube_add, "pebble", size=1, location=(3, 0, 0))
        ground = _collection("Ground", rock, pebble)
        _add_to(ground, "NAVIGATION", navigation_kind="WALKABLE", navigation_cost=2.0)
        reference = _collection("Reference")
        blockout = _collection("Blockout", rock, parent=reference)
        self.assertEqual([component["type"] for component in _native(rock)], ["rigid_body", "collider", "navigation"])
        reference.bevy_component_data.leave_out = True
        self.assertEqual(_components(rock), [])
        self.assertNotIn("bevy_components", rock)
        self.assertEqual(_components(pebble), [WALKABLE])
        layout = self._texts(rock)
        self.assertIn("Left out of Bevy by collection Reference", layout.texts())
        self.assertIn("Reference", [getattr(properties, "collection", None) for text, properties, enabled in layout.buttons()])
        panel = FakePanel(self)
        addon.panel.BEVY_PT_physics_collisions.draw(panel, self._context(rock))
        self.assertIn("Left out of Bevy by collection Reference, so the game gets none of these settings", " ".join(panel.layout.texts()))
        panel = FakePanel(self)
        addon.panel.BEVY_PT_collection_components.draw(panel, self._context(rock, collection=reference))
        self.assertIn("leave_out", panel.layout.props())
        self.assertIn("Every object in this collection and the collections inside it exports as plain glTF", " ".join(panel.layout.texts()))
        self.assertNotIn("Link objects to it with Ctrl+L", " ".join(panel.layout.texts()))
        blockout.bevy_component_data.leave_out = True
        reference.bevy_component_data.leave_out = False
        self.assertEqual(_components(rock), [])
        blockout.objects.unlink(rock)
        bpy.context.view_layer.update()
        self.assertEqual([component["type"] for component in _components(rock)], ["rigid_body", "collider", "navigation"])

    def test_left_out_compound_parents_free_their_children(self):
        cart = add_mesh(bpy.ops.mesh.primitive_cube_add, "cart", size=1)
        _rigid_body(cart, shape="COMPOUND")
        wheel = add_mesh(bpy.ops.mesh.primitive_cylinder_add, "wheel", radius=0.5, depth=0.2, location=(0, 0, -0.5))
        wheel.parent = cart
        _rigid_body(wheel, shape="CYLINDER")
        self.assertEqual([component["type"] for component in _native(wheel)], ["collider"])
        self.assertFalse(addon.panel.BEVY_PT_physics_rigid_body.poll(self._context(wheel)))
        cart.bevy_component_data.leave_out = True
        self.assertEqual([component["type"] for component in _native(wheel)], ["rigid_body", "collider"])
        self.assertTrue(addon.panel.BEVY_PT_physics_rigid_body.poll(self._context(wheel)))
        self.assertEqual(self._messages(), [])

    def test_convert_keeps_components_on_left_out_objects(self):
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=2)
        add_component(crate, "COLLIDER", collider_shape="CUBOID", collider_size=(2, 2, 2))
        crate.bevy_component_data.leave_out = True
        converted, kept = addon.convert.convert_objects(bpy.context, [crate])
        self.assertEqual(converted, [])
        self.assertEqual(kept, [(crate, "it is left out of Bevy, so Blender's settings would not reach the game")])
        self.assertIsNone(crate.rigid_body)
        self.assertEqual([component["type"] for component in _stored(crate)["components"]], ["collider"])


class TestValidation(unittest.TestCase):
    def setUp(self):
        clear_scene()

    def _messages(self, obj=None, modifiers=True):
        issues = addon.validation.check_objects(bpy.data.objects, modifiers=modifiers) if obj is None else addon.validation.check_object(obj, bpy.data.objects, modifiers=modifiers)
        return [addon.validation.describe(issue) for issue in issues]

    def test_sample_scene_is_clean(self):
        build_sample_scene()
        self.assertEqual(self._messages(), [])

    def test_checks_run_again_only_for_objects_that_changed(self):
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate")
        add_component(crate, "RIGID_BODY", rigid_body_kind="DYNAMIC")
        rock = add_mesh(bpy.ops.mesh.primitive_ico_sphere_add, "rock", location=(4, 0, 0))
        add_component(rock, "COLLIDER", collider_shape="CONVEX")
        hinge = add_empty("hinge", (2, 0, 0))
        joint = add_component(hinge, "JOINT")
        joint.joint_body1 = rock
        bpy.context.view_layer.update()
        with mock.patch.object(addon.validation, "_caching", lambda: True), mock.patch.object(addon.validation, "_object_issues", wraps=addon.validation._object_issues) as checked:
            checked_names = lambda: sorted(call.args[0].name for call in checked.call_args_list)
            first = self._messages()
            self.assertEqual(checked_names(), ["crate", "hinge", "rock"])
            self.assertEqual(first, ["crate: Dynamic body has no collider on it or under it, so it has no mass and collides with nothing", "hinge: rock is static, so pinning it does nothing"])
            checked.reset_mock()
            issues = addon.validation.check_objects(bpy.data.objects)
            self.assertEqual(checked_names(), [])
            self.assertEqual([addon.validation.describe(issue) for issue in issues], first)
            self.assertEqual([issue.item.component_type for issue in issues], ["RIGID_BODY", "JOINT"])
            rock.location.x = 6
            self.assertEqual(self._messages(), first)
            self.assertEqual(checked_names(), ["hinge", "rock"])
            checked.reset_mock()
            add_component(crate, "COLLIDER", collider_shape="CUBOID")
            self.assertEqual(self._messages(), first[1:])
            self.assertEqual(checked_names(), ["crate"])
            checked.reset_mock()
            self.assertEqual(self._messages(hinge), first[1:])
            self.assertEqual(checked_names(), [])
            self.assertEqual(self._messages(hinge, modifiers=False), first[1:])
            self.assertEqual(checked_names(), ["hinge"])
            checked.reset_mock()
            addon.changes.forget_revisions()
            self.assertEqual(self._messages(), first[1:])
            self.assertEqual(checked_names(), ["crate", "hinge", "rock"])

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

    def test_collision_only_needs_a_mesh_to_hide(self):
        holder = add_empty("holder", (0, 0, 0))
        add_component(holder, "COLLIDER", collider_shape="CUBOID", collider_collision_only=True)
        self.assertEqual(self._messages(), ["holder: Collision Only finds no mesh on this object or under it to hide"])
        child = add_mesh(bpy.ops.mesh.primitive_cube_add, "child")
        child.parent = holder
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

    def test_navigation_needs_a_mesh_or_collider(self):
        group = add_empty("group", (0, 0, 0))
        navigation = add_component(group, "NAVIGATION")
        self.assertEqual(self._messages(), ["group: No mesh or collider on this object or under it to tag for navigation"])
        navigation.navigation_kind = "IGNORED"
        self.assertEqual(self._messages(), [])
        navigation.navigation_kind = "OBSTACLE"
        handle = add_empty("handle", (0, 0, 0))
        add_component(handle, "COLLIDER", collider_shape="SPHERE")
        handle.parent = group
        self.assertEqual(self._messages(), [])
        add_component(handle, "NAVIGATION")
        self.assertEqual(self._messages(), ["group: No mesh or collider on this object or under it to tag for navigation"])
        child = add_mesh(bpy.ops.mesh.primitive_cube_add, "child")
        child.parent = group
        self.assertEqual(self._messages(), [])

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
        self.assertEqual(_stored(speaker)["components"][0]["path"], "sounds/fire.ogg")

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
        self.assertEqual([addon.validation.describe(issue) for issue in addon.validation.check_objects([hinge, door])], ["hinge: wall is not exported with this scene, so the joint holds nothing"])
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
            reference.scene_file = str(root / "scene.glb")
            (root / "scene.glb").write_bytes((FIXTURE.parent / PROP).read_bytes())
            issues = addon.validation.check_objects(bpy.data.objects, destination=root / "scene.glb")
            self.assertEqual([addon.validation.describe(issue) for issue in issues], ["holder: Spawns the exported scene inside itself, so the game skips it"])

    def test_scene_references_on_another_drive_block_export(self):
        holder = add_empty("holder", (0, 0, 0))
        add_component(holder, "SCENE_REFERENCE", scene_file=str(FIXTURE.parent / PROP))
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(addon.validation, "scene_path", side_effect=ValueError("path is on mount 'D:', start on mount 'C:'")):
            path = Path(directory) / "scene.glb"
            with self.assertRaisesRegex(RuntimeError, "Cannot export: holder: windmill.glb is on another drive than the exported scene, so the game cannot load it"):
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

    def test_lightmaps(self):
        floor = add_mesh(bpy.ops.mesh.primitive_plane_add, "floor")
        item = add_component(floor, "LIGHTMAP")
        self.assertEqual(self._messages(), ["floor: No second UV map, which Bevy reads lightmaps with. Click Unwrap Lightmap UVs", "floor: No lightmap baked yet, so the mesh gets no baked light"])
        bpy.ops.bevy_components.unwrap_lightmap()
        item.probe_file = str(LIGHTMAP)
        self.assertEqual(self._messages(), [])
        item.probe_file = str(CUBEMAP)
        self.assertEqual(self._messages(), ["floor: probe_cubemap.ktx2 is not a 2D texture"])
        item.probe_file = str(LIGHTMAP)
        modifier = floor.modifiers.new("Bevel", "BEVEL")
        self.assertEqual(self._messages(), [])
        self.assertEqual(self._messages(modifiers=False), ["floor: Bake includes the Bevel modifier but the export leaves it out, so the lightmap may not fit. Turn on Apply Modifiers"])
        modifier.show_viewport = False
        self.assertEqual(self._messages(), ["floor: Bake includes the Bevel modifier but the export leaves it out, so the lightmap may not fit. Show it in the viewport"])
        modifier.show_viewport = True
        modifier.show_render = False
        self.assertEqual(self._messages(), ["floor: Export includes the Bevel modifier but the bake leaves it out, so the lightmap may not fit. Enable it in renders"])
        self.assertEqual(self._messages(modifiers=False), [])
        modifier.show_render = True
        holder = add_empty("holder", (0, 0, 0))
        holder.bevy_component_data.components.add().component_type = "LIGHTMAP"
        self.assertEqual(self._messages(), ["holder: Only meshes use lightmaps, so it is not exported"])

    def test_shape_keys_on_meshes_with_modifiers(self):
        blob = add_mesh(bpy.ops.mesh.primitive_plane_add, "blob")
        blob.shape_key_add(name="Basis")
        blob.modifiers.new("Bevel", "BEVEL")
        self.assertEqual(self._messages(), [])
        blob.shape_key_add(name="Puff")
        self.assertEqual(self._messages(), ["blob: glTF leaves out the shape keys of meshes with modifiers. Apply the modifiers, or turn off Apply Modifiers"])
        self.assertEqual(self._messages(modifiers=False), [])
        blob.modifiers.clear()
        self.assertEqual(self._messages(), [])

    def test_materials_gltf_flattens(self):
        obj = add_mesh(bpy.ops.mesh.primitive_cube_add, "painted")
        material, principled = add_material("noisy")
        obj.data.materials.append(material)
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        output = nodes["Material Output"]
        self.assertEqual(self._messages(), [])
        noise = nodes.new("ShaderNodeTexNoise")
        links.new(noise.outputs["Color"], principled.inputs["Base Color"])
        self.assertEqual(self._messages(), ["painted: Material noisy drives Base Color with procedural nodes, which glTF leaves out. Bake them to images"])
        links.new(noise.outputs["Fac"], principled.inputs["Roughness"])
        links.new(noise.outputs["Fac"], principled.inputs["Metallic"])
        self.assertEqual(self._messages(), ["painted: Material noisy drives Base Color, Metallic and Roughness with procedural nodes, which glTF leaves out. Bake them to images"])
        links.new(noise.outputs["Fac"], principled.inputs["Alpha"])
        self.assertEqual(self._messages(), ["painted: Material noisy drives Base Color, Metallic and 2 more inputs with procedural nodes, which glTF leaves out. Bake them to images"])
        image = nodes.new("ShaderNodeTexImage")
        links.new(nodes.new("ShaderNodeTexCoord").outputs["UV"], image.inputs["Vector"])
        for name in ("Base Color", "Metallic", "Roughness", "Alpha"):
            links.new(image.outputs[0], principled.inputs[name])
        self.assertEqual(self._messages(), [])
        mix = nodes.new("ShaderNodeMixShader")
        other = nodes.new("ShaderNodeBsdfGlossy")
        links.new(principled.outputs[0], mix.inputs[1])
        links.new(other.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], output.inputs["Surface"])
        self.assertEqual(self._messages(), ["painted: Material noisy mixes shaders, which glTF flattens into one"])
        nodes.remove(other)
        links.new(nodes.new("ShaderNodeBsdfTransparent").outputs[0], mix.inputs[2])
        self.assertEqual(self._messages(), [])
        nodes.remove(mix)
        nodes.remove(principled)
        links.new(nodes.new("ShaderNodeBsdfDiffuse").outputs[0], output.inputs["Surface"])
        self.assertEqual(self._messages(), ["painted: Material noisy has no Principled BSDF, so glTF exports it plain white"])
        links.new(nodes.new("ShaderNodeEmission").outputs[0], output.inputs["Surface"])
        self.assertEqual(self._messages(), [])

    def test_shared_materials_warn_once(self):
        material, principled = add_material("matte")
        nodes = material.node_tree.nodes
        nodes.remove(principled)
        material.node_tree.links.new(nodes.new("ShaderNodeBsdfDiffuse").outputs[0], nodes["Material Output"].inputs["Surface"])
        first = add_mesh(bpy.ops.mesh.primitive_cube_add, "first")
        second = add_mesh(bpy.ops.mesh.primitive_cube_add, "second", location=(3, 0, 0))
        for obj in (first, second):
            obj.data.materials.append(material)
        self.assertEqual(self._messages(), ["first: Material matte has no Principled BSDF, so glTF exports it plain white"])
        self.assertEqual(self._messages(second), ["second: Material matte has no Principled BSDF, so glTF exports it plain white"])
        self.assertEqual([issue.level for issue in addon.validation.check_objects(bpy.data.objects)], ["WARNING"])

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

    def test_world_sky_checks(self):
        world = bpy.context.scene.world
        self.addCleanup(world.property_unset, "bevy_sky")
        check = lambda: [(issue.level, addon.validation.describe(issue)) for issue in addon.validation.check_world(world)]
        self.assertEqual(check(), [])
        world.bevy_sky.enabled = True
        self.assertEqual(check(), [("WARNING", "Bevy Sky: No cubemap baked yet, so Bevy shows no sky")])
        world.bevy_sky.sky_file = str(CUBEMAP)
        self.assertEqual(check(), [])
        world.bevy_ambient_light.enabled = True
        self.assertEqual(check(), [("WARNING", "Bevy Ambient Light takes the World color, which the Bevy Sky's environment light already gives, so meshes get the World's light twice")])
        world.bevy_ambient_light.use_world_color = False
        self.assertEqual(check(), [])
        world.bevy_ambient_light.use_world_color = True
        world.bevy_sky.environment_light = False
        self.assertEqual(check(), [])
        world.bevy_sky.sky_file = str(LIGHTMAP)
        self.assertEqual(check(), [("ERROR", "Bevy Sky: ground_lightmap.ktx2 is not a cubemap")])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scene.glb"
            with self.assertRaisesRegex(RuntimeError, "1 problem blocks export: Bevy Sky: ground_lightmap.ktx2 is not a cubemap"):
                bpy.ops.bevy_components.validate()
            with self.assertRaisesRegex(RuntimeError, "Cannot export: Bevy Sky: ground_lightmap.ktx2 is not a cubemap"):
                bpy.ops.export_scene.bevy_components_glb(filepath=str(path))
            self.assertFalse(path.exists())
            world.bevy_sky.sky_file = str(Path(directory) / "missing.ktx2")
            self.assertEqual(check(), [("ERROR", "Bevy Sky: Cubemap file missing.ktx2 was not found")])
            operator = _dialog(self, addon.operator.BEVY_OT_export_glb)
            addon.operator.BEVY_OT_export_glb.draw(operator, bpy.context)
            self.assertIn("Bevy Sky: Cubemap file missing.ktx2 was not found", " ".join(operator.layout.texts()))

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
        self.assertEqual(self._messages(window), ["window: Bevy area lights are rectangles, so this disk becomes a 1.5 × 1.5 m rectangle"])
        light = add_component(window, "LIGHT", light_volumetric=True)
        self.assertEqual(self._messages(window), ["window: Bevy area lights are rectangles, so this disk becomes a 1.5 × 1.5 m rectangle"])
        window.data.shape = "ELLIPSE"
        window.data.size_y = 0.5
        self.assertEqual(self._messages(window), ["window: Bevy area lights are rectangles, so this ellipse becomes a 1.5 × 0.5 m rectangle"])
        window.data.shape = "RECTANGLE"
        self.assertEqual(self._messages(window), [])
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
            path = Path(directory) / "scene.glb"
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
        icons = [(bound.get("text"), bound.get("icon")) for name, bound, layout in panel.layout.calls if name == "label" and bound.get("text") in {"Rigid Body", "Collider", "MyComponent"}]
        self.assertEqual(icons, [("Rigid Body", addon.property.COMPONENT_LABELS["RIGID_BODY"][1]), ("Collider", "ERROR"), ("MyComponent", "CANCEL")])

    def test_export_dialog_lists_problems(self):
        properties = bpy.ops.export_scene.bevy_components_glb.get_rna_type()
        operator = _dialog(self, addon.operator.BEVY_OT_export_glb)
        addon.operator.BEVY_OT_export_glb.draw(operator, bpy.context)
        self.assertIn("No problems found", operator.layout.texts())
        for index in range(8):
            add_component(add_empty(f"holder_{index}", (index, 0, 0)), "VISIBILITY_RANGE")
        operator = _dialog(self, addon.operator.BEVY_OT_export_glb)
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
        build_sample_scene(cls.directory.name)
        cls.gltf = export_sample_scene(Path(cls.directory.name) / "sample_scene.glb")
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

    def test_ambient_light_and_sky_are_exported_on_the_scene(self):
        exported = json.loads(self.gltf["scenes"][0]["extras"]["bevy_components"])
        self.assertEqual((exported["version"], exported["addon"]), (1, addon.metadata.addon_version()))
        self.assertEqual(_named_textures(self.gltf, exported["components"]), [{"type": "ambient_light", "color": [0.9, 0.95, 1.0], "brightness": 120.0, "baked": False}, {"type": "sky", "brightness": 1000.0, "environment_light": 300.0, "texture": "probe_cubemap"}])
        self.assertEqual(self.gltf["textures"][exported["components"][1]["texture"]], self.gltf["textures"][json.loads(self.nodes["room_probe"]["extras"]["bevy_components"])["components"][0]["texture"]])
        world = bpy.context.scene.world
        path = Path(self.directory.name) / "scene_lighting.glb"
        scene_components = lambda: [component for scene in export_sample_scene(path)["scenes"] for component in json.loads(scene["extras"]["bevy_components"])["components"]]
        world.bevy_ambient_light.enabled = False
        try:
            self.assertEqual([(component["type"], component.get("brightness")) for component in scene_components()], [("ambient_light", 0.0), ("sky", 1000.0)])
            world.bevy_sky.environment_light = False
            self.assertEqual([component["type"] for component in scene_components()], ["sky"])
            world.bevy_sky.enabled = False
            self.assertEqual([json.loads(scene["extras"]["bevy_components"]) for scene in export_sample_scene(path)["scenes"]], [{"version": 1, "addon": addon.metadata.addon_version(), "components": []}])
        finally:
            world.bevy_ambient_light.enabled = True
            world.bevy_sky.enabled = True
            world.bevy_sky.environment_light = True

    def test_export_again_uses_the_remembered_settings(self):
        path = Path(self.directory.name) / "again" / "again.glb"
        gltf = export_sample_scene(path, include_lights=False)
        settings = bpy.context.scene.bevy_glb_export
        self.assertEqual((_resolved(settings.filepath), settings.include_lights, settings.include_animations, settings.texture_compression), (path, False, True, "DISABLED"))
        self.assertNotIn("KHR_lights_punctual", gltf.get("extensionsUsed", []))
        dialog = _open_dialog(addon.operator.BEVY_OT_export_glb)
        self.assertEqual((Path(dialog.filepath), dialog.include_lights, dialog.include_animations), (path, False, True))
        dialog = _open_dialog(addon.operator.BEVY_OT_export_glb, filepath=str(path.with_name("picked.glb")), include_lights=True)
        self.assertEqual((Path(dialog.filepath), dialog.include_lights), (path.with_name("picked.glb"), True))
        path.unlink()
        self.assertEqual(bpy.ops.export_scene.bevy_components_glb(again=True), {"FINISHED"})
        self.assertEqual(read_gltf(path), gltf)

    def test_export_again_needs_an_earlier_export(self):
        with _remembered_exports():
            with self.assertRaisesRegex(RuntimeError, "Nothing to export again yet"):
                bpy.ops.export_scene.bevy_components_glb(again=True)

    def test_light_data_is_read_at_export(self):
        window = bpy.data.objects["window_light"]
        path = Path(self.directory.name) / "dimmer.glb"
        window.data.energy = 10
        window.data.size = 3
        try:
            node = next(node for node in export_sample_scene(path)["nodes"] if node["name"] == "window_light")
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
        self.assertTrue(FIXTURE.is_file(), f"Missing {FIXTURE}, run tests/blender/sample_scene.py to create it")
        self.assertEqual(_node_summary(read_gltf(FIXTURE)), _node_summary(self.gltf), "importer/tests/assets/sample_scene.glb is out of date, run tests/blender/sample_scene.py to regenerate it")

    def test_prop_fixture_is_current(self):
        path = FIXTURE.parent / PROP
        self.assertTrue(path.is_file(), f"Missing {path}, run tests/blender/sample_scene.py to create it")
        self.assertEqual(_node_summary(read_gltf(path)), _node_summary(self.props), f"importer/tests/assets/{PROP.as_posix()} is out of date, run tests/blender/sample_scene.py to regenerate it")

    def test_animations_start_at_zero(self):
        for gltf, name in ((self.gltf, "gate_open"), (self.props, "windmill_spin")):
            self.assertEqual([animation["name"] for animation in gltf["animations"]], [name])
            inputs = {gltf["accessors"][sampler["input"]]["min"][0] for sampler in gltf["animations"][0]["samplers"]}
            self.assertEqual(inputs, {0.0}, name)
        blades = json.loads(next(node for node in self.props["nodes"] if node["name"] == "windmill_blades")["extras"]["bevy_components"])
        self.assertEqual(blades["components"], [{"type": "animation", "clip": "windmill_spin", "repeat": True, "speed": 0.5}])

    def test_scene_reference_paths_follow_the_exported_scene(self):
        path = Path(self.directory.name) / "scenes" / "scene.glb"
        gltf = export_sample_scene(path, include_animations=False)
        nodes = {node["name"]: node for node in gltf["nodes"]}
        self.assertEqual(json.loads(nodes["windmill_a"]["extras"]["bevy_components"])["components"], [{**WINDMILL, "path": "../props/windmill.glb"}])
        self.assertEqual(json.loads(nodes["lamp_post_b"]["extras"]["bevy_components"])["components"], [{**LAMP_POST, "path": "../props/lamp_post.glb"}])
        self.assertNotIn("animations", gltf)

    def test_plain_gltf_export_leaves_out_editor_state(self):
        path = Path(self.directory.name) / "plain.glb"
        bpy.context.scene.bevy_component_previews.scope = "ALL"
        bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", export_extras=True)
        gltf = read_gltf(path)
        self.assertTrue(all(set(node.get("extras", {})) <= {"bevy_components"} for node in gltf["nodes"]))
        self.assertTrue(all(set(scene.get("extras", {})) <= {"bevy_components"} for scene in gltf["scenes"]))

    def test_light_probe_files_are_embedded(self):
        gltf, binary = addon.compression.read_glb((Path(self.directory.name) / "sample_scene.glb").read_bytes())
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
            with self.assertRaisesRegex(RuntimeError, "Could not embed probe_cubemap.ktx2 in the scene: No such file or directory"):
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


def _vertex_count(gltf, name):
    mesh = gltf["meshes"][next(node for node in gltf["nodes"] if node["name"] == name)["mesh"]]
    return sum(gltf["accessors"][primitive["attributes"]["POSITION"]]["count"] for primitive in mesh["primitives"])


def _node_names(gltf):
    return sorted(node["name"] for node in gltf["nodes"])


def _broken_component(obj):
    item = obj.bevy_component_data.components.add()
    item.component_type = "CUSTOM"
    item.custom_json = "{broken"
    return item


def _all_scenes_report():
    operator = SimpleNamespace(report=mock.Mock())
    result = addon.operator.BEVY_OT_export_all_scenes.execute(operator, bpy.context)
    return result, operator.report.call_args.args


class TestExportOptions(unittest.TestCase):
    def setUp(self):
        clear_scene()
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "scene.glb"
        self.scene = bpy.context.scene

    def tearDown(self):
        bpy.context.window.scene = self.scene
        for scene in list(bpy.data.scenes):
            if scene != self.scene:
                bpy.data.scenes.remove(scene)
        self.scene.property_unset("bevy_glb_export")
        self.directory.cleanup()

    def test_modifiers_are_applied_unless_turned_off(self):
        plane = add_mesh(bpy.ops.mesh.primitive_plane_add, "row")
        plane.modifiers.new("Array", "ARRAY").count = 5
        self.assertEqual(_vertex_count(export_sample_scene(self.path), "row"), 20)
        self.assertTrue(self.scene.bevy_glb_export.apply_modifiers)
        self.assertEqual(_vertex_count(export_sample_scene(self.path, apply_modifiers=False), "row"), 4)
        self.assertFalse(self.scene.bevy_glb_export.apply_modifiers)
        self.assertEqual(plane.modifiers[0].count, 5)

    def test_meshes_with_modifiers_lose_their_shape_keys(self):
        blob = add_mesh(bpy.ops.mesh.primitive_plane_add, "blob")
        blob.shape_key_add(name="Basis")
        blob.shape_key_add(name="Puff")
        blob.modifiers.new("Bevel", "BEVEL")
        primitive = lambda gltf: gltf["meshes"][0]["primitives"][0]
        self.assertNotIn("targets", primitive(export_sample_scene(self.path)))
        self.assertEqual(len(primitive(export_sample_scene(self.path, apply_modifiers=False))["targets"]), 1)

    def test_only_the_active_scene_is_exported(self):
        add_mesh(bpy.ops.mesh.primitive_cube_add, "here")
        other = bpy.data.scenes.new("AAA_other_scene")
        there = bpy.data.objects.new("there", None)
        other.collection.objects.link(there)
        _broken_component(there)
        gltf = export_sample_scene(self.path)
        self.assertEqual((_node_names(gltf), len(gltf["scenes"])), (["here"], 1))
        self.assertEqual(bpy.context.scene, self.scene)
        self.assertEqual(addon.validation.check_objects(addon.system.exported_objects(bpy.context, self.scene.bevy_glb_export, selected=False)), [])

    def test_hidden_objects_can_be_left_out(self):
        add_mesh(bpy.ops.mesh.primitive_cube_add, "shown")
        hidden = add_mesh(bpy.ops.mesh.primitive_cube_add, "hidden", location=(3, 0, 0))
        stored = add_mesh(bpy.ops.mesh.primitive_cube_add, "stored", location=(6, 0, 0))
        unrendered = add_mesh(bpy.ops.mesh.primitive_cube_add, "unrendered", location=(9, 0, 0))
        collection = bpy.data.collections.new("storage")
        self.scene.collection.children.link(collection)
        for user in stored.users_collection:
            user.objects.unlink(stored)
        collection.objects.link(stored)
        hidden.hide_set(True)
        collection.hide_viewport = True
        unrendered.hide_render = True
        self.assertEqual(_node_names(export_sample_scene(self.path)), ["hidden", "shown", "stored", "unrendered"])
        self.assertEqual(_node_names(export_sample_scene(self.path, visible_only=True)), ["shown", "unrendered"])
        self.assertEqual(_node_names(export_sample_scene(self.path, renderable_only=True)), ["hidden", "shown", "stored"])
        self.assertEqual(_node_names(export_sample_scene(self.path, visible_only=True, renderable_only=True)), ["shown"])
        _broken_component(hidden)
        with self.assertRaisesRegex(RuntimeError, "Cannot export: hidden"):
            bpy.ops.export_scene.bevy_components_glb(filepath=str(self.path))
        self.assertEqual(_node_names(export_sample_scene(self.path, visible_only=True)), ["shown", "unrendered"])
        options = SimpleNamespace(selected_only=False, visible_only=True, renderable_only=False)
        self.assertEqual(sorted(obj.name for obj in addon.system.exported_objects(bpy.context, options)), ["shown", "unrendered"])

    def test_failed_exports_keep_the_previous_file(self):
        add_mesh(bpy.ops.mesh.primitive_cube_add, "kept")
        export_sample_scene(self.path)
        before = (self.path.read_bytes(), self.path.stat().st_mtime_ns)
        export_sample_scene(self.path)
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mtime_ns), before)

        def broken(operator, path, collection=None, directory=None):
            Path(path).write_bytes(b"half a scene")
            operator.report({"ERROR"}, "GLB export failed: disk full")
            return {"CANCELLED"}

        with mock.patch.object(addon.operator._SceneExport, "_export_gltf", broken):
            with self.assertRaisesRegex(RuntimeError, "GLB export failed: disk full"):
                bpy.ops.export_scene.bevy_components_glb(filepath=str(self.path))
        self.assertEqual(self.path.read_bytes(), before[0])
        self.assertEqual(sorted(path.name for path in self.path.parent.iterdir()), ["scene.glb"])

    def test_export_on_save(self):
        add_mesh(bpy.ops.mesh.primitive_cube_add, "saved")
        export_sample_scene(self.path)
        self.path.unlink()
        addon.operator.export_on_save(bpy.data.filepath)
        self.assertFalse(self.path.exists())
        self.scene.bevy_glb_export.export_on_save = True
        addon.operator.export_on_save(bpy.data.filepath)
        self.assertEqual(_node_names(read_gltf(self.path)), ["saved"])
        bpy.ops.object.duplicate()
        addon.operator.export_on_save(bpy.data.filepath)
        self.assertEqual(_node_names(read_gltf(self.path)), ["saved", "saved.001"])
        self.assertTrue(self.scene.bevy_glb_export.export_on_save)

    def test_export_on_save_runs_in_the_background(self):
        add_mesh(bpy.ops.mesh.primitive_cube_add, "saved")
        export_sample_scene(self.path)
        self.scene.bevy_glb_export.export_on_save = True
        calls = []
        exports = SimpleNamespace(bevy_components_glb=lambda mode, **options: calls.append((mode, options)))
        with mock.patch.object(bpy.ops, "export_scene", exports):
            addon.operator.export_on_save(bpy.data.filepath)
        self.assertEqual(calls, [("INVOKE_DEFAULT", {"again": True})])

    def test_files_from_the_bsn_export_keep_its_settings_out_of_the_glb(self):
        add_mesh(bpy.ops.mesh.primitive_cube_add, "kept")
        self.scene["bevy_bsn_export"] = {"rust_file": "//src/level.rs", "assets_folder": "", "export_on_save": 1}
        try:
            self.assertEqual([list(scene.get("extras", {})) for scene in export_sample_scene(self.path)["scenes"]], [["bevy_components"]])
        finally:
            del self.scene["bevy_bsn_export"]

    def test_saving_a_copy_does_not_export(self):
        add_mesh(bpy.ops.mesh.primitive_cube_add, "copied")
        export_sample_scene(self.path)
        self.path.unlink()
        self.scene.bevy_glb_export.export_on_save = True
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(self.directory.name) / "copy.blend"), copy=True)
        self.assertTrue((Path(self.directory.name) / "copy.blend").is_file())
        self.assertFalse(self.path.exists())

    def test_export_on_save_failures_keep_the_save(self):
        _broken_component(add_mesh(bpy.ops.mesh.primitive_cube_add, "broken"))
        self.scene.bevy_glb_export.filepath = str(self.path)
        self.scene.bevy_glb_export.export_on_save = True
        addon.operator.export_on_save(bpy.data.filepath)
        self.assertFalse(self.path.exists())

    def test_export_all_scenes(self):
        add_mesh(bpy.ops.mesh.primitive_cube_add, "first_cube")
        export_sample_scene(self.path)
        second = bpy.data.scenes.new("second")
        second.collection.objects.link(bpy.data.objects.new("second_empty", None))
        bpy.context.window.scene = second
        second_path = Path(self.directory.name) / "second.glb"
        export_sample_scene(second_path, include_lights=False)
        bpy.context.window.scene = self.scene
        third = bpy.data.scenes.new("third")
        self.path.unlink()
        second_path.unlink()
        result, report = _all_scenes_report()
        self.assertEqual((result, report), ({"FINISHED"}, ({"WARNING"}, f"Exported 2 scenes: {self.scene.name}, second. Skipped third, export it once with File > Export > Bevy Scene (.glb)")))
        self.assertEqual((_node_names(read_gltf(self.path)), _node_names(read_gltf(second_path))), (["first_cube"], ["second_empty"]))
        self.assertEqual(bpy.context.scene, self.scene)
        self.assertFalse(second.bevy_glb_export.include_lights)
        third.bevy_glb_export.filepath = str(Path(self.directory.name) / "third.glb")
        _broken_component(second.objects["second_empty"])
        result, report = _all_scenes_report()
        self.assertEqual((result, report[0]), ({"FINISHED"}, {"ERROR"}))
        self.assertRegex(report[1], "^Could not export 1 scene, second: Cannot export: second_empty")
        self.assertTrue((Path(self.directory.name) / "third.glb").is_file())
        self.assertEqual(bpy.context.scene, self.scene)

    def test_export_all_scenes_needs_an_earlier_export(self):
        bpy.data.scenes.new("second")
        self.assertEqual(_all_scenes_report(), ({"CANCELLED"}, ({"WARNING"}, f"No scene was exported yet. Skipped {self.scene.name}, second, export each once with File > Export > Bevy Scene (.glb)")))

    def test_flattened_materials_export_like_the_warnings_say(self):
        cube = add_mesh(bpy.ops.mesh.primitive_cube_add, "painted")
        material, principled = add_material("noisy")
        principled.inputs["Base Color"].default_value = (0.2, 0.4, 0.6, 1.0)
        material.node_tree.links.new(material.node_tree.nodes.new("ShaderNodeTexNoise").outputs["Color"], principled.inputs["Base Color"])
        cube.data.materials.append(material)
        diffuse, principled = add_material("diffuse")
        nodes = diffuse.node_tree.nodes
        nodes.remove(principled)
        shader = nodes.new("ShaderNodeBsdfDiffuse")
        shader.inputs["Color"].default_value = (0.8, 0.1, 0.1, 1.0)
        diffuse.node_tree.links.new(shader.outputs["BSDF"], nodes["Material Output"].inputs["Surface"])
        add_mesh(bpy.ops.mesh.primitive_cube_add, "matte", location=(3, 0, 0)).data.materials.append(diffuse)
        self.assertEqual([addon.validation.describe(issue) for issue in addon.validation.check_objects(bpy.data.objects)], ["matte: Material diffuse has no Principled BSDF, so glTF exports it plain white", "painted: Material noisy drives Base Color with procedural nodes, which glTF leaves out. Bake them to images"])
        materials = {material["name"]: material.get("pbrMetallicRoughness", {}) for material in export_sample_scene(self.path)["materials"]}
        self.assertNotIn("baseColorTexture", materials["noisy"])
        self.assertEqual(materials["diffuse"].get("baseColorFactor", [1.0, 1.0, 1.0, 1.0]), [1.0, 1.0, 1.0, 1.0])


GAME = """
import os, sys
print("scene", *sys.argv[1:])
print("view", os.environ.get("BEVY_COMPONENTS_VIEW", ""))
print("2026-10-23T10:00:00.000000Z  WARN bevy_components_importer::system: subject: Invalid mass")
print("2026-10-23T10:00:00.000000Z  WARN bevy_components_importer::system: Unnamed object: Invalid visibility range")
"""


def _until(check, timeout=20):
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.02)


class TestPlay(unittest.TestCase):
    def setUp(self):
        clear_scene()
        self.obj = add_mesh(bpy.ops.mesh.primitive_cube_add, "subject")
        self.directory = tempfile.TemporaryDirectory()
        self.project = Path(self.directory.name) / "my_game"
        (self.project / "assets" / "levels").mkdir(parents=True)
        (self.project / "Cargo.toml").write_text("[package]\n")
        self.glb = self.project / "assets" / "levels" / "arena.glb"
        self.preferences = bpy.context.preferences.addons[addon.__name__].preferences
        self.exports = _remembered_exports()
        self.exports.__enter__()

    def tearDown(self):
        addon.operator.stop_games()
        addon.operator._played.clear()
        self.exports.__exit__(None, None, None)
        self.preferences.game_folder = ""
        self.preferences.run_command = addon.play.DEFAULT_COMMAND
        self.preferences.viewer_folder = ""
        bpy.context.scene.bevy_game.folder = ""
        self.directory.cleanup()

    def _game(self, source, command):
        (self.project / "game.py").write_text(source)
        self.preferences.game_folder = str(self.project)
        self.preferences.run_command = f"\"{sys.executable}\" game.py {command}".strip()

    def _panel(self):
        panel = FakePanel(self)
        addon.panel.BEVY_PT_view_play.draw(panel, bpy.context)
        return panel.layout

    def test_play_exports_again_and_runs_the_game_with_the_view(self):
        self._game(GAME, "{scene}")
        with self.assertRaisesRegex(RuntimeError, "Export the scene once"):
            bpy.ops.bevy_components.play()
        self.assertIn("Export the scene once, then Play exports it again each time", " ".join(self._panel().texts()))
        self.assertEqual(bpy.ops.export_scene.bevy_components_glb(filepath=str(self.glb)), {"FINISHED"})
        self.glb.write_bytes(b"")
        with mock.patch.object(addon.operator, "viewport_view", return_value="1,3,-2,-0.707107,0,0,0.707107"):
            self.assertEqual(bpy.ops.bevy_components.play(), {"FINISHED"})
        game = addon.operator.last_game()
        self.assertTrue(game.wait(20))
        self.assertGreater(self.glb.stat().st_size, 0)
        self.assertEqual(game.output()[:2], [f"scene {self.glb}", "view 1,3,-2,-0.707107,0,0,0.707107"])
        self.assertEqual(game.game_warnings(), ["subject: Invalid mass", "Unnamed object: Invalid visibility range"])
        self.assertEqual((game.name, game.code, game.failed), ("my_game", 0, False))
        layout = self._panel()
        texts = layout.texts()
        self.assertIn(f"Runs {self.preferences.run_command} in my_game", texts)
        self.assertIn("my_game closed", texts)
        self.assertIn("Unnamed object: Invalid visibility range", texts)
        self.assertEqual([(text, properties.name) for text, properties, enabled in layout.buttons() if hasattr(properties, "name")], [("subject: Invalid mass", "subject")])
        self.assertIn("bevy_components.show_game_output", layout.operators())
        self.assertEqual(bpy.ops.bevy_components.show_game_output(), {"FINISHED"})
        self.assertEqual(bpy.data.texts[addon.operator.OUTPUT_TEXT].as_string().splitlines(), game.output())

    def test_play_restarts_and_stops_the_game(self):
        self._game("import time\nprint('ready', flush=True)\ntime.sleep(60)\n", "")
        self.assertEqual(bpy.ops.export_scene.bevy_components_glb(filepath=str(self.glb)), {"FINISHED"})
        self.assertEqual(bpy.ops.bevy_components.play(), {"FINISHED"})
        first = addon.operator.last_game()
        _until(first.output)
        status = FakeLayout(self)
        addon.menu.play_status(SimpleNamespace(layout=status), bpy.context)
        self.assertEqual(([text for text in status.texts() if text], status.operators()), (["my_game running"], ["bevy_components.stop_game"]))
        self.assertIn("Restart", self._panel().texts())
        self.assertEqual(bpy.ops.bevy_components.play(), {"FINISHED"})
        second = addon.operator.last_game()
        self.assertTrue(first.wait(10) and first.stopped)
        self.assertTrue(second.running)
        self.assertEqual(bpy.ops.bevy_components.stop_game(), {"FINISHED"})
        self.assertTrue(second.wait(10) and second.stopped and not second.failed)
        self.assertIn("Stopped my_game", self._panel().texts())
        status = FakeLayout(self)
        addon.menu.play_status(SimpleNamespace(layout=status), bpy.context)
        self.assertEqual(status.calls, [])
        with self.assertRaises(RuntimeError):
            bpy.ops.bevy_components.stop_game()

    def test_failed_games_explain_why(self):
        self._game("import sys\nprint(\"thread 'main' panicked at src/main.rs:3:5:\")\nprint('No scene file')\nsys.exit(101)\n", "")
        self.assertEqual(bpy.ops.export_scene.bevy_components_glb(filepath=str(self.glb)), {"FINISHED"})
        self.assertEqual(bpy.ops.bevy_components.play(), {"FINISHED"})
        self.assertTrue(addon.operator.last_game().wait(20))
        self.assertIn("my_game stopped with exit code 101: No scene file", " ".join(self._panel().texts()))

    def test_play_finds_the_game_project_or_the_viewer(self):
        with self.assertRaisesRegex(addon.play.PlayError, "Set the game project folder"):
            addon.project.play_target(bpy.context)
        layout = self._panel()
        self.assertIn("Set the game project folder", " ".join(layout.texts()))
        self.assertEqual([properties.module for text, properties, enabled in layout.buttons() if hasattr(properties, "module")], [addon.__name__])
        importer = Path(__file__).resolve().parents[2] / "importer"
        self.preferences.viewer_folder = str(importer)
        self.assertEqual(addon.project.play_target(bpy.context), (importer, addon.play.VIEWER_COMMAND))
        self.assertIn("Opens the scene in the importer's viewer", self._panel().texts())
        self.preferences.game_folder = str(self.project)
        self.assertEqual(addon.project.play_target(bpy.context), (self.project, "cargo run"))
        self.assertEqual(next(bound["placeholder"] for name, bound, layout in self._panel().calls if name == "prop" and bound["property"] == "folder"), str(self.project))
        other = Path(self.directory.name) / "other"
        other.mkdir()
        bpy.context.scene.bevy_game.folder = str(other)
        self.assertEqual((addon.project.game_folder(bpy.context), addon.project.game_assets(bpy.context)), (other, other / "assets"))
        with self.assertRaisesRegex(addon.play.PlayError, "has no Cargo.toml"):
            addon.project.play_target(bpy.context)
        panel = SimpleNamespace(layout=FakeLayout(self), bl_rna=self.preferences.bl_rna, ktx_path="", schema_path="", game_folder=str(other), run_command="cargo run", viewer_folder=str(other))
        addon.preferences.BEVY_AP_preferences.draw(panel, bpy.context)
        self.assertEqual([text for text in panel.layout.alerts() if str(other) in text], [f"{other} has no Cargo.toml, pick the folder of your game's Cargo project", f"{other} has no viewer example, pick the bevy_components_importer folder"])

    def test_exports_default_into_the_game_project(self):
        name = addon.files.snake_case(bpy.context.scene.name)
        self.assertEqual(_open_dialog(addon.operator.BEVY_OT_export_glb).filepath, "")
        self.preferences.game_folder = str(self.project)
        self.assertEqual(_open_dialog(addon.operator.BEVY_OT_export_glb).filepath, str(self.project / "assets" / "levels" / f"{name}.glb"))
        self.assertEqual(_open_dialog(addon.operator.BEVY_OT_export_glb, filepath=str(self.glb)).filepath, str(self.glb))

    def test_file_pickers_start_in_the_game_assets(self):
        reference = add_component(self.obj, "SCENE_REFERENCE")
        add_component(self.obj, "AUDIO_PLAYER")
        (self.project / "assets" / "sounds").mkdir()
        opened = []
        context = SimpleNamespace(object=self.obj, scene=bpy.context.scene, preferences=bpy.context.preferences, window_manager=SimpleNamespace(fileselect_add=opened.append))
        operator = SimpleNamespace(index=0, target="scene_file", filepath="", filter_glob="")
        operator._item = MethodType(addon.operator.BEVY_OT_pick_file._item, operator)
        self.assertEqual(addon.operator.BEVY_OT_pick_file.invoke(operator, context, None), {"RUNNING_MODAL"})
        self.assertEqual((operator.filepath, operator.filter_glob), ("", "*.glb;*.gltf"))
        self.preferences.game_folder = str(self.project)
        self.assertEqual(addon.operator.BEVY_OT_pick_file.invoke(operator, context, None), {"RUNNING_MODAL"})
        self.assertEqual(operator.filepath, os.path.join(str(self.project / "assets"), ""))
        tree = self.project / "assets" / "props" / "tree.glb"
        select(self.obj)
        self.assertEqual(bpy.ops.bevy_components.pick_file(index=0, target="scene_file", filepath=str(tree), relative_path=False), {"FINISHED"})
        self.assertEqual(reference.scene_file, str(tree))
        operator.filepath = ""
        addon.operator.BEVY_OT_pick_file.invoke(operator, context, None)
        self.assertEqual(operator.filepath, str(tree))
        self.assertEqual(bpy.ops.bevy_components.pick_file(index=1, target="scene_file", filepath=str(tree)), {"CANCELLED"})
        self.assertEqual(bpy.ops.bevy_components.pick_file(index=0, target="probe_file", filepath=str(tree)), {"CANCELLED"})
        sound = SimpleNamespace(index=1, filepath="")
        self.assertEqual(addon.operator.BEVY_OT_pick_sound.invoke(sound, context, None), {"RUNNING_MODAL"})
        self.assertEqual(sound.filepath, os.path.join(str(self.project / "assets" / "sounds"), ""))
        self.assertEqual(len(opened), 4)

    def test_paths_are_checked_against_the_game_assets(self):
        audio = add_component(self.obj, "AUDIO_PLAYER")
        audio.audio_path = "sounds/fire.ogg"
        reference = add_component(add_empty("holder", (2, 0, 0)), "SCENE_REFERENCE")
        reference.scene_file = str(Path(self.directory.name) / "tree.glb")
        missing = "No file at sounds/fire.ogg in the game's assets folder"
        messages = lambda: [issue.message for issue in addon.validation.check_objects(bpy.data.objects)]
        self.assertNotIn(missing, messages())
        self.assertEqual(addon.validation.check_game_paths(bpy.data.objects, Path(self.directory.name) / "arena.glb", None), [])
        self.preferences.game_folder = str(self.project)
        self.assertIn(missing, messages())
        self.assertIn(missing, [issue.message for issue in addon.validation.check_object(self.obj, bpy.data.objects)])
        (self.project / "assets" / "sounds").mkdir()
        (self.project / "assets" / "sounds" / "fire.ogg").write_bytes(b"")
        self.assertNotIn(missing, messages())
        assets = addon.project.game_assets(bpy.context)
        issues = [(issue.obj.name if issue.obj else None, issue.message) for issue in addon.validation.check_game_paths(bpy.data.objects, Path(self.directory.name) / "arena.glb", assets)]
        self.assertEqual(issues, [(None, f"arena.glb is outside {assets}, so the game cannot load it"), ("holder", "tree.glb is outside the game's assets folder, so the game cannot load it")])
        reference.scene_file = str(self.project / "assets" / "tree.glb")
        self.assertEqual(addon.validation.check_game_paths(bpy.data.objects, self.glb, assets), [])

    def test_the_game_schema_is_read_from_the_game_project(self):
        (self.project / SCHEMA.name).write_bytes(SCHEMA.read_bytes())
        self.preferences.game_folder = str(self.project)
        try:
            self.assertEqual(addon.system.game_schema(force=True)["path"], self.project / SCHEMA.name)
            self.assertIn("my_game::Patrol", addon.system.game_types())
            use_game_schema(SCHEMA.with_name("missing.json"))
            self.assertEqual(addon.system.game_schema()["error"], "missing.json was not found")
        finally:
            self.preferences.game_folder = ""
            use_game_schema(None)

    def test_the_viewport_view_uses_bevy_axes(self):
        values = [float(value) for value in addon.system.bevy_view(Matrix.Translation((1, 2, 3)).inverted()).split(",")]
        self.assertEqual([round(value, 5) for value in values[:3]], [1, 3, -2])
        rotation = Quaternion((values[6], *values[3:6]))
        self.assertLess((rotation @ Vector((0, 0, -1)) - Vector((0, -1, 0))).length, 1e-5)
        self.assertLess((rotation @ Vector((0, 1, 0)) - Vector((0, 0, -1))).length, 1e-5)
        turned = Matrix.Translation((0, -5, 1)) @ Matrix.Rotation(math.radians(90), 4, "X")
        values = [float(value) for value in addon.system.bevy_view(turned.inverted()).split(",")]
        self.assertEqual([round(value, 5) for value in values[:3]], [0, 1, 5])
        self.assertLess((Quaternion((values[6], *values[3:6])) @ Vector((0, 0, -1)) - Vector((0, 0, -1))).length, 1e-5)


def _scene_components(node):
    return json.loads(node["extras"]["bevy_components"])["components"]


class _ExporterOperator(SimpleNamespace):
    def __setattr__(self, name, value):
        if name.startswith("_"):
            raise AttributeError("Writing to ID classes in this context is not allowed")
        super().__setattr__(name, value)


class TestPrefabs(unittest.TestCase):
    def setUp(self):
        clear_scene()
        bpy.context.scene.property_unset("bevy_glb_export")
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.assets = self.root / "assets"
        self.level = self.assets / "level.glb"
        folder = bpy.data.collections.new("prefabs")
        bpy.context.scene.collection.children.link(folder)
        self.lantern = add_prefab("lantern", folder, self.assets / "props" / "lantern.glb")
        self.bulb = move_to(add_mesh(bpy.ops.mesh.primitive_ico_sphere_add, "bulb", subdivisions=1, radius=0.2), self.lantern)
        add_component(self.bulb, "COLLIDER", collider_shape="SPHERE", collider_radius=0.2)
        self.lamp = add_prefab("lamp post", folder, self.assets / "props" / "lamp_post.glb")
        self.lamp.instance_offset = (0, 10, 0)
        self.pole = move_to(add_mesh(bpy.ops.mesh.primitive_cube_add, "pole", size=0.2, location=(0, 10, 1)), self.lamp)
        add_component(self.pole, "RIGID_BODY", rigid_body_kind="STATIC")
        self.head = move_to(add_instance("head", self.lantern, (0, 10, 2)), self.lamp)
        bpy.context.view_layer.layer_collection.children["prefabs"].exclude = True
        self.post_a = add_instance("post_a", self.lamp, (4, 0, 0))
        self.post_b = add_instance("post_b", self.lamp, (-4, 2, 0), 90)
        add_mesh(bpy.ops.mesh.primitive_plane_add, "ground", size=10)

    def tearDown(self):
        clear_scene()
        bpy.context.scene.property_unset("bevy_glb_export")
        self.directory.cleanup()

    def _exported_prefabs(self, **options):
        with mock.patch.object(addon.operator, "collection_export", wraps=addon.operator.collection_export) as exported:
            export_sample_scene(self.level, **options)
        return [call.args[0].name for call in exported.call_args_list]

    def _issues(self):
        objects = addon.system.exported_objects(bpy.context, bpy.context.scene.bevy_glb_export, selected=False)
        return [(issue.level, issue.obj.name if issue.obj else None, issue.message) for issue in addon.validation.check_objects(objects, destination=self.level)]

    def test_instances_spawn_the_prefab_glb(self):
        gltf = export_sample_scene(self.level)
        nodes = {node["name"]: node for node in gltf["nodes"]}
        self.assertEqual(sorted(nodes), ["ground", "post_a", "post_b"])
        self.assertEqual([_scene_components(nodes[name]) for name in ("post_a", "post_b")], [[{"type": "scene_reference", "path": "props/lamp_post.glb", "scene": 0, "prefab": "lamp post"}]] * 2)
        self.assertEqual([_rounded(nodes[name]["translation"]) for name in ("post_a", "post_b")], [[4.0, 0.0, 0.0], [-4.0, 0.0, -2.0]])
        self.assertEqual(_rounded(nodes["post_b"]["rotation"]), [0.0, 0.70711, 0.0, 0.70711])
        lamp = read_gltf(self.assets / "props" / "lamp_post.glb")
        lamp_nodes = {node["name"]: node for node in lamp["nodes"]}
        self.assertEqual((lamp["scenes"][0]["name"], sorted(lamp_nodes)), ("lamp post", ["head", "pole"]))
        self.assertEqual([_rounded(lamp_nodes[name]["translation"]) for name in ("pole", "head")], [[0.0, 1.0, 0.0], [0.0, 2.0, 0.0]])
        self.assertEqual(_scene_components(lamp_nodes["head"]), [{"type": "scene_reference", "path": "lantern.glb", "scene": 0, "prefab": "lantern"}])
        self.assertEqual(_scene_components(lamp_nodes["pole"]), [STATIC_BODY])
        lantern = read_gltf(self.assets / "props" / "lantern.glb")
        self.assertEqual(([node["name"] for node in lantern["nodes"]], lantern["scenes"][0]["name"]), (["bulb"], "lantern"))
        self.assertEqual(_scene_components(lantern["nodes"][0])[0]["shape"], "sphere")
        self.assertEqual([scene.name for scene in bpy.data.scenes], ["Scene"])
        self.assertIs(bpy.context.window.scene, bpy.context.scene)
        self.assertEqual(self.post_a.instance_collection, self.lamp)

    def test_scene_exports_write_prefabs_that_changed(self):
        self.assertEqual(self._exported_prefabs(), ["lantern", "lamp post"])
        self.assertEqual(self._exported_prefabs(), [])
        self.bulb.location.x = 0.5
        self.assertEqual(self._exported_prefabs(), ["lantern"])
        self.pole.bevy_component_data.components[0].rigid_body_kind = "DYNAMIC"
        self.assertEqual(self._exported_prefabs(), ["lamp post"])
        self.bulb.data.vertices[0].co.z += 0.1
        self.assertEqual(self._exported_prefabs(), ["lantern"])
        self.post_a.location.x = 8
        self.assertEqual(self._exported_prefabs(), [])
        (self.assets / "props" / "lantern.glb").unlink()
        self.assertEqual(self._exported_prefabs(), ["lantern"])
        self.lamp.instance_offset = (0, 9, 0)
        self.assertEqual(self._exported_prefabs(), ["lamp post"])
        self.assertEqual(self._exported_prefabs(apply_modifiers=False), ["lantern", "lamp post"])
        self.assertEqual(self._exported_prefabs(apply_modifiers=False), [])
        with mock.patch.object(addon.prefab, "addon_version", lambda: "99.0.0"):
            self.assertEqual(self._exported_prefabs(apply_modifiers=False), ["lantern", "lamp post"])
        record = json.loads(self.lamp.bevy_prefab.exported)
        self.assertEqual(record["size"], (self.assets / "props" / "lamp_post.glb").stat().st_size)

    def test_checks_block_broken_prefabs(self):
        self.assertEqual(self._issues(), [])
        self.lantern.bevy_prefab.filepath = ""
        self.assertEqual(self._issues(), [("ERROR", "head", "Prefab lantern has no GLB file. Set one in Properties > Collection > Bevy Prefab")])
        with self.assertRaisesRegex(RuntimeError, "Cannot export: head: Prefab lantern has no GLB file"):
            export_sample_scene(self.level)
        self.lantern.bevy_prefab.filepath = str(self.assets / "props" / "lamp_post.glb")
        self.assertEqual(self._issues(), [("ERROR", "post_a", "Prefabs lantern and lamp post both export to lamp_post.glb")])
        self.lantern.bevy_prefab.filepath = str(self.level)
        self.assertEqual(self._issues(), [("ERROR", "head", "Prefab lantern exports to level.glb, the scene's own file")])
        self.lantern.bevy_prefab.filepath = str(self.root / "elsewhere" / "lantern.glb")
        self.assertEqual(self._issues(), [("WARNING", "head", "Prefab lantern exports outside the assets folder of lamp_post.glb, so the game cannot load it")])
        self.lantern.bevy_prefab.filepath = str(self.assets / "props" / "lantern.glb")
        loop = move_to(add_instance("loop", self.lamp, (0, 0, 0)), self.lantern)
        self.assertIn(("ERROR", "loop", "Prefab lamp post ends up inside itself through lamp post > lantern > lamp post, so it cannot export"), self._issues())
        bpy.data.objects.remove(loop)
        add_component(self.post_a, "SCENE_REFERENCE", scene_file=str(self.assets / "props" / "lantern.glb"))
        self.assertIn(("ERROR", "post_a", "Spawns prefab lamp post, so it cannot also spawn a Scene Reference. Move the Scene Reference to a child object"), self._issues())
        self.post_a.bevy_component_data.components.clear()
        empty = add_prefab("empty", bpy.context.scene.collection, self.assets / "props" / "empty.glb")
        add_instance("nothing", empty, (0, 0, 0))
        self.assertEqual(self._issues(), [("WARNING", "nothing", "Prefab empty has no objects, so its instances spawn nothing")])
        layout = FakeLayout(self)
        addon.panel.draw_components(layout, bpy.context, self.head)
        self.assertIn("Part of prefab lamp post, so it exports to the prefab's GLB file and not with the scene", " ".join(layout.texts()))
        select(self.post_b)
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertIn("Bevy Prefab: lamp post", panel.layout.texts())
        self.assertFalse(_prop_layout(panel.layout, "filepath").is_alert())
        self.lamp.bevy_prefab.filepath = ""
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertTrue(_prop_layout(panel.layout, "filepath").is_alert())
        self.lamp.bevy_prefab.enabled = False
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertNotIn("filepath", panel.layout.props())
        self.assertIn("Bevy Prefab: lamp post", panel.layout.texts())

    def test_collection_exporter_exports_only_the_collection(self):
        self.assertIsNotNone(bpy.types.FileHandler.bl_rna_get_subclass_py("BEVY_FH_glb"))
        with bpy.context.temp_override(collection=self.lamp):
            self.assertEqual(bpy.ops.collection.exporter_add(name="BEVY_FH_glb"), {"FINISHED"})
        exporter = self.lamp.exporters[0]
        target = self.assets / "export" / "lamp.glb"
        exporter.export_properties.filepath = str(target)
        with bpy.context.temp_override(collection=self.lamp):
            self.assertEqual(bpy.ops.collection.exporter_export(index=0), {"FINISHED"})
        gltf = read_gltf(target)
        nodes = {node["name"]: node for node in gltf["nodes"]}
        self.assertEqual((gltf["scenes"][0]["name"], sorted(nodes)), ("lamp post", ["head", "pole"]))
        self.assertEqual(_rounded(nodes["pole"]["translation"]), [0.0, 1.0, 0.0])
        self.assertEqual(_scene_components(nodes["head"]), [{"type": "scene_reference", "path": "../props/lantern.glb", "scene": 0, "prefab": "lantern"}])
        self.assertTrue((self.assets / "props" / "lantern.glb").is_file())
        self.assertFalse((self.assets / "props" / "lamp_post.glb").exists())
        self.assertEqual((bpy.context.scene.bevy_glb_export.filepath, [scene.name for scene in bpy.data.scenes]), ("", ["Scene"]))
        operator = _ExporterOperator(**vars(_dialog(self, addon.operator.BEVY_OT_export_glb, collection="lamp post", filepath=str(target))))
        addon.operator.BEVY_OT_export_glb.draw(operator, bpy.context)
        self.assertNotIn("export_on_save", operator.layout.props())
        self.assertNotIn("selected_only", operator.layout.props())
        self.assertIn("No problems found", operator.layout.texts())

    def test_exporting_a_prefab_records_it(self):
        own = self.assets / "props" / "lamp_post.glb"
        with bpy.context.temp_override(scene=bpy.context.scene):
            self.assertEqual(bpy.ops.export_scene.bevy_components_glb(collection="lamp post", filepath=str(own), include_animations=True), {"FINISHED"})
        gltf = read_gltf(own)
        self.assertEqual((gltf["scenes"][0]["name"], sorted(node["name"] for node in gltf["nodes"])), ("lamp post", ["head", "pole"]))
        self.assertEqual([_scene_components(node) for node in gltf["nodes"] if node["name"] == "pole"], [[STATIC_BODY]])
        self.assertEqual(self._exported_prefabs(), [])
        with self.assertRaisesRegex(RuntimeError, "No collection named missing"):
            bpy.ops.export_scene.bevy_components_glb(collection="missing", filepath=str(own))

    def test_prefab_panel(self):
        panel_type = addon.panel.BEVY_PT_collection_prefab
        context = SimpleNamespace(collection=self.lamp, scene=bpy.context.scene, region=None)
        self.assertTrue(panel_type.poll(context))
        self.assertFalse(panel_type.poll(SimpleNamespace(collection=bpy.context.scene.collection, scene=bpy.context.scene)))
        panel = FakePanel(self)
        panel_type.draw_header(panel, context)
        self.assertEqual(panel.layout.props(), ["enabled"])
        bpy.context.scene.bevy_glb_export.texture_compression = "UASTC"
        panel = FakePanel(self)
        panel_type.draw(panel, context)
        self.assertEqual(panel.layout.props(), ["filepath"])
        self.assertIn("2 instances in this file", " ".join(panel.layout.texts()))
        [(text, properties, enabled)] = panel.layout.buttons()
        self.assertEqual((text, properties.collection, properties.filepath, properties.texture_compression, enabled), ("Export Prefab", "lamp post", str(self.assets / "props" / "lamp_post.glb"), "UASTC", True))
        self.lamp.bevy_prefab.filepath = ""
        panel = FakePanel(self)
        panel_type.draw(panel, context)
        self.assertTrue(_prop_layout(panel.layout, "filepath").alert)
        self.assertEqual([enabled for text, properties, enabled in panel.layout.buttons()], [False])
        self.assertEqual(bpy.types.BEVY_PT_collection_prefab.bl_context, "collection")

    def test_new_prefabs_get_a_file_next_to_the_scene(self):
        collection = bpy.data.collections.new("Street Lamp")
        collection.bevy_prefab.enabled = True
        self.assertEqual(collection.bevy_prefab.filepath, "")
        collection.bevy_prefab.enabled = False
        with _remembered_exports(glb=str(self.level)):
            collection.bevy_prefab.enabled = True
        self.assertEqual(_resolved(collection.bevy_prefab.filepath), self.assets / "prefabs" / "street_lamp.glb")


def _fake_blender(directory):
    path = Path(directory) / "blender"
    path.write_text(FAKE_BLENDER.format(python=sys.executable), encoding="utf-8")
    path.chmod(0o755)
    return path


def _dark_world():
    world = bpy.data.worlds.new("bake_test")
    if bpy.app.version < (5, 0, 0):
        world.use_nodes = True
    addon.system.world_background(world).inputs["Strength"].default_value = 0.0
    return world


def _emissive(obj, color):
    material = bpy.data.materials.new(obj.name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*color, 1.0)
    material.node_tree.links.new(emission.outputs["Emission"], nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    obj.data.materials.append(material)
    return obj


def _ktx2_pixels(path):
    data = Path(bpy.path.abspath(path)).read_bytes()
    info = addon.compression.ktx2_info(data)
    offset, length = struct.unpack_from("<QQ", data, 80)
    return numpy.frombuffer(data[offset:offset + length], dtype="<f2").astype(numpy.float32).reshape(6 if info["faces"] == 6 else info["depth"], info["height"], info["width"], 4)


def _lightmap_pixels(path):
    data = Path(bpy.path.abspath(path)).read_bytes()
    info = addon.compression.ktx2_info(data)
    offset, length = struct.unpack_from("<QQ", data, 80)
    packed = numpy.frombuffer(data[offset:offset + length], dtype="<u4").reshape(info["height"], info["width"])
    channels = numpy.stack([(packed >> shift) & 511 for shift in (0, 9, 18)], axis=-1).astype(numpy.float64)
    return channels * 2.0 ** ((packed >> 27).astype(numpy.float64) - 24)[..., None]


def _lightmap_texel(obj, polygon, size):
    u, v = numpy.mean([tuple(obj.data.uv_layers[1].data[index].uv) for index in polygon.loop_indices], axis=0)
    return min(int((1 - v) * size), size - 1), min(int(u * size), size - 1)


def _bevy_lookup(obj, item, direction):
    probe = BEVY_FROM_BLENDER @ obj.matrix_world.to_3x3() @ BEVY_FROM_BLENDER.transposed() @ Matrix.Diagonal(item.volume_size)
    local = probe.inverted() @ BEVY_FROM_BLENDER @ Vector(direction)
    return local.x, local.y, -local.z


def _cube_texel(direction, size):
    x, y, z = direction
    largest = max(abs(x), abs(y), abs(z))
    if largest == abs(x):
        face, u, v = (0, -z, -y) if x > 0 else (1, z, -y)
    elif largest == abs(y):
        face, u, v = (2, x, z) if y > 0 else (3, x, -z)
    else:
        face, u, v = (4, x, -y) if z > 0 else (5, -x, -y)
    return face, min(int((v / largest + 1) / 2 * size), size - 1), min(int((u / largest + 1) / 2 * size), size - 1)


def _bake_operator(**values):
    members = {name: getattr(addon.operator.BEVY_OT_bake_lighting, name) for name in ("draw", "modal", "cancel", "_find_jobs", "_start", "_stop_background", "_release", "_store_files", "_failed", "_finish")}
    operator = type("FakeBakeOperator", (), members)()
    operator.reports = []
    operator.report = lambda levels, message: operator.reports.append((next(iter(levels)), message))
    for name, value in {"object_name": "", "index": -1, "sky": False, "_interactive": False, "_directory": None, "_task": None, "_jobs": (), "_folder": "", "_shown": None, **values}.items():
        setattr(operator, name, value)
    return operator


def _wait_for(operator, context):
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        result = operator.modal(context, None)
        if result != {"PASS_THROUGH"}:
            return result
        time.sleep(0.1)
    operator.cancel(context)
    raise AssertionError("The background bake did not finish")


class TestBakeLighting(unittest.TestCase):
    def setUp(self):
        clear_scene()
        self.scene = bpy.context.scene
        self.settings = self.scene.bevy_bake_settings
        self.settings.samples = 4
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name) / "baked_lighting"
        self.addCleanup(self._restore, self.scene.world.name)
        self.scene.world = _dark_world()
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(self.directory.name) / "scene.blend"))

    def _restore(self, world):
        scene = bpy.context.scene
        for name in ("samples", "lamp_direct", "folder", "export_again"):
            scene.bevy_bake_settings.property_unset(name)
        dark = scene.world
        scene.world = bpy.data.worlds.get(world)
        if dark is not None and dark.users == 0:
            bpy.data.worlds.remove(dark)

    def test_bakes_find_components_that_moved(self):
        room = add_empty("room", (0, 0, 0))
        add_component(room, "SHADOWS")
        probe = add_component(room, "REFLECTION_PROBE")
        operator = _bake_operator(_jobs=[{"object": "room", "index": 0, "kind": "CUBEMAP", "file": "//baked_lighting/room.ktx2", "fingerprint": "abc"}])
        self.assertEqual(len(operator._store_files(1)), 1)
        self.assertEqual((probe.probe_file, probe.bake_fingerprint), ("//baked_lighting/room.ktx2", "abc"))

    def _probe(self, name, kind, location=(0, 0, 0), **values):
        holder = add_empty(name, location)
        return holder, add_component(holder, kind, **values)

    def _context(self):
        manager = SimpleNamespace(event_timer_add=mock.Mock(return_value="timer"), event_timer_remove=mock.Mock(), modal_handler_add=mock.Mock())
        return SimpleNamespace(scene=self.scene, view_layer=bpy.context.view_layer, window="window", window_manager=manager)

    def _start(self, context):
        operator = _bake_operator(_folder=self.settings.folder)
        operator._jobs = operator._find_jobs(context)
        self.assertEqual(operator._start(context, self.settings, _fake_blender(self.directory.name)), {"RUNNING_MODAL"})
        return operator

    def _lightmapped(self, name="floor", resolution="64", grid=True):
        if grid:
            bpy.ops.mesh.primitive_grid_add(x_subdivisions=8, y_subdivisions=8, size=4)
        else:
            bpy.ops.mesh.primitive_plane_add(size=40)
        floor = bpy.context.object
        floor.name = name
        item = add_component(floor, "LIGHTMAP", lightmap_resolution=resolution)
        bpy.ops.bevy_components.unwrap_lightmap()
        return floor, item

    def test_lightmaps_hold_light_where_bevy_samples_it(self):
        _emissive(add_mesh(bpy.ops.mesh.primitive_cube_add, "red", size=1, location=(3, 0, 0.5)), (1.0, 0.0, 0.0))
        _emissive(add_mesh(bpy.ops.mesh.primitive_cube_add, "green", size=1, location=(0, 3, 0.5)), (0.0, 1.0, 0.0))
        floor, item = self._lightmapped()
        self.settings.samples = 32
        before = (len(bpy.data.materials), len(bpy.data.images), len(floor.material_slots), [obj.name for obj in bpy.context.selected_objects], bpy.context.view_layer.objects.active)
        self.assertEqual(bpy.ops.bevy_components.bake_lighting(object_name="floor", index=0), {"FINISHED"})
        self.assertEqual(item.probe_file, "//baked_lighting/floor_lightmap.ktx2")
        self.assertEqual((len(bpy.data.materials), len(bpy.data.images), len(floor.material_slots), [obj.name for obj in bpy.context.selected_objects], bpy.context.view_layer.objects.active), before)
        pixels = _lightmap_pixels(item.probe_file)
        self.assertEqual(pixels.shape, (64, 64, 3))
        centers = numpy.array([tuple(floor.matrix_world @ polygon.center) for polygon in floor.data.polygons])
        values = numpy.array([pixels[_lightmap_texel(floor, polygon, 64)] for polygon in floor.data.polygons])
        for channel, axis in ((0, 0), (1, 1)):
            near = values[centers[:, axis] > 1.0, channel].mean()
            far = values[centers[:, axis] < -1.0, channel].mean()
            self.assertGreater(near, 2 * far, f"channel {channel} is {near:.3g} near its light and {far:.3g} away from it")
        self.assertGreater(values[:, 0].max(), 10.0)
        self.assertLess(values[:, 2].max(), 1.0)

    def test_lightmaps_bake_the_direct_light_of_lamps_marked_baked(self):
        floor, item = self._lightmapped(resolution="128", grid=False)
        material, shader = add_material("floor")
        floor.data.materials.append(material)
        nodes = (len(material.node_tree.nodes), material.node_tree.nodes.active)
        sun = add_light("sun", "SUN", (0, 0, 10), energy=3.0)
        light = add_component(sun, "LIGHT")
        lightmaps = {}
        for baked in (False, True):
            light.light_baked = baked
            self.assertEqual(addon.bake.lighting_jobs(self.scene.objects, self.settings.folder)[0]["baked_lamps"], ["sun"] if baked else [])
            self.assertEqual(bpy.ops.bevy_components.bake_lighting(), {"FINISHED"})
            lightmaps[baked] = _lightmap_pixels(item.probe_file)[32:96, 32:96]
        self.assertLess(lightmaps[False].max(), 5.0)
        self.assertAlmostEqual(float(lightmaps[True].mean()) / (3.0 / math.pi * 683), 1.0, delta=0.05)
        self.assertFalse(sun.hide_render)
        self.assertEqual((len(material.node_tree.nodes), material.node_tree.nodes.active, [slot.material for slot in floor.material_slots]), (*nodes, [material]))

    def test_lightmaps_need_a_second_uv_map(self):
        floor = add_mesh(bpy.ops.mesh.primitive_plane_add, "floor")
        add_component(floor, "LIGHTMAP")
        message = "floor has no second UV map for its lightmap. Click Unwrap Lightmap UVs on its Lightmap"
        with self.assertRaisesRegex(RuntimeError, message):
            bpy.ops.bevy_components.bake_lighting()
        operator = _bake_operator(layout=FakeLayout(self))
        addon.operator.BEVY_OT_bake_lighting.draw(operator, bpy.context)
        self.assertIn(message, " ".join(operator.layout.texts()))
        self.assertFalse(self.folder.exists())
        select(add_empty("holder", (0, 0, 0)))
        bpy.data.objects["holder"].bevy_component_data.components.add().component_type = "LIGHTMAP"
        self.assertEqual([job["object"] for job in addon.bake.lighting_jobs(self.scene.objects, self.settings.folder)], ["floor"])

    def test_dialog_explains_what_lightmaps_hold(self):
        self._lightmapped(resolution="128")
        self._probe("room", "REFLECTION_PROBE")
        self._probe("hall", "REFLECTION_PROBE")
        self._probe("gi", "IRRADIANCE_VOLUME")
        operator = _bake_operator(layout=FakeLayout(self))
        addon.operator.BEVY_OT_bake_lighting.draw(operator, bpy.context)
        texts = " ".join(operator.layout.texts())
        self.assertIn("Bakes 1 lightmap, 2 reflection probes and 1 irradiance volume", operator.layout.texts())
        self.assertIn("Lightmaps hold sky light, bounced light and the direct light of lamps marked Baked in their Light component, none here. Bevy lights the meshes with the other lamps", texts)
        self.assertIn("Bevy's ambient light adds to the sky light baked into lightmaps. Turn on Bevy Ambient Light and its Baked option in World properties", texts)
        add_component(add_light("sun", "SUN", (0, 0, 10)), "LIGHT", light_baked=True)
        add_component(add_light("window", "AREA", (0, 0, 3)), "LIGHT", light_baked=True)
        self.scene.world.bevy_ambient_light.enabled = True
        self.scene.world.bevy_ambient_light.baked = True
        operator = _bake_operator(layout=FakeLayout(self))
        addon.operator.BEVY_OT_bake_lighting.draw(operator, bpy.context)
        texts = " ".join(operator.layout.texts())
        self.assertIn("in their Light component, 1 lamp here.", texts)
        self.assertNotIn("ambient light", texts.lower())

    def test_cubemaps_hold_what_bevy_samples_in_each_direction(self):
        for direction, color in SIDE_COLORS.items():
            _emissive(add_mesh(bpy.ops.mesh.primitive_cube_add, f"side_{len(bpy.data.objects)}", size=6, location=tuple(5 * value for value in direction)), color)
        holder, item = self._probe("room", "REFLECTION_PROBE", volume_size=(3, 1, 2), bake_resolution="64")
        holder.rotation_euler = (0.3, 0.2, 0.9)
        holder.scale = (1, 2, 1)
        self.assertEqual(bpy.ops.bevy_components.bake_lighting(object_name="room", index=0), {"FINISHED"})
        pixels = _ktx2_pixels(item.probe_file)
        self.assertEqual(pixels.shape, (6, 64, 64, 4))
        for direction, color in SIDE_COLORS.items():
            face, row, column = _cube_texel(_bevy_lookup(holder, item, direction), 64)
            self.assertTrue(numpy.allclose(pixels[face, row, column, :3], color, atol=0.1), f"{direction} looks up {pixels[face, row, column]}")
        self.assertTrue(numpy.all(pixels[..., 3] == 1.0))

    def test_the_sky_holds_the_world_alone(self):
        world = self.scene.world
        tree = world.node_tree
        background = addon.system.world_background(world)
        background.inputs["Strength"].default_value = 1.0
        positive = tree.nodes.new("ShaderNodeVectorMath")
        positive.operation = "MAXIMUM"
        positive.inputs[1].default_value = (0.0, 0.0, 0.0)
        tree.links.new(tree.nodes.new("ShaderNodeTexCoord").outputs["Generated"], positive.inputs[0])
        tree.links.new(positive.outputs["Vector"], background.inputs["Color"])
        _emissive(add_mesh(bpy.ops.mesh.primitive_cube_add, "walls", size=4), (1.0, 1.0, 1.0))
        world.bevy_sky.enabled = True
        world.bevy_sky.bake_resolution = "64"
        state = lambda: (len(bpy.data.scenes), len(bpy.data.objects), len(bpy.data.cameras), [image.name for image in bpy.data.images if image.type != "RENDER_RESULT"], bpy.context.scene, self.scene.render.engine)
        before = state()
        self.assertEqual(bpy.ops.bevy_components.bake_lighting(sky=True), {"FINISHED"})
        self.assertEqual(state(), before)
        self.assertEqual(world.bevy_sky.sky_file, "//baked_lighting/bake_test_sky.ktx2")
        self.assertEqual(addon.validation.sky_check(world)[:2], (None, "64 × 64 cubemap"))
        pixels = _ktx2_pixels(world.bevy_sky.sky_file)
        self.assertEqual(pixels.shape, (6, 64, 64, 4))
        for direction in SIDE_COLORS:
            local = BEVY_FROM_BLENDER @ Vector(direction)
            face, row, column = _cube_texel((local.x, local.y, -local.z), 64)
            expected = tuple(max(value, 0.0) for value in direction)
            self.assertTrue(numpy.allclose(pixels[face, row, column, :3], expected, atol=0.05), f"{direction} looks up {pixels[face, row, column]}")

    def test_export_checks_warn_when_a_bake_is_out_of_date(self):
        room, reflection = self._probe("room", "REFLECTION_PROBE", bake_resolution="64", volume_size=(4.0, 4.0, 4.0))
        crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=1)
        _emissive(crate, (1.0, 0.0, 0.0))
        far = add_mesh(bpy.ops.mesh.primitive_cube_add, "far", size=1, location=(20, 0, 0))
        sun = add_light("sun", "SUN", (0, 0, 10), energy=3.0)
        sky = self.scene.world.bevy_sky
        sky.enabled = True
        sky.bake_resolution = "64"
        check = lambda: [addon.validation.describe(issue) for issue in addon.validation.stale_bakes(bpy.data.objects)]
        self.assertEqual(check(), [])
        self.assertEqual(bpy.ops.bevy_components.bake_lighting(), {"FINISHED"})
        self.assertEqual(json.loads(reflection.bake_fingerprint)["file"], "//baked_lighting/room_reflection.ktx2")
        self.assertEqual(check(), [])
        far.location.x = 30
        far.data.vertices[0].co.z = 3
        self.assertEqual(check(), [])
        stale = "room: Baked before the meshes in its box changed, so the cubemap is out of date. Bake again"
        for change, undo in ((lambda: setattr(crate.location, "x", 0.5), lambda: setattr(crate.location, "x", 0.0)), (lambda: crate.modifiers.new("bevel", "BEVEL"), lambda: crate.modifiers.clear()), (lambda: setattr(crate.data.materials[0].node_tree.nodes["Emission"].inputs["Color"], "default_value", (0.0, 1.0, 0.0, 1.0)), lambda: setattr(crate.data.materials[0].node_tree.nodes["Emission"].inputs["Color"], "default_value", (1.0, 0.0, 0.0, 1.0))), (lambda: setattr(crate, "hide_render", True), lambda: setattr(crate, "hide_render", False))):
            change()
            self.assertEqual(check(), [stale])
            undo()
            self.assertEqual(check(), [])
        room.location.x = 1
        self.assertEqual(check(), ["room: Baked before its box changed, so the cubemap is out of date. Bake again"])
        room.location.x = 0
        sun.data.energy = 5
        self.assertEqual(check(), ["room: Baked before the lamps changed, so the cubemap is out of date. Bake again"])
        addon.system.world_background(self.scene.world).inputs["Strength"].default_value = 0.5
        self.assertEqual(check(), ["Bevy Sky: Baked before the World changed, so the cubemap is out of date. Bake again", "room: Baked before the lamps and the World changed, so the cubemap is out of date. Bake again"])
        self.assertIn("room: Baked before the lamps and the World changed, so the cubemap is out of date. Bake again", [addon.validation.describe(issue) for issue in addon.operator._glb_issues(_dialog(self, addon.operator.BEVY_OT_export_glb), bpy.data.objects)])
        reflection.probe_file = str(CUBEMAP)
        sky.sky_file = str(CUBEMAP)
        self.assertEqual(check(), [])
        reflection.probe_file = "//baked_lighting/room_reflection.ktx2"
        sky.sky_file = "//baked_lighting/bake_test_sky.ktx2"
        self.assertEqual(bpy.ops.bevy_components.bake_lighting(), {"FINISHED"})
        self.assertEqual(check(), [])
        bpy.ops.wm.save_mainfile()
        bpy.ops.wm.open_mainfile(filepath=bpy.data.filepath)
        self.assertEqual(check(), [])
        bpy.data.objects["sun"].data.color = (1.0, 0.5, 0.5)
        self.assertEqual(check(), ["room: Baked before the lamps changed, so the cubemap is out of date. Bake again"])

    def test_export_checks_warn_when_a_lightmap_is_out_of_date(self):
        wall = add_mesh(bpy.ops.mesh.primitive_cube_add, "wall", size=1, location=(0, 0, 0.5))
        floor, item = self._lightmapped()
        check = lambda: [addon.validation.describe(issue) for issue in addon.validation.stale_bakes([floor])]
        self.assertEqual(bpy.ops.bevy_components.bake_lighting(object_name="floor", index=0), {"FINISHED"})
        self.assertEqual(check(), [])
        wall.location.z = 1
        self.assertEqual(check(), ["floor: Baked before the meshes around it changed, so the lightmap is out of date. Bake again"])
        wall.location.z = 10
        self.assertEqual(check(), ["floor: Baked before the meshes around it changed, so the lightmap is out of date. Bake again"])
        wall.location.z = 0.5
        self.assertEqual(check(), [])
        floor.data.uv_layers["lightmap"].data[0].uv = (0.9, 0.9)
        self.assertEqual(check(), ["floor: Baked before the mesh changed, so the lightmap is out of date. Bake again"])
        floor.rotation_euler.z = 0.5
        add_light("lamp", "POINT", (0, 0, 2))
        self.assertEqual(check(), ["floor: Baked before the mesh and the lamps changed, so the lightmap is out of date. Bake again"])
        self.assertEqual(addon.validation.stale_bakes([wall]), [])

    def test_bake_lighting_can_export_again_when_it_finishes(self):
        self._probe("room", "REFLECTION_PROBE", bake_resolution="64")
        path = Path(self.directory.name) / "level.glb"
        operator = _bake_operator(layout=FakeLayout(self))
        addon.operator.BEVY_OT_bake_lighting.draw(operator, bpy.context)
        self.assertIn("export_again", operator.layout.props())
        self.assertNotIn("Nothing to export again yet", " ".join(operator.layout.texts()))
        self.settings.export_again = "GLB"
        with _remembered_exports():
            operator = _bake_operator(layout=FakeLayout(self))
            addon.operator.BEVY_OT_bake_lighting.draw(operator, bpy.context)
            self.assertIn("Nothing to export again yet, export the scene once with File > Export > Bevy Scene (.glb)", " ".join(operator.layout.texts()))
        with _remembered_exports(glb=str(path)):
            operator = _bake_operator(layout=FakeLayout(self))
            addon.operator.BEVY_OT_bake_lighting.draw(operator, bpy.context)
            self.assertNotIn("Nothing to export again yet", " ".join(operator.layout.texts()))
            self.assertEqual(bpy.ops.bevy_components.bake_lighting(), {"FINISHED"})
        node = next(node for node in read_gltf(path)["nodes"] if node["name"] == "room")
        self.assertEqual(json.loads(node["extras"]["bevy_components"])["components"][0]["type"], "reflection_probe")
        self.assertIn("texture", json.loads(node["extras"]["bevy_components"])["components"][0])
        path.unlink()
        with _remembered_exports():
            operator = _bake_operator(_folder=self.settings.folder)
            operator._jobs = operator._find_jobs(bpy.context)
            self.assertEqual(operator._finish(bpy.context, operator._jobs), {"FINISHED"})
        self.assertEqual(operator.reports, [("INFO", f"Baked 1 reflection probe into {self.settings.folder}"), ("WARNING", "Baked 1 reflection probe, but could not export again: Nothing to export again yet, export the scene once with File > Export > Bevy Scene (.glb)")])
        self.assertFalse(path.exists())

    def test_bake_lighting_bakes_the_sky_first(self):
        self._probe("room", "REFLECTION_PROBE", bake_resolution="64")
        sky = self.scene.world.bevy_sky
        sky.enabled = True
        sky.bake_resolution = "64"
        jobs = addon.bake.lighting_jobs(self.scene.objects, self.settings.folder, world=self.scene.world)
        self.assertEqual([job["kind"] for job in jobs], ["SKY", "CUBEMAP"])
        self.assertEqual(addon.bake.bake_summary(jobs), "the sky and 1 reflection probe")
        self.assertEqual([job["kind"] for job in addon.bake.lighting_jobs(self.scene.objects, self.settings.folder, only=("room", 0), world=self.scene.world)], ["CUBEMAP"])
        operator = _bake_operator(layout=FakeLayout(self))
        addon.operator.BEVY_OT_bake_lighting.draw(operator, bpy.context)
        self.assertIn("Bakes the sky and 1 reflection probe", operator.layout.texts())
        operator = _bake_operator(layout=FakeLayout(self), sky=True)
        addon.operator.BEVY_OT_bake_lighting.draw(operator, bpy.context)
        self.assertIn("Bakes the sky", operator.layout.texts())
        self.assertEqual(bpy.ops.bevy_components.bake_lighting(), {"FINISHED"})
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["bake_test_sky.ktx2", "room_reflection.ktx2"])
        self.assertEqual(sky.sky_file, "//baked_lighting/bake_test_sky.ktx2")
        sky.enabled = False
        with self.assertRaisesRegex(RuntimeError, "No Bevy Sky or enabled Lightmaps, Reflection Probes or Irradiance Volumes to bake"):
            bpy.ops.bevy_components.bake_lighting(sky=True)

    def test_irradiance_volumes_hold_light_from_each_side_of_each_voxel(self):
        _emissive(add_mesh(bpy.ops.mesh.primitive_cube_add, "green", size=2, location=(4, 0, 0)), (0.0, 1.0, 0.0))
        _emissive(add_mesh(bpy.ops.mesh.primitive_cube_add, "red", size=2, location=(0, 0, -3)), (1.0, 0.0, 0.0))
        _emissive(add_mesh(bpy.ops.mesh.primitive_cube_add, "blue", size=2, location=(0, -4, 0)), (0.0, 0.0, 1.0))
        holder, item = self._probe("gi", "IRRADIANCE_VOLUME", volume_size=(2, 2, 2), bake_voxels=(2, 2, 2))
        self.settings.samples = 16
        self.assertEqual(bpy.ops.bevy_components.bake_lighting(), {"FINISHED"})
        pixels = _ktx2_pixels(item.probe_file)
        self.assertEqual(pixels.shape, (6, 4, 2, 4))
        side = lambda axis, negative, x, y, z: pixels[axis * 2 + z, negative * 2 + y, x, :3]
        for x, y, z in ((x, y, z) for x in range(2) for y in range(2) for z in range(2)):
            self.assertGreater(side(0, 0, x, y, z)[1], 0.02)
            self.assertLess(side(0, 1, x, y, z)[1], 0.002)
            self.assertGreater(side(1, 1, x, y, z)[0], 0.02)
            self.assertLess(side(1, 0, x, y, z)[0], 0.002)
            self.assertGreater(side(2, 0, x, y, z)[2], 0.02)
            self.assertLess(side(2, 1, x, y, z)[2], 0.002)
            self.assertGreater(side(0, 0, 1, y, z)[1], side(0, 0, 0, y, z)[1] * 1.3)
            self.assertGreater(side(1, 1, x, 0, z)[0], side(1, 1, x, 1, z)[0] * 1.3)
            self.assertGreater(side(2, 0, x, y, 1)[2], side(2, 0, x, y, 0)[2] * 1.3)

    def test_lamp_light_is_left_to_bevy_unless_asked(self):
        floor = add_mesh(bpy.ops.mesh.primitive_plane_add, "floor", size=40)
        material, shader = add_material("floor")
        shader.inputs["Base Color"].default_value = (0.8, 0.8, 0.8, 1.0)
        floor.data.materials.append(material)
        sun = add_light("sun", "SUN", (0, 0, 10), energy=3.0)
        holder, item = self._probe("gi", "IRRADIANCE_VOLUME", location=(0, 0, 1), volume_size=(2, 1, 2), bake_voxels=(1, 1, 1))
        select(floor)
        before = (self.scene.render.engine, self.scene.cycles.samples, self.scene.camera, len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials), len(bpy.data.images), len(bpy.data.cameras), [obj.name for obj in bpy.context.selected_objects], bpy.context.view_layer.objects.active)
        sides = {}
        for lamp_direct in (False, True):
            self.settings.lamp_direct = lamp_direct
            self.assertEqual(bpy.ops.bevy_components.bake_lighting(), {"FINISHED"})
            pixels = _ktx2_pixels(item.probe_file)
            sides[lamp_direct] = (pixels[1, 0, 0, :3], pixels[1, 1, 0, :3])
        self.assertLess(sides[False][0].max(), 0.01)
        self.assertAlmostEqual(float(sides[True][0].mean()), 3.0 / math.pi, delta=0.05)
        self.assertGreater(sides[False][1].min(), 0.2)
        self.assertTrue(numpy.allclose(sides[False][1], sides[True][1], rtol=0.15))
        self.assertFalse(sun.hide_render)
        self.assertEqual((self.scene.render.engine, self.scene.cycles.samples, self.scene.camera, len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials), len(bpy.data.images), len(bpy.data.cameras), [obj.name for obj in bpy.context.selected_objects], bpy.context.view_layer.objects.active), before)

    def test_bakes_every_probe_into_a_folder_next_to_the_blend_file(self):
        room, reflection = self._probe("Room Probe.001", "REFLECTION_PROBE", bake_resolution="64")
        gi, volume = self._probe("gi", "IRRADIANCE_VOLUME", bake_voxels=(3, 2, 1))
        same, clash = self._probe("room probe_001", "REFLECTION_PROBE", bake_resolution="64")
        _off, disabled = self._probe("off", "REFLECTION_PROBE", enabled=False)
        self.assertEqual(bpy.ops.bevy_components.bake_lighting(), {"FINISHED"})
        self.assertEqual((reflection.probe_file, volume.probe_file, clash.probe_file, disabled.probe_file), ("//baked_lighting/room_probe_001_reflection.ktx2", "//baked_lighting/gi_irradiance.ktx2", "//baked_lighting/room_probe_001_reflection_2.ktx2", ""))
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["gi_irradiance.ktx2", "room_probe_001_reflection.ktx2", "room_probe_001_reflection_2.ktx2"])
        self.assertEqual(addon.validation.texture_check(room, reflection)[:2], (None, "64 × 64 cubemap"))
        self.assertEqual(addon.validation.texture_check(gi, volume)[:2], (None, "3 × 2 × 1 voxels"))
        self.assertEqual(_stored(gi)["components"][0]["file"], "//baked_lighting/gi_irradiance.ktx2")
        self.settings.folder = str(Path(self.directory.name) / "absolute")
        self.assertEqual(bpy.ops.bevy_components.bake_lighting(object_name="gi", index=0), {"FINISHED"})
        self.assertEqual(volume.probe_file, str(Path(self.directory.name) / "absolute" / "gi_irradiance.ktx2"))
        self.settings.folder = "//"
        self.assertEqual(bpy.ops.bevy_components.bake_lighting(object_name="gi", index=0), {"FINISHED"})
        self.assertEqual(volume.probe_file, "//gi_irradiance.ktx2")

    @unittest.skipUnless(os.environ.get("BEVY_COMPONENTS_REQUIRE_KTX") or _encoder_available(), "KTX-Software is not installed")
    def test_baked_files_pass_khronos_validation(self):
        _room, reflection = self._probe("room", "REFLECTION_PROBE", bake_resolution="64")
        _gi, volume = self._probe("gi", "IRRADIANCE_VOLUME", bake_voxels=(3, 2, 1))
        _floor, lightmap = self._lightmapped(resolution="128")
        self.assertEqual(bpy.ops.bevy_components.bake_lighting(), {"FINISHED"})
        path, _version = addon.encoder.check_encoder()
        for item in (reflection, volume, lightmap):
            result = subprocess.run([str(path), "validate", bpy.path.abspath(item.probe_file)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{item.probe_file}: {result.stdout}{result.stderr}")

    def test_one_probe_bakes_alone(self):
        _first, first = self._probe("first", "REFLECTION_PROBE", bake_resolution="64")
        _second, second = self._probe("second", "IRRADIANCE_VOLUME", bake_voxels=(1, 1, 1))
        self.assertEqual(bpy.ops.bevy_components.bake_lighting(object_name="second", index=0), {"FINISHED"})
        self.assertEqual((first.probe_file, second.probe_file), ("", "//baked_lighting/second_irradiance.ktx2"))
        self.assertEqual([path.name for path in self.folder.iterdir()], ["second_irradiance.ktx2"])
        with self.assertRaisesRegex(RuntimeError, "No Bevy Sky or enabled Lightmaps, Reflection Probes or Irradiance Volumes to bake"):
            bpy.ops.bevy_components.bake_lighting(object_name="second", index=1)

    def test_needs_a_folder_and_object_mode(self):
        cube = add_mesh(bpy.ops.mesh.primitive_cube_add, "cube")
        self._probe("room", "REFLECTION_PROBE", bake_resolution="64")
        self.settings.folder = " "
        with self.assertRaisesRegex(RuntimeError, "Pick a folder for the baked lighting files"):
            bpy.ops.bevy_components.bake_lighting()
        select(cube)
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            self.assertFalse(bpy.ops.bevy_components.bake_lighting.poll())
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")
        self.assertTrue(bpy.ops.bevy_components.bake_lighting.poll())

    def test_unsaved_files_need_a_folder_of_their_own(self):
        bpy.ops.wm.read_homefile(use_empty=True)
        self.scene = bpy.context.scene
        self.scene.world = bpy.data.worlds.new("World")
        settings = self.scene.bevy_bake_settings
        settings.samples = 4
        _gi, volume = self._probe("gi", "IRRADIANCE_VOLUME", bake_voxels=(1, 1, 1))
        with self.assertRaisesRegex(RuntimeError, "Save the .blend file first, or pick a bake folder that does not start with //"):
            bpy.ops.bevy_components.bake_lighting()
        settings.folder = str(self.folder)
        self.assertEqual(bpy.ops.bevy_components.bake_lighting(), {"FINISHED"})
        self.assertEqual(volume.probe_file, str(self.folder / "gi_irradiance.ktx2"))

    def test_failures_keep_the_probes_that_finished(self):
        _first, first = self._probe("first", "REFLECTION_PROBE")
        _second, second = self._probe("second", "REFLECTION_PROBE")

        def failing(scene, view_layer, jobs, samples, lamp_direct):
            yield jobs[0]
            raise RuntimeError("Cycles ran out of memory")

        with mock.patch.object(addon.operator, "bake_jobs", failing):
            with self.assertRaisesRegex(RuntimeError, "Baking lighting failed after 1 reflection probe: Cycles ran out of memory"):
                bpy.ops.bevy_components.bake_lighting()
        self.assertEqual((first.probe_file, second.probe_file), ("//baked_lighting/first_reflection.ktx2", ""))

    def test_dialog_shows_the_settings_and_what_it_bakes(self):
        operator = _bake_operator(layout=FakeLayout(self))
        addon.operator.BEVY_OT_bake_lighting.draw(operator, bpy.context)
        self.assertEqual(operator.layout.props(), ["samples", "folder", "lamp_direct", "export_again"])
        self.assertIn("No Bevy Sky or enabled Lightmaps, Reflection Probes or Irradiance Volumes in this scene", " ".join(operator.layout.texts()))
        self._probe("room", "REFLECTION_PROBE")
        self._probe("hall", "REFLECTION_PROBE")
        self._probe("gi", "IRRADIANCE_VOLUME")
        operator = _bake_operator(layout=FakeLayout(self))
        addon.operator.BEVY_OT_bake_lighting.draw(operator, bpy.context)
        self.assertIn("Bakes 2 reflection probes and 1 irradiance volume", operator.layout.texts())
        self.assertNotIn("Bevy Ambient Light", " ".join(operator.layout.texts()))
        self.scene.world.bevy_ambient_light.enabled = True
        operator = _bake_operator(layout=FakeLayout(self))
        addon.operator.BEVY_OT_bake_lighting.draw(operator, bpy.context)
        self.assertIn("Bevy Ambient Light adds to the sky light baked into irradiance volumes", " ".join(operator.layout.texts()))
        operator = _bake_operator(layout=FakeLayout(self), object_name="room", index=0)
        addon.operator.BEVY_OT_bake_lighting.draw(operator, bpy.context)
        self.assertIn("Bakes 1 reflection probe", operator.layout.texts())

    def test_background_bakes_render_a_saved_copy(self):
        _room, reflection = self._probe("room", "REFLECTION_PROBE", bake_resolution="64")
        gi, volume = self._probe("gi", "IRRADIANCE_VOLUME", bake_voxels=(2, 1, 2))
        _floor, lightmap = self._lightmapped(resolution="128")
        context = self._context()
        operator = self._start(context)
        scratch = Path(operator._directory.name)
        context.window_manager.modal_handler_add.assert_called_once_with(operator)
        context.window_manager.event_timer_add.assert_called_once_with(addon.operator.PROGRESS_INTERVAL, window="window")
        self.assertIs(addon.operator.running_bake(), operator._task)
        self.assertEqual(json.loads((scratch / "bake.json").read_text(encoding="utf-8"))["jobs"], operator._jobs)
        bpy.data.objects.remove(gi)
        self.assertEqual(_wait_for(operator, context), {"FINISHED"})
        self.assertEqual(operator.reports, [("INFO", "Baked 1 lightmap and 1 reflection probe into //baked_lighting/")])
        self.assertEqual((reflection.probe_file, lightmap.probe_file), ("//baked_lighting/room_reflection.ktx2", "//baked_lighting/floor_lightmap.ktx2"))
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["floor_lightmap.ktx2", "gi_irradiance.ktx2", "room_reflection.ktx2"])
        self.assertEqual(addon.probe.check_texture((self.folder / "floor_lightmap.ktx2").read_bytes(), "LIGHTMAP"), (None, "128 × 128 lightmap"))
        self.assertEqual(addon.probe.check_texture((self.folder / "gi_irradiance.ktx2").read_bytes(), "VOXELS"), (None, "2 × 1 × 2 voxels"))
        context.window_manager.event_timer_remove.assert_called_once_with("timer")
        self.assertEqual(addon.operator._bakes, {})
        self.assertFalse(scratch.exists())

    def test_cancelled_background_bakes_clean_up(self):
        _room, reflection = self._probe("room", "REFLECTION_PROBE", bake_resolution="64")
        context = self._context()
        operator = self._start(context)
        scratch = Path(operator._directory.name)
        bpy.ops.bevy_components.cancel_bake()
        self.assertEqual(_wait_for(operator, context), {"CANCELLED"})
        self.assertEqual(operator.reports, [("INFO", "Cancelled baking lighting")])
        self.assertEqual(reflection.probe_file, "")
        self.assertFalse(scratch.exists())
        operator = self._start(context)
        scratch = Path(operator._directory.name)
        operator.cancel(context)
        self.assertEqual(addon.operator._bakes, {})
        self.assertFalse(scratch.exists())

    def test_background_failures_are_reported(self):
        self._probe("room", "REFLECTION_PROBE", bake_resolution="64")
        (Path(self.directory.name) / "taken").write_text("not a folder", encoding="utf-8")
        self.settings.folder = "//taken/baked"
        context = self._context()
        operator = self._start(context)
        self.assertEqual(_wait_for(operator, context), {"CANCELLED"})
        self.assertEqual([level for level, message in operator.reports], ["ERROR"])
        self.assertRegex(operator.reports[0][1], "^Baking lighting failed: .*taken")


class TestSharedExponents(unittest.TestCase):
    def test_values_survive_the_round_trip(self):
        values = 10 ** numpy.random.default_rng(7).uniform(-4, 4.8, (4096, 3))
        values = numpy.concatenate((values, [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [65408.0, 1.0, 0.0], [90000.0, -5.0, numpy.nan], [1e-9, 0.0, 0.0]]))
        packed = numpy.frombuffer(addon.bake.shared_exponents(values), dtype="<u4")
        self.assertEqual(int(packed[-4]), 256 | 256 << 9 | 256 << 18 | 16 << 27)
        self.assertEqual(int(packed[-5]), 0)
        self.assertTrue(((packed >> 27) <= 31).all())
        decoded = numpy.stack([(packed >> shift) & 511 for shift in (0, 9, 18)], axis=-1) * 2.0 ** ((packed >> 27).astype(numpy.float64) - 24)[..., None]
        expected = numpy.clip(numpy.nan_to_num(values), 0.0, 65408.0)
        self.assertTrue(numpy.array_equal(decoded[-3], [65408.0, 0.0, 0.0]))
        self.assertTrue((numpy.abs(decoded - expected) <= expected.max(axis=-1, keepdims=True) * 2.0 ** -9 + 2.0 ** -24).all())


class TestBackgroundBake(unittest.TestCase):
    def _run(self, script, total, **options):
        task = addon.bake.BackgroundBake([sys.executable, "-c", script], total, **options)
        self.assertTrue(task.wait(60))
        self.assertFalse(task.running)
        return task

    def test_progress_comes_from_the_output(self):
        task = self._run("print('BEVY_BAKE_SAMPLES 8 32'); print('BEVY_BAKE_PROGRESS 1'); print('BEVY_BAKE_SAMPLES 16 32'); print('BEVY_BAKE_PROGRESS 2')", 2)
        self.assertEqual((task.done, task.fraction, task.error, task.cancelled), (2, 0.0, None, False))
        task = self._run("print('BEVY_BAKE_PROGRESS 1'); print('BEVY_BAKE_SAMPLES 8 32')", 2)
        self.assertEqual((task.done, task.fraction, task.error), (1, 0.25, "Blender stopped after baking 1 of 2: no output"))

    def test_failures_are_reported(self):
        cases = (
            ("print('BEVY_BAKE_ERROR No space left on device'); raise SystemExit(1)", "No space left on device"),
            ("print('Segmentation fault'); raise SystemExit(139)", "Blender stopped with exit code 139: Segmentation fault"),
            ("print('BEVY_BAKE_PROGRESS 1'); print('Blender quit')", "Blender stopped after baking 1 of 2: Blender quit"),
        )
        for script, error in cases:
            self.assertEqual(self._run(script, 2).error, error, script)

    def test_cancel_stops_blender(self):
        task = addon.bake.BackgroundBake([sys.executable, "-c", "import time; print('BEVY_BAKE_PROGRESS 1', flush=True); time.sleep(60)"], 3)
        deadline = time.monotonic() + 30
        while task.done < 1 and time.monotonic() < deadline:
            time.sleep(0.05)
        task.cancel()
        self.assertTrue(task.wait(30))
        self.assertEqual((task.done, task.cancelled, task.error), (1, True, None))

    def test_temporary_files_stay_in_the_scratch_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self._run("import tempfile; print('BEVY_BAKE_ERROR ' + tempfile.gettempdir())", 1, scratch=directory)
        self.assertEqual(task.error, directory)

    def test_blender_runs_the_bake_module_from_the_add_on(self):
        command = addon.bake.bake_command("blender", "scene.blend", "bake.json")
        self.assertEqual(command[:6], ["blender", "--background", "scene.blend", "--python-exit-code", "1", "--python-expr"])
        self.assertIn(repr(str(Path(addon.bake.__file__).parent)), command[6])
        self.assertIn(".run('bake.json')", command[6])


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
        build_sample_scene(cls.directory.name)
        cls.images = _image_state()
        cls.cache = Path(cls.directory.name) / "texture_cache"
        cls.cache.mkdir()
        cls.cache_patch = mock.patch.object(addon.operator, "texture_cache", return_value=cls.cache)
        cls.cache_patch.start()
        cls.exports = {}
        for mode in ("DISABLED", "ETC1S", "UASTC", "AUTOMATIC"):
            path = Path(cls.directory.name) / f"scene_{mode.lower()}.glb"
            export_sample_scene(path, texture_compression=mode)
            cls.exports[mode] = addon.compression.read_glb(path.read_bytes())
        cls.compressed = {mode: cls.exports[mode] for mode in ("ETC1S", "UASTC", "AUTOMATIC")}

    @classmethod
    def tearDownClass(cls):
        cls.cache_patch.stop()
        cls.directory.cleanup()

    def test_compression_is_off_by_default(self):
        gltf, binary = self.exports["DISABLED"]
        self.assertNotIn("KHR_texture_basisu", gltf.get("extensionsUsed", []))
        self.assertEqual({image["mimeType"] for image in gltf["images"] if image["name"] not in LIGHTING_IMAGES}, {"image/png"})
        self.assertEqual({image["mimeType"] for image in gltf["images"] if image["name"] in LIGHTING_IMAGES}, {"image/ktx2"})
        self.assertIn(addon.compression.PNG_SIGNATURE, binary)

    def test_textures_reference_embedded_ktx2(self):
        for mode, (gltf, binary) in self.compressed.items():
            self.assertIn("KHR_texture_basisu", gltf["extensionsUsed"], mode)
            self.assertIn("KHR_texture_basisu", gltf["extensionsRequired"], mode)
            self.assertEqual(len(gltf["textures"]), 12, mode)
            for texture in gltf["textures"]:
                if "source" in texture:
                    self.assertIn(gltf["images"][texture["source"]]["name"], LIGHTING_IMAGES, mode)
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
            self.assertEqual(names, ["ball_pixels", "ground_lightmap", "irradiance_volume", "lamp_emissive", "metal_color", "pillar_gradient", "probe_cubemap", "wood_color", "wood_normal", "wood_orm", "wood_orm"], mode)
            sources = [texture["extensions"]["KHR_texture_basisu"]["source"] for texture in gltf["textures"] if "source" not in texture]
            self.assertEqual(len(sources) - len(set(sources)), 1, mode)

    def test_embedded_ktx2_files_pass_khronos_validation(self):
        path, _version = addon.encoder.check_encoder()
        for mode, (gltf, binary) in self.compressed.items():
            for index, image in enumerate(gltf["images"]):
                file = Path(self.directory.name) / f"{mode}_{index}.ktx2"
                file.write_bytes(addon.compression.image_payload(gltf, binary, index)[0])
                result = subprocess.run([str(path), "validate", *(() if image["name"] in LIGHTING_IMAGES else ("--gltf-basisu",)), str(file)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, f"{mode} {image['name']}: {result.stdout}{result.stderr}")

    def test_codecs_color_spaces_and_mipmaps(self):
        for mode, (gltf, binary) in self.compressed.items():
            usages = _usages(gltf)
            for index, (name, _mime_type, model, width, height, levels, transfer, primaries) in enumerate(_texture_summary(gltf, binary)):
                if name in LIGHTING_IMAGES:
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
            self.assertTrue(path.is_file(), f"Missing {path}, run tests/blender/sample_scene.py to create it")
            gltf, binary = addon.compression.read_glb(path.read_bytes())
            fresh, fresh_binary = self.compressed[mode]
            self.assertEqual(_node_summary(gltf), _node_summary(fresh), f"{path.name} is out of date, run tests/blender/sample_scene.py to regenerate it")
            self.assertEqual(_sorted_texture_summary(gltf, binary), _sorted_texture_summary(fresh, fresh_binary), f"{path.name} is out of date, run tests/blender/sample_scene.py to regenerate it")


    def test_reexports_reuse_cached_textures(self):
        self.assertTrue(any(self.cache.glob("*.ktx2")))
        path = Path(self.directory.name) / "scene_again.glb"
        with mock.patch.object(addon.encoder, "_run", side_effect=AssertionError("textures were encoded again")):
            export_sample_scene(path, texture_compression="AUTOMATIC")
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
        build_sample_scene()
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "scene.glb"
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
        self.path.write_bytes(b"previous scene")
        with mock.patch.object(addon.operator, "check_encoder", return_value=(Path("ktx"), (4, 4, 0))), mock.patch.object(addon.operator, "encode", side_effect=addon.encoder.EncoderError("KTX-Software could not encode wood_color: broken input")):
            with self.assertRaisesRegex(RuntimeError, "Texture compression failed: KTX-Software could not encode wood_color: broken input"):
                bpy.ops.export_scene.bevy_components_glb(filepath=str(self.path), texture_compression="ETC1S")
        self.assertEqual(self.path.read_bytes(), b"previous scene")
        self.assertEqual(sorted(path.name for path in Path(self.directory.name).iterdir()), ["scene.glb"])

    def test_invalid_encoder_output_is_rejected(self):
        with mock.patch.object(addon.operator, "check_encoder", return_value=(Path("ktx"), (4, 4, 0))), mock.patch.object(addon.operator, "encode", side_effect=lambda path, jobs, *args, **options: [b"not ktx2"] * len(jobs)):
            with self.assertRaisesRegex(RuntimeError, "the encoder wrote an invalid KTX2 file"):
                bpy.ops.export_scene.bevy_components_glb(filepath=str(self.path), texture_compression="UASTC")
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
