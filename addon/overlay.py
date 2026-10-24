from array import array
from math import cos, degrees, radians
from pathlib import PurePosixPath

import blf
import bmesh
import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from .geometry import arrow_lines, box_lines, capsule_lines, cone_lines, cone_shape_lines, cuboid_lines, cylinder_lines, joint_lines, perpendicular, sphere_lines, spin_lines, voxel_lines
from .metadata import EXTRAS_KEY, PRIMITIVE_SHAPES, initial_velocities, light_amount, light_intensity, light_of, light_range, light_unit, serialize_items
from .native import native_components
from .property import JOINT_LABELS
from .reference import read_scenes
from .schema import short_name
from .system import changes_mesh, children_map, collider_sources, component_of, components_for, export_settings, file_path, mesh_sources, panel_expanded, redraw_viewports
from .validation import texture_check

DRAW_3D = None
DRAW_2D = None
MESH_PREVIEWS = {}
MESH_PREVIEW_LIMIT = 1024
PREVIEW_CACHE = {}
PREVIEW_LIMIT = 4096
MESH_SHAPES = {"TRIMESH", "CONVEX"}
IDENTITY = Matrix.Identity(4)

COLLIDER_COLOR = (0.22, 0.96, 0.55, 0.90)
SENSOR_COLOR = (0.96, 0.60, 0.20, 0.90)
COLLISION_ONLY_COLOR = (0.30, 0.86, 0.94, 0.90)
LOD_IN_COLOR = (0.20, 0.72, 1.0, 0.55)
LOD_OUT_COLOR = (1.0, 0.62, 0.25, 0.55)
AUDIO_COLOR = (0.95, 0.80, 0.25, 0.70)
AUDIO_QUIET_COLOR = (0.95, 0.80, 0.25, 0.30)
AUDIO_QUIET_FACTOR = 10
SHADOW_LABELS = {
    (False, True): "no casting",
    (True, False): "no receiving",
    (False, False): "no casting or receiving",
    (True, True): "as usual",
}
JOINT_COLOR = (0.82, 0.52, 1.0, 0.90)
VELOCITY_COLOR = (1.0, 0.90, 0.30, 0.90)
JOINT_AXES = {
    "X": Vector((1.0, 0.0, 0.0)),
    "Y": Vector((0.0, 0.0, 1.0)),
    "Z": Vector((0.0, -1.0, 0.0)),
}
JOINT_SIZE = 0.5
JOINT_SIZES = (0.25, 5.0)
VELOCITY_SECONDS = 0.25
VELOCITY_LENGTHS = (0.3, 5.0)
JOINT_TAG = '"type":"joint"'
SCENE_COLOR = (1.0, 0.42, 0.70, 0.85)
VOLUME_COLORS = {
    "FOG_VOLUME": (0.72, 0.80, 0.92, 0.80),
    "REFLECTION_PROBE": (0.35, 0.85, 1.0, 0.85),
    "IRRADIANCE_VOLUME": (1.0, 0.82, 0.30, 0.85),
}
VOLUME_NAMES = {
    "FOG_VOLUME": "Fog Volume",
    "REFLECTION_PROBE": "Reflection Probe",
    "IRRADIANCE_VOLUME": "Irradiance Volume",
}
MISSING_TEXTURES = {
    "REFLECTION_PROBE": "no cubemap",
    "IRRADIANCE_VOLUME": "no voxels",
}
LIGHT_COLOR = (1.0, 0.86, 0.35, 0.6)
LABEL_COLOR = (0.9, 1.0, 0.95, 0.98)
NAME_COLOR = (0.9, 1.0, 0.95, 0.7)
LABEL_SIZE = 12
LABEL_SPACING = 16
LABEL_OFFSET = (14, 16)
LABEL_DESCENT = 4
LIGHT_LABELS = {
    "POINT": "Point",
    "SPOT": "Spot",
    "SUN": "Sun",
    "AREA": "Area",
}
NAVIGATION_COLORS = {
    "WALKABLE": (0.30, 0.62, 1.0, 0.85),
    "OBSTACLE": (1.0, 0.32, 0.32, 0.85),
}
NAVIGATION_LABELS = {
    "WALKABLE": "Walkable",
    "OBSTACLE": "Obstacle",
    "IGNORED": "Ignored",
}
WALKABLE_SLOPE = radians(45)


