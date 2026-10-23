import importlib.util
import json
import math
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "addon" / "bsn.py"
spec = importlib.util.spec_from_file_location("bevy_bsn", MODULE)
bsn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bsn)

BODY = [{"type": "collider", "shape": "cuboid", "size": [1, 1, 1]}, {"type": "rigid_body", "kind": "dynamic"}]
CONVEX = [{"type": "collider", "shape": "convex"}, {"type": "rigid_body", "kind": "dynamic"}]


def node(name, components=(), **fields):
    if components:
        fields["extras"] = {"bevy_components": json.dumps({"version": 1, "components": list(components)})}
    return {"name": name, **fields}


def scene(*nodes, meshes=1, **fields):
    return {
        "nodes": list(nodes),
        "scenes": [{"nodes": [index for index in range(len(nodes)) if not any(index in other.get("children", []) for other in nodes)]}],
        "meshes": [{"name": f"Mesh{index}", "primitives": [{"attributes": {"POSITION": 0}, "material": index}]} for index in range(meshes)],
        **fields,
    }


def source(gltf, glb="scenes/level.glb", name="level", **options):
    return bsn.scene_source(gltf, glb, name, **options)


def body(gltf, **options):
    text, _warnings = source(gltf, **options)
    return text.partition("\n")[2]


def function(text, name):
    start = text.index(f"fn {name}() -> impl Scene")
    return text[start:text.index("\n}\n", start)]


class TestPrefabs(unittest.TestCase):
    def test_shared_mesh_and_behavior_make_one_prefab(self):
        text, warnings = source(scene(node("Rock.001", BODY, mesh=0, translation=[1, 0, 0]), node("Rock.002", BODY, mesh=0, translation=[2, 0, 0])))
        self.assertEqual(warnings, [])
        self.assertEqual(text.count("@object_rock()"), 2)
        prefab = function(text, "object_rock")
        self.assertIn('Mesh3d("scenes/level.glb#Mesh0/Primitive0")', prefab)
        self.assertIn("Collider::cuboid(1.0, 1.0, 1.0)", prefab)
        self.assertIn("RigidBody::Dynamic", prefab)
        setup = function(text, "setup")
        self.assertNotIn("Mesh3d", setup)
        self.assertNotIn("Collider", setup)
        self.assertIn('Name("Rock.001")\n            @object_rock()\n            Transform { translation: Vec3::new(1.0, 0.0, 0.0) }', setup)

    def test_different_meshes_share_only_behavior(self):
        text, _warnings = source(scene(node("barrel", CONVEX, mesh=0), node("crate_box", CONVEX, mesh=1), meshes=2))
        prefab = function(text, "object_dynamic_convex")
        self.assertNotIn("Mesh3d", prefab)
        self.assertIn("ColliderConstructor::ConvexHullFromMesh", prefab)
        setup = function(text, "setup")
        self.assertEqual(setup.count("@object_dynamic_convex()"), 2)
        self.assertIn('Mesh3d("scenes/level.glb#Mesh0/Primitive0")', setup)
        self.assertIn('Mesh3d("scenes/level.glb#Mesh1/Primitive0")', setup)

    def test_prefab_names(self):
        cases = [
            (["crate_small", "crate_big"], BODY, "object_crate"),
            (["rocket", "rock"], BODY, "object_dynamic_cuboid"),
            (["coin", "gem"], [{"type": "custom", "type_path": "my_game::Pickup<u32>", "data": {}}], "object_pickup"),
            (["Tree.001", "Tree.002"], [{"type": "shadows", "cast": False}], "object_tree"),
        ]
        for names, components, expected in cases:
            text, _warnings = source(scene(*(node(name, components, mesh=0) for name in names)))
            self.assertIn(f"pub fn {expected}() -> impl Scene", text, names)

    def test_objects_with_only_a_mesh_get_no_prefab(self):
        text, _warnings = source(scene(node("tree.001", mesh=0), node("tree.002", mesh=0)))
        self.assertNotIn("object_", text)
        self.assertEqual(text.count('Mesh3d("scenes/level.glb#Mesh0/Primitive0")'), 2)

    def test_single_objects_get_no_prefab(self):
        text, _warnings = source(scene(node("rock", BODY, mesh=0), node("ball", [{"type": "collider", "shape": "sphere"}], mesh=0)))
        self.assertNotIn("object_", text)

    def test_prefab_functions_can_be_turned_off(self):
        gltf = scene(node("Rock.001", BODY, mesh=0), node("Rock.002", BODY, mesh=0))
        text, _warnings = source(gltf, prefabs=False)
        self.assertNotIn("object_", text)
        self.assertEqual(text.count("RigidBody::Dynamic"), 2)
        self.assertEqual(text.count("Mesh3d("), 2)

    def test_animated_objects_are_never_shared(self):
        gltf = scene(node("door_a", BODY, mesh=0), node("door_b", BODY, mesh=0), animations=[{"name": "open", "channels": [{"target": {"node": 0, "path": "rotation"}}]}])
        text, _warnings = source(gltf)
        self.assertNotIn("object_", text)
        self.assertIn('~AnimationTargetId::from_names([Name::new("door_a")].iter())', text)
        self.assertIn("@animated_by(#door_a)", text)


