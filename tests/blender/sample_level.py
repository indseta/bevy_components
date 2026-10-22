import json
import math
import sys
import tempfile
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "importer" / "tests" / "assets" / "sample_level.glb"
REPOSITORY = "bevy_components_test"

sys.path.insert(0, str(ROOT))

from inspect_glb import read_gltf
from scripts.build_addon import build


def install_addon():
    repositories = bpy.context.preferences.extensions.repos
    if REPOSITORY not in repositories:
        bpy.ops.preferences.extension_repo_add(name=REPOSITORY, type="LOCAL", custom_directory=tempfile.mkdtemp(prefix="bevy_components_"), use_custom_directory=True)
    module = f"bl_ext.{repositories[REPOSITORY].module}.bevy_components"
    if module not in bpy.context.preferences.addons:
        bpy.ops.extensions.package_install_files(filepath=str(build()), repo=repositories[REPOSITORY].module, enable_on_install=True)
    if module not in bpy.context.preferences.addons:
        raise RuntimeError(f"Could not enable {module}")
    return module


def uninstall_addon():
    repositories = bpy.context.preferences.extensions.repos
    if REPOSITORY not in repositories:
        return
    module = f"bl_ext.{repositories[REPOSITORY].module}.bevy_components"
    if module in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_disable(module=module)
    bpy.ops.preferences.extension_repo_remove(index=list(repositories).index(repositories[REPOSITORY]), remove_files=True)


def clear_scene():
    for collection in (bpy.data.objects, bpy.data.meshes, bpy.data.lights, bpy.data.cameras, bpy.data.materials):
        for block in list(collection):
            collection.remove(block)


def select(*objects):
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0] if objects else None


def add_mesh(operator, name, **options):
    operator(**options)
    obj = bpy.context.object
    obj.name = name
    obj.data.name = name
    return obj


def add_empty(name, location):
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=location)
    obj = bpy.context.object
    obj.name = name
    return obj


def add_component(obj, kind, **values):
    select(obj)
    if "FINISHED" not in bpy.ops.bevy_components.add(component_type=kind):
        raise RuntimeError(f"Could not add {kind} to {obj.name}")
    item = obj.bevy_component_data.components[-1]
    for name, value in values.items():
        setattr(item, name, value)
    return item


def apply_lod_preset(obj, preset):
    select(obj)
    index = next(index for index, item in enumerate(obj.bevy_component_data.components) if item.component_type == "VISIBILITY_RANGE")
    bpy.ops.bevy_components.lod_preset(index=index, preset=preset)


