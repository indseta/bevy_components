import json
import os
import struct

SCHEMA_VERSION = 1
EXTRAS_KEY = "bevy_components"
RANGE_TOLERANCE = 0.0001
FIELD_VALUES = {
    "FLOAT": "float_value",
    "INT": "int_value",
    "BOOL": "bool_value",
    "STRING": "string_value",
    "VECTOR": "vector_value",
    "COLOR": "color_value",
}
COLOR_CHANNELS = ("red", "green", "blue", "alpha")
INT_LIMIT = 2 ** 31
AXIS_VECTORS = {
    "X": [1.0, 0.0, 0.0],
    "Y": [0.0, 1.0, 0.0],
    "Z": [0.0, 0.0, 1.0],
}


def _single(value):
    try:
        return struct.unpack("f", struct.pack("f", value))[0]
    except OverflowError:
        return None


def _float32(value):
    single = _single(value)
    if single is None:
        return value
    for digits in range(1, 10):
        candidate = float(f"{single:.{digits}g}")
        if _single(candidate) == single:
            return candidate
    return single


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) < 1e38


def _numbers(value, sizes):
    return isinstance(value, (list, tuple)) and len(value) in sizes and all(_number(number) for number in value)


def field_value(field):
    kind = field.field_type
    if kind == "FLOAT":
        return _float32(field.float_value)
    if kind == "INT":
        return int(field.int_value)
    if kind == "BOOL":
        return bool(field.bool_value)
    if kind == "STRING":
        return str(field.string_value)
    if kind == "VECTOR":
        return [_float32(value) for value in field.vector_value]
    if kind == "COLOR":
        return {"Srgba": {channel: _float32(value) for channel, value in zip(COLOR_CHANNELS, field.color_value)}}
    raise ValueError(f"Unsupported field type: {kind}")


def field_data(fields):
    return {field.name: field_value(field) for field in fields}


def convert_value(kind, value):
    if kind == "FLOAT":
        return float(value) if _number(value) else None
    if kind == "INT":
        return int(round(value)) if _number(value) and -INT_LIMIT <= round(value) < INT_LIMIT else None
    if kind == "BOOL":
        return value if isinstance(value, bool) else None
    if kind == "STRING":
        return value if isinstance(value, str) else None
    if kind == "VECTOR":
        return tuple(float(number) for number in value) if _numbers(value, (3,)) else None
    if kind == "COLOR":
        if isinstance(value, dict) and list(value) == ["Srgba"] and isinstance(value["Srgba"], dict):
            value = [value["Srgba"].get(channel, 1.0 if channel == "alpha" else None) for channel in COLOR_CHANNELS]
        return tuple(float(number) for number in value) + (1.0,) * (4 - len(value)) if _numbers(value, (3, 4)) else None
    return None


def infer_field_type(value):
    if isinstance(value, bool):
        return "BOOL"
    if isinstance(value, int):
        return "INT" if convert_value("INT", value) is not None else None
    if isinstance(value, float):
        return "FLOAT" if _number(value) else None
    if isinstance(value, str):
        return "STRING"
    for kind in ("VECTOR", "COLOR"):
        if convert_value(kind, value) is not None:
            return kind
    return None


def infer_fields(data):
    if not isinstance(data, dict):
        raise ValueError("Only a JSON object can be split into fields")
    unsupported = [name for name, value in data.items() if infer_field_type(value) is None]
    if unsupported:
        raise ValueError(f"No field type fits {', '.join(unsupported)}")
    return [(name, infer_field_type(value), convert_value(infer_field_type(value), value)) for name, value in data.items()]


def invalid_names(names):
    names = list(names)
    return {name for name in names if not name.strip() or names.count(name) > 1}


def relative_path(path, directory):
    return os.path.relpath(path, directory).replace(os.sep, "/")


def _portable(path):
    return path.replace("\\", "/")


