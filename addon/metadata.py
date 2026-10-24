import functools
import json
import math
import os
import re
import struct
import tomllib
from pathlib import Path

SCHEMA_VERSION = 1
EXTRAS_KEY = "bevy_components"
MANIFEST = Path(__file__).with_name("blender_manifest.toml")
RANGE_TOLERANCE = 0.0001
FIELD_VALUES = {
    "FLOAT": "float_value",
    "INT": "int_value",
    "BOOL": "bool_value",
    "STRING": "string_value",
    "VECTOR2": "vector2_value",
    "VECTOR": "vector_value",
    "COLOR": "color_value",
    "ENUM": "string_value",
}
FIELD_ZEROS = {
    "FLOAT": 0.0,
    "INT": 0,
    "BOOL": False,
    "STRING": "",
    "VECTOR2": (0.0, 0.0),
    "VECTOR": (0.0, 0.0, 0.0),
    "COLOR": (1.0, 1.0, 1.0, 1.0),
    "ENUM": "",
}
COLOR_CHANNELS = ("red", "green", "blue", "alpha")
PRIMITIVE_SHAPES = {"CUBOID", "SPHERE", "CAPSULE"}
INT_LIMIT = 2 ** 31
INT_RANGES = {
    "i8": (-2 ** 7, 2 ** 7 - 1),
    "i16": (-2 ** 15, 2 ** 15 - 1),
    "u8": (0, 2 ** 8 - 1),
    "u16": (0, 2 ** 16 - 1),
    "u32": (0, INT_LIMIT - 1),
    "u64": (0, INT_LIMIT - 1),
    "usize": (0, INT_LIMIT - 1),
}
AXIS_VECTORS = {
    "X": [1.0, 0.0, 0.0],
    "Y": [0.0, 1.0, 0.0],
    "Z": [0.0, 0.0, 1.0],
}
WATTS_TO_LUMENS = 683
BEVY_LIGHT_RANGE = 20.0
LIGHT_KINDS = {
    "POINT": "point",
    "SPOT": "spot",
    "SUN": "directional",
    "AREA": "area",
}
SHADOW_DEFAULTS = {
    "POINT": (0.08, 0.6, 0.1),
    "SPOT": (0.02, 1.8, 0.1),
    "SUN": (0.02, 1.8, None),
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
    if kind in {"STRING", "ENUM"}:
        return str(field.string_value)
    if kind == "VECTOR2":
        return [_float32(value) for value in field.vector2_value]
    if kind == "VECTOR":
        return [_float32(value) for value in field.vector_value]
    if kind == "COLOR":
        return {"Srgba": {channel: _float32(value) for channel, value in zip(COLOR_CHANNELS, field.color_value)}}
    raise ValueError(f"Unsupported field type: {kind}")


def tuple_fields(names):
    names = list(names)
    return bool(names) and names == [str(index) for index in range(len(names))]


def field_data(fields):
    if tuple_fields(field.name for field in fields):
        values = [field_value(field) for field in fields]
        return values[0] if len(values) == 1 else values
    return {field.name: field_value(field) for field in fields}


def json_fields(data):
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {str(index): value for index, value in enumerate(data)}
    return {} if data is None else {"0": data}


def variant_names(text):
    names = []
    for name in text.split(","):
        if name.strip() and name.strip() not in names:
            names.append(name.strip())
    return names


def convert_value(kind, value):
    if kind == "FLOAT":
        return float(value) if _number(value) else None
    if kind == "INT":
        return int(round(value)) if _number(value) and -INT_LIMIT <= round(value) < INT_LIMIT else None
    if kind == "BOOL":
        return value if isinstance(value, bool) else None
    if kind in {"STRING", "ENUM"}:
        return value if isinstance(value, str) else None
    if kind == "VECTOR2":
        return tuple(float(number) for number in value) if _numbers(value, (2,)) else None
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
    for kind in ("VECTOR2", "VECTOR", "COLOR"):
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
            "offset": _floats(item.collider_offset) if item.collider_shape in PRIMITIVE_SHAPES else None,
            "sensor": bool(item.collider_sensor),
            "events": bool(item.collider_events),
            "collision_only": bool(item.collider_collision_only),
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
    if kind == "FOG_VOLUME":
        return {
            "type": "fog_volume",
            "size": _floats(item.volume_size),
            "color": _floats(item.fog_color),
            "density": _float32(item.fog_density),
            "absorption": _float32(item.fog_absorption),
            "scattering": _float32(item.fog_scattering),
            "anisotropy": _float32(item.fog_anisotropy),
            "light_tint": _floats(item.fog_light_tint),
            "light_intensity": _float32(item.fog_light_intensity),
        }
    if kind == "REFLECTION_PROBE":
        return {
            "type": "reflection_probe",
            "size": _floats(item.volume_size),
            "falloff": [_float32(item.volume_falloff)] * 3,
            "intensity": _float32(item.probe_intensity),
            "parallax_correction": bool(item.probe_parallax),
            "file": item.probe_file or None,
        }
    if kind == "IRRADIANCE_VOLUME":
        return {
            "type": "irradiance_volume",
            "size": _floats(item.volume_size),
            "falloff": [_float32(item.volume_falloff)] * 3,
            "intensity": _float32(item.probe_intensity),
            "file": item.probe_file or None,
        }
    if kind == "LIGHTMAP":
        if getattr(getattr(item, "id_data", None), "type", "MESH") != "MESH":
            return None
        return {
            "type": "lightmap",
            "bicubic": bool(item.lightmap_bicubic),
            "file": item.probe_file or None,
        }
    if kind == "LIGHT":
        return _serialize_light(item, getattr(item, "id_data", None))
    if kind == "CUSTOM":
        if item.use_fields:
            enums = {field.name: field.rust_type.strip() for field in item.fields if field.field_type == "ENUM" and field.rust_type.strip()}
            return {"type": "custom", "type_path": item.custom_type, "data": field_data(item.fields), **({"enums": enums} if enums else {})}
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
    if kind == "NAVIGATION":
        return {
            "type": "navigation",
            "kind": item.navigation_kind.lower(),
            "cost": _float32(item.navigation_cost) if item.navigation_kind == "WALKABLE" else None,
        }
    raise ValueError(f"Unsupported component: {kind}")


def initial_velocities(item):
    dynamic = item.rigid_body_kind == "DYNAMIC"
    linear = [0.0 if dynamic and locked else float(value) for value, locked in zip(item.rigid_body_linear_velocity, item.rigid_body_lock_translation)]
    angular = [0.0 if dynamic and locked else float(value) for value, locked in zip(item.rigid_body_angular_velocity, item.rigid_body_lock_rotation)]
    return linear, angular


def _floats(values):
    return [_float32(value) for value in values]


def _layer_bits(layers):
    return sum(1 << index for index, enabled in enumerate(layers) if enabled)


def light_of(obj):
    light = getattr(obj, "data", None) if getattr(obj, "type", None) == "LIGHT" else None
    return light if light is not None and light.type in LIGHT_KINDS else None


def light_size(light):
    if light.shape in {"RECTANGLE", "ELLIPSE"}:
        return float(light.size), float(light.size_y)
    return float(light.size), float(light.size)


def light_color(light):
    color = [float(value) for value in light.color]
    if getattr(light, "use_temperature", False):
        color = [value * float(tint) for value, tint in zip(color, light.temperature_color)]
    return [_float32(value) for value in color]


def light_range(light):
    return float(light.cutoff_distance) if light.use_custom_distance else BEVY_LIGHT_RANGE


def light_intensity(light, obj=None):
    power = float(light.energy) * 2 ** float(getattr(light, "exposure", 0.0)) * WATTS_TO_LUMENS
    if light.type == "AREA" and not getattr(light, "normalize", True):
        width, height = light_size(light)
        scale = obj.matrix_world.to_scale() if obj is not None else (1.0, 1.0)
        power *= width * height * abs(scale[0] * scale[1]) * (math.pi / 4 if light.shape in {"DISK", "ELLIPSE"} else 1.0)
    return power


def light_unit(light):
    return "lx" if light.type == "SUN" else "lm"


def light_amount(value, unit):
    return f"{value:,.0f} {unit}" if value >= 100 else f"{value:.3g} {unit}"


def _serialize_light(item, obj):
    light = light_of(obj)
    if light is None:
        return None
    kind = light.type
    area = kind == "AREA"
    bias = item.light_use_bias and not area
    return {
        "type": "light",
        "kind": LIGHT_KINDS[kind],
        "intensity": _float32(item.light_intensity) if item.light_use_intensity else _float32(light_intensity(light, obj)) if area else None,
        "radius": _float32(light.shadow_soft_size) if kind in {"POINT", "SPOT"} else None,
        "range": _float32(light.cutoff_distance) if area and light.use_custom_distance else None,
        "color": light_color(light) if area else None,
        "size": [_float32(value) for value in light_size(light)] if area else None,
        "shadows": bool(light.use_shadow) and not area,
        "contact_shadows": bool(item.light_contact_shadows) and not area,
        "volumetric": bool(item.light_volumetric) and not area,
        "baked": bool(item.light_baked) and not area,
        "depth_bias": _float32(item.light_depth_bias) if bias else None,
        "normal_bias": _float32(item.light_normal_bias) if bias else None,
        "near_clip": _float32(item.light_near_clip) if bias and kind in {"POINT", "SPOT"} else None,
        "cascades": _cascades(item) if kind == "SUN" and item.light_use_cascades else None,
    }


def _cascades(item):
    return {
        "count": int(item.light_cascade_count),
        "minimum_distance": _float32(item.light_cascade_near),
        "first_cascade_far_bound": _float32(item.light_cascade_first),
        "maximum_distance": _float32(item.light_cascade_far),
        "overlap_proportion": _float32(item.light_cascade_overlap),
    }


def serialize_items(items, locate=_portable):
    components = [component for component in (serialize_component(item, locate) for item in items) if component is not None]
    return json.dumps({"version": SCHEMA_VERSION, "components": components}, separators=(",", ":"), ensure_ascii=False)


@functools.cache
def addon_version():
    return tomllib.loads(MANIFEST.read_text(encoding="utf-8"))["version"]


def ambient_light_component(color, brightness, baked):
    return {"type": "ambient_light", "color": [_float32(value) for value in color[:3]], "brightness": _float32(brightness), "baked": bool(baked)}


def sky_component(sky):
    return {"type": "sky", "brightness": _float32(sky.brightness), "environment_light": _float32(sky.environment_intensity) if sky.environment_light else None, "file": sky.sky_file or None}


def serialize_scene(components, addon):
    return json.dumps({"version": SCHEMA_VERSION, "addon": addon, "components": list(components)}, separators=(",", ":"), ensure_ascii=False)


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
            errors.extend(field_errors(item.fields))
        else:
            try:
                json.loads(item.custom_json)
            except json.JSONDecodeError:
                errors.append("invalid JSON in Custom Component")
    elif item.component_type == "LIGHT":
        light = light_of(getattr(item, "id_data", None))
        if light is not None and light.type == "SUN" and item.light_use_cascades:
            if not item.light_cascade_near < item.light_cascade_far or (item.light_cascade_count > 1 and not item.light_cascade_near < item.light_cascade_first < item.light_cascade_far):
                errors.append("Shadow cascades must satisfy near < first cascade < max distance")
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


def field_errors(fields):
    errors = []
    for field in fields:
        bounds = INT_RANGES.get(field.rust_type.strip())
        if field.field_type == "INT" and bounds is not None and not bounds[0] <= field.int_value <= bounds[1]:
            errors.append(f"{field.name} must be from {bounds[0]} to {bounds[1]} to fit {field.rust_type.strip()}")
        if field.field_type == "ENUM" and field.string_value not in variant_names(field.variants):
            errors.append(f"{field.name} needs one of its variants" if variant_names(field.variants) else f"{field.name} needs a list of variants")
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
