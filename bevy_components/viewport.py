"""Non-exporting viewport wireframes, distance guides, labels, and drag handles."""

import bpy
import blf
import gpu
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from .geometry import capsule_lines, cuboid_lines, spawn_marker_lines, sphere_lines


DRAW_3D = None
DRAW_2D = None

COLLIDER_COLOR = (0.22, 0.96, 0.55, 0.90)
SENSOR_COLOR = (0.96, 0.60, 0.20, 0.90)
LOD_IN_COLOR = (0.20, 0.72, 1.0, 0.55)
LOD_OUT_COLOR = (1.0, 0.62, 0.25, 0.55)
SPAWN_COLOR = (0.90, 0.35, 1.0, 0.95)


def redraw_viewports(_self=None, _context=None):
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def components_for(obj):
    if not hasattr(obj, "bevy_component_data"):
        return []
    return obj.bevy_component_data.components


def component_of(obj, kind):
    for item in components_for(obj):
        if item.component_type == kind:
            return item
    return None


class BEVY_PG_viewport_settings(bpy.types.PropertyGroup):
    enabled: BoolProperty(name="Show Bevy Previews", description="Draw Bevy component overlays in the 3D Viewport; never exported", default=True, update=redraw_viewports)
    scope: EnumProperty(name="Draw On", items=[
        ("SELECTED", "Selected", "Draw only selected objects"),
        ("ALL", "All Visible", "Draw every visible object with Bevy components"),
    ], default="SELECTED", update=redraw_viewports)
    colliders: BoolProperty(name="Colliders", default=True, update=redraw_viewports)
    visibility_ranges: BoolProperty(name="Visibility Ranges", default=True, update=redraw_viewports)
    spawn_points: BoolProperty(name="Spawn Points", default=True, update=redraw_viewports)
    labels: BoolProperty(name="Labels", default=True, update=redraw_viewports)
    xray: BoolProperty(name="See Through Meshes", default=False, update=redraw_viewports)
    edit_handles: BoolProperty(name="Edit Collider in Viewport", description="Drag the colored gizmo arrows to change primitive collider dimensions", default=True, update=redraw_viewports)
    max_mesh_edges: IntProperty(name="Max Mesh Edges", description="Limits the wireframe preview cost per triangle-mesh collider", default=2000, min=64, max=20000, update=redraw_viewports)


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
    verts = mesh.vertices
    return [(tuple(verts[edge.vertices[0]].co), tuple(verts[edge.vertices[1]].co)) for edge in mesh.edges]


def _mesh_bounds_lines(obj):
    # Object.bound_box is Blender-local, unlike Bevy collider primitive dimensions.
    bounds = [tuple(v) for v in obj.bound_box]
    edges = ((0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3),
             (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7))
    return [(bounds[a], bounds[b]) for a, b in edges]


def collider_lines(obj, item, limit):
    kind = item.collider_shape
    if kind == "CUBOID":
        return cuboid_lines(item.collider_size)
    if kind == "SPHERE":
        return sphere_lines(item.collider_radius)
    if kind == "CAPSULE":
        return capsule_lines(item.collider_radius, item.collider_height)
    if kind == "CONVEX":
        # A bounding box is a deliberately conservative preview. Avian computes the hull.
        return _mesh_bounds_lines(obj) if obj.type == "MESH" else cuboid_lines((1, 1, 1))
    return mesh_preview_lines(obj, limit)


def _draw_lines(shader, obj, lines, color, width=1.5):
    if not lines:
        return
    matrix = obj.matrix_world
    points = [tuple(matrix @ Vector(p)) for a, b in lines for p in (a, b)]
    batch = batch_for_shader(shader, "LINES", {"pos": points})
    shader.bind()
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_geometry():
    context = bpy.context
    if not context.scene or not hasattr(context.scene, "bevy_component_previews"):
        return
    settings = context.scene.bevy_component_previews
    if not settings.enabled or context.region_data is None:
        return
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE" if settings.xray else "LESS_EQUAL")
    try:
        for obj in preview_objects(context, settings):
            collider = component_of(obj, "COLLIDER")
            if collider and settings.colliders:
                color = SENSOR_COLOR if collider.collider_sensor else COLLIDER_COLOR
                _draw_lines(shader, obj, collider_lines(obj, collider, settings.max_mesh_edges), color, width=2.0)

            visibility = component_of(obj, "VISIBILITY_RANGE")
            if visibility and settings.visibility_ranges:
                # These are true 3D distance shells centered at the object's origin,
                # not mesh-scaled collision shapes. Compensate for obj scale.
                inv = obj.matrix_world.to_3x3().inverted_safe()
                offset = Vector((0, 0, 0))
                if visibility.use_aabb and obj.type == "MESH":
                    offset = sum((Vector(v) for v in obj.bound_box), Vector()) / 8
                radii = (
                    (visibility.fade_in_start, LOD_IN_COLOR, 1.1),
                    (visibility.fade_in_end, LOD_IN_COLOR, 1.9),
                    (visibility.fade_out_start, LOD_OUT_COLOR, 1.9),
                    (visibility.fade_out_end, LOD_OUT_COLOR, 1.1),
                )
                for radius, color, width in radii:
                    if radius < 0.01:
                        continue
                    # sphere_lines() is in local coordinates; convert to world-radius
                    # by undoing the object's scaling before applying matrix_world.
                    local_lines = [
                        (tuple(offset + inv @ Vector(a)), tuple(offset + inv @ Vector(b)))
                        for a, b in sphere_lines(radius, segments=48)
                    ]
                    _draw_lines(shader, obj, local_lines, color, width=width)

            spawn = component_of(obj, "SPAWN_POINT")
            if spawn and settings.spawn_points:
                _draw_lines(shader, obj, spawn_marker_lines(), SPAWN_COLOR, width=2.4)
    finally:
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")


