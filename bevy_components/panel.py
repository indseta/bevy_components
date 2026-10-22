import bpy

from .metadata import validate_items
from .operator import BEVY_OT_export_glb


def draw_component_cards(layout, obj):
    items = obj.bevy_component_data.components
    row = layout.row(align=True)
    row.label(text=f"{len(items)} component(s)")
    row.operator("bevy_components.add", text="Add Component", icon="ADD")
    if not items:
        layout.label(text="Use Add Component to begin", icon="INFO")
    for index, item in enumerate(items):
        title, icon = {
            "VISIBILITY_RANGE": ("Visibility Range", "HIDE_OFF"),
            "COLLIDER": ("Collider", "MESH_ICOSPHERE"),
            "RIGID_BODY": ("Rigid Body", "PHYSICS"),
            "SPAWN_POINT": ("Spawn Point", "EMPTY_AXIS"),
            "CUSTOM": (item.custom_type or "Custom Component", "FILE_SCRIPT"),
        }[item.component_type]
        card = layout.box()
        header = card.row(align=True)
        header.prop(item, "expanded", icon="TRIA_DOWN" if item.expanded else "TRIA_RIGHT", text="", emboss=False)
        header.label(text=title, icon=icon)
        button = header.operator("bevy_components.remove", icon="X", text="", emboss=False)
        button.index = index
        if not item.expanded:
            continue
        column = card.column(align=True)
        if item.component_type == "VISIBILITY_RANGE":
            column.label(text="LOD presets (matched crossfades)")
            preset_row = column.row(align=True)
            for preset, name in (("NEAR", "LOD0"), ("MID", "LOD1"), ("FAR", "LOD2")):
                button = preset_row.operator("bevy_components.lod_preset", text=name)
                button.index = index
                button.preset = preset
            column.separator(factor=0.5)
            column.label(text="Fade In (meters)")
            row = column.row(align=True)
            row.prop(item, "fade_in_start", text="Start")
            row.prop(item, "fade_in_end", text="End")
            column.label(text="Fade Out (meters)")
            row = column.row(align=True)
            row.prop(item, "fade_out_start", text="Start")
            row.prop(item, "fade_out_end", text="End")
            column.prop(item, "use_aabb")
            if validate_items([item], obj.name):
                column.label(text="Distances must be ordered", icon="ERROR")
        elif item.component_type == "COLLIDER":
            column.prop(item, "collider_shape")
            if item.collider_shape == "CUBOID":
                column.prop(item, "collider_size")
                column.label(text="Bevy local axes: X, Y (up), Z", icon="INFO")
            elif item.collider_shape == "SPHERE":
                column.prop(item, "collider_radius")
            elif item.collider_shape == "CAPSULE":
                column.prop(item, "collider_radius")
                column.prop(item, "collider_height")
            else:
                column.label(text="Derived from imported mesh geometry", icon="INFO")
            column.prop(item, "collider_sensor")
            if item.collider_shape == "TRIMESH":
                column.label(text="Use only for static bodies", icon="INFO")
        elif item.component_type == "RIGID_BODY":
            column.prop(item, "rigid_body_kind")
        elif item.component_type == "SPAWN_POINT":
            column.prop(item, "spawn_tag")
        elif item.component_type == "CUSTOM":
            column.prop(item, "custom_type")
            column.prop(item, "custom_json")
            column.label(text="Custom data requires your game-side handler", icon="INFO")
    if items:
        layout.separator()
        row = layout.row(align=True)
        row.operator("bevy_components.copy_to_selected", text="Copy to Selected", icon="DUPLICATE")
        row.operator("bevy_components.validate", text="Validate", icon="CHECKMARK")
    layout.separator()
    if hasattr(bpy.context, "scene") and bpy.context.scene:
        preview = layout.box()
        preview.label(text="3D Viewport Preview", icon="SHADING_WIRE")
        preview.prop(bpy.context.scene.bevy_component_previews, "enabled")
        preview.label(text="More controls: 3D View > N > Bevy")
    layout.operator("export_scene.bevy_components_glb", text="Export Level (.glb)", icon="EXPORT")


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


def export_menu(self, context):
    self.layout.operator(BEVY_OT_export_glb.bl_idname, text="Bevy Level (.glb)")


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
        draw_component_cards(self.layout, context.object)


class BEVY_PT_view_sidebar(bpy.types.Panel):
    bl_label = "Bevy Components"
    bl_idname = "BEVY_PT_view_sidebar"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bevy"

    def draw(self, context):
        obj = context.object
        if obj is None:
            self.layout.label(text="Select an object", icon="INFO")
            return
        draw_component_cards(self.layout, obj)


class BEVY_PT_viewport_previews(bpy.types.Panel):
    bl_label = "Viewport Previews"
    bl_idname = "BEVY_PT_viewport_previews"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bevy"
    bl_order = 1

    def draw(self, context):
        draw_viewport_controls(self.layout, context)
