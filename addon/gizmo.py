import bpy
from mathutils import Matrix, Vector

from .metadata import PRIMITIVE_SHAPES, light_of, light_range
from .native import is_native
from .system import component_of, components_for, object_components, panel_expanded, redraw_viewports, touch_object

VOLUME_TYPES = {"FOG_VOLUME", "REFLECTION_PROBE", "IRRADIANCE_VOLUME"}
VOLUME_NAMES = {
    "FOG_VOLUME": "Fog Volume",
    "REFLECTION_PROBE": "Reflection Probe",
    "IRRADIANCE_VOLUME": "Irradiance Volume",
}
AXIS_COLORS = ((0.95, 0.26, 0.25), (0.35, 0.95, 0.35), (0.30, 0.55, 1.0))
OFFSET_COLOR = (0.30, 0.86, 0.94)
AUDIO_COLOR = (0.95, 0.80, 0.25)
LIGHT_COLOR = (1.0, 0.86, 0.35)
RANGE_PROPS = ("fade_in_start", "fade_in_end", "fade_out_start", "fade_out_end")
RANGE_COLORS = ((0.20, 0.72, 1.0), (0.20, 0.72, 1.0), (1.0, 0.62, 0.25), (1.0, 0.62, 0.25))
RANGE_DIRECTIONS = (Vector((1, 0, 0)), Vector((-1, 0, 0)), Vector((1, 0, 0)), Vector((-1, 0, 0)))
HANDLE_AXES = (Vector((1, 0, 0)), Vector((0, 0, 1)), Vector((0, -1, 0)))
UP = Vector((0, 0, 1))
DRAG_INTERVAL = 0.1

_drag = None


def _amount(value):
    return float(value[0] if isinstance(value, (tuple, list)) else value)


def _bevy_to_blender(vector):
    return Vector((vector[0], -vector[2], vector[1]))


def _blender_to_bevy(vector):
    return (vector[0], vector[2], -vector[1])


def _pointing(direction):
    return UP.rotation_difference(direction).to_matrix().to_4x4()


def _handle_state(obj):
    light = light_of(obj)
    return object_components(obj), (light.use_custom_distance, light.cutoff_distance) if light is not None else None


def push_undo(message):
    windows = bpy.context.window_manager.windows
    if not windows:
        return
    with bpy.context.temp_override(window=windows[0]):
        if bpy.ops.ed.undo_push.poll():
            bpy.ops.ed.undo_push(message=message)


def watch_drag(gizmo, message):
    global _drag
    obj = bpy.context.object
    if obj is None:
        return
    _drag = (gizmo, obj.name, message, _handle_state(obj))
    if not bpy.app.timers.is_registered(_finish_drag):
        bpy.app.timers.register(_finish_drag, first_interval=DRAG_INTERVAL)


def _finish_drag():
    global _drag
    if _drag is None:
        return None
    gizmo, name, message, state = _drag
    try:
        if gizmo.is_modal:
            return DRAG_INTERVAL
    except ReferenceError:
        pass
    _drag = None
    obj = bpy.data.objects.get(name)
    if obj is not None and _handle_state(obj) != state:
        push_undo(message)
    return None


def stop_drag_tracking():
    global _drag
    _drag = None
    if bpy.app.timers.is_registered(_finish_drag):
        bpy.app.timers.unregister(_finish_drag)


def _handles_shown(context):
    obj = context.object
    if not obj or obj.library or obj.mode != "OBJECT" or not obj.select_get() or not context.scene or not panel_expanded():
        return None
    if not hasattr(context.scene, "bevy_component_previews"):
        return None
    settings = context.scene.bevy_component_previews
    return settings if settings.enabled and settings.edit_handles else None


def _arrow(group, color, get, set):
    gizmo = group.gizmos.new("GIZMO_GT_arrow_3d")
    gizmo.draw_style = "BOX"
    gizmo.scale_basis = 0.75
    gizmo.color = color
    gizmo.alpha = 0.82
    gizmo.color_highlight = (1.0, 1.0, 1.0)
    gizmo.alpha_highlight = 1.0
    gizmo.target_set_handler("offset", get=get, set=set)
    return gizmo


