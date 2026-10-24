import os

import bpy

from .collection import left_out
from .metadata import MESH_SHAPES, WATTS_TO_LUMENS, serialize_component
from .native import BLENDER_JOINTS, BLENDER_LAYERS, BLENDER_SHAPES, FOG_SETTINGS, JOINT_AXES, LIGHT_SETTINGS, MESH_TYPES, NATIVE_KINDS, NATIVE_SOURCES, PRINCIPLED_VOLUME, SPEAKER_SETTINGS, active_action, asset_path, blender_axes, blender_vector, compound_parent, fog_source, linear, native_components
from .project import game_assets
from .property import EVENTS_KEY, LAYER_COUNT
from .system import children_map, component_of, components_for, data_users, inherited, mesh_sources, owns_mesh, touch_object

TOLERANCE = 1e-3
PHYSICS_KINDS = ("COLLIDER", "RIGID_BODY", "JOINT")
NATIVE_TYPES = {"AUDIO_PLAYER": "SPEAKER", "REFLECTION_PROBE": "LIGHT_PROBE", "IRRADIANCE_VOLUME": "LIGHT_PROBE"}
CHILD_SUFFIXES = {"AUDIO_PLAYER": "speaker", "FOG_VOLUME": "fog", "REFLECTION_PROBE": "probe", "IRRADIANCE_VOLUME": "probe"}
PROBE_TYPES = {"REFLECTION_PROBE": "SPHERE", "IRRADIANCE_VOLUME": "VOLUME"}
VOLUME_TYPES = {"fog_volume", "reflection_probe", "irradiance_volume"}
BOX_FACES = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))
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
    found = {item.component_type: serialize_component(item) for item in native_components(obj) if item.component_type in PHYSICS_KINDS}
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


def _label(kind):
    return kind.replace("_", " ").title()


def _native(obj, kind):
    return next((serialize_component(item) for item in native_components(obj) if item.component_type == kind), None)


def _serialized(obj, kind):
    item = component_of(obj, kind)
    return serialize_component(item) if item is not None else None


def _settings(group, names):
    return {name: getattr(group, name) for name in names if group.is_property_set(name)}


def _restore(group, names, saved):
    for name in names:
        group.property_unset(name)
    for name, value in saved.items():
        setattr(group, name, value)


def _changed(obj, kind, users, before):
    return next((user for user in users if not _same(before[user], _native(user, kind) if user == obj else _serialized(user, kind))), None)


def _convert_physics(context, obj, cards, children, shared):
    if context.view_layer.objects.get(obj.name) != obj:
        return "it is not in the view layer"
    if obj.rigid_body is not None and ("COLLIDER" in cards or "RIGID_BODY" in cards) or obj.rigid_body_constraint is not None and "JOINT" in cards:
        return "it already has Blender physics, which the components replace"
    reason = _reason(obj, cards, children)
    if reason is not None:
        return reason
    expected = {**{item.component_type: serialize_component(item) for item in native_components(obj) if item.component_type in PHYSICS_KINDS}, **_expected(obj, cards)}
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
        return _difference_reason(differences)
    return None


def _convert_light(obj, card):
    light = obj.data if obj.type == "LIGHT" else None
    if light is None or light.library is not None:
        return "its Light component is not on a light of this .blend file"
    users = data_users(light)
    before = {user: _serialized(user, "LIGHT") for user in users}
    settings = light.bevy_light
    saved = _settings(settings, LIGHT_SETTINGS)
    for name in LIGHT_SETTINGS:
        setattr(settings, name, getattr(card, name))
    changed = _changed(obj, "LIGHT", users, before)
    if changed is not None:
        _restore(settings, LIGHT_SETTINGS, saved)
        for user in users:
            touch_object(user)
        return "Blender's light would change what the game gets" if changed == obj else f"{changed.name} shares its light data and would get these Light settings too"
    return None


def _shadows_above(obj):
    parent = obj.parent
    while parent is not None and (component_of(parent, "SHADOWS") is None or owns_mesh(parent, "SHADOWS")):
        parent = parent.parent
    return parent


def _convert_shadows(obj, card, children):
    if obj.type not in MESH_TYPES or any(source != obj for source, _matrix in mesh_sources(obj, children, "SHADOWS")):
        return "its Shadows component covers the meshes of child objects, while Blender sets shadows on each mesh object"
    owner = _shadows_above(obj)
    if card.shadows_cast and card.shadows_receive and owner is not None:
        return f"{owner.name}'s Shadows component would reach its mesh"
    obj.visible_shadow = card.shadows_cast
    obj.bevy_object.receive_shadows = card.shadows_receive
    return None