def preview_objects(context, settings):
    if not context.scene or not context.view_layer:
        return []
    objects = context.selected_objects if settings.scope == "SELECTED" else context.scene.objects
    return [obj for obj in objects if obj.visible_get(view_layer=context.view_layer) and len(components_for(obj))]


def joint_objects(context, settings, objects):
    found = [obj for obj in objects if component_of(obj, "JOINT") is not None]
    if settings.scope == "ALL" or not context.selected_objects:
        return found
    selected = set(context.selected_objects)
    listed = set(found)
    for obj in context.scene.objects:
        if obj in listed or JOINT_TAG not in str(obj.get(EXTRAS_KEY, "")) and getattr(obj, "rigid_body_constraint", None) is None or not obj.visible_get(view_layer=context.view_layer):
            continue
        joint = component_of(obj, "JOINT")
        if joint is not None and (joint.joint_body1 in selected or joint.joint_body2 in selected):
            found.append(obj)
    return found


def bevy_to_blender(vector):
    return Vector((vector[0], -vector[2], vector[1]))


def _clamp(value, limits):
    return max(limits[0], min(value, limits[1]))


def joint_batches(obj, item):
    location, rotation, _scale = obj.matrix_world.decompose()
    inverse = rotation.inverted()
    axis = JOINT_AXES[item.joint_axis]
    offsets = [(inverse @ (body.matrix_world.translation - location), sign) for body, sign in ((item.joint_body2, 1.0), (item.joint_body1, -1.0)) if body is not None]
    offset, sign = next(((offset, sign) for offset, sign in offsets if offset.length > 1e-4), (Vector(), offsets[0][1] if offsets else 1.0))
    size = _clamp(offset.length, JOINT_SIZES) if offset.length > 1e-4 else JOINT_SIZE
    reference = perpendicular(tuple(axis), tuple(offset))
    limits = None
    if item.joint_use_limits and item.joint_kind in {"REVOLUTE", "SPHERICAL"}:
        limits = (item.joint_angle_min, item.joint_angle_max)
    elif item.joint_use_limits and item.joint_kind == "PRISMATIC":
        limits = (item.joint_distance_min, item.joint_distance_max)
    if limits is not None and sign < 0:
        limits = (-limits[1], -limits[0])
    swing = item.joint_swing if item.joint_use_swing and item.joint_kind == "SPHERICAL" else None
    batches = [(Matrix.LocRotScale(location, rotation, None), joint_lines(item.joint_kind, tuple(axis), reference, size, limits, swing), JOINT_COLOR, 2.0)]
    links = [(tuple(location), tuple(body.matrix_world.translation)) for body in (item.joint_body1, item.joint_body2) if body is not None and body != obj]
    if links:
        batches.append((Matrix.Identity(4), links, JOINT_COLOR, 1.0))
    return batches


def velocity_batches(obj, item):
    if item.rigid_body_kind == "STATIC":
        return []
    origin = obj.matrix_world.translation
    linear, angular = (bevy_to_blender(vector) for vector in initial_velocities(item))
    lines = []
    if linear.length > 1e-6:
        lines.extend(arrow_lines(tuple(origin), tuple(origin + linear.normalized() * _clamp(linear.length * VELOCITY_SECONDS, VELOCITY_LENGTHS))))
    if angular.length > 1e-6:
        radius = _clamp(max(obj.dimensions) * 0.6, VELOCITY_LENGTHS) if max(obj.dimensions) > 0 else JOINT_SIZE
        lines.extend(spin_lines(tuple(angular.normalized()), radius, tuple(origin)))
    return [(Matrix.Identity(4), lines, VELOCITY_COLOR, 2.0)] if lines else []


def collider_matrix(obj, item):
    return obj.matrix_world @ Matrix.Translation(bevy_to_blender(item.collider_offset))