class TestLiterals(unittest.TestCase):
    def test_custom_components(self):
        cases = [
            ("my_game::Marker", {}, None, "my_game::Marker"),
            ("my_game::Marker", None, "my_game", "crate::Marker"),
            ("my_game::Health", 5, None, "my_game::Health(5)"),
            ("my_game::Pair", [1, "two"], None, 'my_game::Pair(1, "two")'),
            ("other::Wrapper<f32>", {"value": 0.5}, "my_game", "other::Wrapper::<f32> { value: 0.5 }"),
            ("my_game::Pickup", {"item": "coin \"gold\"", "respawn": True, "spin": [0, 1.5, 0], "glow": {"Srgba": {"red": 1, "green": 0.5, "blue": 0, "alpha": 1}}}, "my_game", 'crate::Pickup { item: "coin \\"gold\\"", respawn: true, spin: Vec3::new(0.0, 1.5, 0.0), glow: Color::srgba(1.0, 0.5, 0.0, 1.0) }'),
            ("my_game::Tint", {"color": {"LinearRgba": {"red": 0.1, "green": 0.2, "blue": 0.3}}}, None, "my_game::Tint { color: Color::linear_rgba(0.1, 0.2, 0.3, 1.0) }"),
        ]
        for type_path, data, crate, expected in cases:
            self.assertEqual(bsn.custom_literal(type_path, data, crate), expected, type_path)

    def test_values_rust_cannot_hold(self):
        with self.assertRaisesRegex(bsn.BsnError, "not Rust names, so the BSN export cannot write it: max-speed, type"):
            bsn.custom_literal("my_game::Car", {"max-speed": 1, "type": 2, "ok": 3})
        with self.assertRaisesRegex(bsn.BsnError, "holds \\{\"a\": 1, \"b\": 2\\}, which the BSN export cannot write as Rust"):
            bsn.custom_literal("my_game::Nested", {"inner": {"a": 1, "b": 2}})
        with self.assertRaisesRegex(bsn.BsnError, "holds \\[1, 2, 3, 4, 5\\]"):
            bsn.custom_literal("my_game::Many", {"values": [1, 2, 3, 4, 5]})

    def test_rust_paths(self):
        self.assertEqual(bsn.rust_path("my_game::Health", "my_game"), "crate::Health")
        self.assertEqual(bsn.rust_path("my_game_extra::Health", "my_game"), "my_game_extra::Health")
        self.assertEqual(bsn.rust_path("my_game::Stat<my_game::Speed>", "my_game"), "crate::Stat::<my_game::Speed>")
        self.assertEqual(bsn.rust_path("my_game::Stat::<f32>"), "my_game::Stat::<f32>")

    def test_floats_round_trip_as_f32(self):
        cases = [(1, "1.0"), (0.1, "0.1"), (1 / 3, "0.33333334"), (-2.5, "-2.5"), (1e-5, "0.00001"), (1e-6, "1e-6"), (1e20, "1e20"), (123456.0, "123456.0"), (math.inf, "f32::INFINITY"), (-math.inf, "f32::NEG_INFINITY"), (math.nan, "f32::NAN"), (1e40, "f32::INFINITY")]
        for value, expected in cases:
            self.assertEqual(bsn._float(value), expected, value)

    def test_names(self):
        self.assertEqual(bsn.snake_case("Sample Scene"), "sample_scene")
        self.assertEqual(bsn.snake_case("HTTPServer.001"), "http_server_001")
        self.assertEqual(bsn.snake_case("my-level"), "my_level")
        self.assertTrue(bsn.identifier("crate_box"))
        for name in ("crate", "self", "_", "2nd", "rock.001", "a b"):
            self.assertFalse(bsn.identifier(name), name)

    def test_entity_names(self):
        text, _warnings = source(scene(node("crate", mesh=0), node("door"), node("Lamp Post"), node("lamp"), node("lamp")), name="level")
        self.assertIn('Name("crate")', text)
        self.assertIn("#door\n", text)
        self.assertIn('Name("Lamp Post")', text)
        self.assertEqual(text.count('Name("lamp")'), 2)
        self.assertNotIn("#lamp\n", text)


