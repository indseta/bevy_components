import bpy

from .metadata import MESH_SHAPES, serialize_component
from .native import BLENDER_JOINTS, BLENDER_LAYERS, BLENDER_SHAPES, JOINT_AXES, NATIVE_KINDS, blender_axes, blender_vector, compound_parent, native_components
from .property import EVENTS_KEY, LAYER_COUNT
from .system import children_map, components_for, inherited, mesh_sources, sync_object

TOLERANCE = 1e-3
BLENDER_DAMPING = 1.0
DEFAULT_LAYERS = (1, (1 << LAYER_COUNT) - 1)
SHAPE_FIELDS = {
    "cuboid": ("radius", "height"),
    "sphere": ("size", "height"),
    "capsule": ("size",),
    "convex": ("size", "radius", "height"),
    "trimesh": ("size", "radius", "height"),
}
STATIC_BODY = {
    "type": "rigid_body",
    "kind": "static",
    "mass": None,
    "gravity_scale": None,
    "linear_damping": None,
    "angular_damping": None,
    "lock_translation": None,
    "lock_rotation": None,
    "ccd": None,
    "linear_velocity": None,
    "angular_velocity": None,
}


def _cards(obj):
    return {item.component_type: item for item in obj.bevy_component_data.components if item.enabled and item.component_type in NATIVE_KINDS}


def _duplicate(obj):
    kinds = [item.component_type for item in obj.bevy_component_data.components if item.enabled and item.component_type in NATIVE_KINDS]
    return next((kind for kind in kinds if kinds.count(kind) > 1), None)


def _bits(layers):
    return sum(1 << index for index, enabled in enumerate(layers) if enabled)


def _layers(layers):
    return tuple(bool(layers >> index & 1) for index in range(LAYER_COUNT))


def _same(first, second):
    if isinstance(first, (int, float)) and isinstance(second, (int, float)) and not isinstance(first, bool) and not isinstance(second, bool):
        return abs(first - second) <= TOLERANCE * max(1.0, abs(first), abs(second))
    if isinstance(first, (list, tuple)) and isinstance(second, (list, tuple)):
        return len(first) == len(second) and all(_same(one, other) for one, other in zip(first, second))
    if isinstance(first, dict) and isinstance(second, dict):
        return first.keys() == second.keys() and all(_same(first[key], second[key]) for key in first)
    return first == second


def _comparable(component):
    found = {key: value for key, value in component.items() if key not in {"memberships", "filters", "own_mesh"}}
    if found.get("type") == "collider":
        for key in SHAPE_FIELDS.get(found.get("shape"), ()):
            found.pop(key, None)
    return found


def default_layers_shared(objects):
    for obj in objects:
        for item in components_for(obj):
            if item.component_type != "COLLIDER":
                continue
            memberships, filters = _bits(item.collider_memberships), _bits(item.collider_filters)
            if filters & 1 and memberships and not memberships & 1:
                return False
    return True


def plan_layers(card, shared):
    memberships, filters = _bits(card.collider_memberships), _bits(card.collider_filters)
    if memberships == filters and memberships < 1 << BLENDER_LAYERS:
        return False, _layers(memberships)[:BLENDER_LAYERS]
    if (memberships, filters) == DEFAULT_LAYERS and shared:
        return False, _layers(1)[:BLENDER_LAYERS]
    return True, None


def _expected(obj, cards):
    expected = {}
    for kind, item in cards.items():
        expected[kind] = serialize_component(item)
    if "COLLIDER" in cards and "RIGID_BODY" not in cards and inherited(obj.parent, "RIGID_BODY")[1] is None:
        expected["RIGID_BODY"] = dict(STATIC_BODY)
    return expected


