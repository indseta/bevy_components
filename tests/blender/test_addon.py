import json
import sys
import tempfile
import unittest
from pathlib import Path

import bpy
import gpu
from mathutils import Matrix, Vector

from sample_level import FIXTURE, add_component, add_empty, add_mesh, apply_lod_preset, build_sample_level, clear_scene, export_sample_level, install_addon, read_gltf, select, uninstall_addon

LAYOUT = bpy.types.UILayout.bl_rna
ICONS = set(LAYOUT.functions["label"].parameters["icon"].enum_items.keys())
CHILD_LAYOUTS = {"row", "column", "box", "split", "grid_flow", "column_flow"}
DEFAULT_COLLIDER = {"size": [1.0, 1.0, 1.0], "radius": 0.5, "height": 1.0, "sensor": False}
EXPECTED_COMPONENTS = {
    "ground": [
        {"type": "collider", "shape": "trimesh", **DEFAULT_COLLIDER},
        {"type": "rigid_body", "kind": "static"},
    ],
    "crate": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [2.0, 2.0, 2.0]}},
        {"type": "rigid_body", "kind": "dynamic"},
        {"type": "visibility_range", "start": [20.0, 25.0], "end": [80.0, 85.0], "use_aabb": False},
    ],
    "crate_copy": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [2.0, 2.0, 2.0]}},
        {"type": "rigid_body", "kind": "dynamic"},
        {"type": "visibility_range", "start": [20.0, 25.0], "end": [80.0, 85.0], "use_aabb": False},
    ],
    "ball": [
        {"type": "collider", "shape": "sphere", **DEFAULT_COLLIDER},
        {"type": "rigid_body", "kind": "kinematic"},
    ],
    "pillar": [
        {"type": "collider", "shape": "capsule", **{**DEFAULT_COLLIDER, "radius": 0.4, "height": 1.2}},
    ],
    "rock": [
        {"type": "collider", "shape": "convex", **DEFAULT_COLLIDER},
        {"type": "rigid_body", "kind": "dynamic"},
    ],
    "trigger_zone": [
        {"type": "collider", "shape": "cuboid", **{**DEFAULT_COLLIDER, "size": [1.0, 2.0, 3.0], "sensor": True}},
    ],
    "pickup_zone": [
        {"type": "collider", "shape": "sphere", **{**DEFAULT_COLLIDER, "radius": 1.5, "sensor": True}},
    ],
    "player_spawn": [
        {"type": "spawn_point", "tag": "player"},
    ],
    "enemy_spawn": [
        {"type": "spawn_point", "tag": "enemy"},
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
}

addon = None


def setUpModule():
    global addon
    addon = sys.modules[install_addon()]


def tearDownModule():
    uninstall_addon()
    if hasattr(bpy.types.Object, "bevy_component_data") or _operator_exists("bevy_components.add"):
        raise AssertionError("Bevy Components did not unregister cleanly")


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
    def __init__(self, test, calls=None):
        object.__setattr__(self, "test", test)
        object.__setattr__(self, "calls", [] if calls is None else calls)

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
        if name == "prop":
            self.test.assertIn(bound["property"], bound["data"].bl_rna.properties.keys())
        self.calls.append((name, bound))
        if name == "operator":
            self.test.assertTrue(_operator_exists(bound["operator"]), bound["operator"])
            return FakeOperatorProperties(self.test, bound["operator"])
        if name in CHILD_LAYOUTS:
            return FakeLayout(self.test, self.calls)
        return None

    def texts(self):
        return [bound.get("text", "") for name, bound in self.calls]

    def operators(self):
        return [bound["operator"] for name, bound in self.calls if name == "operator"]


class FakePanel:
    def __init__(self, test):
        self.layout = FakeLayout(test)