def _label_lines(obj, settings):
    descriptions = []
    collider = component_of(obj, "COLLIDER")
    if collider and settings.colliders:
        kind = collider.collider_shape.title()
        if collider.collider_shape == "CUBOID":
            details = " × ".join(f"{x:g}" for x in collider.collider_size)
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
    if not settings.enabled or not settings.labels or context.region_data is None:
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


def _get_handle_value(index):
    obj = bpy.context.object
    item = component_of(obj, "COLLIDER") if obj else None
    if item is None:
        return 0.0
    if item.collider_shape == "CUBOID":
        return float(item.collider_size[index]) * 0.5
    if index == 0 and item.collider_shape in {"SPHERE", "CAPSULE"}:
        return float(item.collider_radius)
    if index == 1 and item.collider_shape == "CAPSULE":
        return float(item.collider_height) * 0.5 + float(item.collider_radius)
    return 0.0


def _set_handle_value(index, value):
    obj = bpy.context.object
    item = component_of(obj, "COLLIDER") if obj else None
    if item is None or obj.library:
        return
    amount = max(0.001, float(value[0] if isinstance(value, (tuple, list)) else value))
    if item.collider_shape == "CUBOID":
        dimensions = list(item.collider_size)
        dimensions[index] = amount * 2
        item.collider_size = dimensions
    elif index == 0 and item.collider_shape in {"SPHERE", "CAPSULE"}:
        item.collider_radius = amount
    elif index == 1 and item.collider_shape == "CAPSULE":
        item.collider_height = max(0.0, (amount - item.collider_radius) * 2)
    redraw_viewports()


class BEVY_GGT_collider_handles(bpy.types.GizmoGroup):
    bl_idname = "BEVY_GGT_collider_handles"
    bl_label = "Bevy Collider Resize Handles"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.library or obj.mode != "OBJECT" or not context.scene:
            return False
        if not hasattr(context.scene, "bevy_component_previews"):
            return False
        settings = context.scene.bevy_component_previews
        collider = component_of(obj, "COLLIDER")
        return (settings.enabled and settings.colliders and settings.edit_handles and
                collider is not None and collider.collider_shape in {"CUBOID", "SPHERE", "CAPSULE"})

    def setup(self, _context):
        colors = ((0.95, 0.26, 0.25), (0.35, 0.95, 0.35), (0.30, 0.55, 1.0))
        self.handles = []
        for index, color in enumerate(colors):
            gizmo = self.gizmos.new("GIZMO_GT_arrow_3d")
            gizmo.draw_style = "BOX"
            gizmo.scale_basis = 0.75
            gizmo.color = color
            gizmo.alpha = 0.82
            gizmo.color_highlight = (1.0, 1.0, 1.0)
            gizmo.alpha_highlight = 1.0
            gizmo.target_set_handler(
                "offset",
                get=lambda idx=index: _get_handle_value(idx),
                set=lambda value, idx=index: _set_handle_value(idx, value),
            )
            self.handles.append(gizmo)
        self.refresh(bpy.context)

    def refresh(self, context):
        obj = context.object
        item = component_of(obj, "COLLIDER") if obj else None
        if item is None:
            return
        # Mapping of Bevy XYZ handles to Blender local X, Z, -Y.
        axes = (Vector((1, 0, 0)), Vector((0, 0, 1)), Vector((0, -1, 0)))
        if item.collider_shape == "CUBOID":
            shown = (True, True, True)
        elif item.collider_shape == "CAPSULE":
            shown = (True, True, False)
        else:
            shown = (True, False, False)
        for index, gizmo in enumerate(self.handles):
            gizmo.hide = not shown[index]
            if shown[index]:
                rotation = Vector((0, 0, 1)).rotation_difference(axes[index]).to_matrix().to_4x4()
                gizmo.matrix_basis = obj.matrix_world @ rotation


def draw_viewport_controls(layout, context):
    if context.scene is None:
        return
    settings = context.scene.bevy_component_previews
    row = layout.row(align=True)
    row.prop(settings, "enabled", toggle=True, icon="OVERLAY")
    controls = layout.column(align=True)
    controls.enabled = settings.enabled
    controls.prop(settings, "scope", expand=True)
    row = controls.row(align=True)
    row.prop(settings, "colliders", toggle=True)
    row.prop(settings, "visibility_ranges", text="LOD Ranges", toggle=True)
    row.prop(settings, "spawn_points", text="Spawns", toggle=True)
    row = controls.row(align=True)
    row.prop(settings, "labels", toggle=True)
    row.prop(settings, "xray", toggle=True)
    controls.prop(settings, "edit_handles")
    if settings.edit_handles:
        controls.label(text="Drag colored arrows to resize colliders", icon="INFO")
    if settings.scope == "ALL":
        controls.prop(settings, "max_mesh_edges")


class BEVY_PT_viewport_previews(bpy.types.Panel):
    bl_label = "Viewport Previews"
    bl_idname = "BEVY_PT_viewport_previews"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bevy"
    bl_order = 1

    def draw(self, context):
        draw_viewport_controls(self.layout, context)


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
