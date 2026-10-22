import json

import bpy

from .menu import BEVY_MT_component_add, BEVY_MT_component_context_menu, BEVY_MT_object_context_menu
from .metadata import validate_items
from .operator import BEVY_OT_lod_preset, BEVY_OT_remove_component
from .property import COMPONENT_LABELS
from .system import component_of


def _labeled_row(layout, text):
    row = layout.row(align=True)
    row.use_property_split = False
    split = row.split(factor=0.4, align=True)
    split.alignment = "RIGHT"
    split.label(text=text)
    return split.row(align=True)


def _is_json(text):
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return False
    return True


def _draw_visibility_range(layout, obj, index, item):
    presets = _labeled_row(layout, "Preset")
    for preset, text in (("NEAR", "LOD0"), ("MID", "LOD1"), ("FAR", "LOD2")):
        button = presets.operator(BEVY_OT_lod_preset.bl_idname, text=text)
        button.index = index
        button.preset = preset
    invalid = bool(validate_items([item]))
    column = layout.column(align=True)
    column.alert = invalid
    column.prop(item, "fade_in_start", text="Fade In Start")
    column.prop(item, "fade_in_end", text="End")
    column = layout.column(align=True)
    column.alert = invalid
    column.prop(item, "fade_out_start", text="Fade Out Start")
    column.prop(item, "fade_out_end", text="End")
    layout.prop(item, "use_aabb")
    if invalid:
        layout.label(text="Fade distances must increase from top to bottom", icon="ERROR")


def _draw_collider(layout, obj, index, item):
    layout.prop(item, "collider_shape")
    if item.collider_shape == "CUBOID":
        column = layout.column(align=True)
        column.prop(item, "collider_size", index=0, text="Size X")
        column.prop(item, "collider_size", index=1, text="Y (Up)")
        column.prop(item, "collider_size", index=2, text="Z")
    elif item.collider_shape == "SPHERE":
        layout.prop(item, "collider_radius")
    elif item.collider_shape == "CAPSULE":
        column = layout.column(align=True)
        column.prop(item, "collider_radius")
        column.prop(item, "collider_height")
    layout.prop(item, "collider_sensor")
    rigid_body = component_of(obj, "RIGID_BODY")
    if item.collider_shape == "TRIMESH" and rigid_body is not None and rigid_body.rigid_body_kind != "STATIC":
        layout.label(text="Triangle meshes work best on static bodies", icon="INFO")


def _draw_rigid_body(layout, obj, index, item):
    layout.prop(item, "rigid_body_kind")


def _draw_spawn_point(layout, obj, index, item):
    layout.prop(item, "spawn_tag")


def _draw_custom(layout, obj, index, item):
    row = layout.row()
    row.alert = not item.custom_type.strip()
    row.prop(item, "custom_type")
    row = layout.row()
    row.alert = not _is_json(item.custom_json)
    row.prop(item, "custom_json")


DRAWERS = {
    "VISIBILITY_RANGE": _draw_visibility_range,
    "COLLIDER": _draw_collider,
    "RIGID_BODY": _draw_rigid_body,
    "SPAWN_POINT": _draw_spawn_point,
    "CUSTOM": _draw_custom,
}


def _draw_component(layout, obj, index, item):
    text, icon = COMPONENT_LABELS[item.component_type]
    header, body = layout.panel_prop(item, "show_expanded")
    header.prop(item, "enabled", text="")
    header.label(text=item.custom_type if item.component_type == "CUSTOM" and item.custom_type.strip() else text, icon=icon)
    tools = header.row(align=True)
    tools.emboss = "NONE"
    tools.context_pointer_set("bevy_component", item)
    tools.menu(BEVY_MT_component_context_menu.bl_idname, text="", icon="DOWNARROW_HLT")
    tools.operator(BEVY_OT_remove_component.bl_idname, text="", icon="X").index = index
    if body is None:
        return
    body.use_property_split = True
    body.use_property_decorate = False
    body.active = item.enabled
    DRAWERS[item.component_type](body, obj, index, item)


def draw_components(layout, obj):
    row = layout.row()
    row.operator("wm.call_menu", text="Add Component", icon="ADD").name = BEVY_MT_component_add.bl_idname
    row.menu(BEVY_MT_object_context_menu.bl_idname, text="", icon="DOWNARROW_HLT")
    for index, item in enumerate(obj.bevy_component_data.components):
        _draw_component(layout, obj, index, item)


class BEVY_PT_object_properties(bpy.types.Panel):
    bl_label = "Bevy Components"
    bl_idname = "BEVY_PT_object_properties"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def draw(self, context):
        draw_components(self.layout, context.object)


class BEVY_PT_view_sidebar(bpy.types.Panel):
    bl_label = "Bevy Components"
    bl_idname = "BEVY_PT_view_sidebar"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bevy"

    def draw(self, context):
        if context.object is None:
            self.layout.label(text="Select an object", icon="INFO")
            return
        draw_components(self.layout, context.object)


class BEVY_PT_overlay(bpy.types.Panel):
    bl_label = "Bevy Components"
    bl_idname = "BEVY_PT_overlay"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_parent_id = "VIEW3D_PT_overlay"

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def draw_header(self, context):
        self.layout.active = context.space_data.overlay.show_overlays
        self.layout.prop(context.scene.bevy_component_previews, "enabled", text=self.bl_label)

    def draw(self, context):
        layout = self.layout
        settings = context.scene.bevy_component_previews
        layout.active = context.space_data.overlay.show_overlays and settings.enabled
        layout.row().prop(settings, "scope", expand=True)
        split = layout.split()
        column = split.column()
        column.prop(settings, "colliders")
        column.prop(settings, "visibility_ranges")
        column.prop(settings, "spawn_points")
        column = split.column()
        column.prop(settings, "labels")
        column.prop(settings, "xray")
        column.prop(settings, "edit_handles")
        layout.prop(settings, "max_mesh_edges")