def collider_lines(obj, item, limit, children):
    kind = item.collider_shape
    if kind == "CUBOID":
        return [(collider_matrix(obj, item), cuboid_lines(item.collider_size))]
    if kind == "SPHERE":
        return [(collider_matrix(obj, item), sphere_lines(item.collider_radius))]
    if kind == "CAPSULE":
        return [(collider_matrix(obj, item), capsule_lines(item.collider_radius, item.collider_height))]
    if kind == "CYLINDER":
        return [(collider_matrix(obj, item), cylinder_lines(item.collider_radius, item.collider_height))]
    if kind == "CONE":
        return [(collider_matrix(obj, item), cone_shape_lines(item.collider_radius, item.collider_height))]
    return [(matrix, mesh_lines(source, kind, limit)) for source, matrix in collider_sources(obj, children, item)]


def collider_color(item):
    if item.collider_sensor:
        return SENSOR_COLOR
    return COLLISION_ONLY_COLOR if item.collider_collision_only else COLLIDER_COLOR


def volume_lines(obj, item):
    found = [(cuboid_lines(item.volume_size), 2.0)]
    if item.component_type != "FOG_VOLUME" and 0 < item.volume_falloff < 1:
        found.append((cuboid_lines([value * (1 - item.volume_falloff) for value in item.volume_size]), 1.0))
    if item.component_type == "IRRADIANCE_VOLUME":
        found.append((voxel_lines(item.volume_size, texture_check(obj, item).voxels), 1.0))
    return found


def light_lines(obj):
    light = light_of(obj)
    if light is None or light.type == "SUN":
        return []
    location, rotation, _scale = obj.matrix_world.decompose()
    if light.type == "SPOT":
        return [(Matrix.Translation(location) @ rotation.to_matrix().to_4x4(), cone_lines(light_range(light), light.spot_size / 2))]
    return [(Matrix.Translation(location), sphere_lines(light_range(light), segments=48))]


def light_label(obj, item):
    light = light_of(obj)
    if light is None:
        return "Light · not a light, so not exported"
    parts = ["Light", LIGHT_LABELS[light.type], light_amount(item.light_intensity if item.light_use_intensity else light_intensity(light, obj), light_unit(light))]
    if light.use_shadow and light.type != "AREA":
        parts.append("shadows")
    if light.type != "SUN":
        parts.append(f"range {light_range(light):g}m")
    return " · ".join(parts)


def navigation_lines(obj, item, limit, children):
    sources = mesh_sources(obj, children, "NAVIGATION")
    if item.navigation_kind == "OBSTACLE":
        return [(matrix, box_lines(*_bounds([Vector(corner) for corner in source.bound_box]))) for source, matrix in sources]
    return [(matrix, walkable_lines(source, matrix, limit)) for source, matrix in sources]


def walkable_lines(obj, matrix, limit):
    if exceeds_edge_limit(obj, limit):
        return box_lines(*_bounds([Vector(corner) for corner in obj.bound_box]))
    return _mesh_preview(obj, "WALKABLE", limit, matrix.to_3x3().inverted_safe().transposed())[0]


def mesh_lines(obj, kind, limit):
    return _mesh_preview(obj, kind, limit)[0]


def mesh_parts(obj, kind, limit):
    return _mesh_preview(obj, kind, limit)[1]


def exceeds_edge_limit(obj, limit):
    return obj.type == "MESH" and len(_exported_mesh(obj).edges) > limit


def _applies_modifiers():
    return export_settings(bpy.context.scene).apply_modifiers


def _exported_mesh(obj):
    if _applies_modifiers() and changes_mesh(obj):
        return obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    return obj.data


def _mesh_preview(obj, kind, limit, normals=None):
    if obj.type == "MESH":
        mesh = _exported_mesh(obj)
        pointer = (obj if mesh != obj.data else mesh).as_pointer()
        return _cached_preview(mesh, kind, limit, pointer if normals is None else (pointer, obj.as_pointer()), normals)
    source = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()) if _applies_modifiers() else obj
    try:
        mesh = source.to_mesh()
    except RuntimeError:
        return box_lines(*_bounds([Vector(corner) for corner in obj.bound_box])), 1
    try:
        return _cached_preview(mesh, kind, limit, obj.as_pointer(), normals) if mesh is not None else ([], 0)
    finally:
        source.to_mesh_clear()


