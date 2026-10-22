import json
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


def serialize_component(item):
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
        }
    if kind == "RIGID_BODY":
        return {"type": "rigid_body", "kind": item.rigid_body_kind.lower()}
    if kind == "CUSTOM":
        if item.use_fields:
            return {"type": "custom", "type_path": item.custom_type, "data": field_data(item.fields)}
        try:
            value = json.loads(item.custom_json)
        except json.JSONDecodeError as error:
            raise ValueError(f"Custom JSON for {item.custom_type} is invalid: {error}") from error
        return {"type": "custom", "type_path": item.custom_type, "data": value}
    raise ValueError(f"Unsupported component: {kind}")


def serialize_items(items):
    return json.dumps({"version": SCHEMA_VERSION, "components": [serialize_component(item) for item in items]}, separators=(",", ":"), ensure_ascii=False)


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
    return errors


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