def _convert_animation(obj, card):
    action = active_action(obj)
    if action is None or action.name != card.animation_clip:
        return f"its Animation clip {card.animation_clip} is not the object's active action"
    if action.library is not None and action.use_cyclic != card.animation_loop:
        return f"its action {action.name} is linked from another .blend file, so its Cyclic setting cannot change"
    users = [user for user in bpy.data.objects if active_action(user) == action]
    before = {user: _serialized(user, "ANIMATION") for user in users}
    settings = obj.bevy_object
    saved, cyclic = _settings(settings, ("autoplay", "speed")), action.use_cyclic
    settings.autoplay = True
    settings.speed = card.animation_speed
    if cyclic != card.animation_loop:
        action.use_cyclic = card.animation_loop
    changed = _changed(obj, "ANIMATION", users, before)
    if changed is not None:
        _restore(settings, ("autoplay", "speed"), saved)
        if action.use_cyclic != cyclic:
            action.use_cyclic = cyclic
        for user in users:
            touch_object(user)
        return "Blender's action would change what the game gets" if changed == obj else f"{changed.name} also plays {action.name}, so its Cyclic setting would change for it too"
    return None


def _sound_file(context, path):
    destination = context.scene.bevy_glb_export.filepath.strip()
    roots = [game_assets(context), asset_path(os.path.abspath(bpy.path.abspath(destination)))[1] if destination else None]
    return next((root / path for root in roots if root is not None and (root / path).is_file()), None)


def _fog_inputs(card):
    tint = [linear(channel) for channel in card.fog_color]
    scattering = card.fog_scattering
    remaining = card.fog_absorption + scattering * (1.0 - max(tint))
    ratio = max(1.0, remaining + scattering * sum(tint) / 3, scattering * max(tint))
    room = sum(ratio - channel * scattering for channel in tint) / 3
    share = remaining / room if room > 0 else 0.0
    return [channel * scattering / ratio for channel in tint], card.fog_density * ratio, (1.0 - share) ** 2


def _speaker_data(context, name, card):
    path = card.audio_path.strip()
    if not path:
        return None, "its Audio Player has no sound file"
    if card.audio_volume > 1.0:
        return None, "its Audio Player volume is above 1, the most a Speaker allows"
    found = _sound_file(context, path)
    if found is None:
        return None, f"its Audio Player sound {path} is not in the game's assets folder, so a Speaker cannot load it"
    speaker = bpy.data.speakers.new(name)
    speaker.sound = bpy.data.sounds.load(str(found), check_existing=True)
    speaker.volume = card.audio_volume
    speaker.distance_reference = card.audio_distance
    for setting in SPEAKER_SETTINGS:
        setattr(speaker.bevy_speaker, setting, getattr(card, setting))
    return speaker, None


def _fog_data(name, card):
    width, height, depth = card.volume_size
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(x, y, z) for x in (-width / 2, width / 2) for y in (-depth / 2, depth / 2) for z in (-height / 2, height / 2)], [], BOX_FACES)
    material = bpy.data.materials.new(name)
    if bpy.app.version < (5, 0, 0):
        material.use_nodes = True
    nodes = material.node_tree.nodes
    for node in [node for node in nodes if node.bl_idname != "ShaderNodeOutputMaterial"]:
        nodes.remove(node)
    output = next((node for node in nodes if node.bl_idname == "ShaderNodeOutputMaterial"), None) or nodes.new("ShaderNodeOutputMaterial")
    volume = nodes.new(PRINCIPLED_VOLUME)
    volume.location = (output.location.x - 300, output.location.y)
    material.node_tree.links.new(volume.outputs["Volume"], output.inputs["Volume"])
    color, density, absorption = _fog_inputs(card)
    volume.inputs["Color"].default_value = (*color, 1.0)
    volume.inputs["Density"].default_value = density
    volume.inputs["Absorption Color"].default_value = (absorption, absorption, absorption, 1.0)
    volume.inputs["Anisotropy"].default_value = card.fog_anisotropy
    for setting in FOG_SETTINGS:
        setattr(material.bevy_fog, setting, getattr(card, setting))
    mesh.materials.append(material)
    return mesh


