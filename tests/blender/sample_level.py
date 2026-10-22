import json
import math
import os
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "importer" / "tests" / "assets" / "sample_level.glb"
COMPRESSED_FIXTURES = {mode: FIXTURE.with_name(f"sample_level_{mode.lower()}.glb") for mode in ("ETC1S", "UASTC", "AUTOMATIC")}
REPOSITORY = "bevy_components_test"
RAMP_CENTER = (0, 8, 2)
RAMP_ANGLE = 30

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
    for collection in (bpy.data.objects, bpy.data.meshes, bpy.data.lights, bpy.data.cameras, bpy.data.materials, bpy.data.images, bpy.data.node_groups):
        for block in list(collection):
            collection.remove(block)
    if hasattr(bpy.context.scene, "bevy_component_definitions"):
        bpy.context.scene.bevy_component_definitions.definitions.clear()


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


def add_component(obj, kind, type_path="", **values):
    select(obj)
    if "FINISHED" not in bpy.ops.bevy_components.add(component_type=kind, type_path=type_path):
        raise RuntimeError(f"Could not add {kind} to {obj.name}")
    item = obj.bevy_component_data.components[-1]
    for name, value in values.items():
        setattr(item, name, value)
    return item


def define_component(type_path, *fields):
    bpy.ops.bevy_components.definition_add()
    library = bpy.context.scene.bevy_component_definitions
    definition = library.definitions[library.active_index]
    definition.name = type_path
    for name, kind, default in fields:
        bpy.ops.bevy_components.field_add()
        field = definition.fields[definition.active_field]
        field.name = name
        field.field_type = kind
        setattr(field, f"{kind.lower()}_value", default)
    return definition


def set_fields(item, **values):
    for field in item.fields:
        if field.name in values:
            setattr(field, f"{field.field_type.lower()}_value", values[field.name])
    return item


def add_image(name, width, height, pixel, alpha=False, color=True):
    image = bpy.data.images.new(name, width, height, alpha=alpha)
    image.colorspace_settings.name = "sRGB" if color else "Non-Color"
    image.pixels = [value for y in range(height) for x in range(width) for value in pixel(x, y)]
    image.pack()
    return image


def add_material(name):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    return material, material.node_tree.nodes["Principled BSDF"]


def add_texture(material, image, interpolation="Linear", uv_map=None, scale=None):
    nodes = material.node_tree.nodes
    node = nodes.new("ShaderNodeTexImage")
    node.image = image
    node.interpolation = interpolation
    if uv_map or scale:
        coordinates = nodes.new("ShaderNodeUVMap")
        coordinates.uv_map = uv_map or ""
        vector = coordinates.outputs["UV"]
        if scale:
            mapping = nodes.new("ShaderNodeMapping")
            mapping.inputs["Scale"].default_value = scale
            _link(material, vector, mapping.inputs["Vector"])
            vector = mapping.outputs["Vector"]
        _link(material, vector, node.inputs["Vector"])
    return node


def _link(material, source, target):
    material.node_tree.links.new(source, target)


def _separate(material, node):
    separate = material.node_tree.nodes.new("ShaderNodeSeparateColor")
    _link(material, node.outputs["Color"], separate.inputs["Color"])
    return separate


