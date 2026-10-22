import json

SCHEMA_VERSION = 1
EXTRAS_KEY = "bevy_components"


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


def validate_items(items, object_name="Object"):
    errors = []
    for item in items:
        if item.component_type == "VISIBILITY_RANGE":
            if not (0 <= item.fade_in_start <= item.fade_in_end <= item.fade_out_start <= item.fade_out_end):
                errors.append(f"{object_name}: Visibility Range must satisfy 0 <= in.start <= in.end <= out.start <= out.end")
        elif item.component_type == "CUSTOM":
            if not item.custom_type.strip():
                errors.append(f"{object_name}: Custom Component needs a Rust type path")
            try:
                json.loads(item.custom_json)
            except json.JSONDecodeError:
                errors.append(f"{object_name}: invalid JSON in Custom Component")
        elif item.component_type == "COLLIDER":
            if item.collider_shape == "CUBOID" and any(value <= 0 for value in item.collider_size):
                errors.append(f"{object_name}: collider cuboid dimensions must be positive")
            if item.collider_shape in {"SPHERE", "CAPSULE"} and item.collider_radius <= 0:
                errors.append(f"{object_name}: collider radius must be positive")
    return errors
