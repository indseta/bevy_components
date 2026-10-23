import json
from fnmatch import fnmatchcase

import bpy

from .menu import BEVY_MT_component_add, BEVY_MT_component_context_menu, BEVY_MT_object_context_menu, draw_export_again, draw_export_all
from .metadata import BEVY_LIGHT_RANGE, FIELD_VALUES, PRIMITIVE_SHAPES, invalid_names, joint_limits_inverted, light_amount, light_intensity, light_of, light_unit, validate_items
from .operator import BEVY_OT_bake_lighting, BEVY_OT_definition_add, BEVY_OT_definition_remove, BEVY_OT_edit_as_text, BEVY_OT_export_bsn, BEVY_OT_export_glb, BEVY_OT_field_add, BEVY_OT_field_move, BEVY_OT_field_remove, BEVY_OT_fit_collider, BEVY_OT_lod_preset, BEVY_OT_pick_sound, BEVY_OT_reload_schema, BEVY_OT_remove_component, BEVY_OT_select_by_component, BEVY_OT_set_collision_layers, BEVY_OT_unwrap_lightmap
from .property import COMPONENT_LABELS, FIELD_LABELS, LAYER_COUNT
from .schema import short_name
from .system import ambient_light, export_settings, exported_objects, game_schema, game_types, layer_names, lightmap_uv_map, panel_body_drawn, panel_header_drawn, sky_lights_scene, world_background, world_color
from .validation import AMBIENT_WITH_SKY, ambient_doubles_sky, check_object, draw_message, draw_problem_count, sky_check, texture_check

OVERVIEW_ICONS = 4


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


def _draw_size(layout, item, prop):
    column = layout.column(align=True)
    column.prop(item, prop, index=0, text="Size X")
    column.prop(item, prop, index=1, text="Y (Up)")
    column.prop(item, prop, index=2, text="Z")


def _draw_collider(layout, obj, index, item):
    layout.prop(item, "collider_shape")
    if item.collider_shape in PRIMITIVE_SHAPES:
        if item.collider_shape == "CUBOID":
            _draw_size(layout, item, "collider_size")
        elif item.collider_shape == "SPHERE":
            layout.prop(item, "collider_radius")
        else:
            column = layout.column(align=True)
            column.prop(item, "collider_radius")
            column.prop(item, "collider_height")
        _draw_vector(layout, item, "collider_offset", "Offset", (False, False, False))
        layout.operator(BEVY_OT_fit_collider.bl_idname, icon="SHADING_BBOX").index = index
    column = layout.column(align=True)
    column.prop(item, "collider_sensor")
    column.prop(item, "collider_events")
    column.prop(item, "collider_collision_only")
    column = layout.column(align=True)
    column.active = not item.collider_sensor
    column.prop(item, "collider_friction")
    column.prop(item, "collider_restitution")
    header, body = layout.panel_prop(item, "show_layers")
    header.label(text="Collision Layers")
    if body is None:
        return
    names = layer_names(bpy.context.scene)
    named = [layer for layer in range(LAYER_COUNT) if names[layer]]
    unnamed = [layer for layer in range(LAYER_COUNT) if not names[layer]]
    for layers, prop, text in (("MEMBERSHIPS", "collider_memberships", "Belongs To"), ("FILTERS", "collider_filters", "Collides With")):
        buttons = _labeled_row(body, text)
        for enable, label in ((True, "All"), (False, "None")):
            button = buttons.operator(BEVY_OT_set_collision_layers.bl_idname, text=label)
            button.index = index
            button.layers = layers
            button.enable = enable
        column = body.column(align=True)
        for shown, columns in ((named, 2), (unnamed, 8)):
            if not shown:
                continue
            grid = column.grid_flow(row_major=True, columns=columns, even_columns=True, even_rows=True, align=True)
            grid.use_property_split = False
            for layer in shown:
                grid.prop(item, prop, index=layer, text=f"{layer} {names[layer]}" if names[layer] else str(layer), toggle=True)
    if not any(item.collider_memberships) or not any(item.collider_filters):
        body.label(text="Collides with nothing", icon="INFO")


def _draw_axes(layout, item, prop, text):
    row = layout.row(heading=text, align=True)
    for axis, label in enumerate(("X", "Y (Up)", "Z")):
        row.prop(item, prop, index=axis, text=label, toggle=True)