def build_sample_level():
    clear_scene()
    ground = add_mesh(bpy.ops.mesh.primitive_plane_add, "ground", size=20)
    add_component(ground, "COLLIDER", collider_shape="TRIMESH")
    add_component(ground, "RIGID_BODY", rigid_body_kind="STATIC")

    crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=2, location=(3, -2, 1), rotation=(0, 0, math.radians(30)))
    for material in ("crate_wood", "crate_metal"):
        crate.data.materials.append(bpy.data.materials.new(material))
    crate.data.polygons[0].material_index = 1
    add_component(crate, "COLLIDER", collider_shape="CUBOID", collider_size=(2, 2, 2))
    add_component(crate, "RIGID_BODY", rigid_body_kind="DYNAMIC")
    add_component(crate, "VISIBILITY_RANGE")
    apply_lod_preset(crate, "MID")
    add_component(crate, "SPAWN_POINT")
    select(crate)
    bpy.ops.bevy_components.remove(index=len(crate.bevy_component_data.components) - 1)

    crate_copy = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate_copy", size=2, location=(6, -2, 1))
    select(crate, crate_copy)
    bpy.ops.bevy_components.copy_to_selected()

    ball = add_mesh(bpy.ops.mesh.primitive_uv_sphere_add, "ball", radius=0.5, segments=16, ring_count=8, location=(-3, 0, 0.5))
    add_component(ball, "COLLIDER", collider_shape="SPHERE", collider_radius=0.5)
    add_component(ball, "RIGID_BODY", rigid_body_kind="KINEMATIC")

    pillar = add_mesh(bpy.ops.mesh.primitive_cylinder_add, "pillar", radius=0.4, depth=2, location=(0, 4, 1))
    add_component(pillar, "COLLIDER", collider_shape="CAPSULE", collider_radius=0.4, collider_height=1.2)

    rock = add_mesh(bpy.ops.mesh.primitive_ico_sphere_add, "rock", radius=0.8, subdivisions=1, location=(-4, 4, 0.8))
    add_component(rock, "COLLIDER", collider_shape="CONVEX")
    add_component(rock, "RIGID_BODY", rigid_body_kind="DYNAMIC")

    trigger_zone = add_mesh(bpy.ops.mesh.primitive_cube_add, "trigger_zone", size=1, location=(0, -6, 1))
    trigger_zone.scale = (2, 1, 1)
    add_component(trigger_zone, "COLLIDER", collider_shape="CUBOID", collider_size=(1, 2, 3), collider_sensor=True)

    pickup_zone = add_empty("pickup_zone", (4, -4, 1))
    add_component(pickup_zone, "COLLIDER", collider_shape="SPHERE", collider_radius=1.5, collider_sensor=True)

    add_component(add_empty("player_spawn", (2, 3, 0)), "SPAWN_POINT", spawn_tag="player")
    enemy_spawn = add_empty("enemy_spawn", (-6, -6, 0))
    add_component(enemy_spawn, "SPAWN_POINT", spawn_tag="enemy")
    add_component(enemy_spawn, "CUSTOM", custom_type="my_game::Wave", custom_json=json.dumps({"count": 3, "delay": 1.5}))

    lamp = add_mesh(bpy.ops.mesh.primitive_cube_add, "lamp", size=0.5, location=(4, 4, 0.25))
    add_component(lamp, "CUSTOM", custom_type="my_game::Glow", custom_json=json.dumps({"color": [1.0, 0.8, 0.6], "label": "Lamp ✦"}))
    add_component(lamp, "CUSTOM", custom_type="my_game::Flicker", custom_json="0.25")

    house = add_mesh(bpy.ops.mesh.primitive_cube_add, "house", size=4, location=(10, 10, 2))
    add_component(house, "VISIBILITY_RANGE", use_aabb=True)
    apply_lod_preset(house, "FAR")
    add_component(house, "COLLIDER", collider_shape="TRIMESH")
    chimney = add_mesh(bpy.ops.mesh.primitive_cube_add, "chimney", size=0.5, location=(1, 1, 2.25))
    chimney.parent = house

    tree_lod0 = add_mesh(bpy.ops.mesh.primitive_cone_add, "tree_lod0", radius1=1, depth=3, location=(-8, 8, 1.5))
    add_component(tree_lod0, "VISIBILITY_RANGE")
    apply_lod_preset(tree_lod0, "NEAR")
    tree_lod1 = add_mesh(bpy.ops.mesh.primitive_cone_add, "tree_lod1", radius1=1, depth=3, vertices=8, location=(-8, 8, 1.5))
    add_component(tree_lod1, "VISIBILITY_RANGE", fade_in_start=20, fade_in_end=25, fade_out_start=100, fade_out_end=120)

    bpy.ops.object.light_add(type="SUN", location=(0, 0, 10))
    bpy.context.object.name = "sun"
    select()


def export_sample_level(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    result = bpy.ops.export_scene.bevy_components_glb(filepath=str(path))
    if "FINISHED" not in result:
        raise RuntimeError(f"Export failed: {result}")
    return read_gltf(path)


if __name__ == "__main__":
    install_addon()
    build_sample_level()
    export_sample_level(Path(sys.argv[-1]) if sys.argv[-1].endswith(".glb") else FIXTURE)
