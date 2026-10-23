import bpy
from mathutils import Matrix, Vector

from .system import component_of, components_for, panel_expanded, redraw_viewports

PRIMITIVE_SHAPES = {"CUBOID", "SPHERE", "CAPSULE"}
VOLUME_TYPES = {"FOG_VOLUME", "REFLECTION_PROBE", "IRRADIANCE_VOLUME"}


def handle_item(obj, settings):
    collider = component_of(obj, "COLLIDER")
    if settings.colliders and collider is not None and collider.collider_shape in PRIMITIVE_SHAPES:
        return collider
    if settings.volumes:
        return next((item for item in components_for(obj) if item.component_type in VOLUME_TYPES), None)
    return None


def _target():
    obj = bpy.context.object
    scene = bpy.context.scene
    if obj is None or scene is None or not hasattr(scene, "bevy_component_previews"):
        return obj, None
    return obj, handle_item(obj, scene.bevy_component_previews)


def _get_handle_value(index):
    _obj, item = _target()
    if item is None:
        return 0.0
    if item.component_type in VOLUME_TYPES:
        return float(item.volume_size[index]) * 0.5
    if item.collider_shape == "CUBOID":
        return float(item.collider_size[index]) * 0.5
    if index == 0 and item.collider_shape in {"SPHERE", "CAPSULE"}:
        return float(item.collider_radius)
    if index == 1 and item.collider_shape == "CAPSULE":
        return float(item.collider_height) * 0.5 + float(item.collider_radius)
    return 0.0


def _set_handle_value(index, value):
    obj, item = _target()
    if item is None or obj.library:
        return
    amount = max(0.001, float(value[0] if isinstance(value, (tuple, list)) else value))
    if item.component_type in VOLUME_TYPES:
        dimensions = list(item.volume_size)
        dimensions[index] = amount * 2
        item.volume_size = dimensions
    elif item.collider_shape == "CUBOID":
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
    bl_label = "Bevy Resize Handles"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.library or obj.mode != "OBJECT" or not obj.select_get() or not context.scene or not panel_expanded():
            return False
        if not hasattr(context.scene, "bevy_component_previews"):
            return False
        settings = context.scene.bevy_component_previews
        return settings.enabled and settings.edit_handles and handle_item(obj, settings) is not None

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
            gizmo.target_set_handler("offset", get=lambda handle=index: _get_handle_value(handle), set=lambda value, handle=index: _set_handle_value(handle, value))
            self.handles.append(gizmo)
        self.refresh(bpy.context)

    def refresh(self, context):
        obj, item = _target()
        if item is None:
            return
        axes = (Vector((1, 0, 0)), Vector((0, 0, 1)), Vector((0, -1, 0)))
        if item.component_type in VOLUME_TYPES or item.collider_shape == "CUBOID":
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


def _audio_player():
    obj = bpy.context.object
    return component_of(obj, "AUDIO_PLAYER") if obj else None


def _get_audio_distance():
    item = _audio_player()
    return float(item.audio_distance) if item else 0.0


def _set_audio_distance(value):
    item = _audio_player()
    if item is None or bpy.context.object.library:
        return
    item.audio_distance = max(0.01, float(value[0] if isinstance(value, (tuple, list)) else value))
    redraw_viewports()


class BEVY_GGT_audio_handles(bpy.types.GizmoGroup):
    bl_idname = "BEVY_GGT_audio_handles"
    bl_label = "Bevy Audio Range Handle"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.library or obj.mode != "OBJECT" or not obj.select_get() or not context.scene or not panel_expanded():
            return False
        if not hasattr(context.scene, "bevy_component_previews"):
            return False
        settings = context.scene.bevy_component_previews
        item = component_of(obj, "AUDIO_PLAYER")
        return settings.enabled and settings.audio_ranges and settings.edit_handles and item is not None and item.audio_spatial

    def setup(self, _context):
        gizmo = self.gizmos.new("GIZMO_GT_arrow_3d")
        gizmo.draw_style = "BOX"
        gizmo.scale_basis = 0.75
        gizmo.color = (0.95, 0.80, 0.25)
        gizmo.alpha = 0.82
        gizmo.color_highlight = (1.0, 1.0, 1.0)
        gizmo.alpha_highlight = 1.0
        gizmo.target_set_handler("offset", get=_get_audio_distance, set=_set_audio_distance)
        self.handle = gizmo
        self.refresh(bpy.context)

    def refresh(self, context):
        obj = context.object
        if obj is None:
            return
        rotation = Vector((0, 0, 1)).rotation_difference(Vector((-1, 0, 0))).to_matrix().to_4x4()
        self.handle.matrix_basis = Matrix.Translation(obj.matrix_world.translation) @ rotation
