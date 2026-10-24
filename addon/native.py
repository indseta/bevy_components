import os
from contextlib import contextmanager
from math import sqrt
from pathlib import Path

import bpy

from .metadata import WATTS_TO_LUMENS, gravity_component, light_of

SHAPES = {
    "BOX": "CUBOID",
    "SPHERE": "SPHERE",
    "CAPSULE": "CAPSULE",
    "CYLINDER": "CYLINDER",
    "CONE": "CONE",
    "CONVEX_HULL": "CONVEX",
    "MESH": "TRIMESH",
}
BLENDER_SHAPES = {shape: blender for blender, shape in SHAPES.items()}
JOINTS = {
    "FIXED": "FIXED",
    "POINT": "SPHERICAL",
    "HINGE": "REVOLUTE",
    "SLIDER": "PRISMATIC",
}
BLENDER_JOINTS = {joint: blender for blender, joint in JOINTS.items()}
JOINT_AXES = {
    "FIXED": "Y",
    "SPHERICAL": "Y",
    "REVOLUTE": "Y",
    "PRISMATIC": "X",
}
UNSUPPORTED_JOINTS = {
    "PISTON": "Piston",
    "GENERIC": "Generic",
    "GENERIC_SPRING": "Generic Spring",
    "MOTOR": "Motor",
}
NATIVE_KINDS = ("COLLIDER", "RIGID_BODY", "JOINT", "LIGHT", "SHADOWS", "ANIMATION", "AUDIO_PLAYER", "FOG_VOLUME", "REFLECTION_PROBE", "IRRADIANCE_VOLUME")
NATIVE_SOURCES = {
    "COLLIDER": ("Physics", "PHYSICS", "PHYSICS"),
    "RIGID_BODY": ("Physics", "PHYSICS", "PHYSICS"),
    "JOINT": ("Physics", "PHYSICS", "PHYSICS"),
    "LIGHT": ("Light Properties", "DATA", "LIGHT_DATA"),
    "SHADOWS": ("Visibility", None, None),
    "ANIMATION": ("Action", None, None),
    "AUDIO_PLAYER": ("Speaker", "DATA", "OUTLINER_DATA_SPEAKER"),
    "FOG_VOLUME": ("Material", "MATERIAL", "MATERIAL"),
    "REFLECTION_PROBE": ("Light Probe", "DATA", "OUTLINER_DATA_LIGHTPROBE"),
    "IRRADIANCE_VOLUME": ("Light Probe", "DATA", "OUTLINER_DATA_LIGHTPROBE"),
}
LIGHT_SETTINGS = ("light_intensity", "light_use_intensity", "light_baked", "light_volumetric", "light_contact_shadows", "light_depth_bias", "light_normal_bias", "light_near_clip", "light_use_bias", "light_cascade_count", "light_cascade_near", "light_cascade_first", "light_cascade_far", "light_cascade_overlap", "light_use_cascades")
SPEAKER_SETTINGS = ("audio_loop", "audio_autoplay", "audio_spatial")
FOG_SETTINGS = ("fog_light_tint", "fog_light_intensity")
PROBE_KINDS = {"SPHERE": "REFLECTION_PROBE", "VOLUME": "IRRADIANCE_VOLUME"}
MESH_TYPES = {"MESH", "CURVE", "SURFACE", "FONT"}
PRINCIPLED_VOLUME = "ShaderNodeVolumePrincipled"
BLENDER_LAYERS = 20
MINIMUM_SIZE = 0.001


class NativeComponent:
    native = True
    enabled = True

    def __init__(self, obj, kind, values):
        self.id_data = obj
        self.component_type = kind
        self.values = values

    def __getattr__(self, name):
        values = self.__dict__.get("values")
        if values is not None and name in values:
            return values[name]
        return _default(name)


def _default(name):
    from .property import BEVY_PG_component
    prop = BEVY_PG_component.bl_rna.properties.get(name)
    if prop is None:
        raise AttributeError(name)
    if prop.type == "POINTER":
        return None
    if prop.type == "COLLECTION":
        return ()
    if getattr(prop, "is_array", False):
        return tuple(prop.default_array)
    return prop.default


def is_native(item):
    return getattr(item, "native", False)


def bevy_axes(values):
    return (values[0], values[2], values[1])


