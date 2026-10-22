from array import array
from math import radians

import blf
import bmesh
import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .geometry import box_lines, capsule_lines, cuboid_lines, sphere_lines
from .system import children_map, component_of, components_for, mesh_sources, panel_expanded, redraw_viewports

DRAW_3D = None
DRAW_2D = None
MESH_PREVIEWS = {}
MESH_PREVIEW_LIMIT = 1024

COLLIDER_COLOR = (0.22, 0.96, 0.55, 0.90)
SENSOR_COLOR = (0.96, 0.60, 0.20, 0.90)
LOD_IN_COLOR = (0.20, 0.72, 1.0, 0.55)
LOD_OUT_COLOR = (1.0, 0.62, 0.25, 0.55)


def preview_objects(context, settings):
    if not context.scene or not context.view_layer:
        return []
    objects = context.selected_objects if settings.scope == "SELECTED" else context.scene.objects
    return [obj for obj in objects if obj.visible_get(view_layer=context.view_layer) and len(components_for(obj))]


def collider_lines(obj, item, limit, children):
    kind = item.collider_shape
    if kind == "CUBOID":
        return [(obj.matrix_world, cuboid_lines(item.collider_size))]
    if kind == "SPHERE":
        return [(obj.matrix_world, sphere_lines(item.collider_radius))]
    if kind == "CAPSULE":
        return [(obj.matrix_world, capsule_lines(item.collider_radius, item.collider_height))]
    return [(matrix, mesh_lines(source, kind, limit)) for source, matrix in mesh_sources(obj, children, "COLLIDER")]


def mesh_lines(obj, kind, limit):
    return _mesh_preview(obj, kind, limit)[0]


def mesh_parts(obj, kind, limit):
    return _mesh_preview(obj, kind, limit)[1]


def exceeds_edge_limit(obj, limit):
    return obj.type == "MESH" and len(obj.data.edges) > limit


def _mesh_preview(obj, kind, limit):
    if obj.type == "MESH":
        return _cached_preview(obj.data, kind, limit, obj.data.as_pointer())
    try:
        mesh = obj.to_mesh()
    except RuntimeError:
        return box_lines(*_bounds([Vector(corner) for corner in obj.bound_box])), 1
    try:
        return _cached_preview(mesh, kind, limit, obj.as_pointer()) if mesh is not None else ([], 0)
    finally:
        obj.to_mesh_clear()


def _cached_preview(mesh, kind, limit, pointer):
    key = (kind, pointer)
    fingerprint = (_fingerprint(mesh), limit if kind == "TRIMESH" else None)
    cached = MESH_PREVIEWS.pop(key, None)
    if cached is not None and cached[0] == fingerprint:
        MESH_PREVIEWS[key] = cached
        return cached[1]
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


def _bounds(points):
    if not points:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    return tuple(min(point[axis] for point in points) for axis in range(3)), tuple(max(point[axis] for point in points) for axis in range(3))


def _draw_lines(shader, matrix, lines, color, width=1.5):
    if not lines:
        return
    batch = batch_for_shader(shader, "LINES", {"pos": [point for line in lines for point in line]})
    shader.bind()
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    with gpu.matrix.push_pop():
        gpu.matrix.multiply_matrix(matrix)
        batch.draw(shader)


def _previews_shown(context):
    space = context.space_data
    return panel_expanded() and context.region_data is not None and (space is None or space.overlay.show_overlays)


def _hierarchy(context, objects):
    colliders = [component_of(obj, "COLLIDER") for obj in objects]
    return children_map(context.scene.objects) if any(collider is not None and collider.collider_shape in {"TRIMESH", "CONVEX"} for collider in colliders) else {}


def preview_batches(context, settings):
    batches = []
    objects = preview_objects(context, settings)
    children = _hierarchy(context, objects)
    for obj in objects:
        collider = component_of(obj, "COLLIDER")
        if collider and settings.colliders:
            color = SENSOR_COLOR if collider.collider_sensor else COLLIDER_COLOR
            batches.extend((matrix, lines, color, 2.0) for matrix, lines in collider_lines(obj, collider, settings.max_mesh_edges, children))

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
    return batches


def _draw_geometry():
    context = bpy.context
    if not context.scene or not hasattr(context.scene, "bevy_component_previews"):
        return
    settings = context.scene.bevy_component_previews
    if not settings.enabled or not _previews_shown(context):
        return
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE" if settings.xray else "LESS_EQUAL")
    try:
        for matrix, lines, color, width in preview_batches(context, settings):
            _draw_lines(shader, matrix, lines, color, width=width)
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
        else:
            sources = [source for source, _matrix in mesh_sources(obj, children, "COLLIDER")]
            if not sources:
                details = "no mesh, so no collider"
            elif collider.collider_shape == "CONVEX":
                count = sum(mesh_parts(source, "CONVEX", settings.max_mesh_edges) for source in sources)
                details = "1 hull" if count == 1 else f"{count} hulls, one per mesh part"
            elif any(exceeds_edge_limit(source, settings.max_mesh_edges) for source in sources):
                details = "AABB preview (mesh edge limit)"
            else:
                details = "mesh edges"
        descriptions.append(f"Collider · {kind} · {details}")
    visibility = component_of(obj, "VISIBILITY_RANGE")
    if visibility and settings.visibility_ranges:
        descriptions.append(f"LOD · in {visibility.fade_in_start:g}–{visibility.fade_in_end:g}m · out {visibility.fade_out_start:g}–{visibility.fade_out_end:g}m")
    return descriptions


def _draw_labels():
    context = bpy.context
    if not context.scene or not hasattr(context.scene, "bevy_component_previews"):
        return
    settings = context.scene.bevy_component_previews
    if not settings.enabled or not settings.labels or not _previews_shown(context):
        return
    region = context.region
    font_id = 0
    blf.size(font_id, 12)
    blf.color(font_id, 0.9, 1.0, 0.95, 0.98)
    objects = preview_objects(context, settings)
    children = _hierarchy(context, objects)
    for obj in objects:
        descriptions = _label_lines(obj, settings, children)
        if not descriptions:
            continue
        point = view3d_utils.location_3d_to_region_2d(region, context.region_data, obj.matrix_world.translation)
        if point is None:
            continue
        blf.position(font_id, point.x + 14, point.y + 16, 0)
        blf.draw(font_id, obj.name)
        for index, label in enumerate(descriptions):
            blf.position(font_id, point.x + 14, point.y - (index + 1) * 16 + 16, 0)
            blf.draw(font_id, label)


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
