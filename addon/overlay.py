import blf
import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .geometry import capsule_lines, cuboid_lines, spawn_marker_lines, sphere_lines
from .system import component_of, components_for, redraw_viewports

DRAW_3D = None
DRAW_2D = None

COLLIDER_COLOR = (0.22, 0.96, 0.55, 0.90)
SENSOR_COLOR = (0.96, 0.60, 0.20, 0.90)
LOD_IN_COLOR = (0.20, 0.72, 1.0, 0.55)
LOD_OUT_COLOR = (1.0, 0.62, 0.25, 0.55)
SPAWN_COLOR = (0.90, 0.35, 1.0, 0.95)


def preview_objects(context, settings):
    if not context.scene or not context.view_layer:
        return []
    objects = context.selected_objects if settings.scope == "SELECTED" else context.scene.objects
    return [obj for obj in objects if obj.visible_get(view_layer=context.view_layer) and len(components_for(obj))]


def mesh_preview_lines(obj, max_edges):
    if obj.type != "MESH":
        return cuboid_lines((1, 1, 1))
    mesh = obj.data
    if len(mesh.edges) > max_edges:
        return _mesh_bounds_lines(obj)
    vertices = mesh.vertices
    return [(tuple(vertices[edge.vertices[0]].co), tuple(vertices[edge.vertices[1]].co)) for edge in mesh.edges]


def _mesh_bounds_lines(obj):
    bounds = [tuple(corner) for corner in obj.bound_box]
    edges = ((0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3), (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7))
    return [(bounds[start], bounds[end]) for start, end in edges]


def collider_lines(obj, item, limit):
    kind = item.collider_shape
    if kind == "CUBOID":
        return cuboid_lines(item.collider_size)
    if kind == "SPHERE":
        return sphere_lines(item.collider_radius)
    if kind == "CAPSULE":
        return capsule_lines(item.collider_radius, item.collider_height)
    if kind == "CONVEX":
        return _mesh_bounds_lines(obj) if obj.type == "MESH" else cuboid_lines((1, 1, 1))
    return mesh_preview_lines(obj, limit)


def _draw_lines(shader, obj, lines, color, width=1.5):
    if not lines:
        return
    matrix = obj.matrix_world
    points = [tuple(matrix @ Vector(point)) for start, end in lines for point in (start, end)]
    batch = batch_for_shader(shader, "LINES", {"pos": points})
    shader.bind()
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    batch.draw(shader)


def _overlays_shown(context):
    space = context.space_data
    return space is None or space.overlay.show_overlays


def preview_batches(context, settings):
    batches = []
    for obj in preview_objects(context, settings):
        collider = component_of(obj, "COLLIDER")
        if collider and settings.colliders:
            color = SENSOR_COLOR if collider.collider_sensor else COLLIDER_COLOR
            batches.append((obj, collider_lines(obj, collider, settings.max_mesh_edges), color, 2.0))

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
                batches.append((obj, local_lines, color, width))

        spawn = component_of(obj, "SPAWN_POINT")
        if spawn and settings.spawn_points:
            batches.append((obj, spawn_marker_lines(), SPAWN_COLOR, 2.4))
    return batches


def _draw_geometry():
    context = bpy.context
    if not context.scene or not hasattr(context.scene, "bevy_component_previews"):
        return
    settings = context.scene.bevy_component_previews
    if not settings.enabled or context.region_data is None or not _overlays_shown(context):
        return
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE" if settings.xray else "LESS_EQUAL")
    try:
        for obj, lines, color, width in preview_batches(context, settings):
            _draw_lines(shader, obj, lines, color, width=width)
    finally:
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")


def _label_lines(obj, settings):
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
        elif collider.collider_shape == "CONVEX":
            details = "bounds preview (not exact hull)"
        elif obj.type == "MESH" and len(obj.data.edges) > settings.max_mesh_edges:
            details = "AABB preview (mesh edge limit)"
        else:
            details = "mesh edges"
        descriptions.append(f"Collider · {kind} · {details}")
    visibility = component_of(obj, "VISIBILITY_RANGE")
    if visibility and settings.visibility_ranges:
        descriptions.append(f"LOD · in {visibility.fade_in_start:g}–{visibility.fade_in_end:g}m · out {visibility.fade_out_start:g}–{visibility.fade_out_end:g}m")
    spawn = component_of(obj, "SPAWN_POINT")
    if spawn and settings.spawn_points:
        descriptions.append(f"Spawn · {spawn.spawn_tag}")
    return descriptions


def _draw_labels():
    context = bpy.context
    if not context.scene or not hasattr(context.scene, "bevy_component_previews"):
        return
    settings = context.scene.bevy_component_previews
    if not settings.enabled or not settings.labels or context.region_data is None or not _overlays_shown(context):
        return
    region = context.region
    font_id = 0
    blf.size(font_id, 12)
    blf.color(font_id, 0.9, 1.0, 0.95, 0.98)
    for obj in preview_objects(context, settings):
        descriptions = _label_lines(obj, settings)
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
    redraw_viewports()


def unregister_draw_handlers():
    global DRAW_3D, DRAW_2D
    if DRAW_3D is not None:
        bpy.types.SpaceView3D.draw_handler_remove(DRAW_3D, "WINDOW")
        DRAW_3D = None
    if DRAW_2D is not None:
        bpy.types.SpaceView3D.draw_handler_remove(DRAW_2D, "WINDOW")
        DRAW_2D = None
    redraw_viewports()
