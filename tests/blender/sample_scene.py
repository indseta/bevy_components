import json
import math
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "importer" / "tests" / "assets" / "sample_scene.glb"
SOUNDS = FIXTURE.parent / "sounds"
COMPRESSED_FIXTURES = {mode: FIXTURE.with_name(f"sample_scene_{mode.lower()}.glb") for mode in ("ETC1S", "UASTC", "AUTOMATIC")}
BSN_FIXTURE = ROOT / "importer" / "tests" / "bsn" / "sample_scene.rs"
BSN_ASSETS = FIXTURE.parent / "bsn"
STATIC_FIXTURE = BSN_FIXTURE.with_name("static_scene.rs")
STATIC_ASSETS = FIXTURE.parent / "bsn_static"
STATIC_ROCKS = 260
PROP = Path("props") / "windmill.glb"
REPOSITORY = "bevy_components_test"
RAMP_CENTER = (0, 8, 2)
RAMP_ANGLE = 30
PROBE_ASSETS = ROOT / "tests" / "blender" / "assets"
CUBEMAP = PROBE_ASSETS / "probe_cubemap.ktx2"
CUBEMAP_SIZE = 16
CUBEMAP_FACES = (
    (1.0, 0.55, 0.35),
    (0.35, 0.45, 1.0),
    (0.9, 0.95, 1.0),
    (0.25, 0.2, 0.15),
    (0.6, 0.9, 0.5),
    (0.9, 0.5, 0.8),
)
IRRADIANCE_VOLUME = PROBE_ASSETS / "irradiance_volume.ktx2"
VOXELS = (2, 2, 2)
LIGHTMAP = PROBE_ASSETS / "ground_lightmap.ktx2"
LIGHTMAP_SIZE = 16
LIGHTMAP_WARM = (900.0, 700.0, 450.0)
LIGHTMAP_COOL = (120.0, 140.0, 200.0)
AMBIENT_SIDES = (
    (0.4, 0.3, 0.25),
    (0.5, 0.35, 0.3),
    (0.2, 0.15, 0.1),
    (0.6, 0.7, 0.9),
    (0.3, 0.3, 0.35),
    (0.35, 0.35, 0.4),
)

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
    for collection in (bpy.data.objects, bpy.data.meshes, bpy.data.lights, bpy.data.cameras, bpy.data.materials, bpy.data.images, bpy.data.node_groups, bpy.data.actions):
        for block in list(collection):
            collection.remove(block)
    if hasattr(bpy.context.scene, "bevy_component_definitions"):
        bpy.context.scene.bevy_component_definitions.definitions.clear()
    if bpy.context.scene.world is None:
        bpy.context.scene.world = bpy.data.worlds.new("World")
    if hasattr(bpy.context.scene.world, "bevy_ambient_light"):
        bpy.context.scene.world.property_unset("bevy_ambient_light")


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