def _draw_vector(layout, item, prop, text, locked):
    column = layout.column(align=True)
    for axis, label in enumerate((f"{text} X", "Y (Up)", "Z")):
        row = column.row(align=True)
        row.active = not locked[axis]
        row.prop(item, prop, index=axis, text=label)


def _draw_rigid_body(layout, obj, index, item):
    layout.prop(item, "rigid_body_kind")
    if item.rigid_body_kind == "STATIC":
        return
    dynamic = item.rigid_body_kind == "DYNAMIC"
    if dynamic:
        row = layout.row(heading="Mass")
        row.prop(item, "rigid_body_use_mass", text="")
        mass = row.row()
        mass.active = item.rigid_body_use_mass
        mass.prop(item, "rigid_body_mass", text="")
        layout.prop(item, "rigid_body_gravity_scale")
    header, body = layout.panel_prop(item, "show_velocity")
    header.label(text="Initial Velocity")
    if body is not None:
        _draw_vector(body, item, "rigid_body_linear_velocity", "Velocity", item.rigid_body_lock_translation if dynamic else (False, False, False))
        _draw_vector(body, item, "rigid_body_angular_velocity", "Spin", item.rigid_body_lock_rotation if dynamic else (False, False, False))
    if not dynamic:
        return
    header, body = layout.panel_prop(item, "show_dynamics")
    header.label(text="Dynamics")
    if body is None:
        return
    column = body.column(align=True)
    column.prop(item, "rigid_body_linear_damping", text="Damping")
    column.prop(item, "rigid_body_angular_damping", text="Spin Damping")
    _draw_axes(body, item, "rigid_body_lock_translation", "Lock Position")
    _draw_axes(body, item, "rigid_body_lock_rotation", "Lock Rotation")
    body.prop(item, "rigid_body_ccd")


def _draw_joint(layout, obj, index, item):
    layout.prop(item, "joint_kind")
    column = layout.column(align=True)
    column.prop(item, "joint_body1", placeholder="World")
    column.prop(item, "joint_body2", placeholder="World")
    kind = item.joint_kind
    if kind != "FIXED":
        layout.prop(item, "joint_axis", expand=True)
        if kind == "SPHERICAL":
            row = layout.row(heading="Swing Limit")
            row.prop(item, "joint_use_swing", text="")
            swing = row.row()
            swing.active = item.joint_use_swing
            swing.prop(item, "joint_swing", text="")
        layout.prop(item, "joint_use_limits", text="Twist Limits" if kind == "SPHERICAL" else "Limits")
        column = layout.column(align=True)
        column.active = item.joint_use_limits
        column.alert = joint_limits_inverted(item)
        unit = "distance" if kind == "PRISMATIC" else "angle"
        column.prop(item, f"joint_{unit}_min")
        column.prop(item, f"joint_{unit}_max")
        if column.alert:
            layout.label(text="Min must not be above Max", icon="ERROR")
        column = layout.column(align=True)
        column.prop(item, "joint_linear_damping", text="Damping")
        column.prop(item, "joint_angular_damping", text="Turn Damping")
    layout.prop(item, "joint_collide")
    if (item.joint_body1 is None) != (item.joint_body2 is None):
        pinned = item.joint_body1 or item.joint_body2
        draw_message(layout, f"Pins {pinned.name} to this spot in the scene", icon="INFO")


def _draw_shadows(layout, obj, index, item):
    column = layout.column(heading="Shadows", align=True)
    column.prop(item, "shadows_cast")
    column.prop(item, "shadows_receive")
    if item.shadows_cast and item.shadows_receive:
        row = layout.row()
        row.active = False
        row.label(text="Casts and receives shadows", icon="INFO")


def _draw_navigation(layout, obj, index, item):
    layout.prop(item, "navigation_kind")
    if item.navigation_kind == "WALKABLE":
        layout.prop(item, "navigation_cost")


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


def _draw_fog_volume(layout, obj, index, item):
    _draw_size(layout, item, "volume_size")
    layout.prop(item, "fog_color")
    column = layout.column(align=True)
    column.prop(item, "fog_density")
    column.prop(item, "fog_absorption")
    column.prop(item, "fog_scattering")
    column.prop(item, "fog_anisotropy")
    column = layout.column(align=True)
    column.prop(item, "fog_light_tint")
    column.prop(item, "fog_light_intensity", text="Intensity")