def handle_item(obj, settings):
    collider = component_of(obj, "COLLIDER")
    if settings.colliders and collider is not None and not is_native(collider) and collider.collider_shape in PRIMITIVE_SHAPES:
        return collider
    if settings.volumes:
        return next((item for item in components_for(obj) if item.component_type in VOLUME_TYPES and not is_native(item)), None)
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
    if index == 0 and item.collider_shape in {"SPHERE", "CAPSULE", "CYLINDER", "CONE"}:
        return float(item.collider_radius)
    if index == 1 and item.collider_shape == "CAPSULE":
        return float(item.collider_height) * 0.5 + float(item.collider_radius)
    if index == 1 and item.collider_shape in {"CYLINDER", "CONE"}:
        return float(item.collider_height) * 0.5
    return 0.0


def _set_handle_value(index, value):
    obj, item = _target()
    if item is None or obj.library:
        return
    amount = max(0.001, _amount(value))
    if item.component_type in VOLUME_TYPES:
        dimensions = list(item.volume_size)
        dimensions[index] = amount * 2
        item.volume_size = dimensions
    elif item.collider_shape == "CUBOID":
        dimensions = list(item.collider_size)
        dimensions[index] = amount * 2
        item.collider_size = dimensions
    elif index == 0 and item.collider_shape in {"SPHERE", "CAPSULE", "CYLINDER", "CONE"}:
        item.collider_radius = amount
    elif index == 1 and item.collider_shape == "CAPSULE":
        item.collider_height = max(0.0, (amount - item.collider_radius) * 2)
    elif index == 1 and item.collider_shape in {"CYLINDER", "CONE"}:
        item.collider_height = amount * 2
    redraw_viewports()


def _get_offset():
    obj, item = _target()
    if item is None or item.component_type != "COLLIDER":
        return (0.0, 0.0, 0.0)
    return tuple(obj.matrix_world.to_3x3() @ _bevy_to_blender(item.collider_offset))


def _set_offset(value):
    obj, item = _target()
    if item is None or item.component_type != "COLLIDER" or obj.library:
        return
    item.collider_offset = _blender_to_bevy(obj.matrix_world.to_3x3().inverted_safe() @ Vector(value))
    redraw_viewports()


class BEVY_GGT_collider_handles(bpy.types.GizmoGroup):
    bl_idname = "BEVY_GGT_collider_handles"
    bl_label = "Bevy Resize Handles"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        settings = _handles_shown(context)
        return settings is not None and handle_item(context.object, settings) is not None

    def setup(self, context):
        self.handles = [_arrow(self, color, lambda handle=index: _get_handle_value(handle), lambda value, handle=index: _set_handle_value(handle, value)) for index, color in enumerate(AXIS_COLORS)]
        mover = self.gizmos.new("GIZMO_GT_move_3d")
        mover.draw_options = {"ALIGN_VIEW", "FILL_SELECT"}
        mover.scale_basis = 0.18
        mover.color = OFFSET_COLOR
        mover.alpha = 0.82
        mover.color_highlight = (1.0, 1.0, 1.0)
        mover.alpha_highlight = 1.0
        mover.target_set_handler("offset", get=_get_offset, set=_set_offset)
        self.mover = mover
        self.refresh(context)

    def invoke_prepare(self, context, gizmo):
        _obj, item = _target()
        if item is None:
            return
        if item.component_type in VOLUME_TYPES:
            watch_drag(gizmo, f"Resize {VOLUME_NAMES[item.component_type]}")
        else:
            watch_drag(gizmo, "Move Collider" if gizmo == self.mover else "Resize Collider")

    def refresh(self, context):
        obj, item = _target()
        if item is None:
            return
        collider = item.component_type == "COLLIDER"
        center = obj.matrix_world @ Matrix.Translation(_bevy_to_blender(item.collider_offset)) if collider else obj.matrix_world
        if not collider or item.collider_shape == "CUBOID":
            shown = (True, True, True)
        elif item.collider_shape in {"CAPSULE", "CYLINDER", "CONE"}:
            shown = (True, True, False)
        else:
            shown = (True, False, False)
        for index, gizmo in enumerate(self.handles):
            gizmo.hide = not shown[index]
            if shown[index]:
                gizmo.matrix_basis = center @ _pointing(HANDLE_AXES[index])
        self.mover.hide = not collider
        self.mover.matrix_basis = Matrix.Translation(obj.matrix_world.translation)

    def draw_prepare(self, context):
        self.refresh(context)


def _visibility_range():
    obj = bpy.context.object
    return component_of(obj, "VISIBILITY_RANGE") if obj else None