def bevy_vector(values):
    return (values[0] + 0.0, values[2] + 0.0, -values[1] + 0.0)


def blender_axes(values):
    return (values[0], values[2], values[1])


def blender_vector(values):
    return (values[0] + 0.0, -values[2] + 0.0, values[1] + 0.0)


def bounds(obj):
    corners = [tuple(corner) for corner in obj.bound_box]
    minimum = [min(corner[axis] for corner in corners) for axis in range(3)]
    maximum = [max(corner[axis] for corner in corners) for axis in range(3)]
    return [high - low for low, high in zip(minimum, maximum)], [(low + high) / 2 for low, high in zip(minimum, maximum)]


def shape_values(shape, size):
    width, depth, height = size
    if shape == "CUBOID":
        return {"collider_size": tuple(max(value, MINIMUM_SIZE) for value in (width, height, depth))}
    if shape == "SPHERE":
        return {"collider_radius": max(max(size) / 2, MINIMUM_SIZE)}
    radius = max(max(width, depth) / 2, MINIMUM_SIZE)
    if shape == "CAPSULE":
        return {"collider_radius": radius, "collider_height": max(height - 2 * radius, 0.0)}
    if shape in {"CYLINDER", "CONE"}:
        return {"collider_radius": radius, "collider_height": max(height, MINIMUM_SIZE)}
    return {}


def compound_parent(obj):
    parent = obj.parent
    body = getattr(parent, "rigid_body", None)
    return parent if body is not None and body.collision_shape == "COMPOUND" and not _left_out(parent) else None


def rigid_body_kind(body):
    if body.kinematic:
        return "KINEMATIC"
    if body.type == "PASSIVE" or not body.enabled:
        return "STATIC"
    return "DYNAMIC"


def collision_layers(body, physics):
    if physics.use_layers:
        return tuple(physics.memberships), tuple(physics.filters)
    layers = tuple(body.collision_collections) + (False,) * (len(physics.memberships) - BLENDER_LAYERS)
    return layers, layers


def _body_values(obj, body, physics):
    return {
        "rigid_body_kind": rigid_body_kind(body),
        "rigid_body_use_mass": not physics.auto_mass,
        "rigid_body_mass": body.mass,
        "rigid_body_linear_damping": body.linear_damping,
        "rigid_body_angular_damping": body.angular_damping,
        "rigid_body_gravity_scale": physics.gravity_scale,
        "rigid_body_ccd": physics.ccd,
        "rigid_body_lock_translation": bevy_axes(physics.lock_translation),
        "rigid_body_lock_rotation": bevy_axes(physics.lock_rotation),
        "rigid_body_linear_velocity": bevy_vector(physics.linear_velocity),
        "rigid_body_angular_velocity": bevy_vector(physics.angular_velocity),
    }


def _collider_values(obj, body, physics):
    shape = SHAPES[body.collision_shape]
    memberships, filters = collision_layers(body, physics)
    values = {
        "collider_shape": shape,
        "collider_offset": (0.0, 0.0, 0.0),
        "collider_sensor": physics.sensor,
        "collider_events": physics.events,
        "collider_collision_only": physics.collision_only,
        "collider_friction": body.friction,
        "collider_restitution": body.restitution,
        "collider_memberships": memberships,
        "collider_filters": filters,
        "collider_own_mesh": True,
    }
    if shape not in {"CONVEX", "TRIMESH"}:
        values.update(shape_values(shape, bounds(obj)[0]))
    return values


def _joint_values(obj, constraint, physics):
    kind = JOINTS[constraint.type]
    limits = constraint.use_limit_ang_z if kind == "REVOLUTE" else constraint.use_limit_lin_x if kind == "PRISMATIC" else False
    return {
        "joint_kind": kind,
        "joint_body1": constraint.object1,
        "joint_body2": constraint.object2,
        "joint_axis": JOINT_AXES[kind],
        "joint_use_limits": limits,
        "joint_angle_min": constraint.limit_ang_z_lower,
        "joint_angle_max": constraint.limit_ang_z_upper,
        "joint_distance_min": constraint.limit_lin_x_lower,
        "joint_distance_max": constraint.limit_lin_x_upper,
        "joint_use_swing": physics.joint_use_swing and kind == "SPHERICAL",
        "joint_swing": physics.joint_swing,
        "joint_linear_damping": physics.joint_linear_damping,
        "joint_angular_damping": physics.joint_angular_damping,
        "joint_collide": not constraint.disable_collisions,
    }