def _cached_preview(mesh, kind, limit, pointer, normals=None):
    key = (kind, pointer)
    fingerprint = (_fingerprint(mesh), limit if kind == "TRIMESH" else None, None if normals is None else tuple(round(value, 4) for row in normals for value in row))
    cached = MESH_PREVIEWS.pop(key, None)
    if cached is not None and cached[0] == fingerprint:
        MESH_PREVIEWS[key] = cached
        return cached[1]
    if kind == "WALKABLE":
        preview = (_walkable_lines(mesh, normals), 1)
    else:
        preview = hull_lines(mesh) if kind == "CONVEX" else (_triangle_mesh_lines(mesh, limit), 1)
    if len(MESH_PREVIEWS) >= MESH_PREVIEW_LIMIT:
        MESH_PREVIEWS.pop(next(iter(MESH_PREVIEWS)))
    MESH_PREVIEWS[key] = (fingerprint, preview)
    return preview


def _fingerprint(mesh):
    positions = array("f", bytes(len(mesh.vertices) * 12))
    mesh.attributes["position"].data.foreach_get("vector", positions)
    attribute = mesh.attributes.get("material_index")
    materials = array("i", bytes(len(mesh.polygons) * 4))
    if attribute is not None:
        attribute.data.foreach_get("value", materials)
    return (len(mesh.vertices), len(mesh.edges), len(mesh.polygons), len(mesh.loops), hash(positions.tobytes()), hash(materials.tobytes()))


def hull_lines(mesh):
    groups = {}
    for polygon in mesh.polygons:
        groups.setdefault(polygon.material_index, set()).update(polygon.vertices)
    vertices = mesh.vertices
    lines = []
    for indices in groups.values():
        lines.extend(_hull_lines([vertices[index].co for index in indices]))
    return lines, len(groups)


def _hull_lines(points):
    hull = bmesh.new()
    try:
        for point in points:
            hull.verts.new(point)
        result = bmesh.ops.convex_hull(hull, input=list(hull.verts))
        kept = {element for element in result["geom"] if isinstance(element, bmesh.types.BMVert)}
        bmesh.ops.delete(hull, geom=[vertex for vertex in hull.verts if vertex not in kept], context="VERTS")
        bmesh.ops.dissolve_limit(hull, angle_limit=radians(0.1), verts=list(hull.verts), edges=list(hull.edges))
        return [(tuple(edge.verts[0].co), tuple(edge.verts[1].co)) for edge in hull.edges]
    finally:
        hull.free()


def _triangle_mesh_lines(mesh, limit):
    vertices = mesh.vertices
    if len(mesh.edges) > limit:
        return box_lines(*_bounds([vertex.co for vertex in vertices]))
    edges = {key for polygon in mesh.polygons for key in polygon.edge_keys}
    return [(tuple(vertices[start].co), tuple(vertices[end].co)) for start, end in edges]


def _walkable_lines(mesh, normals):
    threshold = cos(WALKABLE_SLOPE)
    edges = set()
    for polygon in mesh.polygons:
        normal = normals @ polygon.normal
        if normal.length > 0 and normal.normalized().z > threshold:
            edges.update(polygon.edge_keys)
    vertices = mesh.vertices
    return [(tuple(vertices[start].co), tuple(vertices[end].co)) for start, end in edges]


def _bounds(points):
    if not points:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    return tuple(min(point[axis] for point in points) for axis in range(3)), tuple(max(point[axis] for point in points) for axis in range(3))


def scene_bounds(item):
    if not item.scene_file.strip():
        return None
    try:
        scenes = read_scenes(file_path(item.scene_file))
    except (OSError, ValueError):
        return None
    if item.scene_index >= len(scenes) or scenes[item.scene_index] is None:
        return None
    minimum, maximum = scenes[item.scene_index]
    return (minimum[0], -maximum[2], minimum[1]), (maximum[0], -minimum[2], maximum[1])


def _previews_shown(context):
    space = context.space_data
    return panel_expanded() and context.region_data is not None and (space is None or space.overlay.show_overlays)


def _hierarchy(context, objects):
    colliders = [component_of(obj, "COLLIDER") for obj in objects]
    meshes = any(collider is not None and collider.collider_shape in MESH_SHAPES for collider in colliders) or any(component_of(obj, "NAVIGATION") is not None for obj in objects)
    return children_map(context.scene.objects) if meshes else {}