def _range_center(obj, item):
    offset = Vector()
    if item.use_aabb and obj.type == "MESH":
        offset = sum((Vector(corner) for corner in obj.bound_box), Vector()) / 8
    return obj.matrix_world @ offset


def _get_range(index):
    item = _visibility_range()
    return float(getattr(item, RANGE_PROPS[index])) if item else 0.0


def _set_range(index, value):
    item = _visibility_range()
    if item is None or bpy.context.object.library:
        return
    amount = max(0.0, _amount(value))
    for other, prop in enumerate(RANGE_PROPS):
        current = getattr(item, prop)
        wanted = amount if other == index else min(current, amount) if other < index else max(current, amount)
        if wanted != current:
            setattr(item, prop, wanted)
    redraw_viewports()


class BEVY_GGT_range_handles(bpy.types.GizmoGroup):
    bl_idname = "BEVY_GGT_range_handles"
    bl_label = "Bevy Visibility Range Handles"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        settings = _handles_shown(context)
        return settings is not None and settings.visibility_ranges and component_of(context.object, "VISIBILITY_RANGE") is not None

    def setup(self, context):
        self.handles = [_arrow(self, color, lambda handle=index: _get_range(handle), lambda value, handle=index: _set_range(handle, value)) for index, color in enumerate(RANGE_COLORS)]
        self.refresh(context)

    def invoke_prepare(self, context, gizmo):
        watch_drag(gizmo, "Resize Visibility Range")

    def refresh(self, context):
        obj = context.object
        item = component_of(obj, "VISIBILITY_RANGE") if obj else None
        if item is None:
            return
        center = Matrix.Translation(_range_center(obj, item))
        for gizmo, direction in zip(self.handles, RANGE_DIRECTIONS):
            gizmo.matrix_basis = center @ _pointing(direction)

    def draw_prepare(self, context):
        self.refresh(context)


def _ranged_light(obj):
    light = light_of(obj) if obj else None
    return light if light is not None and light.type != "SUN" and component_of(obj, "LIGHT") is not None else None


def _get_light_range():
    light = _ranged_light(bpy.context.object)
    return light_range(light) if light else 0.0


def _set_light_range(value):
    obj = bpy.context.object
    light = _ranged_light(obj)
    if light is None or obj.library or light.library:
        return
    light.use_custom_distance = True
    light.cutoff_distance = max(0.01, _amount(value))
    touch_object(obj)
    redraw_viewports()


class BEVY_GGT_light_handles(bpy.types.GizmoGroup):
    bl_idname = "BEVY_GGT_light_handles"
    bl_label = "Bevy Light Range Handle"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        settings = _handles_shown(context)
        return settings is not None and settings.lights and _ranged_light(context.object) is not None

    def setup(self, context):
        self.handle = _arrow(self, LIGHT_COLOR, _get_light_range, _set_light_range)
        self.refresh(context)

    def invoke_prepare(self, context, gizmo):
        watch_drag(gizmo, "Resize Light Range")

    def refresh(self, context):
        obj = context.object
        light = _ranged_light(obj)
        if light is None:
            return
        location, rotation, _scale = obj.matrix_world.decompose()
        if light.type == "SPOT":
            self.handle.matrix_basis = Matrix.Translation(location) @ rotation.to_matrix().to_4x4() @ _pointing(Vector((0, 0, -1)))
        else:
            self.handle.matrix_basis = Matrix.Translation(location)

    def draw_prepare(self, context):
        self.refresh(context)


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
    item.audio_distance = max(0.01, _amount(value))
    redraw_viewports()


class BEVY_GGT_audio_handles(bpy.types.GizmoGroup):
    bl_idname = "BEVY_GGT_audio_handles"
    bl_label = "Bevy Audio Range Handle"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        settings = _handles_shown(context)
        item = component_of(context.object, "AUDIO_PLAYER") if settings is not None else None
        return settings is not None and settings.audio_ranges and item is not None and item.audio_spatial

    def setup(self, context):
        self.handle = _arrow(self, AUDIO_COLOR, _get_audio_distance, _set_audio_distance)
        self.refresh(context)

    def invoke_prepare(self, context, gizmo):
        watch_drag(gizmo, "Resize Audio Range")

    def refresh(self, context):
        obj = context.object
        if obj is None:
            return
        self.handle.matrix_basis = Matrix.Translation(obj.matrix_world.translation) @ _pointing(Vector((-1, 0, 0)))