def srgb(value):
    return value * 12.92 if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055


def linear(value):
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def asset_path(path):
    path = Path(path)
    folders = [parent for parent in path.parents if parent.name.lower() == "assets"]
    if not folders:
        return path.name, None
    root = folders[0] if len(folders) == 1 else next((folder for folder in folders if (folder.parent / "Cargo.toml").is_file()), folders[0])
    return path.relative_to(root).as_posix(), root


def sound_file(sound):
    return os.path.abspath(bpy.path.abspath(sound.filepath, library=sound.library)) if sound is not None and sound.filepath.strip() else None


def _light_values(obj, light):
    settings = light.bevy_light
    return {name: getattr(settings, name) for name in LIGHT_SETTINGS}


def _shadow_values(obj):
    receive = obj.bevy_object.receive_shadows
    if obj.visible_shadow and receive:
        return None
    return {"shadows_cast": obj.visible_shadow, "shadows_receive": receive, "shadows_own_mesh": True}


def active_action(obj):
    animation = getattr(obj, "animation_data", None)
    return animation.action if animation is not None else None


def _animation_values(obj):
    action = active_action(obj)
    settings = obj.bevy_object
    if action is None or not settings.autoplay:
        return None
    return {"animation_clip": action.name, "animation_loop": action.use_cyclic, "animation_speed": settings.speed}


def _speaker_values(obj, speaker):
    path = sound_file(speaker.sound)
    if path is None or speaker.muted:
        return None
    values = {name: getattr(speaker.bevy_speaker, name) for name in SPEAKER_SETTINGS}
    values.update(audio_path=asset_path(path)[0], audio_volume=speaker.volume, audio_distance=max(speaker.distance_reference, 0.01), audio_speed=speaker.pitch)
    return values


def volume_shader(material):
    tree = material.node_tree if material is not None and (bpy.app.version >= (5, 0, 0) or material.use_nodes) else None
    if tree is None:
        return None
    output = next((node for node in tree.nodes if node.bl_idname == "ShaderNodeOutputMaterial" and node.is_active_output), None)
    if output is None or output.inputs["Surface"].is_linked or not output.inputs["Volume"].is_linked:
        return None
    node = output.inputs["Volume"].links[0].from_node
    while node.bl_idname == "NodeReroute" and node.inputs[0].is_linked:
        node = node.inputs[0].links[0].from_node
    return node


def fog_source(obj):
    if getattr(obj, "type", None) != "MESH" or _left_out(obj):
        return None
    materials = [slot.material for slot in obj.material_slots if slot.material is not None]
    shaders = [volume_shader(material) for material in materials]
    if not materials or any(shader is None for shader in shaders):
        return None
    return materials[0], shaders[0]


def _input(node, name):
    value = node.inputs[name].default_value
    return [float(channel) for channel in value[:3]] if hasattr(value, "__len__") else float(value)


def fog_coefficients(color, absorption_color):
    scattering = max(max(color), 0.0)
    absorption = sum(max(1.0 - channel, 0.0) * max(1.0 - sqrt(max(tint, 0.0)), 0.0) for channel, tint in zip(color, absorption_color)) / 3
    fog_color = tuple(srgb(channel / scattering) for channel in color) if scattering > 0 else (1.0, 1.0, 1.0)
    return fog_color, scattering, absorption


def _fog_values(obj, material, node):
    if node.bl_idname != PRINCIPLED_VOLUME:
        return None
    width, depth, height = bounds(obj)[0]
    fog_color, scattering, absorption = fog_coefficients(_input(node, "Color"), _input(node, "Absorption Color"))
    values = {name: getattr(material.bevy_fog, name) for name in FOG_SETTINGS}
    values.update(volume_size=tuple(max(value, MINIMUM_SIZE) for value in (width, height, depth)), fog_color=fog_color, fog_density=_input(node, "Density"), fog_absorption=absorption, fog_scattering=scattering, fog_anisotropy=_input(node, "Anisotropy"))
    return values