def serialize_component(item, locate=_portable):
    kind = item.component_type
    if kind == "VISIBILITY_RANGE":
        return {
            "type": "visibility_range",
            "start": [float(item.fade_in_start), float(item.fade_in_end)],
            "end": [float(item.fade_out_start), float(item.fade_out_end)],
            "use_aabb": bool(item.use_aabb),
        }
    if kind == "COLLIDER":
        return {
            "type": "collider",
            "shape": item.collider_shape.lower(),
            "size": [float(value) for value in item.collider_size],
            "radius": float(item.collider_radius),
            "height": float(item.collider_height),
            "sensor": bool(item.collider_sensor),
            "friction": float(item.collider_friction),
            "restitution": float(item.collider_restitution),
            "memberships": _layer_bits(item.collider_memberships),
            "filters": _layer_bits(item.collider_filters),
        }
    if kind == "RIGID_BODY":
        dynamic = item.rigid_body_kind == "DYNAMIC"
        moving = item.rigid_body_kind != "STATIC"
        return {
            "type": "rigid_body",
            "kind": item.rigid_body_kind.lower(),
            "mass": float(item.rigid_body_mass) if dynamic and item.rigid_body_use_mass else None,
            "gravity_scale": float(item.rigid_body_gravity_scale) if dynamic else None,
            "linear_damping": float(item.rigid_body_linear_damping) if dynamic else None,
            "angular_damping": float(item.rigid_body_angular_damping) if dynamic else None,
            "lock_translation": [bool(value) for value in item.rigid_body_lock_translation] if dynamic else None,
            "lock_rotation": [bool(value) for value in item.rigid_body_lock_rotation] if dynamic else None,
            "ccd": item.rigid_body_ccd.lower() if dynamic else None,
            "linear_velocity": [float(value) for value in item.rigid_body_linear_velocity] if moving else None,
            "angular_velocity": [float(value) for value in item.rigid_body_angular_velocity] if moving else None,
        }
    if kind == "JOINT":
        joint = item.joint_kind
        limits = item.joint_use_limits
        return {
            "type": "joint",
            "kind": joint.lower(),
            "body1": item.joint_body1.name if item.joint_body1 else None,
            "body2": item.joint_body2.name if item.joint_body2 else None,
            "axis": AXIS_VECTORS[item.joint_axis] if joint != "FIXED" else None,
            "angle_limits": [float(item.joint_angle_min), float(item.joint_angle_max)] if limits and joint in {"REVOLUTE", "SPHERICAL"} else None,
            "distance_limits": [float(item.joint_distance_min), float(item.joint_distance_max)] if limits and joint == "PRISMATIC" else None,
            "swing_limit": float(item.joint_swing) if item.joint_use_swing and joint == "SPHERICAL" else None,
            "linear_damping": float(item.joint_linear_damping) if joint != "FIXED" else None,
            "angular_damping": float(item.joint_angular_damping) if joint != "FIXED" else None,
            "collide": bool(item.joint_collide),
        }
    if kind == "SHADOWS":
        return {
            "type": "shadows",
            "cast": bool(item.shadows_cast),
            "receive": bool(item.shadows_receive),
        }
    if kind == "AUDIO_PLAYER":
        return {
            "type": "audio_player",
            "path": item.audio_path.strip(),
            "volume": _float32(item.audio_volume),
            "loop": bool(item.audio_loop),
            "autoplay": bool(item.audio_autoplay),
            "spatial": bool(item.audio_spatial),
            "distance": _float32(item.audio_distance),
        }
    if kind == "CUSTOM":
        if item.use_fields:
            return {"type": "custom", "type_path": item.custom_type, "data": field_data(item.fields)}
        try:
            value = json.loads(item.custom_json)
        except json.JSONDecodeError as error:
            raise ValueError(f"Custom JSON for {item.custom_type} is invalid: {error}") from error
        return {"type": "custom", "type_path": item.custom_type, "data": value}
    if kind == "SCENE_REFERENCE":
        return {
            "type": "scene_reference",
            "path": locate(item.scene_file),
            "scene": int(item.scene_index),
        }
    if kind == "ANIMATION":
        return {
            "type": "animation",
            "clip": item.animation_clip,
            "repeat": bool(item.animation_loop),
            "speed": _float32(item.animation_speed),
        }
    raise ValueError(f"Unsupported component: {kind}")