def object_batches(obj, settings, children):
    batches = []
    collider = component_of(obj, "COLLIDER")
    if collider and settings.colliders:
        batches.extend((matrix, lines, collider_color(collider), 2.0) for matrix, lines in collider_lines(obj, collider, settings.max_mesh_edges, children))
    visibility = component_of(obj, "VISIBILITY_RANGE")
    if visibility and settings.visibility_ranges:
        inverse = obj.matrix_world.to_3x3().inverted_safe()
        offset = Vector((0, 0, 0))
        if visibility.use_aabb and obj.type == "MESH":
            offset = sum((Vector(corner) for corner in obj.bound_box), Vector()) / 8
        radii = ((visibility.fade_in_start, LOD_IN_COLOR, 1.1), (visibility.fade_in_end, LOD_IN_COLOR, 1.9), (visibility.fade_out_start, LOD_OUT_COLOR, 1.9), (visibility.fade_out_end, LOD_OUT_COLOR, 1.1))
        for radius, color, width in radii:
            if radius < 0.01:
                continue
            local_lines = [(tuple(offset + inverse @ Vector(start)), tuple(offset + inverse @ Vector(end))) for start, end in sphere_lines(radius, segments=48)]
            batches.append((obj.matrix_world, local_lines, color, width))
    audio = component_of(obj, "AUDIO_PLAYER")
    if audio and audio.audio_spatial and settings.audio_ranges:
        center = Matrix.Translation(obj.matrix_world.translation)
        for radius, color, width in ((audio.audio_distance, AUDIO_COLOR, 1.9), (audio.audio_distance * AUDIO_QUIET_FACTOR, AUDIO_QUIET_COLOR, 1.1)):
            batches.append((center, sphere_lines(radius, segments=48), color, width))
    light = component_of(obj, "LIGHT")
    if light and settings.lights:
        batches.extend((matrix, lines, LIGHT_COLOR, 1.5) for matrix, lines in light_lines(obj))
    navigation = component_of(obj, "NAVIGATION")
    if navigation and settings.navigation and navigation.navigation_kind in NAVIGATION_COLORS:
        batches.extend((matrix, lines, NAVIGATION_COLORS[navigation.navigation_kind], 1.5) for matrix, lines in navigation_lines(obj, navigation, settings.max_mesh_edges, children))
    body = component_of(obj, "RIGID_BODY")
    if body and settings.velocities:
        batches.extend(velocity_batches(obj, body))
    reference = component_of(obj, "SCENE_REFERENCE")
    bounds = scene_bounds(reference) if reference and settings.scene_references else None
    if bounds:
        batches.append((obj.matrix_world, box_lines(*bounds), SCENE_COLOR, 1.5))
    if settings.volumes:
        for item in components_for(obj):
            if item.component_type in VOLUME_COLORS:
                batches.extend((obj.matrix_world, lines, VOLUME_COLORS[item.component_type], width) for lines, width in volume_lines(obj, item))
    return batches


def _matrix_key(matrix):
    return tuple(map(tuple, matrix))


def _settings_key(settings):
    return (settings.colliders, settings.joints, settings.velocities, settings.visibility_ranges, settings.audio_ranges, settings.scene_references, settings.volumes, settings.lights, settings.navigation, settings.max_mesh_edges)


def _native_key(obj):
    natives = native_components(obj)
    return serialize_items(natives) if natives else None


def _stored_key(obj):
    stored = obj.get(EXTRAS_KEY)
    native = _native_key(obj)
    if not isinstance(stored, str) and native is None:
        return None
    return (stored if isinstance(stored, str) else None, native)