class TestScene(unittest.TestCase):
    def test_plain_scene_needs_only_the_prelude(self):
        text, warnings = source(scene(node("marker"), meshes=0), name="Empty Level")
        self.assertEqual(warnings, [])
        self.assertTrue(text.partition("\n")[2].startswith("use bevy::prelude::*;\n\npub fn setup() -> impl Scene {\n    return bsn! {\n        #empty_level\n        Transform\n        Visibility\n"))
        self.assertNotIn("preload", text)

    def test_meshes_preload_the_glb(self):
        text, _warnings = source(scene(node("rock", mesh=0)))
        self.assertTrue(text.partition("\n")[2].startswith("use bevy::{gltf::Gltf, prelude::*, scene::{ResolveContext, ResolveSceneError, ResolvedScene, SceneDependencies}};\n"))
        self.assertIn('@preload("scenes/level.glb")', function(text, "setup"))
        self.assertIn("dependencies.register::<Gltf>(self.0.into());", text)
        self.assertNotIn("avian3d", text)

    def test_physics_imports_avian(self):
        self.assertTrue(body(scene(node("rock", BODY, mesh=0))).startswith("use avian3d::prelude::*;\nuse bevy::"))

    def test_primitives_and_materials(self):
        gltf = {"nodes": [node("statue", mesh=0, scale=[-1, 1, 1])], "scenes": [{"nodes": [0]}], "meshes": [{"primitives": [{"attributes": {}}, {"attributes": {}, "material": 2}]}]}
        text, _warnings = source(gltf)
        self.assertIn('Children [\n                Transform\n                Mesh3d("scenes/level.glb#Mesh0/Primitive0")\n                MeshMaterial3d::<StandardMaterial>("scenes/level.glb#DefaultMaterial/std")\n                --\n                Transform\n                Mesh3d("scenes/level.glb#Mesh0/Primitive1")\n                MeshMaterial3d::<StandardMaterial>("scenes/level.glb#Material2 (inverted)/std")\n            ]', text)

    def test_children_keep_their_hierarchy(self):
        text, _warnings = source(scene(node("house", children=[1], translation=[0, 0, 5]), node("chimney", mesh=0, translation=[0, 3, 0])))
        self.assertIn("#house\n            Transform { translation: Vec3::new(0.0, 0.0, 5.0) }\n            Visibility\n            Children [\n                #chimney\n                Transform { translation: Vec3::new(0.0, 3.0, 0.0) }", text)

    def test_lights_follow_the_gltf_loader(self):
        lights = [{"type": "point", "intensity": 10.0, "range": 5.0}, {"type": "spot", "color": [1.0, 0.5, 0.25], "intensity": 1.0, "spot": {"innerConeAngle": 0.1, "outerConeAngle": 0.5}}, {"type": "directional", "intensity": 3.0}, {"type": "spot", "intensity": 1.0, "range": 8.0, "spot": {"innerConeAngle": 0.2, "outerConeAngle": 0.6}}]
        gltf = scene(node("lamp", extensions={"KHR_lights_punctual": {"light": 0}}), node("spot", [{"type": "light", "shadows": True}], extensions={"KHR_lights_punctual": {"light": 1}}), node("sun", extensions={"KHR_lights_punctual": {"light": 2}}), node("ranged_spot", extensions={"KHR_lights_punctual": {"light": 3}}), meshes=0, extensions={"KHR_lights_punctual": {"lights": lights}})
        text, _warnings = source(gltf)
        self.assertIn("PointLight { color: Color::srgb(1.0, 1.0, 1.0), intensity: 125.663704, range: 5.0, radius: 0.0 }", text)
        self.assertIn("SpotLight { color: Color::srgb(1.0, 0.5, 0.25), intensity: 12.566371, range: 20.0, radius: 0.0, inner_angle: 0.1, outer_angle: 0.5, shadow_maps_enabled: true }", text)
        self.assertIn("SpotLight { color: Color::srgb(1.0, 1.0, 1.0), intensity: 12.566371, range: 8.0, radius: 0.0, inner_angle: 0.2, outer_angle: 0.6 }", text)
        self.assertIn("DirectionalLight { color: Color::srgb(1.0, 1.0, 1.0), illuminance: 3.0 }", text)

    def test_scene_references(self):
        gltf = scene(node("house", [{"type": "scene_reference", "path": "props/windmill.glb", "scene": 1}]), node("far", [{"type": "scene_reference", "path": "../../outside.glb"}]), node("copied", [{"type": "scene_reference", "path": "../other/tree.glb"}]), meshes=0)
        text, warnings = source(gltf, files={"../other/tree.glb": "scenes/tree.glb"})
        self.assertIn('WorldAssetRoot("scenes/props/windmill.glb#Scene1")', text)
        self.assertIn('WorldAssetRoot("scenes/tree.glb#Scene0")', text)
        self.assertEqual(text.count("WorldAssetRoot("), 2)
        self.assertEqual(warnings, ["far: ../../outside.glb is outside the assets folder, so it is left out"])

    def test_probe_files_come_from_the_file_map(self):
        probe = {"type": "reflection_probe", "file": "//probes/room.ktx2", "intensity": 500.0}
        text, warnings = source(scene(node("room", [probe]), meshes=0), files={"//probes/room.ktx2": "scenes/room.ktx2"})
        self.assertEqual(warnings, [])
        self.assertIn('GeneratedEnvironmentMapLight { environment_map: "scenes/room.ktx2", intensity: 500.0, affects_lightmapped_mesh_diffuse: true }', text)
        text, warnings = source(scene(node("room", [probe]), meshes=0))
        self.assertNotIn("GeneratedEnvironmentMapLight", text)
        self.assertEqual(warnings, ["room: no cubemap file, so it is left out"])

    def test_ambient_light_sets_the_resource(self):
        gltf = scene(node("marker"), meshes=0)
        gltf["scenes"][0]["extras"] = {"bevy_components": json.dumps({"version": 1, "components": [{"type": "ambient_light", "color": [1, 0.5, 0.5], "brightness": 50, "baked": True}]})}
        text, _warnings = source(gltf)
        self.assertIn("@ambient_light(GlobalAmbientLight { color: Color::linear_rgb(1.0, 0.5, 0.5), brightness: 50.0, affects_lightmapped_meshes: false })", text)
        self.assertIn("fn ambient_light(light: GlobalAmbientLight) -> impl Scene", text)

    def test_joints_name_their_bodies(self):
        joint = {"type": "joint", "kind": "revolute", "body1": "frame", "body2": "door", "axis": [0, 2, 0]}
        text, _warnings = source(scene(node("frame", BODY), node("door", BODY, translation=[1, 0, 0]), node("hinge", [joint], translation=[0.5, 0, 0]), meshes=0))
        self.assertIn("@joint(#frame, #door, |body1, body2| RevoluteJoint::new(body1, body2).with_local_frame1(Isometry3d::new(Vec3::new(0.5, 0.0, 0.0), Quat::from_xyzw(0.0, 0.0, 0.0, 1.0))).with_local_frame2(Isometry3d::new(Vec3::new(-0.5, 0.0, 0.0), Quat::from_xyzw(0.0, 0.0, 0.0, 1.0))).with_hinge_axis(Vec3::new(0.0, 1.0, 0.0)))", text)
        self.assertIn("fn joint<J: Component + Clone>", text)

    def test_long_lists_move_into_list_functions(self):
        joint = {"type": "joint", "kind": "fixed", "body1": "frame", "body2": "door"}
        nodes = [node(f"rock_{index}", mesh=0) for index in range(600)]
        nodes[100:100] = [node("frame", BODY), node("door", BODY), node("hinge", [joint])]
        text, warnings = source(scene(*nodes))
        self.assertEqual(warnings, [])
        setup = function(text, "setup")
        self.assertEqual([line.strip() for line in setup.splitlines() if line.strip().startswith(("{", "#", "Name("))], ["#level", "{children_1()}", "#frame", "#door", "#hinge", "Name(\"hinge joint\")", "{children_2()}", "{children_3()}"])
        self.assertIn("@joint(#frame, #door,", setup)
        self.assertEqual([function(text, f"children_{number}").count("#rock_") for number in range(1, 4)], [100, 256, 244])
        self.assertIn("fn children_1() -> impl SceneList {\n    return bsn_list! {\n        #rock_0\n", text)
        self.assertIn("        #rock_99\n        Transform\n        Visibility\n        Mesh3d(\"scenes/level.glb#Mesh0/Primitive0\")\n        MeshMaterial3d::<StandardMaterial>(\"scenes/level.glb#Material0/std\")\n    };\n}", text)

    def test_short_lists_stay_inline(self):
        text, _warnings = source(scene(*(node(f"rock_{index}", mesh=0) for index in range(256))))
        self.assertNotIn("children_", text)
        self.assertNotIn("SceneList", text)