def _probe_values(obj, probe):
    settings = probe.bevy_probe
    values = {"probe_file": obj.bevy_object.probe_file, "bake_fingerprint": obj.bevy_object.bake_fingerprint}
    if probe.type == "SPHERE":
        size = 2 * max(probe.influence_distance, MINIMUM_SIZE / 2)
        values.update(volume_size=(size, size, size), volume_falloff=probe.falloff, probe_intensity=WATTS_TO_LUMENS * settings.intensity, probe_parallax=settings.parallax, bake_resolution=settings.bake_resolution)
    else:
        values.update(volume_size=(2.0, 2.0, 2.0), volume_falloff=settings.falloff, probe_intensity=WATTS_TO_LUMENS * probe.intensity, bake_voxels=(probe.resolution_x, probe.resolution_z, probe.resolution_y))
    return values


def _data_components(obj):
    found = []
    light = light_of(obj)
    if light is not None and hasattr(light, "bevy_light"):
        found.append(NativeComponent(obj, "LIGHT", _light_values(obj, light)))
    if obj.type in MESH_TYPES and (values := _shadow_values(obj)) is not None:
        found.append(NativeComponent(obj, "SHADOWS", values))
    if (values := _animation_values(obj)) is not None:
        found.append(NativeComponent(obj, "ANIMATION", values))
    if obj.type == "SPEAKER" and hasattr(obj.data, "bevy_speaker") and (values := _speaker_values(obj, obj.data)) is not None:
        found.append(NativeComponent(obj, "AUDIO_PLAYER", values))
    if obj.type == "LIGHT_PROBE" and obj.data.type in PROBE_KINDS and hasattr(obj.data, "bevy_probe"):
        found.append(NativeComponent(obj, PROBE_KINDS[obj.data.type], _probe_values(obj, obj.data)))
    source = fog_source(obj)
    if source is not None and hasattr(source[0], "bevy_fog") and (values := _fog_values(obj, *source)) is not None:
        found.append(NativeComponent(obj, "FOG_VOLUME", values))
    return found


def _left_out(obj):
    from .collection import left_out
    return left_out(obj)


def native_components(obj):
    physics = getattr(obj, "bevy_physics", None)
    if physics is None or getattr(obj, "bevy_object", None) is None or _left_out(obj):
        return []
    found = []
    body = getattr(obj, "rigid_body", None)
    if body is not None:
        if compound_parent(obj) is None:
            found.append(NativeComponent(obj, "RIGID_BODY", _body_values(obj, body, physics)))
        if body.collision_shape in SHAPES:
            found.append(NativeComponent(obj, "COLLIDER", _collider_values(obj, body, physics)))
    constraint = getattr(obj, "rigid_body_constraint", None)
    if constraint is not None and constraint.enabled and constraint.type in JOINTS:
        found.append(NativeComponent(obj, "JOINT", _joint_values(obj, constraint, physics)))
    return found + _data_components(obj)


def with_native(obj, cards):
    kinds = {item.component_type for item in cards}
    return cards + [item for item in native_components(obj) if item.component_type not in kinds]


def scene_gravity(scene):
    world = getattr(scene, "rigidbody_world", None)
    if world is None:
        return None
    if not scene.use_gravity:
        return (0.0, 0.0, 0.0)
    weight = world.effector_weights.gravity * world.effector_weights.all
    return bevy_vector([value * weight for value in scene.gravity])


def physics_components(scene):
    gravity = scene_gravity(scene)
    component = gravity_component(gravity) if gravity is not None else None
    return [component] if component is not None else []


def simulated(scene):
    world = getattr(scene, "rigidbody_world", None)
    if world is None or not world.enabled or world.collection is None:
        return False
    return any(obj.rigid_body is not None and obj.rigid_body.type == "ACTIVE" and obj.rigid_body.enabled and not obj.rigid_body.kinematic for obj in world.collection.all_objects)


@contextmanager
def rest_frame(scene):
    start = scene.rigidbody_world.point_cache.frame_start if simulated(scene) else None
    current, subframe = scene.frame_current, scene.frame_subframe
    if start is None or (start == current and subframe == 0.0):
        yield
        return
    scene.frame_set(start)
    try:
        yield
    finally:
        scene.frame_set(current, subframe=subframe)