class TestRegistration(unittest.TestCase):
    def test_extension_registers_types_and_operators(self):
        self.assertTrue(hasattr(bpy.types.Object, "bevy_component_data"))
        self.assertTrue(hasattr(bpy.types.Scene, "bevy_component_previews"))
        for idname in ("bevy_components.add", "bevy_components.remove", "bevy_components.lod_preset", "bevy_components.copy_to_selected", "bevy_components.validate", "export_scene.bevy_components_glb"):
            self.assertTrue(_operator_exists(idname), idname)
        self.assertIn(addon.panel.export_menu, bpy.types.TOPBAR_MT_file_export._dyn_ui_initialize())
        self.assertIn(addon.system.save_sync, bpy.app.handlers.save_pre)

    def test_add_operator_searches_component_types(self):
        self.assertEqual(addon.operator.BEVY_OT_add_component.bl_property, "component_type")

    def test_disable_and_enable_keeps_components(self):
        clear_scene()
        obj = add_mesh(bpy.ops.mesh.primitive_cube_add, "kept")
        add_component(obj, "SPAWN_POINT", spawn_tag="kept")
        bpy.ops.preferences.addon_disable(module=addon.__name__)
        self.assertFalse(hasattr(bpy.types.Object, "bevy_component_data"))
        self.assertFalse(_operator_exists("bevy_components.add"))
        bpy.ops.preferences.addon_enable(module=addon.__name__)
        self.assertEqual(obj.bevy_component_data.components[0].spawn_tag, "kept")
        self.assertEqual(_stored(obj)["components"], [{"type": "spawn_point", "tag": "kept"}])


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
        add_component(self.obj, "SPAWN_POINT")
        self.assertEqual(bpy.ops.bevy_components.remove(index=5), {"CANCELLED"})
        self.assertEqual(bpy.ops.bevy_components.remove(index=0), {"FINISHED"})
        self.assertEqual(_stored(self.obj)["components"], [{"type": "spawn_point", "tag": "default"}])
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
        add_component(self.obj, "COLLIDER", collider_shape="CAPSULE", collider_radius=0.3, collider_height=1.7, collider_size=(1, 2, 3), collider_sensor=True)
        add_component(self.obj, "CUSTOM", custom_type="game::Tag", custom_json='{"a": 1}')
        first = add_mesh(bpy.ops.mesh.primitive_cube_add, "first")
        add_component(first, "SPAWN_POINT")
        second = add_empty("second", (0, 0, 0))
        select(self.obj, first, second)
        self.assertEqual(bpy.ops.bevy_components.copy_to_selected(), {"FINISHED"})
        for obj in (first, second):
            self.assertEqual(_stored(obj), _stored(self.obj))
            self.assertEqual(tuple(obj.bevy_component_data.components[0].collider_size), (1.0, 2.0, 3.0))

    def test_validate(self):
        add_component(self.obj, "VISIBILITY_RANGE")
        self.assertEqual(bpy.ops.bevy_components.validate(), {"FINISHED"})
        item = add_component(self.obj, "CUSTOM", custom_json="{broken")
        with self.assertRaises(RuntimeError):
            bpy.ops.bevy_components.validate()
        item.custom_json = "[1, 2]"
        self.assertEqual(bpy.ops.bevy_components.validate(), {"FINISHED"})

    def test_invalid_custom_json_is_not_stored(self):
        add_component(self.obj, "CUSTOM", custom_json="{broken")
        self.assertNotIn("bevy_components", self.obj.keys())

    def test_save_and_reload(self):
        add_component(self.obj, "COLLIDER", collider_shape="SPHERE", collider_radius=2)
        self.obj["bevy_components"] = "stale"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "level.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(path))
            bpy.ops.wm.open_mainfile(filepath=str(path))
        obj = bpy.data.objects["subject"]
        self.assertEqual(obj.bevy_component_data.components[0].collider_radius, 2.0)
        self.assertEqual(_stored(obj)["components"][0]["radius"], 2.0)


