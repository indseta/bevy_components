from contextlib import contextmanager

import bpy

from .metadata import gravity_component

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
NATIVE_KINDS = ("COLLIDER", "RIGID_BODY", "JOINT")
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
    return parent if body is not None and body.collision_shape == "COMPOUND" else None


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


def native_components(obj):
    physics = getattr(obj, "bevy_physics", None)
    if physics is None:
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
    return found


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
