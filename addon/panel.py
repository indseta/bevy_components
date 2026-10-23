import json

import bpy

from .menu import BEVY_MT_component_add, BEVY_MT_component_context_menu, BEVY_MT_object_context_menu
from .metadata import FIELD_VALUES, invalid_names, validate_items
from .operator import BEVY_OT_definition_add, BEVY_OT_definition_remove, BEVY_OT_field_add, BEVY_OT_field_move, BEVY_OT_field_remove, BEVY_OT_lod_preset, BEVY_OT_pick_sound, BEVY_OT_remove_component, BEVY_OT_set_collision_layers
from .property import COMPONENT_LABELS, FIELD_LABELS, LAYER_COUNT
from .system import panel_body_drawn, panel_header_drawn
from .validation import check_object, draw_message


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
    column = layout.column(align=True)
    column.active = not item.collider_sensor
    column.prop(item, "collider_friction")
    column.prop(item, "collider_restitution")
    header, body = layout.panel_prop(item, "show_layers")
    header.label(text="Collision Layers")
    if body is None:
        return
    for layers, prop, text in (("MEMBERSHIPS", "collider_memberships", "Belongs To"), ("FILTERS", "collider_filters", "Collides With")):
        buttons = _labeled_row(body, text)
        for enable, label in ((True, "All"), (False, "None")):
            button = buttons.operator(BEVY_OT_set_collision_layers.bl_idname, text=label)
            button.index = index
            button.layers = layers
            button.enable = enable
        grid = body.grid_flow(row_major=True, columns=8, even_columns=True, even_rows=True, align=True)
        grid.use_property_split = False
        for layer in range(LAYER_COUNT):
            grid.prop(item, prop, index=layer, text=str(layer), toggle=True)
    if not any(item.collider_memberships) or not any(item.collider_filters):
        body.label(text="Collides with nothing", icon="INFO")


def _draw_rigid_body(layout, obj, index, item):
    layout.prop(item, "rigid_body_kind")
    if item.rigid_body_kind != "DYNAMIC":
        return
    row = layout.row(heading="Mass")
    row.prop(item, "rigid_body_use_mass", text="")
    mass = row.row()
    mass.active = item.rigid_body_use_mass
    mass.prop(item, "rigid_body_mass", text="")


def _draw_shadows(layout, obj, index, item):
    column = layout.column(heading="Shadows", align=True)
    column.prop(item, "shadows_cast")
    column.prop(item, "shadows_receive")
    if item.shadows_cast and item.shadows_receive:
        row = layout.row()
        row.active = False
        row.label(text="Casts and receives shadows", icon="INFO")


def _draw_audio_player(layout, obj, index, item):
    row = layout.row(align=True)
    row.alert = not item.audio_path.strip()
    row.prop(item, "audio_path")
    row.operator(BEVY_OT_pick_sound.bl_idname, text="", icon="FILEBROWSER").index = index
    layout.prop(item, "audio_volume", slider=True)
    column = layout.column(heading="Playback", align=True)
    column.prop(item, "audio_loop")
    column.prop(item, "audio_autoplay")
    layout.prop(item, "audio_spatial")
    row = layout.row()
    row.active = item.audio_spatial
    row.prop(item, "audio_distance")


def _draw_fields(layout, item):
    problems = invalid_names(field.name for field in item.fields)
    for field in item.fields:
        row = layout.row()
        row.alert = field.name in problems
        row.prop(field, FIELD_VALUES[field.field_type], text=field.name)
    if not len(item.fields):
        row = layout.row()
        row.active = False
        row.label(text="No fields")


def _draw_custom(layout, obj, index, item):
    if item.use_fields:
        _draw_fields(layout, item)
        return
    row = layout.row()
    row.alert = not item.custom_type.strip()
    row.prop_search(item, "custom_type", bpy.context.scene.bevy_component_definitions, "definitions", results_are_suggestions=True)
    row = layout.row()
    row.alert = not _is_json(item.custom_json)
    row.prop(item, "custom_json")


DRAWERS = {
    "VISIBILITY_RANGE": _draw_visibility_range,
    "COLLIDER": _draw_collider,
    "RIGID_BODY": _draw_rigid_body,
    "SHADOWS": _draw_shadows,
    "AUDIO_PLAYER": _draw_audio_player,
    "CUSTOM": _draw_custom,
}