def _gltf_output_group():
    group = bpy.data.node_groups.get("glTF Material Output")
    if group is None:
        group = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
        group.interface.new_socket(name="Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
    return group


def wood_color(x, y):
    return (0.55 + 0.3 * ((x // 8) % 2), 0.3 + 0.15 * ((y // 4) % 2), 0.12, 1.0)


def wood_normal(x, y):
    normal_x = 0.35 * math.sin(2 * math.pi * x / 16)
    normal_y = 0.35 * math.cos(2 * math.pi * y / 16)
    normal_z = math.sqrt(1 - normal_x * normal_x - normal_y * normal_y)
    return (normal_x * 0.5 + 0.5, normal_y * 0.5 + 0.5, normal_z * 0.5 + 0.5, 1.0)


def wood_orm(x, y):
    return (0.6 + 0.4 * x / 63, 0.3 + 0.6 * ((x + y) % 16) / 15, float((x // 16 + y // 16) % 2), 1.0)


def metal_color(x, y):
    return (0.7, 0.72, 0.78, 0.4 + 0.6 * y / 63)


def lamp_emissive(x, y):
    return (1.0, 0.6 + 0.4 * x / 31, 0.2, 1.0)


def ball_pixels(x, y):
    return (0.9, 0.1, 0.1, 1.0) if (x + y) % 2 else (0.1, 0.2, 0.9, 1.0)


def pillar_gradient(x, y):
    return (0.1, 0.4 + 0.5 * x / 29, 0.2 + 0.6 * y / 17, 1.0)


def add_textured_materials(crate, crate_copy, ground, ball, pillar, rock, lamp):
    color = add_image("wood_color", 64, 64, wood_color)
    normal = add_image("wood_normal", 64, 64, wood_normal, color=False)
    orm = add_image("wood_orm", 64, 64, wood_orm, color=False)

    wood, shader = add_material("crate_wood")
    _link(wood, add_texture(wood, color).outputs["Color"], shader.inputs["Base Color"])
    normal_map = wood.node_tree.nodes.new("ShaderNodeNormalMap")
    _link(wood, add_texture(wood, normal).outputs["Color"], normal_map.inputs["Color"])
    _link(wood, normal_map.outputs["Normal"], shader.inputs["Normal"])
    channels = _separate(wood, add_texture(wood, orm))
    _link(wood, channels.outputs["Green"], shader.inputs["Roughness"])
    _link(wood, channels.outputs["Blue"], shader.inputs["Metallic"])
    output = wood.node_tree.nodes.new("ShaderNodeGroup")
    output.node_tree = _gltf_output_group()
    _link(wood, _separate(wood, add_texture(wood, orm, uv_map="uv_ao")).outputs["Red"], output.inputs["Occlusion"])
    crate.data.uv_layers.new(name="uv_ao")
    crate.data.materials.append(wood)
    crate_copy.data.uv_layers.new(name="uv_ao")
    crate_copy.data.materials.append(wood)

    metal, shader = add_material("crate_metal")
    texture = add_texture(metal, add_image("metal_color", 64, 64, metal_color, alpha=True))
    _link(metal, texture.outputs["Color"], shader.inputs["Base Color"])
    _link(metal, texture.outputs["Alpha"], shader.inputs["Alpha"])
    shader.inputs["Metallic"].default_value = 1.0
    metal.surface_render_method = "BLENDED"
    crate.data.materials.append(metal)
    crate.data.polygons[0].material_index = 1

    floor, shader = add_material("ground_wood")
    _link(floor, add_texture(floor, color, uv_map="UVMap", scale=(4.0, 4.0, 1.0)).outputs["Color"], shader.inputs["Base Color"])
    ground.data.materials.append(floor)

    pixels, shader = add_material("ball_pixels")
    _link(pixels, add_texture(pixels, add_image("ball_pixels", 8, 8, ball_pixels), interpolation="Closest").outputs["Color"], shader.inputs["Base Color"])
    ball.data.materials.append(pixels)

    gradient, shader = add_material("pillar_gradient")
    _link(gradient, add_texture(gradient, add_image("pillar_gradient", 30, 18, pillar_gradient)).outputs["Color"], shader.inputs["Base Color"])
    pillar.data.materials.append(gradient)

    stone, shader = add_material("rock_orm")
    _link(stone, add_texture(stone, orm).outputs["Color"], shader.inputs["Base Color"])
    rock.data.materials.append(stone)

    glow, shader = add_material("lamp_glow")
    shader.inputs["Base Color"].default_value = (0.1, 0.1, 0.1, 1.0)
    _link(glow, add_texture(glow, add_image("lamp_emissive", 32, 32, lamp_emissive)).outputs["Color"], shader.inputs["Emission Color"])
    shader.inputs["Emission Strength"].default_value = 1.0
    lamp.data.materials.append(glow)


def layers(*numbers):
    return [index in numbers for index in range(32)]


def apply_lod_preset(obj, preset):
    select(obj)
    index = next(index for index, item in enumerate(obj.bevy_component_data.components) if item.component_type == "VISIBILITY_RANGE")
    bpy.ops.bevy_components.lod_preset(index=index, preset=preset)


def build_sample_level():
    clear_scene()
    define_component("my_game::Wave", ("count", "INT", 1), ("delay", "FLOAT", 1.0))
    define_component("my_game::Pickup", ("item", "STRING", "coin"), ("amount", "INT", 1), ("respawn", "BOOL", False), ("weight", "FLOAT", 0.1), ("spin", "VECTOR", (0.0, 1.5, 0.0)), ("glow", "COLOR", (1.0, 0.8, 0.2, 1.0)))
    ground = add_mesh(bpy.ops.mesh.primitive_plane_add, "ground", size=20)
    add_component(ground, "COLLIDER", collider_shape="TRIMESH")
    add_component(ground, "RIGID_BODY", rigid_body_kind="STATIC")

    crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=2, location=(3, -2, 1), rotation=(0, 0, math.radians(30)))
    add_component(crate, "COLLIDER", collider_shape="CUBOID", collider_size=(2, 2, 2), collider_friction=0.8, collider_restitution=0.1)
    add_component(crate, "RIGID_BODY", rigid_body_kind="DYNAMIC")
    add_component(crate, "VISIBILITY_RANGE")
    apply_lod_preset(crate, "MID")
    add_component(crate, "CUSTOM", custom_type="my_game::Removed")
    select(crate)
    bpy.ops.bevy_components.remove(index=len(crate.bevy_component_data.components) - 1)

    crate_copy = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate_copy", size=2, location=(6, -2, 1))
    select(crate, crate_copy)
    bpy.ops.bevy_components.copy_to_selected()

    ball = add_mesh(bpy.ops.mesh.primitive_uv_sphere_add, "ball", radius=0.5, segments=16, ring_count=8, location=(-3, 0, 0.5))
    add_component(ball, "COLLIDER", collider_shape="SPHERE", collider_radius=0.5)
    add_component(ball, "RIGID_BODY", rigid_body_kind="KINEMATIC")
    add_component(ball, "CUSTOM", custom_type="my_game::Disabled", enabled=False)

    pillar = add_mesh(bpy.ops.mesh.primitive_cylinder_add, "pillar", radius=0.4, depth=2, location=(0, 4, 1))
    add_component(pillar, "COLLIDER", collider_shape="CAPSULE", collider_radius=0.4, collider_height=1.2)

    rock = add_mesh(bpy.ops.mesh.primitive_ico_sphere_add, "rock", radius=0.8, subdivisions=1, location=(-4, 4, 0.8))
    add_component(rock, "COLLIDER", collider_shape="CONVEX")
    add_component(rock, "RIGID_BODY", rigid_body_kind="DYNAMIC", rigid_body_use_mass=True, rigid_body_mass=25)

    trigger_zone = add_mesh(bpy.ops.mesh.primitive_cube_add, "trigger_zone", size=1, location=(0, -6, 1))
    trigger_zone.scale = (2, 1, 1)
    add_component(trigger_zone, "COLLIDER", collider_shape="CUBOID", collider_size=(1, 2, 3), collider_sensor=True, collider_memberships=layers(2), collider_filters=layers(1))

    pickup_zone = add_empty("pickup_zone", (4, -4, 1))
    add_component(pickup_zone, "COLLIDER", collider_shape="SPHERE", collider_radius=1.5, collider_sensor=True)
    set_fields(add_component(pickup_zone, "CUSTOM", type_path="my_game::Pickup"), amount=5, respawn=True)

    add_component(add_empty("player_spawn", (2, 3, 0)), "CUSTOM", custom_type="my_game::PlayerSpawn")
    enemy_spawn = add_empty("enemy_spawn", (-6, -6, 0))
    add_component(enemy_spawn, "CUSTOM", custom_type="my_game::EnemySpawn")
    set_fields(add_component(enemy_spawn, "CUSTOM", type_path="my_game::Wave"), count=3, delay=1.5)

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

    cart = add_empty("cart", (-8, -2, 0.5))
    add_component(cart, "RIGID_BODY", rigid_body_kind="DYNAMIC", rigid_body_use_mass=True, rigid_body_mass=12)
    cart_shape = add_empty("cart_shape", (0, 0, 0))
    add_component(cart_shape, "COLLIDER", collider_shape="CUBOID")
    cart_handle = add_empty("cart_handle", (-0.75, 0, 0.25))
    add_component(cart_handle, "COLLIDER", collider_shape="SPHERE", collider_radius=0.25)
    cart_body = add_mesh(bpy.ops.mesh.primitive_cube_add, "cart_body", size=1)
    for child in (cart_shape, cart_handle, cart_body):
        child.parent = cart

    bouncy_ball = add_mesh(bpy.ops.mesh.primitive_uv_sphere_add, "bouncy_ball", radius=0.3, segments=16, ring_count=8, location=(8, -8, 4))
    add_component(bouncy_ball, "COLLIDER", collider_shape="SPHERE", collider_radius=0.3, collider_restitution=1)
    add_component(bouncy_ball, "RIGID_BODY", rigid_body_kind="DYNAMIC")

    ghost = add_mesh(bpy.ops.mesh.primitive_cube_add, "ghost", size=1, location=(8, 0, 0.5))
    add_component(ghost, "COLLIDER", collider_shape="CUBOID", collider_memberships=layers(1), collider_filters=layers(1))
    add_component(ghost, "RIGID_BODY", rigid_body_kind="DYNAMIC")

    slope = math.radians(RAMP_ANGLE)
    ramp = add_mesh(bpy.ops.mesh.primitive_cube_add, "ramp", size=1, location=RAMP_CENTER, rotation=(0, slope, 0))
    ramp.data.transform(Matrix.Diagonal((6, 2, 0.2, 1)))
    add_component(ramp, "COLLIDER", collider_shape="CUBOID", collider_size=(6, 0.2, 2))
    add_component(ramp, "RIGID_BODY", rigid_body_kind="STATIC")
    for name, friction, side in (("ice_block", 0, -0.6), ("rubber_block", 1, 0.6)):
        location = Vector(RAMP_CENTER) + Vector((math.sin(slope), 0, math.cos(slope))) * 0.35 + Vector((math.cos(slope), 0, -math.sin(slope))) * -1.5 + Vector((0, side, 0))
        block = add_mesh(bpy.ops.mesh.primitive_cube_add, name, size=0.5, location=location, rotation=(0, slope, 0))
        add_component(block, "COLLIDER", collider_shape="CUBOID", collider_size=(0.5, 0.5, 0.5), collider_friction=friction)
        add_component(block, "RIGID_BODY", rigid_body_kind="DYNAMIC")

    bpy.ops.object.light_add(type="SUN", location=(0, 0, 10))
    bpy.context.object.name = "sun"
    add_textured_materials(crate, crate_copy, ground, ball, pillar, rock, lamp)
    select()


def export_sample_level(path, **options):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    result = bpy.ops.export_scene.bevy_components_glb(filepath=str(path), **options)
    if "FINISHED" not in result:
        raise RuntimeError(f"Export failed: {result}")
    return read_gltf(path)


if __name__ == "__main__":
    install_addon()
    build_sample_level()
    if sys.argv[-1].endswith(".glb"):
        export_sample_level(Path(sys.argv[-1]))
    else:
        export_sample_level(FIXTURE)
        for mode, path in COMPRESSED_FIXTURES.items():
            export_sample_level(path, texture_compression=mode)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