def _draw_probe(layout, obj, index, item, text):
    _draw_size(layout, item, "volume_size")
    layout.prop(item, "volume_falloff")
    layout.prop(item, "probe_intensity")
    if item.component_type == "REFLECTION_PROBE":
        layout.prop(item, "probe_parallax")
    _draw_texture(layout, obj, item, text)
    if item.component_type == "REFLECTION_PROBE":
        layout.prop(item, "bake_resolution")
    else:
        column = layout.column(align=True)
        column.prop(item, "bake_voxels", index=0, text="Bake Voxels X")
        column.prop(item, "bake_voxels", index=1, text="Y (Up)")
        column.prop(item, "bake_voxels", index=2, text="Z")
    _draw_bake_button(layout, obj, index)


def _draw_texture(layout, obj, item, text):
    _draw_file(layout, texture_check(obj, item), item, "probe_file", text)


def _draw_file(layout, check, owner, name, text):
    row = layout.row()
    row.alert = check.level == "ERROR"
    row.prop(owner, name, text=text)
    if check.level is None:
        row = layout.row()
        row.active = False
        row.label(text=check.message, icon="INFO")
    elif check.level == "ERROR":
        draw_message(layout, check.message, icon="CANCEL", width=bpy.context.region.width if bpy.context.region else 300)


def _draw_bake_button(layout, obj, index):
    button = layout.operator(BEVY_OT_bake_lighting.bl_idname, text="Bake", icon="RENDER_STILL")
    button.object_name = obj.name
    button.index = index


def _draw_reflection_probe(layout, obj, index, item):
    _draw_probe(layout, obj, index, item, "Cubemap")


def _draw_irradiance_volume(layout, obj, index, item):
    _draw_probe(layout, obj, index, item, "Voxels")


def _draw_lightmap(layout, obj, index, item):
    if obj.type != "MESH":
        return
    _draw_texture(layout, obj, item, "Lightmap")
    layout.prop(item, "lightmap_resolution")
    layout.prop(item, "lightmap_bicubic")
    uv_map = lightmap_uv_map(obj)
    row = _labeled_row(layout, "UV Map")
    row.alert = uv_map is None
    row.label(text=uv_map.name if uv_map is not None else "None")
    layout.operator(BEVY_OT_unwrap_lightmap.bl_idname, icon="UV")
    _draw_bake_button(layout, obj, index)


def _draw_light(layout, obj, index, item):
    light = light_of(obj)
    if light is None:
        return
    unit = light_unit(light)
    row = layout.row(heading="Intensity")
    row.prop(item, "light_use_intensity", text="")
    value = row.row(align=True)
    if item.light_use_intensity:
        value.prop(item, "light_intensity", text="")
        value.label(text=unit)
    else:
        value.active = False
        value.label(text=light_amount(light_intensity(light, obj), unit))
    if light.type in {"POINT", "SPOT"}:
        layout.prop(light, "shadow_soft_size", text="Radius")
    if light.type != "SUN":
        row = layout.row(heading="Range")
        row.prop(light, "use_custom_distance", text="")
        distance = row.row()
        if light.use_custom_distance:
            distance.prop(light, "cutoff_distance", text="")
        else:
            distance.active = False
            distance.label(text=f"{BEVY_LIGHT_RANGE:g} m, Bevy's default")
    if light.type == "AREA":
        draw_message(layout, "Bevy area lights cast no shadows, and need its area_light_luts feature", icon="INFO", width=bpy.context.region.width if bpy.context.region else 300)
        return
    layout.prop(item, "light_baked")
    layout.prop(item, "light_volumetric")
    header, body = layout.panel_prop(item, "show_shadows")
    header.prop(light, "use_shadow", text="Shadows")
    if body is None:
        return
    body.active = light.use_shadow
    body.prop(item, "light_contact_shadows")
    body.prop(item, "light_use_bias")
    if item.light_use_bias:
        column = body.column(align=True)
        column.prop(item, "light_depth_bias")
        column.prop(item, "light_normal_bias")
        if light.type != "SUN":
            column.prop(item, "light_near_clip")
    if light.type != "SUN":
        return
    body.prop(item, "light_use_cascades")
    if item.light_use_cascades:
        column = body.column(align=True)
        column.alert = bool(validate_items([item]))
        column.prop(item, "light_cascade_count")
        column.prop(item, "light_cascade_near")
        column.prop(item, "light_cascade_first")
        column.prop(item, "light_cascade_far")
        body.prop(item, "light_cascade_overlap")