class TestSceneGraph(unittest.TestCase):
    def test_unanimated_scenes_drop_their_nodes(self):
        gltf = scene(node("rock", mesh=0), node("house", children=[2]), node("chimney", mesh=0))
        self.assertTrue(bsn.drop_scenes(gltf))
        self.assertEqual(sorted(gltf), ["meshes"])

    def test_mirrored_meshes_keep_a_node_for_their_inverted_materials(self):
        gltf = scene(node("statue", mesh=1, scale=[-1, 1, 1]), node("mirror", children=[2, 3], scale=[1, -1, 1]), node("flipped_back", mesh=0, scale=[1, 1, -1]), node("lamp", mesh=2), meshes=3)
        self.assertTrue(bsn.drop_scenes(gltf))
        self.assertEqual(gltf["nodes"], [{"mesh": 1, "scale": [-1.0, 1.0, 1.0]}, {"mesh": 2, "scale": [-1.0, 1.0, 1.0]}])
        self.assertEqual((gltf["scenes"], gltf["scene"]), ([{"nodes": [0, 1]}], 0))

    def test_animated_and_skinned_scenes_keep_their_nodes(self):
        for extra in ({"animations": [{"name": "spin", "channels": []}]}, {"skins": [{"joints": [0]}]}):
            gltf = scene(node("rock", mesh=0), **extra)
            before = json.dumps(gltf)
            self.assertFalse(bsn.drop_scenes(gltf))
            self.assertEqual(json.dumps(gltf), before)


