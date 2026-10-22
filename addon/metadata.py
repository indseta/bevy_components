import json

SCHEMA_VERSION = 1
EXTRAS_KEY = "bevy_components"
RANGE_TOLERANCE = 0.0001


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