def _object_key(obj, settings, shown, children):
    stored = _stored_key(obj)
    if stored is None:
        return None
    key = [shown, _matrix_key(obj.matrix_world), stored]
    for item in components_for(obj):
        kind = item.component_type
        if kind == "COLLIDER" and settings.colliders and item.collider_shape in MESH_SHAPES:
            key.append(tuple((_matrix_key(matrix), lines) for matrix, lines in collider_lines(obj, item, settings.max_mesh_edges, children)))
        elif kind == "NAVIGATION" and settings.navigation:
            key.append(tuple((_matrix_key(matrix), lines) for matrix, lines in navigation_lines(obj, item, settings.max_mesh_edges, children)))
        elif kind == "VISIBILITY_RANGE" and settings.visibility_ranges and item.use_aabb:
            key.append(tuple(tuple(corner) for corner in obj.bound_box))
        elif kind == "RIGID_BODY" and settings.velocities:
            key.append(tuple(obj.dimensions))
        elif kind == "LIGHT" and settings.lights:
            light = light_of(obj)
            key.append((light.type, light_range(light), getattr(light, "spot_size", None)) if light is not None else None)
        elif kind == "SCENE_REFERENCE" and settings.scene_references:
            key.append(scene_bounds(item))
        elif kind == "IRRADIANCE_VOLUME" and settings.volumes:
            key.append(texture_check(obj, item).voxels)
    return tuple(key)


def _joint_key(obj):
    stored = _stored_key(obj)
    if stored is None:
        return None
    joint = component_of(obj, "JOINT")
    bodies = tuple((body.as_pointer(), tuple(body.matrix_world.translation)) if body is not None else None for body in (joint.joint_body1, joint.joint_body2))
    return (_matrix_key(obj.matrix_world), stored, bodies)


def _cached_entry(key, signature, build):
    entry = PREVIEW_CACHE.pop(key, None)
    if entry is None or signature is None or entry["signature"] != signature:
        entry = {"signature": signature, "batches": build(), "drawables": None}
    if len(PREVIEW_CACHE) >= PREVIEW_LIMIT:
        PREVIEW_CACHE.pop(next(iter(PREVIEW_CACHE)))
    PREVIEW_CACHE[key] = entry
    return entry


def preview_entries(context, settings):
    objects = preview_objects(context, settings)
    children = _hierarchy(context, objects)
    shown = _settings_key(settings)
    entries = [_cached_entry(("OBJECT", obj.as_pointer()), _object_key(obj, settings, shown, children), lambda obj=obj: object_batches(obj, settings, children)) for obj in objects]
    if settings.joints:
        entries.extend(_cached_entry(("JOINT", obj.as_pointer()), _joint_key(obj), lambda obj=obj: joint_batches(obj, component_of(obj, "JOINT"))) for obj in joint_objects(context, settings, objects))
    return entries


def preview_batches(context, settings):
    return [batch for entry in preview_entries(context, settings) for batch in entry["batches"]]


def _drawables(shader, batches):
    merged = {}
    for matrix, lines, color, width in batches:
        points = merged.setdefault((tuple(color), width), [])
        if matrix == IDENTITY:
            points.extend(point for line in lines for point in line)
        else:
            points.extend(tuple(matrix @ Vector(point)) for line in lines for point in line)
    return [(batch_for_shader(shader, "LINES", {"pos": points}), color, width) for (color, width), points in merged.items() if points]


def draw_entries(shader, entries):
    shader.bind()
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    for entry in entries:
        if entry["drawables"] is None:
            entry["drawables"] = _drawables(shader, entry["batches"])
        for batch, color, width in entry["drawables"]:
            shader.uniform_float("lineWidth", width)
            shader.uniform_float("color", color)
            batch.draw(shader)