def add_light(name, kind, location, rotation=(0, 0, 0), **values):
    bpy.ops.object.light_add(type=kind, location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.data.name = name
    for key, value in values.items():
        setattr(obj.data, key, value)
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


def add_box(name, location, size):
    obj = add_mesh(bpy.ops.mesh.primitive_cube_add, name, size=1, location=location)
    obj.data.transform(Matrix.Diagonal((size[0], size[2], size[1], 1)))
    return obj


def add_box_body(name, location, size, kind="DYNAMIC", **values):
    obj = add_box(name, location, size)
    add_component(obj, "COLLIDER", collider_shape="CUBOID", collider_size=size)
    if kind is not None:
        add_component(obj, "RIGID_BODY", rigid_body_kind=kind, **values)
    return obj


def add_joint(obj, kind, body1=None, body2=None, **values):
    item = add_component(obj, "JOINT", joint_kind=kind, **values)
    item.joint_body1 = body1
    item.joint_body2 = body2
    return item


def _half_floats(colors):
    return b"".join(struct.pack("<4e", *color, 1.0) for color in colors)


def _irradiance_slice(depth):
    width, height, slices = VOXELS
    axis, z = divmod(depth, slices)
    rows = []
    for row in range(height * 2):
        positive, y = divmod(row, height)
        rows.extend(tuple(value * (0.75 + 0.25 * (x + y + z) / (width + height + slices - 3)) for value in AMBIENT_SIDES[axis * 2 + positive]) for x in range(width))
    return rows


def _shared_exponent(color):
    largest = max(color)
    exponent = max(-16, math.floor(math.log2(largest))) + 16 if largest > 0 else 0
    if math.floor(largest / 2 ** (exponent - 24) + 0.5) >= 512:
        exponent += 1
    red, green, blue = (math.floor(value / 2 ** (exponent - 24) + 0.5) for value in color)
    return struct.pack("<I", red | green << 9 | blue << 18 | exponent << 27)


def _lightmap_texel(x, y):
    weight = max(0.0, 1.0 - 2 * math.hypot((x + 0.5) / LIGHTMAP_SIZE - 0.5, (y + 0.5) / LIGHTMAP_SIZE - 0.5))
    return tuple(cool + (warm - cool) * weight for warm, cool in zip(LIGHTMAP_WARM, LIGHTMAP_COOL))


def make_probe_textures(ktx):
    PROBE_ASSETS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bevy_components_") as directory:
        faces = []
        for index, color in enumerate(CUBEMAP_FACES):
            faces.append(Path(directory) / f"face_{index}.raw")
            faces[-1].write_bytes(_half_floats([color] * CUBEMAP_SIZE * CUBEMAP_SIZE))
        slices = []
        for depth in range(VOXELS[2] * 3):
            slices.append(Path(directory) / f"slice_{depth}.raw")
            slices[-1].write_bytes(_half_floats(_irradiance_slice(depth)))
        common = [str(ktx), "create", "--raw", "--format", "R16G16B16A16_SFLOAT", "--assign-tf", "linear"]
        subprocess.run([*common, "--width", str(CUBEMAP_SIZE), "--height", str(CUBEMAP_SIZE), "--cubemap", *map(str, faces), str(CUBEMAP)], check=True)
        subprocess.run([*common, "--width", str(VOXELS[0]), "--height", str(VOXELS[1] * 2), "--depth", str(VOXELS[2] * 3), *map(str, slices), str(IRRADIANCE_VOLUME)], check=True)
        lightmap = Path(directory) / "lightmap.raw"
        lightmap.write_bytes(b"".join(_shared_exponent(_lightmap_texel(x, y)) for y in range(LIGHTMAP_SIZE) for x in range(LIGHTMAP_SIZE)))
        subprocess.run([str(ktx), "create", "--raw", "--format", "E5B9G9R9_UFLOAT_PACK32", "--assign-tf", "linear", "--width", str(LIGHTMAP_SIZE), "--height", str(LIGHTMAP_SIZE), str(lightmap), str(LIGHTMAP)], check=True)


def layers(*numbers):
    return [index in numbers for index in range(32)]


def pick_sound(obj, path):
    select(obj)
    index = next(index for index, item in enumerate(obj.bevy_component_data.components) if item.component_type == "AUDIO_PLAYER")
    return bpy.ops.bevy_components.pick_sound(index=index, filepath=str(path))


def animate(obj, name, path, index, frames):
    for frame, value in frames:
        getattr(obj, path)[index] = value
        obj.keyframe_insert(path, index=index, frame=frame)
    getattr(obj, path)[index] = frames[0][1]
    action = obj.animation_data.action
    action.name = name
    curves = [curve for layer in action.layers for strip in layer.strips for bag in strip.channelbags for curve in bag.fcurves] if hasattr(action, "layers") else action.fcurves
    for curve in curves:
        for point in curve.keyframe_points:
            point.interpolation = "LINEAR"
    return action


def build_windmill():
    clear_scene()
    tower = add_mesh(bpy.ops.mesh.primitive_cylinder_add, "windmill_tower", radius=0.3, depth=3, location=(0, 0, 1.5))
    add_component(tower, "COLLIDER", collider_shape="CAPSULE", collider_radius=0.3, collider_height=2.4)
    blades = add_mesh(bpy.ops.mesh.primitive_cube_add, "windmill_blades", size=1)
    blades.data.transform(Matrix.Diagonal((2.4, 0.1, 0.3, 1)))
    blades.parent = tower
    blades.location = (0, -0.4, 1.2)
    animate(blades, "windmill_spin", "rotation_euler", 1, [(1, 0.0), (49, 2 * math.pi)])
    add_component(blades, "ANIMATION", animation_speed=0.5)
    select()


def apply_lod_preset(obj, preset):
    select(obj)
    index = next(index for index, item in enumerate(obj.bevy_component_data.components) if item.component_type == "VISIBILITY_RANGE")
    bpy.ops.bevy_components.lod_preset(index=index, preset=preset)


def build_sample_scene(directory=FIXTURE.parent):
    clear_scene()
    define_component("my_game::Wave", ("count", "INT", 1), ("delay", "FLOAT", 1.0))
    define_component("my_game::Pickup", ("item", "STRING", "coin"), ("amount", "INT", 1), ("respawn", "BOOL", False), ("weight", "FLOAT", 0.1), ("spin", "VECTOR", (0.0, 1.5, 0.0)), ("glow", "COLOR", (1.0, 0.8, 0.2, 1.0)))
    ground = add_mesh(bpy.ops.mesh.primitive_plane_add, "ground", size=20)
    add_component(ground, "COLLIDER", collider_shape="TRIMESH")
    add_component(ground, "RIGID_BODY", rigid_body_kind="STATIC")
    add_component(ground, "LIGHTMAP", lightmap_resolution="128", lightmap_bicubic=True, probe_file=str(LIGHTMAP))
    add_component(ground, "NAVIGATION")
    select(ground)
    bpy.ops.bevy_components.unwrap_lightmap()

    crate = add_mesh(bpy.ops.mesh.primitive_cube_add, "crate", size=2, location=(3, -2, 1), rotation=(0, 0, math.radians(30)))
    add_component(crate, "COLLIDER", collider_shape="CUBOID", collider_size=(2, 2, 2), collider_friction=0.8, collider_restitution=0.1)
    add_component(crate, "RIGID_BODY", rigid_body_kind="DYNAMIC")
    add_component(crate, "VISIBILITY_RANGE")
    apply_lod_preset(crate, "MID")
    add_component(crate, "CUSTOM", custom_type="my_game::Removed")
    select(crate)
    bpy.ops.bevy_components.remove(index=len(crate.bevy_component_data.components) - 1)
    add_component(crate, "NAVIGATION", navigation_kind="OBSTACLE")

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
    add_component(house, "NAVIGATION", navigation_kind="OBSTACLE")
    chimney = add_mesh(bpy.ops.mesh.primitive_cube_add, "chimney", size=0.5, location=(1, 1, 2.25))
    chimney.parent = house

    tree_lod0 = add_mesh(bpy.ops.mesh.primitive_cone_add, "tree_lod0", radius1=1, depth=3, location=(-8, 8, 1.5))
    add_component(tree_lod0, "VISIBILITY_RANGE")
    apply_lod_preset(tree_lod0, "NEAR")
    tree_lod1 = add_mesh(bpy.ops.mesh.primitive_cone_add, "tree_lod1", radius1=1, depth=3, vertices=8, location=(-8, 8, 1.5))
    add_component(tree_lod1, "VISIBILITY_RANGE", fade_in_start=20, fade_in_end=25, fade_out_start=100, fade_out_end=120)

    cart = add_empty("cart", (-8, -2, 0.5))
    add_component(cart, "RIGID_BODY", rigid_body_kind="DYNAMIC", rigid_body_use_mass=True, rigid_body_mass=12)
    add_component(cart, "NAVIGATION", navigation_kind="OBSTACLE")
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

    water = add_mesh(bpy.ops.mesh.primitive_plane_add, "water", size=3, location=(-8, -8, 0.05))
    add_component(water, "SHADOWS", shadows_receive=False)
    add_component(water, "NAVIGATION", navigation_cost=3)
    bushes = add_empty("bushes", (6, 8, 0))
    add_component(bushes, "SHADOWS")
    add_component(bushes, "NAVIGATION", navigation_kind="OBSTACLE")
    for name, location in (("bush_a", (-0.6, 0, 0.4)), ("bush_b", (0.6, 0.3, 0.6))):
        bush = add_mesh(bpy.ops.mesh.primitive_ico_sphere_add, name, radius=0.5, subdivisions=1, location=location)
        bush.parent = bushes
    add_component(bpy.data.objects["bush_b"], "SHADOWS", shadows_cast=True)
    add_component(bpy.data.objects["bush_b"], "NAVIGATION", navigation_kind="IGNORED")

    campfire = add_empty("campfire", (-2, -4, 0))
    add_component(campfire, "AUDIO_PLAYER", audio_volume=0.8, audio_loop=True, audio_distance=4)
    pick_sound(campfire, SOUNDS / "campfire.ogg")
    jingle = add_empty("jingle", (0, 0, 3))
    add_component(jingle, "AUDIO_PLAYER", audio_path="sounds/chime.ogg", audio_volume=0.5, audio_autoplay=False, audio_spatial=False)

    door_frame = add_box_body("door_frame", (-2.05, -9, 1.1), (0.1, 2.2, 0.2), kind=None)
    door = add_box_body("door", (-1.5, -9, 1.1), (1.0, 2.0, 0.1), rigid_body_angular_velocity=(0, 6, 0))
    add_joint(add_empty("door_hinge", (-2, -9, 1.1)), "REVOLUTE", door_frame, door, joint_use_limits=True, joint_angle_min=0, joint_angle_max=math.radians(90))

    chain_link_1 = add_box_body("chain_link_1", (-6, 2, 3.7), (0.15, 0.6, 0.15))
    chain_link_2 = add_box_body("chain_link_2", (-6, 2, 3.1), (0.15, 0.6, 0.15), rigid_body_linear_velocity=(3, 0, 0))
    add_joint(add_empty("chain_top", (-6, 2, 4)), "SPHERICAL", None, chain_link_1)
    add_joint(add_empty("chain_middle", (-6, 2, 3.4)), "SPHERICAL", chain_link_1, chain_link_2, joint_use_swing=True, joint_swing=math.radians(45))

    drawer_cabinet = add_box_body("drawer_cabinet", (2, -9, 0.5), (1, 1, 1), kind="STATIC")
    drawer = add_box_body("drawer", (2, -9, 0.5), (0.8, 0.3, 0.8), rigid_body_linear_velocity=(2, 0, 0))
    joint = add_component(drawer, "JOINT", joint_kind="PRISMATIC", joint_axis="X", joint_use_limits=True, joint_distance_min=0, joint_distance_max=0.4)
    joint.joint_body1 = drawer_cabinet

    barrel = add_box_body("barrel", (6, 2, 1.5), (0.8, 1.0, 0.8))
    barrel_lid = add_box_body("barrel_lid", (6, 2, 2.1), (0.9, 0.1, 0.9))
    add_component(barrel_lid, "JOINT", joint_kind="FIXED").joint_body1 = barrel

    balloon = add_mesh(bpy.ops.mesh.primitive_uv_sphere_add, "balloon", radius=0.3, segments=16, ring_count=8, location=(-2, 5, 1))
    add_component(balloon, "COLLIDER", collider_shape="SPHERE", collider_radius=0.3)
    add_component(balloon, "RIGID_BODY", rigid_body_kind="DYNAMIC", rigid_body_gravity_scale=-0.5, rigid_body_linear_damping=0.5, rigid_body_angular_damping=0.2)
    add_box_body("spinner", (8, 4, 1), (1.5, 0.2, 0.2), kind="KINEMATIC", rigid_body_angular_velocity=(0, math.radians(90), 0))
    add_box_body("puck", (-8, -5, 0.05), (0.5, 0.1, 0.5), rigid_body_lock_translation=(False, True, False), rigid_body_lock_rotation=(True, True, True), rigid_body_linear_velocity=(2, 0, 0), rigid_body_angular_velocity=(0, 3, 0))
    bullet = add_mesh(bpy.ops.mesh.primitive_uv_sphere_add, "bullet", radius=0.05, segments=8, ring_count=4, location=(-9.5, 9.5, 1))
    add_component(bullet, "COLLIDER", collider_shape="SPHERE", collider_radius=0.05)
    add_component(bullet, "RIGID_BODY", rigid_body_kind="DYNAMIC", rigid_body_gravity_scale=0, rigid_body_ccd="ALL", rigid_body_linear_velocity=(80, 0, 0))
    add_box_body("bullet_target", (-6, 9.5, 1), (0.02, 1, 1), rigid_body_gravity_scale=0)

    gate = add_mesh(bpy.ops.mesh.primitive_cube_add, "gate", size=1, location=(3.5, -9.5, 1))
    gate.data.transform(Matrix.Diagonal((1, 0.1, 2, 1)))
    animate(gate, "gate_open", "rotation_euler", 2, [(1, 0.0), (25, math.pi / 2)])
    add_component(gate, "ANIMATION", animation_loop=False)

    for name, location, angle, scale in (("windmill_a", (-7, -9.5, 0), 0, 1), ("windmill_b", (6, -9.5, 0), 45, 0.75)):
        windmill = add_empty(name, location)
        windmill.rotation_euler = (0, 0, math.radians(angle))
        windmill.scale = (scale, scale, scale)
        add_component(windmill, "SCENE_REFERENCE", scene_file=str(Path(directory) / PROP))

    fog_bank = add_empty("fog_bank", (-6, 6, 1))
    add_component(fog_bank, "FOG_VOLUME", volume_size=(6, 2, 6), fog_color=(0.8, 0.85, 1.0), fog_density=0.2, fog_anisotropy=0.6, fog_light_intensity=1.5)
    room_probe = add_empty("room_probe", (0, 0, 2.5))
    add_component(room_probe, "REFLECTION_PROBE", volume_size=(24, 5, 24), volume_falloff=0.25, probe_intensity=2000, probe_file=str(CUBEMAP))
    gi_volume = add_empty("gi_volume", (0, 0, 3))
    add_component(gi_volume, "IRRADIANCE_VOLUME", volume_size=(24, 6, 24), volume_falloff=0.1, probe_intensity=500, probe_file=str(IRRADIANCE_VOLUME))


    sun = add_light("sun", "SUN", (0, 0, 10))
    add_component(sun, "LIGHT", light_volumetric=True, light_use_cascades=True, light_cascade_count=3, light_cascade_first=8, light_cascade_far=80)
    lamp_light = add_light("lamp_light", "POINT", (4, 4, 1), energy=200, shadow_soft_size=0.1, use_custom_distance=True, cutoff_distance=15)
    add_component(lamp_light, "LIGHT", light_baked=True, light_use_bias=True, light_depth_bias=0.1, light_normal_bias=0.5, light_near_clip=0.05)
    spot_light = add_light("spot_light", "SPOT", (-4, -4, 4), rotation=(math.radians(30), 0, 0), use_shadow=False)
    add_component(spot_light, "LIGHT", light_contact_shadows=True, light_use_intensity=True, light_intensity=2000)
    window_light = add_light("window_light", "AREA", (0, 9, 2), rotation=(math.radians(-90), 0, 0), shape="RECTANGLE", size=2, size_y=1, energy=50)
    add_component(window_light, "LIGHT")
    ambient = bpy.context.scene.world.bevy_ambient_light
    ambient.enabled = True
    ambient.use_world_color = False
    ambient.color = (0.9, 0.95, 1.0)
    ambient.brightness = 120
    add_textured_materials(crate, crate_copy, ground, ball, pillar, rock, lamp)
    select()


def build_static_scene():
    clear_scene()
    material, _shader = add_material("painted")
    material.use_backface_culling = True
    statue = add_mesh(bpy.ops.mesh.primitive_cube_add, "statue", size=1, location=(-2, 0, 0.5))
    statue.data.materials.append(material)
    mirrored = bpy.data.objects.new("statue_mirrored", statue.data)
    mirrored.location = (2, 0, 0.5)
    mirrored.scale = (-1, 1, 1)
    bpy.context.scene.collection.objects.link(mirrored)
    rocks = add_empty("rocks", (0, 4, 0))
    rock = add_mesh(bpy.ops.mesh.primitive_ico_sphere_add, "rock", subdivisions=1, radius=0.2)
    for index in range(STATIC_ROCKS):
        obj = bpy.data.objects.new(f"rock.{index:03d}", rock.data)
        obj.location = (index % 20 - 10, index // 20, 0)
        obj.parent = rocks
        bpy.context.scene.collection.objects.link(obj)
    bpy.data.objects.remove(rock)
    select()


def export_sample_scene(path, **options):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    result = bpy.ops.export_scene.bevy_components_glb(filepath=str(path), **{"include_animations": True, **options})
    if "FINISHED" not in result:
        raise RuntimeError(f"Export failed: {result}")
    return read_gltf(path)


def export_bsn_scene(path, assets_folder="", **options):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    result = bpy.ops.export_scene.bevy_components_bsn(filepath=str(path), assets_folder=str(assets_folder), **{"include_animations": True, **options})
    if "FINISHED" not in result:
        raise RuntimeError(f"Export failed: {result}")
    return Path(path).read_text(encoding="utf-8")


def export_props(directory):
    build_windmill()
    return export_sample_scene(Path(directory) / PROP)


if __name__ == "__main__":
    module = install_addon()
    if sys.argv[-1].endswith(".glb"):
        export_props(Path(sys.argv[-1]).parent)
        build_sample_scene(Path(sys.argv[-1]).parent)
        export_sample_scene(Path(sys.argv[-1]))
    else:
        make_probe_textures(sys.modules[module].encoder.check_encoder()[0])
        export_props(FIXTURE.parent)
        build_sample_scene()
        export_sample_scene(FIXTURE)
        for mode, path in COMPRESSED_FIXTURES.items():
            export_sample_scene(path, texture_compression=mode)
        export_bsn_scene(BSN_FIXTURE, BSN_ASSETS)
        build_static_scene()
        export_bsn_scene(STATIC_FIXTURE, STATIC_ASSETS)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