def _draw_component(layout, context, obj, index, item, issues):
    text, icon = COMPONENT_LABELS.get(item.component_type, ("Removed Component", "ERROR"))
    issues = [issue for issue in issues if issue.item == item]
    header, body = layout.panel_prop(item, "show_expanded")
    header.prop(item, "enabled", text="")
    header.label(text=item.custom_type if item.component_type == "CUSTOM" and item.custom_type.strip() else text, icon=icon)
    if issues:
        header.label(text="", icon="CANCEL" if any(issue.level == "ERROR" for issue in issues) else "ERROR")
    tools = header.row(align=True)
    tools.emboss = "NONE"
    tools.context_pointer_set("bevy_component", item)
    tools.menu(BEVY_MT_component_context_menu.bl_idname, text="", icon="DOWNARROW_HLT")
    tools.operator(BEVY_OT_remove_component.bl_idname, text="", icon="X").index = index
    if body is None:
        return
    if item.component_type not in DRAWERS:
        body.label(text="No longer exported", icon="INFO")
        return
    body.use_property_split = True
    body.use_property_decorate = False
    body.active = item.enabled
    DRAWERS[item.component_type](body, obj, index, item)
    for issue in issues:
        if issue.level == "WARNING":
            draw_message(body, issue.message, width=context.region.width if context.region else 300)


def draw_components(layout, context, obj):
    row = layout.row()
    row.operator("wm.call_menu", text="Add Component", icon="ADD").name = BEVY_MT_component_add.bl_idname
    row.menu(BEVY_MT_object_context_menu.bl_idname, text="", icon="DOWNARROW_HLT")
    issues = check_object(obj, bpy.data.objects)
    for index, item in enumerate(obj.bevy_component_data.components):
        _draw_component(layout, context, obj, index, item, issues)


class BEVY_PT_object_properties(bpy.types.Panel):
    bl_label = "Bevy Components"
    bl_idname = "BEVY_PT_object_properties"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def draw_header(self, context):
        panel_header_drawn()

    def draw(self, context):
        panel_body_drawn()
        draw_components(self.layout, context, context.object)


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
        draw_components(self.layout, context, context.object)


class BEVY_UL_definitions(bpy.types.UIList):
    bl_idname = "BEVY_UL_definitions"

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0, flt_flag=0):
        layout.alert = item.name in invalid_names(definition.name for definition in data.definitions)
        layout.prop(item, "name", text="", emboss=False, icon=COMPONENT_LABELS["CUSTOM"][1])


class BEVY_UL_fields(bpy.types.UIList):
    bl_idname = "BEVY_UL_fields"

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0, flt_flag=0):
        split = layout.split(factor=0.6)
        split.alert = item.name in invalid_names(field.name for field in data.fields)
        split.prop(item, "name", text="", emboss=False)
        row = split.row()
        row.alignment = "RIGHT"
        row.active = False
        row.label(text=FIELD_LABELS[item.field_type])


class BEVY_PT_scene_definitions(bpy.types.Panel):
    bl_label = "Bevy Custom Components"
    bl_idname = "BEVY_PT_scene_definitions"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def draw(self, context):
        layout = self.layout
        library = context.scene.bevy_component_definitions
        row = layout.row()
        row.template_list(BEVY_UL_definitions.bl_idname, "", library, "definitions", library, "active_index", rows=3)
        column = row.column(align=True)
        column.operator(BEVY_OT_definition_add.bl_idname, text="", icon="ADD")
        column.operator(BEVY_OT_definition_remove.bl_idname, text="", icon="REMOVE")
        if not 0 <= library.active_index < len(library.definitions):
            return
        definition = library.definitions[library.active_index]
        header, body = layout.panel("BEVY_definition_fields")
        header.label(text="Fields")
        if body is None:
            return
        row = body.row()
        row.template_list(BEVY_UL_fields.bl_idname, "", definition, "fields", definition, "active_field", rows=4)
        column = row.column(align=True)
        column.operator(BEVY_OT_field_add.bl_idname, text="", icon="ADD")
        column.operator(BEVY_OT_field_remove.bl_idname, text="", icon="REMOVE")
        column.separator()
        column.operator(BEVY_OT_field_move.bl_idname, text="", icon="TRIA_UP").direction = "UP"
        column.operator(BEVY_OT_field_move.bl_idname, text="", icon="TRIA_DOWN").direction = "DOWN"
        if not 0 <= definition.active_field < len(definition.fields):
            return
        field = definition.fields[definition.active_field]
        body.use_property_split = True
        body.use_property_decorate = False
        body.prop(field, "field_type")
        body.prop(field, FIELD_VALUES[field.field_type], text="Default")


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
        column.prop(settings, "audio_ranges")
        column = split.column()
        column.prop(settings, "labels")
        column.prop(settings, "xray")
        column.prop(settings, "edit_handles")
        layout.prop(settings, "max_mesh_edges")