def _draw_geometry():
    context = bpy.context
    if not context.scene or not hasattr(context.scene, "bevy_component_previews"):
        return
    settings = context.scene.bevy_component_previews
    if not settings.enabled or not _previews_shown(context):
        return
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE" if settings.xray else "LESS_EQUAL")
    try:
        draw_entries(gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR"), preview_entries(context, settings))
    finally:
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")


def _label_lines(obj, settings, children):
    descriptions = []
    collider = component_of(obj, "COLLIDER")
    if collider and settings.colliders:
        kind = collider.collider_shape.title()
        if collider.collider_shape == "CUBOID":
            details = " × ".join(f"{size:g}" for size in collider.collider_size)
        elif collider.collider_shape == "SPHERE":
            details = f"r={collider.collider_radius:g}m"
        elif collider.collider_shape == "CAPSULE":
            details = f"r={collider.collider_radius:g}, cylinder={collider.collider_height:g}m"
        elif collider.collider_shape in {"CYLINDER", "CONE"}:
            details = f"r={collider.collider_radius:g}, height={collider.collider_height:g}m"
        else:
            sources = [source for source, _matrix in collider_sources(obj, children, collider)]
            if not sources:
                details = "no mesh, so no collider"
            elif collider.collider_shape == "CONVEX":
                count = sum(mesh_parts(source, "CONVEX", settings.max_mesh_edges) for source in sources)
                details = "1 hull" if count == 1 else f"{count} hulls, one per mesh part"
            elif any(exceeds_edge_limit(source, settings.max_mesh_edges) for source in sources):
                details = "AABB preview (mesh edge limit)"
            else:
                details = "mesh edges"
        parts = ["Collider", kind, details]
        if collider.collider_shape in PRIMITIVE_SHAPES and any(abs(value) > 1e-6 for value in collider.collider_offset):
            parts.append(f"offset {', '.join(f'{round(value, 3):g}' for value in collider.collider_offset)}")
        if collider.collider_events:
            parts.append("events")
        if collider.collider_collision_only:
            parts.append("collision only")
        descriptions.append(" · ".join(parts))
    body = component_of(obj, "RIGID_BODY")
    if body and settings.velocities and body.rigid_body_kind != "STATIC":
        linear, angular = (Vector(vector).length for vector in initial_velocities(body))
        speeds = [f"{speed:.3g} {unit}" for speed, unit in ((linear, "m/s"), (degrees(angular), "°/s")) if speed > 1e-6]
        if speeds:
            descriptions.append(" · ".join(["Velocity", *speeds]))
    visibility = component_of(obj, "VISIBILITY_RANGE")
    if visibility and settings.visibility_ranges:
        descriptions.append(f"LOD · in {visibility.fade_in_start:g}–{visibility.fade_in_end:g}m · out {visibility.fade_out_start:g}–{visibility.fade_out_end:g}m")
    shadows = component_of(obj, "SHADOWS")
    if shadows:
        descriptions.append(f"Shadows · {SHADOW_LABELS[(shadows.shadows_cast, shadows.shadows_receive)]}")
    audio = component_of(obj, "AUDIO_PLAYER")
    if audio and settings.audio_ranges:
        details = [PurePosixPath(audio.audio_path.strip()).name or "no sound"]
        if audio.audio_loop:
            details.append("loop")
        if not audio.audio_autoplay:
            details.append("paused")
        if audio.audio_spatial:
            details.append(f"full volume within {round(audio.audio_distance, 2):g}m, 1% at {round(audio.audio_distance * AUDIO_QUIET_FACTOR, 2):g}m")
        else:
            details.append("same volume everywhere")
        descriptions.append(f"Audio · {' · '.join(details)}")
    reference = component_of(obj, "SCENE_REFERENCE")
    if reference and settings.scene_references:
        name = file_path(reference.scene_file).name if reference.scene_file.strip() else "no file"
        descriptions.append(f"Scene · {name}#Scene{reference.scene_index}")
    animation = component_of(obj, "ANIMATION")
    if animation:
        descriptions.append(f"Animation · {animation.animation_clip or 'no clip'} · {'loop' if animation.animation_loop else 'once'} · {animation.animation_speed:g}×")
    if settings.volumes:
        descriptions.extend(_volume_label(obj, item) for item in components_for(obj) if item.component_type in VOLUME_NAMES)
    light = component_of(obj, "LIGHT")
    if light and settings.lights:
        descriptions.append(light_label(obj, light))
    lightmap = component_of(obj, "LIGHTMAP")
    if lightmap and obj.type == "MESH":
        descriptions.append(_lightmap_label(obj, lightmap))
    navigation = component_of(obj, "NAVIGATION")
    if navigation and settings.navigation:
        descriptions.append(_navigation_label(navigation))
    return _custom_names(obj) + descriptions + _joint_label(obj, settings)


def _lightmap_label(obj, item):
    if not item.probe_file.strip():
        return "Lightmap · not baked"
    check = texture_check(obj, item)
    return f"Lightmap · {check.message.removesuffix(' lightmap')}" if check.level is None else "Lightmap · file problem, see its card"


def _navigation_label(item):
    parts = ["Navigation", NAVIGATION_LABELS[item.navigation_kind]]
    if item.navigation_kind == "WALKABLE" and round(item.navigation_cost, 4) != 1:
        parts.append(f"cost {item.navigation_cost:.3g}")
    return " · ".join(parts)


def _joint_label(obj, settings):
    joint = component_of(obj, "JOINT")
    if joint is None or not settings.joints:
        return []
    names = [body.name if body is not None else "World" for body in (joint.joint_body1, joint.joint_body2)]
    return [f"Joint · {JOINT_LABELS[joint.joint_kind]} · {names[0]} – {names[1]}"]


def _volume_label(obj, item):
    size = " × ".join(f"{value:g}" for value in item.volume_size)
    if item.component_type == "FOG_VOLUME":
        return f"Fog Volume · {size} · density {item.fog_density:g}"
    check = texture_check(obj, item)
    details = check.message if check.level is None else MISSING_TEXTURES[item.component_type] if not item.probe_file.strip() else "file problem, see its panel"
    return f"{VOLUME_NAMES[item.component_type]} · {size} · {details}"


def _custom_names(obj):
    return [short_name(item.custom_type) for item in components_for(obj) if item.component_type == "CUSTOM" and item.custom_type.strip()]


def label_rows(context, settings):
    objects = preview_objects(context, settings)
    children = _hierarchy(context, objects)
    selected = set(context.selected_objects)
    listed = set(objects)
    rows = []
    for obj in objects:
        if obj not in selected:
            rows.append((obj, [" · ".join([obj.name, *_custom_names(obj)])], False))
            continue
        details = _label_lines(obj, settings, children)
        if details:
            rows.append((obj, [obj.name, *details], True))
    if settings.joints:
        rows.extend((obj, [obj.name, *_joint_label(obj, settings)], True) for obj in joint_objects(context, settings, objects) if obj not in listed)
    return sorted(rows, key=lambda row: not row[2])


def _overlaps(first, second):
    return first[0] < second[2] and second[0] < first[2] and first[1] < second[3] and second[1] < first[3]


def _draw_labels():
    context = bpy.context
    if not context.scene or not hasattr(context.scene, "bevy_component_previews"):
        return
    settings = context.scene.bevy_component_previews
    if not settings.enabled or not settings.labels or not _previews_shown(context):
        return
    region = context.region
    scale = context.preferences.system.ui_scale
    spacing = LABEL_SPACING * scale
    font_id = 0
    blf.size(font_id, LABEL_SIZE * scale)
    taken = []
    for obj, lines, details in label_rows(context, settings):
        point = view3d_utils.location_3d_to_region_2d(region, context.region_data, obj.matrix_world.translation)
        if point is None:
            continue
        left = point.x + LABEL_OFFSET[0] * scale
        top = point.y + LABEL_OFFSET[1] * scale
        box = (left, top - (len(lines) - 1) * spacing - LABEL_DESCENT * scale, left + max(blf.dimensions(font_id, line)[0] for line in lines), top + LABEL_SIZE * scale)
        if not details and any(_overlaps(box, other) for other in taken):
            continue
        taken.append(box)
        blf.color(font_id, *(LABEL_COLOR if details else NAME_COLOR))
        for index, line in enumerate(lines):
            blf.position(font_id, left, top - index * spacing, 0)
            blf.draw(font_id, line)


def register_draw_handlers():
    global DRAW_3D, DRAW_2D
    if DRAW_3D is None:
        DRAW_3D = bpy.types.SpaceView3D.draw_handler_add(_draw_geometry, (), "WINDOW", "POST_VIEW")
    if DRAW_2D is None:
        DRAW_2D = bpy.types.SpaceView3D.draw_handler_add(_draw_labels, (), "WINDOW", "POST_PIXEL")


def unregister_draw_handlers():
    global DRAW_3D, DRAW_2D
    if DRAW_3D is not None:
        bpy.types.SpaceView3D.draw_handler_remove(DRAW_3D, "WINDOW")
        DRAW_3D = None
    if DRAW_2D is not None:
        bpy.types.SpaceView3D.draw_handler_remove(DRAW_2D, "WINDOW")
        DRAW_2D = None
    redraw_viewports()