def _reason(obj, cards, children):
    collider = cards.get("COLLIDER")
    body = cards.get("RIGID_BODY")
    if collider is not None or body is not None:
        if obj.type != "MESH":
            return "Blender only gives meshes a Rigid Body"
        owner, inherited_body = inherited(obj.parent, "RIGID_BODY")
        if body is None and inherited_body is not None:
            if owner != obj.parent:
                return f"its collider is part of {owner.name}'s body, but Blender only joins direct children to a body"
            if compound_parent(obj) is None:
                return f"its collider is part of {owner.name}'s body, which needs a Blender Rigid Body with the Compound Parent shape first"
        if body is not None and compound_parent(obj) is not None:
            return f"{obj.parent.name}'s Compound Parent shape would make it part of that body"
        if body is not None and body.rigid_body_kind == "DYNAMIC" and max(body.rigid_body_linear_damping, body.rigid_body_angular_damping) > BLENDER_DAMPING:
            return "its damping is above 1, the most Blender allows"
        sources = [source for source, _matrix in mesh_sources(obj, children, "COLLIDER")]
        others = [source for source in sources if source != obj]
        if collider is not None and others and collider.collider_shape in MESH_SHAPES:
            return "its collider also covers the meshes of child objects"
        if collider is not None and others and collider.collider_collision_only:
            return "its Collision Only also hides the meshes of child objects"
    joint = cards.get("JOINT")
    if joint is not None:
        kind = joint.joint_kind
        if kind in {"REVOLUTE", "PRISMATIC"} and joint.joint_axis != JOINT_AXES[kind]:
            return f"its axis is {joint.joint_axis}, while Blender's {'Hinge turns around Z' if kind == 'REVOLUTE' else 'Slider moves along X'}"
        if kind == "SPHERICAL" and joint.joint_use_limits:
            return "Blender's Point constraint has no twist limits"
        if kind == "SPHERICAL" and joint.joint_use_swing and joint.joint_axis != "Y":
            return "its swing limit is around another axis than Z"
    return None


def _active(context, obj):
    context.view_layer.objects.active = obj


def _apply_body(context, obj, cards, physics, shared):
    collider = cards.get("COLLIDER")
    body = cards.get("RIGID_BODY")
    _active(context, obj)
    bpy.ops.rigidbody.object_add(type="ACTIVE" if body is not None and body.rigid_body_kind == "DYNAMIC" else "PASSIVE")
    native = obj.rigid_body
    native.collision_shape = BLENDER_SHAPES[collider.collider_shape] if collider is not None else "COMPOUND"
    kind = body.rigid_body_kind if body is not None else "STATIC"
    native.kinematic = kind == "KINEMATIC"
    if body is not None:
        physics.auto_mass = not body.rigid_body_use_mass
        if body.rigid_body_use_mass:
            native.mass = body.rigid_body_mass
        native.linear_damping = body.rigid_body_linear_damping
        native.angular_damping = body.rigid_body_angular_damping
        physics.gravity_scale = body.rigid_body_gravity_scale
        physics.ccd = body.rigid_body_ccd
        physics.lock_translation = blender_axes(body.rigid_body_lock_translation)
        physics.lock_rotation = blender_axes(body.rigid_body_lock_rotation)
        physics.linear_velocity = blender_vector(body.rigid_body_linear_velocity)
        physics.angular_velocity = blender_vector(body.rigid_body_angular_velocity)
    if collider is None:
        return
    native.friction = collider.collider_friction
    native.restitution = collider.collider_restitution
    physics.sensor = collider.collider_sensor
    physics.collision_only = collider.collider_collision_only
    if collider.collider_events != collider.collider_sensor:
        physics.events = collider.collider_events
    override, collections = plan_layers(collider, shared)
    physics.use_layers = override
    if override:
        physics.memberships = collider.collider_memberships
        physics.filters = collider.collider_filters
    else:
        native.collision_collections = collections


