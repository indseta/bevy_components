import bpy

from .operator import BEVY_OT_add_component, BEVY_OT_copy_component_to_selected, BEVY_OT_copy_to_selected, BEVY_OT_duplicate_component, BEVY_OT_export_glb, BEVY_OT_move_component, BEVY_OT_remove_component, BEVY_OT_reset_component, BEVY_OT_validate
from .property import COMPONENT_LABELS
from .system import component_index


def _draw_add_items(layout, obj, kinds):
    present = {item.component_type for item in obj.bevy_component_data.components} if obj else set()
    for kind in kinds:
        text, icon = COMPONENT_LABELS[kind]
        column = layout.column()
        column.enabled = kind == "CUSTOM" or kind not in present
        column.operator(BEVY_OT_add_component.bl_idname, text=text, icon=icon).component_type = kind


class BEVY_MT_component_add(bpy.types.Menu):
    bl_idname = "BEVY_MT_component_add"
    bl_label = "Add Component"
    bl_options = {"SEARCH_ON_KEY_PRESS"}

    def draw(self, context):
        layout = self.layout
        _draw_add_items(layout, context.object, ("CUSTOM",))
        layout.separator()
        layout.menu(BEVY_MT_component_add_physics.bl_idname)
        layout.menu(BEVY_MT_component_add_rendering.bl_idname)
        layout.menu(BEVY_MT_component_add_gameplay.bl_idname)


class BEVY_MT_component_add_physics(bpy.types.Menu):
    bl_idname = "BEVY_MT_component_add_physics"
    bl_label = "Physics"
    bl_options = {"SEARCH_ON_KEY_PRESS"}

    def draw(self, context):
        _draw_add_items(self.layout, context.object, ("COLLIDER", "RIGID_BODY"))


class BEVY_MT_component_add_rendering(bpy.types.Menu):
    bl_idname = "BEVY_MT_component_add_rendering"
    bl_label = "Rendering"
    bl_options = {"SEARCH_ON_KEY_PRESS"}

    def draw(self, context):
        _draw_add_items(self.layout, context.object, ("VISIBILITY_RANGE",))


class BEVY_MT_component_add_gameplay(bpy.types.Menu):
    bl_idname = "BEVY_MT_component_add_gameplay"
    bl_label = "Gameplay"
    bl_options = {"SEARCH_ON_KEY_PRESS"}

    def draw(self, context):
        _draw_add_items(self.layout, context.object, ("SPAWN_POINT",))


class BEVY_MT_component_context_menu(bpy.types.Menu):
    bl_idname = "BEVY_MT_component_context_menu"
    bl_label = "Component"

    def draw(self, context):
        layout = self.layout
        obj = context.object
        item = getattr(context, "bevy_component", None)
        if obj is None or item is None:
            return
        index = component_index(obj, item)
        last = len(obj.bevy_component_data.components) - 1
        column = layout.column()
        column.enabled = item.component_type == "CUSTOM"
        column.operator(BEVY_OT_duplicate_component.bl_idname, text="Duplicate", icon="DUPLICATE").index = index
        layout.operator(BEVY_OT_copy_component_to_selected.bl_idname, text="Copy to Selected", icon="COPYDOWN").index = index
        layout.separator()
        layout.operator(BEVY_OT_reset_component.bl_idname, text="Reset to Defaults", icon="LOOP_BACK").index = index
        layout.separator()
        for direction, text, icon, enabled in (("FIRST", "Move to First", "TRIA_UP_BAR", index > 0), ("UP", "Move Up", "TRIA_UP", index > 0), ("DOWN", "Move Down", "TRIA_DOWN", index < last), ("LAST", "Move to Last", "TRIA_DOWN_BAR", index < last)):
            column = layout.column()
            column.enabled = enabled
            button = column.operator(BEVY_OT_move_component.bl_idname, text=text, icon=icon)
            button.index = index
            button.direction = direction
        layout.separator()
        layout.operator(BEVY_OT_remove_component.bl_idname, text="Remove", icon="X").index = index


class BEVY_MT_object_context_menu(bpy.types.Menu):
    bl_idname = "BEVY_MT_object_context_menu"
    bl_label = "Bevy Components"

    def draw(self, context):
        layout = self.layout
        layout.operator(BEVY_OT_copy_to_selected.bl_idname, text="Copy All to Selected", icon="COPYDOWN")
        layout.separator()
        layout.operator(BEVY_OT_validate.bl_idname, text="Validate All Objects", icon="CHECKMARK")
        layout.operator(BEVY_OT_export_glb.bl_idname, text="Export Bevy Level (.glb)...", icon="EXPORT")


def export_menu(self, context):
    self.layout.operator(BEVY_OT_export_glb.bl_idname, text="Bevy Level (.glb)")