def _probe_data(name, kind, card):
    probe = bpy.data.lightprobes.new(name, PROBE_TYPES[kind])
    if kind == "REFLECTION_PROBE":
        probe.influence_type = "BOX"
        probe.influence_distance = 1.0
        probe.falloff = card.volume_falloff
        probe.bevy_probe.intensity = card.probe_intensity / WATTS_TO_LUMENS
        probe.bevy_probe.parallax = card.probe_parallax
        probe.bevy_probe.bake_resolution = card.bake_resolution
    else:
        probe.intensity = card.probe_intensity / WATTS_TO_LUMENS
        probe.bevy_probe.falloff = card.volume_falloff
        probe.resolution_x, probe.resolution_z, probe.resolution_y = card.bake_voxels
    return probe


def _effective(component, scale=(1.0, 1.0, 1.0)):
    found = dict(component)
    if found.get("type") in VOLUME_TYPES:
        found["size"] = [value * factor for value, factor in zip(found["size"], scale)]
    if found.get("type") == "fog_volume":
        density, scattering = found.pop("density"), found.pop("scattering")
        found["in_scatter"] = [linear(channel) * scattering * density for channel in found.pop("color")]
        found["extinction"] = density * (found.pop("absorption") + scattering)
    return found


def _same_type(obj, kind):
    return fog_source(obj) is not None if kind == "FOG_VOLUME" else obj.type == NATIVE_TYPES[kind]


def _convert_same(obj, kind, card):
    found = _native(obj, kind)
    if found is None or not _same(_effective(serialize_component(card)), _effective(found)):
        return f"its {_label(kind)} component differs from the {NATIVE_SOURCES[kind][0]}'s settings"
    return None


def _convert_child(context, obj, kind, card):
    name = f"{obj.name}_{CHILD_SUFFIXES[kind]}"
    if kind == "AUDIO_PLAYER":
        data, reason = _speaker_data(context, name, card)
        if data is None:
            return reason
    else:
        data = _fog_data(name, card) if kind == "FOG_VOLUME" else _probe_data(name, kind, card)
    child = bpy.data.objects.new(name, data)
    for collection in obj.users_collection:
        collection.objects.link(child)
    child.parent = obj
    if kind in PROBE_TYPES:
        width, height, depth = card.volume_size
        child.scale = (width / 2, depth / 2, height / 2)
        child.bevy_object.probe_file = card.probe_file
        child.bevy_object.bake_fingerprint = card.bake_fingerprint
    found = _native(child, kind)
    if found is None or not _same(_effective(serialize_component(card)), _effective(found, (child.scale.x, child.scale.z, child.scale.y))):
        bpy.data.batch_remove([child, data, *getattr(data, "materials", ())])
        return f"a {NATIVE_SOURCES[kind][0]} would change what the game gets from its {_label(kind)} component"
    touch_object(child)
    return None


def _convert_data(context, obj, kind, card, children):
    if kind == "LIGHT":
        return _convert_light(obj, card)
    if kind == "SHADOWS":
        return _convert_shadows(obj, card, children)
    if kind == "ANIMATION":
        return _convert_animation(obj, card)
    if _same_type(obj, kind):
        return _convert_same(obj, kind, card)
    return _convert_child(context, obj, kind, card)


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
            if left_out(obj):
                kept.append((obj, "it is left out of Bevy, so Blender's settings would not reach the game"))
                continue
            duplicate = _duplicate(obj)
            if duplicate is not None:
                kept.append((obj, f"it has more than one {_label(duplicate)} component"))
                continue
            done = []
            physics = {kind: card for kind, card in cards.items() if kind in PHYSICS_KINDS}
            if physics:
                reason = _convert_physics(context, obj, physics, children, shared)
                if reason is None:
                    done.extend(physics.values())
                else:
                    kept.append((obj, reason))
            for kind, card in cards.items():
                if kind in PHYSICS_KINDS:
                    continue
                reason = _convert_data(context, obj, kind, card, children)
                if reason is None:
                    done.append(card)
                else:
                    kept.append((obj, reason))
            if not done:
                continue
            components = obj.bevy_component_data.components
            for index in reversed([index for index, item in enumerate(components) if any(item == card for card in done)]):
                components.remove(index)
            touch_object(obj)
            converted.append(obj)
    finally:
        context.view_layer.objects.active = previous
    return converted, kept