class TestPanels(unittest.TestCase):
    def setUp(self):
        clear_scene()
        self.obj = add_mesh(bpy.ops.mesh.primitive_cube_add, "subject")

    def test_object_panel_draws_every_component(self):
        for kind in ("VISIBILITY_RANGE", "COLLIDER", "RIGID_BODY", "SPAWN_POINT", "CUSTOM"):
            add_component(self.obj, kind)
        collider = self.obj.bevy_component_data.components[1]
        for shape in ("TRIMESH", "CONVEX", "CUBOID", "SPHERE", "CAPSULE"):
            collider.collider_shape = shape
            panel = FakePanel(self)
            self.assertTrue(addon.panel.BEVY_PT_object_properties.poll(bpy.context))
            addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
            self.assertIn("bevy_components.add", panel.layout.operators())
            self.assertIn("export_scene.bevy_components_glb", panel.layout.operators())
        self.assertNotIn("Distances must be ordered", panel.layout.texts())

    def test_object_panel_flags_bad_ranges_and_collapsed_cards(self):
        add_component(self.obj, "VISIBILITY_RANGE", fade_in_end=50)
        add_component(self.obj, "COLLIDER", expanded=False)
        panel = FakePanel(self)
        addon.panel.BEVY_PT_object_properties.draw(panel, bpy.context)
        self.assertIn("Distances must be ordered", panel.layout.texts())
        self.assertNotIn("Shape", panel.layout.texts())

    def test_sidebar_without_active_object(self):
        select()
        panel = FakePanel(self)
        addon.panel.BEVY_PT_view_sidebar.draw(panel, bpy.context)
        self.assertEqual(panel.layout.texts(), ["Select an object"])

    def test_sidebar_and_viewport_controls(self):
        add_component(self.obj, "SPAWN_POINT")
        select(self.obj)
        addon.panel.BEVY_PT_view_sidebar.draw(FakePanel(self), bpy.context)
        settings = bpy.context.scene.bevy_component_previews
        for scope, edit_handles in (("SELECTED", True), ("ALL", False)):
            settings.scope = scope
            settings.edit_handles = edit_handles
            addon.panel.BEVY_PT_viewport_previews.draw(FakePanel(self), bpy.context)

    def test_export_menu(self):
        panel = FakePanel(self)
        addon.panel.export_menu(panel, bpy.context)
        self.assertEqual(panel.layout.operators(), ["export_scene.bevy_components_glb"])


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
        spawn = add_empty("spawn", (5, 0, 0))
        add_component(spawn, "SPAWN_POINT")
        select(self.obj)
        colors = [color for obj, lines, color, width in addon.overlay.preview_batches(bpy.context, self.settings)]
        self.assertEqual(colors, [addon.overlay.SENSOR_COLOR, addon.overlay.LOD_OUT_COLOR, addon.overlay.LOD_OUT_COLOR])
        self.settings.scope = "ALL"
        self.assertEqual(len(addon.overlay.preview_batches(bpy.context, self.settings)), 4)
        self.settings.colliders = False
        self.settings.visibility_ranges = False
        self.assertEqual([obj.name for obj, lines, color, width in addon.overlay.preview_batches(bpy.context, self.settings)], ["spawn"])
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
        add_component(self.obj, "SPAWN_POINT", spawn_tag="hero")
        self.assertEqual(addon.overlay._label_lines(self.obj, self.settings), ["Collider · Capsule · r=0.25, cylinder=2m", "LOD · in 0–0m · out 20–25m", "Spawn · hero"])

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
        self.assertEqual(set(self.nodes), set(EXPECTED_COMPONENTS) | {"chimney", "sun"})
        self.assertEqual(self.nodes["house"].get("children"), [self.gltf["nodes"].index(self.nodes["chimney"])])

    def test_component_extras(self):
        for name, expected in EXPECTED_COMPONENTS.items():
            extras = self.nodes[name]["extras"]
            self.assertEqual(list(extras), ["bevy_components"], name)
            exported = json.loads(extras["bevy_components"])
            self.assertEqual(exported["version"], 1)
            self.assertEqual(_rounded(exported["components"]), expected, name)

    def test_editor_state_is_not_exported(self):
        self.assertNotIn("extras", self.nodes["chimney"])
        self.assertNotIn("extras", self.nodes["sun"])
        self.assertTrue(all("extras" not in scene for scene in self.gltf["scenes"]))

    def test_transforms_are_y_up(self):
        self.assertEqual(_rounded(self.nodes["crate"]["translation"]), [3.0, 1.0, 2.0])
        self.assertEqual(_rounded(self.nodes["crate"]["rotation"]), [0.0, 0.25882, 0.0, 0.96593])
        self.assertEqual(_rounded(self.nodes["trigger_zone"]["scale"]), [2.0, 1.0, 1.0])
        self.assertEqual(_rounded(self.nodes["player_spawn"]["translation"]), [2.0, 0.0, -3.0])

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


if __name__ == "__main__":
    unittest.main()