def _apply_joint(context, obj, joint, physics):
    if context.scene.rigidbody_world is None:
        bpy.ops.rigidbody.world_add()
    _active(context, obj)
    bpy.ops.rigidbody.constraint_add(type=BLENDER_JOINTS[joint.joint_kind])
    constraint = obj.rigid_body_constraint
    constraint.object1 = joint.joint_body1
    constraint.object2 = joint.joint_body2
    constraint.disable_collisions = not joint.joint_collide
    if joint.joint_kind == "REVOLUTE":
        constraint.use_limit_ang_z = joint.joint_use_limits
        constraint.limit_ang_z_lower = joint.joint_angle_min
        constraint.limit_ang_z_upper = joint.joint_angle_max
    elif joint.joint_kind == "PRISMATIC":
        constraint.use_limit_lin_x = joint.joint_use_limits
        constraint.limit_lin_x_lower = joint.joint_distance_min
        constraint.limit_lin_x_upper = joint.joint_distance_max
    physics.joint_use_swing = joint.joint_use_swing
    physics.joint_swing = joint.joint_swing
    physics.joint_linear_damping = joint.joint_linear_damping
    physics.joint_angular_damping = joint.joint_angular_damping


def _revert(context, obj, added):
    _active(context, obj)
    if "BODY" in added and obj.rigid_body is not None:
        bpy.ops.rigidbody.object_remove()
    if "JOINT" in added and obj.rigid_body_constraint is not None:
        bpy.ops.rigidbody.constraint_remove()
    physics = obj.bevy_physics
    for name in physics.bl_rna.properties.keys():
        if name != "rna_type":
            physics.property_unset(name)
    if EVENTS_KEY in physics:
        del physics[EVENTS_KEY]


def _differences(obj, expected):
    found = {item.component_type: serialize_component(item) for item in native_components(obj)}
    differences = {(kind, None) for kind in found.keys() ^ expected.keys()}
    for kind in found.keys() & expected.keys():
        first, second = _comparable(expected[kind]), _comparable(found[kind])
        differences.update((kind, key) for key in first.keys() | second.keys() if not _same(first.get(key), second.get(key)))
    return differences


def _difference_reason(differences):
    if any(kind == "COLLIDER" and key in {"size", "radius", "height", "offset"} for kind, key in differences):
        return "its collider's size or offset differs from the mesh, which Blender's shape always fits"
    return "Blender's physics would change what the game gets"


def _depth(obj):
    depth = 0
    while obj.parent is not None:
        obj = obj.parent
        depth += 1
    return depth


def convert_objects(context, objects):
    objects = sorted(objects, key=_depth)
    children = children_map(context.scene.objects)
    shared = default_layers_shared(context.scene.objects)
    previous = context.view_layer.objects.active
    converted = []
    kept = []
    try:
        for obj in objects:
            cards = _cards(obj)
            if not cards or obj.library is not None:
                continue
            if context.view_layer.objects.get(obj.name) != obj:
                kept.append((obj, "it is not in the view layer"))
                continue
            if obj.rigid_body is not None and ("COLLIDER" in cards or "RIGID_BODY" in cards) or obj.rigid_body_constraint is not None and "JOINT" in cards:
                kept.append((obj, "it already has Blender physics, which the components replace"))
                continue
            duplicate = _duplicate(obj)
            if duplicate is not None:
                kept.append((obj, f"it has more than one {duplicate.replace('_', ' ').title()} component"))
                continue
            reason = _reason(obj, cards, children)
            if reason is not None:
                kept.append((obj, reason))
                continue
            expected = {**{item.component_type: serialize_component(item) for item in native_components(obj)}, **_expected(obj, cards)}
            physics = obj.bevy_physics
            added = set()
            if "COLLIDER" in cards or "RIGID_BODY" in cards:
                _apply_body(context, obj, cards, physics, shared)
                added.add("BODY")
            if "JOINT" in cards:
                _apply_joint(context, obj, cards["JOINT"], physics)
                added.add("JOINT")
            differences = _differences(obj, expected)
            if differences:
                _revert(context, obj, added)
                kept.append((obj, _difference_reason(differences)))
                continue
            components = obj.bevy_component_data.components
            for index in reversed([index for index, item in enumerate(components) if any(item == card for card in cards.values())]):
                components.remove(index)
            sync_object(obj)
            converted.append(obj)
    finally:
        context.view_layer.objects.active = previous
    return converted, kept