def _field_property(field):
    return "enum_value" if field.field_type == "ENUM" else FIELD_VALUES[field.field_type]


def _draw_fields(layout, item):
    problems = invalid_names(field.name for field in item.fields)
    for field in item.fields:
        row = layout.row()
        row.alert = field.name in problems
        row.prop(field, _field_property(field), text=field.name)
    game_type = game_types().get(item.custom_type)
    others = game_type.others if game_type is not None else []
    for name, rust_type in others:
        row = _labeled_row(layout, name)
        row.active = False
        row.label(text=f"Game default ({short_name(rust_type)})")
    if not len(item.fields) and not others:
        row = layout.row()
        row.active = False
        row.label(text="No fields")


def _draw_custom(layout, obj, index, item):
    if item.use_fields:
        _draw_fields(layout, item)
        return
    column = layout.column()
    column.use_property_split = False
    row = column.row()
    row.alert = not item.custom_type.strip()
    row.prop(item, "custom_type", text="")
    row = column.row(align=True)
    row.alert = not _is_json(item.custom_json)
    row.prop(item, "custom_json", text="")
    row.operator(BEVY_OT_edit_as_text.bl_idname, text="", icon="TEXT").index = index


def _draw_scene_reference(layout, obj, index, item):
    row = layout.row()
    row.alert = not item.scene_file.strip()
    row.prop(item, "scene_file")
    layout.prop(item, "scene_index")


def _draw_animation(layout, obj, index, item):
    layout.prop_search(item, "animation_clip", bpy.data, "actions", icon="ACTION")
    layout.prop(item, "animation_loop")
    layout.prop(item, "animation_speed")


DRAWERS = {
    "VISIBILITY_RANGE": _draw_visibility_range,
    "COLLIDER": _draw_collider,
    "RIGID_BODY": _draw_rigid_body,
    "SHADOWS": _draw_shadows,
    "AUDIO_PLAYER": _draw_audio_player,
    "LIGHT": _draw_light,
    "CUSTOM": _draw_custom,
    "JOINT": _draw_joint,
    "SCENE_REFERENCE": _draw_scene_reference,
    "ANIMATION": _draw_animation,
    "NAVIGATION": _draw_navigation,
    "FOG_VOLUME": _draw_fog_volume,
    "REFLECTION_PROBE": _draw_reflection_probe,
    "IRRADIANCE_VOLUME": _draw_irradiance_volume,
    "LIGHTMAP": _draw_lightmap,
}


def _draw_component(layout, context, obj, index, item, issues):
    text, icon = COMPONENT_LABELS.get(item.component_type, ("Removed Component", "ERROR"))
    issues = [issue for issue in issues if issue.item == item]
    if issues:
        icon = "CANCEL" if any(issue.level == "ERROR" for issue in issues) else "ERROR"
    header, body = layout.panel_prop(item, "show_expanded")
    header.prop(item, "enabled", text="")
    header.label(text=short_name(item.custom_type) if item.component_type == "CUSTOM" and item.custom_type.strip() else text, icon=icon)
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
    settings = export_settings(context.scene)
    issues = check_object(obj, exported_objects(context, settings, selected=False), modifiers=settings.apply_modifiers)
    for issue in issues:
        if issue.item is None:
            draw_message(layout, issue.message, width=context.region.width if context.region else 300)
    for index, item in enumerate(obj.bevy_component_data.components):
        _draw_component(layout, context, obj, index, item, issues)


class BEVY_PT_object_properties(bpy.types.Panel):
    bl_label = "Components"
    bl_idname = "BEVY_PT_object_properties"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def draw_header(self, context):
        panel_header_drawn()

    def draw_header_preset(self, context):
        draw_problem_count(self.layout, context.scene)

    def draw(self, context):
        panel_body_drawn()
        draw_components(self.layout, context, context.object)


class BEVY_PT_view_sidebar(bpy.types.Panel):
    bl_label = "Bevy Components"
    bl_idname = "BEVY_PT_view_sidebar"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bevy"

    def draw_header_preset(self, context):
        draw_problem_count(self.layout, context.scene)

    def draw(self, context):
        if context.object is None:
            self.layout.label(text="Select an object", icon="INFO")
            return
        draw_components(self.layout, context, context.object)