def initial_velocities(item):
    dynamic = item.rigid_body_kind == "DYNAMIC"
    linear = [0.0 if dynamic and locked else float(value) for value, locked in zip(item.rigid_body_linear_velocity, item.rigid_body_lock_translation)]
    angular = [0.0 if dynamic and locked else float(value) for value, locked in zip(item.rigid_body_angular_velocity, item.rigid_body_lock_rotation)]
    return linear, angular


def _layer_bits(layers):
    return sum(1 << index for index, enabled in enumerate(layers) if enabled)


def serialize_items(items, locate=_portable):
    return json.dumps({"version": SCHEMA_VERSION, "components": [serialize_component(item, locate) for item in items]}, separators=(",", ":"), ensure_ascii=False)


def component_errors(item):
    errors = []
    if item.component_type == "VISIBILITY_RANGE":
        if not (0 <= item.fade_in_start <= item.fade_in_end <= item.fade_out_start <= item.fade_out_end):
            errors.append("Visibility Range must satisfy 0 <= in.start <= in.end <= out.start <= out.end")
    elif item.component_type == "CUSTOM":
        if not item.custom_type.strip():
            errors.append("Custom Component needs a Rust type path")
        if item.use_fields:
            if invalid_names(field.name for field in item.fields):
                errors.append(f"{item.custom_type} needs a unique name for every field")
        else:
            try:
                json.loads(item.custom_json)
            except json.JSONDecodeError:
                errors.append("invalid JSON in Custom Component")
    elif item.component_type == "COLLIDER":
        if item.collider_shape == "CUBOID" and any(value <= 0 for value in item.collider_size):
            errors.append("collider cuboid dimensions must be positive")
        if item.collider_shape in {"SPHERE", "CAPSULE"} and item.collider_radius <= 0:
            errors.append("collider radius must be positive")
    elif item.component_type == "JOINT" and joint_limits_inverted(item):
        errors.append("Joint limit Min is above Max")
    elif item.component_type == "SCENE_REFERENCE":
        if not item.scene_file.strip():
            errors.append("Scene Reference needs a glTF file")
    return errors


def joint_limits_inverted(item):
    if not item.joint_use_limits or item.joint_kind == "FIXED":
        return False
    if item.joint_kind == "PRISMATIC":
        return item.joint_distance_min > item.joint_distance_max
    return item.joint_angle_min > item.joint_angle_max


def validate_items(items, object_name="Object"):
    return [f"{object_name}: {error}" for item in items for error in component_errors(item)]


def visibility_range_problems(entries):
    levels = {}
    for name, ranges in entries:
        levels.setdefault(tuple(round(float(value), 4) for value in ranges), []).append(name)
    ordered = sorted(levels.items())
    problems = []
    for (near_ranges, near_names), (far_ranges, far_names) in zip(ordered, ordered[1:]):
        _near_in_start, _near_in_end, out_start, out_end = near_ranges
        in_start, in_end, _far_out_start, _far_out_end = far_ranges
        near = near_names[0]
        if in_start > out_end + RANGE_TOLERANCE:
            message = f"Gap after {near}: nothing shows from {out_end:g} to {in_start:g} m"
        elif in_end < out_start - RANGE_TOLERANCE:
            message = f"Shows together with {near} from {in_end:g} to {out_start:g} m"
        elif abs(in_start - out_start) > RANGE_TOLERANCE or abs(in_end - out_end) > RANGE_TOLERANCE:
            message = f"Fades in over {in_start:g}–{in_end:g} m but {near} fades out over {out_start:g}–{out_end:g} m, so they do not crossfade"
        else:
            continue
        problems.extend((name, message) for name in far_names)
    return problems