class TestPaths(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def project(self, name="my-game", manifest="", library=False):
        folder = self.root / name
        (folder / "src").mkdir(parents=True)
        (folder / "Cargo.toml").write_text(f'[package]\nname = "{name}"\nversion = "0.1.0"\n{manifest}')
        if library:
            (folder / "src" / "lib.rs").write_text("")
        return folder

    def write(self, path, text=""):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_cargo_projects(self):
        project = self.project()
        self.assertEqual(bsn.cargo_project(project / "src" / "scenes" / "level.rs"), project)
        self.assertIsNone(bsn.cargo_project(self.root / "loose" / "level.rs"))
        self.assertEqual(bsn.module_crate(project / "src" / "level.rs"), "my_game")
        self.assertIsNone(bsn.module_crate(self.root / "loose" / "level.rs"))
        broken = self.root / "broken"
        broken.mkdir()
        (broken / "Cargo.toml").write_text("[package")
        self.assertIsNone(bsn.module_crate(broken / "src" / "level.rs"))

    def test_scenes_under_a_library_use_crate_paths(self):
        project = self.project(library=True)
        self.write(project / "src" / "main.rs", "fn main() {}\n")
        level = project / "src" / "level.rs"
        self.assertEqual(bsn.module_crate(level), "my_game")
        self.write(project / "src" / "lib.rs", "pub mod level;\n")
        self.assertEqual(bsn.module_crate(level), "my_game")
        self.write(project / "src" / "lib.rs", "")
        self.write(project / "src" / "main.rs", "// mod level;\n#[cfg(feature = \"x\")]\npub(crate) mod level;\nfn main() {}\n")
        self.assertIsNone(bsn.module_crate(level))
        self.write(project / "src" / "main.rs", "mod scenes;\nfn main() {}\n")
        self.write(project / "src" / "scenes" / "mod.rs", "pub mod forest;\n")
        self.assertIsNone(bsn.module_crate(project / "src" / "scenes" / "forest.rs"))
        self.assertEqual(bsn.module_crate(project / "src" / "scenes" / "desert.rs"), "my_game")
        self.write(project / "src" / "lib.rs", "pub mod scenes {\n    pub mod desert;\n}\n")
        self.assertEqual(bsn.module_crate(project / "src" / "scenes" / "desert.rs"), "my_game")

    def test_named_libraries_and_binaries(self):
        project = self.project("game", manifest='\n[lib]\nname = "game_core"\npath = "src/core.rs"\n\n[[bin]]\nname = "editor"\npath = "src/editor.rs"\n')
        self.write(project / "src" / "core.rs")
        self.write(project / "src" / "editor.rs", "mod level;\nfn main() {}\n")
        self.assertEqual(bsn.module_crate(project / "src" / "level.rs"), "editor")
        self.assertEqual(bsn.module_crate(project / "src" / "other.rs"), "game_core")
        self.assertEqual([(target.name, target.path.name, target.library) for target in bsn.crate_targets(project)], [("game_core", "core.rs", True), ("editor", "editor.rs", False)])
        self.write(project / "src" / "bin" / "tool.rs", "fn main() {}\n")
        self.assertEqual(bsn.crate_targets(project)[-1].name, "tool")

    def test_crate_roots(self):
        project = self.project(manifest='\n[[bin]]\nname = "editor"\npath = "tools/editor.rs"\n')
        self.write(project / "src" / "main.rs")
        self.write(project / "tools" / "editor.rs")
        self.write(project / "src" / "bin" / "tool.rs")
        self.write(project / "build.rs")
        for path in (project / "src" / "main.rs", project / "src" / "lib.rs", project / "tools" / "editor.rs", project / "src" / "bin" / "tool.rs", project / "build.rs", self.root / "loose" / "Main.rs"):
            self.assertTrue(bsn.crate_root(path), path)
        for path in (project / "src" / "level.rs", project / "src" / "scenes" / "mod.rs", project / "src" / "build.rs", self.root / "loose" / "level.rs"):
            self.assertFalse(bsn.crate_root(path), path)

    def test_generated_files_carry_a_checksum(self):
        text, _warnings = source(scene(node("rock", BODY, mesh=0)))
        self.assertTrue(text.startswith("// @generated by the Bevy Components BSN export, which replaces this file (checksum "))
        self.assertEqual(bsn.file_state(text), "generated")
        formatted = text.replace("use bevy::{gltf::Gltf, prelude::*, scene::{", "use bevy::{\n    gltf::Gltf,\n    prelude::*,\n    scene::{\n        ").replace("fn resolve(self, _context", "fn resolve(\n        self,\n        _context").replace("Result<(), ResolveSceneError> {", "Result<(), ResolveSceneError>,\n    {").replace("\n", "\r\n")
        self.assertEqual(bsn.file_state(formatted), "generated")
        self.assertEqual(bsn.file_state(text.replace("RigidBody::Dynamic", "RigidBody::Static")), "edited")
        self.assertEqual(bsn.file_state(text + "\n// my notes\n"), "edited")
        self.assertEqual(bsn.file_state(text.partition("\n")[2]), "foreign")
        self.assertEqual(bsn.file_state("mod level;\n"), "foreign")
        self.assertIsNone(bsn.file_state(" \n"))

    def test_stale_files_are_removed(self):
        folder = self.root / "assets" / "level"
        files = {name: self.write(folder / name, name) for name in ("level.glb", "old_lightmap.ktx2", "replaced.ktx2", "kept.ktx2")}
        outside = self.write(self.root / "assets" / "other.glb", "../other.glb")
        previous = {name: bsn.digest(name.encode()) for name in (*files, "missing.ktx2", "../other.glb")}
        files["replaced.ktx2"].write_text("the user's own file")
        removed = bsn.remove_stale(previous, folder, {"level.glb": "", "kept.ktx2": ""})
        self.assertEqual(removed, ["old_lightmap.ktx2"])
        self.assertEqual(sorted(path.name for path in folder.iterdir()), ["kept.ktx2", "level.glb", "replaced.ktx2"])
        self.assertTrue(outside.is_file())

    def test_assets_folders(self):
        project = self.project()
        self.assertEqual(bsn.default_assets_folder(project / "src" / "level.rs"), project / "assets" / "scenes" / "level")
        self.assertEqual(bsn.default_assets_folder(self.root / "loose" / "level.rs"), self.root / "loose" / "assets" / "level")
        folder = project / "assets" / "scenes" / "level"
        self.assertEqual(bsn.asset_root(folder), project / "assets")
        self.assertEqual(bsn.load_path(folder / "level.glb", bsn.asset_root(folder)), "scenes/level/level.glb")
        nested = project / "assets" / "packs" / "assets" / "forest"
        self.assertEqual(bsn.asset_root(nested), project / "assets")
        self.assertEqual(bsn.asset_root(self.root / "elsewhere" / "Assets" / "forest"), self.root / "elsewhere" / "Assets")
        self.assertEqual(bsn.asset_root(self.root / "elsewhere"), self.root / "elsewhere")
        self.assertTrue(bsn.inside(folder / "level.glb", project / "assets"))
        self.assertFalse(bsn.inside(project / "textures" / "wood.ktx2", project / "assets"))

    def test_files_are_written_only_when_they_change(self):
        path = self.root / "assets" / "level.glb"
        self.assertTrue(bsn.write_if_changed(path, b"one"))
        modified = path.stat().st_mtime_ns
        self.assertFalse(bsn.write_if_changed(path, b"one"))
        self.assertEqual(path.stat().st_mtime_ns, modified)
        self.assertTrue(bsn.write_if_changed(path, b"two"))
        self.assertEqual(path.read_bytes(), b"two")
        self.assertEqual(sorted(item.name for item in path.parent.iterdir()), ["level.glb"])


if __name__ == "__main__":
    unittest.main()