class BEVY_UL_objects(bpy.types.UIList):
    bl_idname = "BEVY_UL_objects"

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0, flt_flag=0):
        split = layout.split(factor=0.5)
        split.prop(item, "name", text="", emboss=False, icon_value=layout.icon(item))
        icons = split.row(align=True)
        icons.alignment = "RIGHT"
        kinds = list(dict.fromkeys(component.component_type for component in item.bevy_component_data.components if component.component_type))
        for kind in kinds[:OVERVIEW_ICONS]:
            icons.label(text="", icon=COMPONENT_LABELS[kind][1])
        if len(kinds) > OVERVIEW_ICONS:
            icons.label(text=f"+{len(kinds) - OVERVIEW_ICONS}")

    def filter_items(self, context, data, propname):
        objects = getattr(data, propname)
        shown = data.bevy_component_overview.filter
        pattern = f"*{self.filter_name.lower()}*" if self.filter_name else ""
        flags = []
        for obj in objects:
            items = obj.bevy_component_data.components
            listed = len(items) > 0 and (shown == "ALL" or any(item.component_type == shown for item in items))
            if listed and pattern:
                names = [obj.name] + [item.custom_type for item in items if item.component_type == "CUSTOM"]
                listed = any(fnmatchcase(name.lower(), pattern) for name in names) != self.use_filter_invert
            flags.append(self.bitflag_filter_item if listed else 0)
        return flags, bpy.types.UI_UL_list.sort_items_by_name(objects, "name") if self.use_filter_sort_alpha else []


class BEVY_PT_view_overview(bpy.types.Panel):
    bl_label = "Scene Overview"
    bl_idname = "BEVY_PT_view_overview"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bevy"

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def draw(self, context):
        layout = self.layout
        overview = context.scene.bevy_component_overview
        row = layout.row(align=True)
        row.prop(overview, "filter", text="")
        row.operator(BEVY_OT_select_by_component.bl_idname, text="", icon="RESTRICT_SELECT_OFF").component_type = overview.filter
        layout.template_list(BEVY_UL_objects.bl_idname, "", context.scene, "objects", overview, "active", rows=6)


class BEVY_PT_view_export(bpy.types.Panel):
    bl_label = "Export"
    bl_idname = "BEVY_PT_view_export"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bevy"

    def draw(self, context):
        column = self.layout.column()
        draw_export_again(column, context.scene)
        draw_export_all(column)
        column.operator(BEVY_OT_export_glb.bl_idname, text="Bevy Scene (.glb)...", icon="EXPORT")
        column.operator(BEVY_OT_export_bsn.bl_idname, text="Bevy Scene (BSN)...", icon="EXPORT")
        exports = [(operator, label) for operator, label in ((BEVY_OT_export_glb, "GLB"), (BEVY_OT_export_bsn, "BSN")) if operator.remembered(context.scene)]
        if exports:
            column.separator()
        for operator, label in exports:
            column.prop(getattr(context.scene, operator._settings), "export_on_save", text="Export on Save" if len(exports) == 1 else f"Export {label} on Save")


class BEVY_UL_definitions(bpy.types.UIList):
    bl_idname = "BEVY_UL_definitions"

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0, flt_flag=0):
        layout.alert = item.name in invalid_names(definition.name for definition in data.definitions)
        layout.active = item.name not in game_types()
        layout.prop(item, "name", text="", emboss=False, icon=COMPONENT_LABELS["CUSTOM"][1])
        if not layout.active:
            layout.label(text="", icon="LINKED")


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
        _draw_game_status(layout)
        library = context.scene.bevy_component_definitions
        row = layout.row()
        row.template_list(BEVY_UL_definitions.bl_idname, "", library, "definitions", library, "active_index", rows=3)
        column = row.column(align=True)
        column.operator(BEVY_OT_definition_add.bl_idname, text="", icon="ADD")
        column.operator(BEVY_OT_definition_remove.bl_idname, text="", icon="REMOVE")
        if not 0 <= library.active_index < len(library.definitions):
            return
        definition = library.definitions[library.active_index]
        if definition.name in game_types():
            draw_message(layout, f"Your game defines {definition.name}, so objects use its fields instead of these", icon="INFO", width=context.region.width if context.region else 300)
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
        if field.field_type == "ENUM":
            body.prop(field, "variants")
            body.prop(field, "rust_type", text="Enum Type")
        body.prop(field, _field_property(field), text="Default")


def _draw_game_status(layout):
    schema = game_schema()
    row = layout.row()
    if schema["error"]:
        column = row.column()
        column.alert = True
        draw_message(column, schema["error"], width=bpy.context.region.width if bpy.context.region else 300)
    elif schema["path"] is None:
        row.active = False
        row.label(text="No game components found", icon="INFO")
    else:
        row.label(text=f"{len(schema['types'])} components from your game", icon="CHECKMARK")
    row.operator(BEVY_OT_reload_schema.bl_idname, text="", icon="FILE_REFRESH")


class BEVY_PT_scene_collision_layers(bpy.types.Panel):
    bl_label = "Bevy Collision Layers"
    bl_idname = "BEVY_PT_scene_collision_layers"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.active = False
        row.label(text="Names for the Collision Layers of Colliders")
        layers = context.scene.bevy_collision_layers
        grid = layout.grid_flow(row_major=False, columns=2, even_columns=True, align=True)
        for layer in range(LAYER_COUNT):
            grid.prop(layers, f"layer_{layer}", text=str(layer))


class BEVY_PT_world_sky(bpy.types.Panel):
    bl_label = "Bevy Sky"
    bl_idname = "BEVY_PT_world_sky"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "world"

    @classmethod
    def poll(cls, context):
        return context.world is not None

    def draw_header(self, context):
        self.layout.prop(context.world.bevy_sky, "enabled", text="")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        world = context.world
        settings = world.bevy_sky
        layout.active = settings.enabled
        width = context.region.width if context.region else 300
        check = sky_check(world)
        _draw_file(layout, check, settings, "sky_file", "Cubemap")
        if check.level == "WARNING":
            draw_message(layout, check.message, width=width)
        layout.prop(settings, "bake_resolution")
        layout.operator(BEVY_OT_bake_lighting.bl_idname, text="Bake", icon="RENDER_STILL").sky = True
        layout.prop(settings, "brightness")
        layout.prop(settings, "environment_light")
        row = layout.row()
        row.active = settings.environment_light
        row.prop(settings, "environment_intensity")
        if ambient_doubles_sky(world):
            draw_message(layout, f"{AMBIENT_WITH_SKY}. Turn Bevy Ambient Light off to light the scene with the sky alone", width=width)


class BEVY_PT_world_ambient_light(bpy.types.Panel):
    bl_label = "Bevy Ambient Light"
    bl_idname = "BEVY_PT_world_ambient_light"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "world"

    @classmethod
    def poll(cls, context):
        return context.world is not None

    def draw_header(self, context):
        self.layout.prop(context.world.bevy_ambient_light, "enabled", text="")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        world = context.world
        settings = world.bevy_ambient_light
        width = context.region.width if context.region else 300
        if ambient_doubles_sky(world):
            draw_message(layout, AMBIENT_WITH_SKY, width=width)
        elif not settings.enabled and sky_lights_scene(world):
            draw_message(layout, "Off, so the export sets Bevy's ambient light to 0 and the Bevy Sky's environment light lights the scene alone", icon="INFO", width=width)
        layout.active = settings.enabled
        layout.prop(settings, "use_world_color")
        if settings.use_world_color:
            background = world_background(world)
            if background is None:
                layout.prop(world, "color", text="Color")
                if world_color(world) is None:
                    draw_message(layout, "The World color comes from a texture or other nodes, so this uses its viewport color. Turn off From World to pick one", icon="INFO", width=width)
            else:
                layout.prop(background.inputs["Color"], "default_value", text="Color")
                layout.prop(background.inputs["Strength"], "default_value", text="Strength")
            _color, brightness = ambient_light(world)
            row = layout.row()
            row.active = False
            row.label(text=f"Bevy gets {light_amount(brightness, 'cd/m²')}")
        else:
            layout.prop(settings, "color")
            layout.prop(settings, "brightness")
        layout.prop(settings, "baked")


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
        column.prop(settings, "joints")
        column.prop(settings, "velocities")
        column.prop(settings, "visibility_ranges")
        column.prop(settings, "audio_ranges")
        column.prop(settings, "scene_references")
        column.prop(settings, "volumes")
        column.prop(settings, "lights")
        column.prop(settings, "navigation")
        column = split.column()
        column.prop(settings, "labels")
        column.prop(settings, "xray")
        column.prop(settings, "edit_handles")
        layout.prop(settings, "max_mesh_edges")
