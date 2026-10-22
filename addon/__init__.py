bl_info = {
    "name": "Bevy Components",
    "author": "Ask Indset",
    "version": (0, 3, 3),
    "blender": (4, 2, 0),
    "location": "Properties > Object > Bevy Components, 3D Viewport > Sidebar > Bevy, 3D Viewport > Overlays",
    "description": "Add Bevy components to objects, preview them in the viewport and export levels as GLB",
    "category": "Import-Export",
}

import bpy
from bpy.props import PointerProperty

from .gizmo import BEVY_GGT_collider_handles
from .menu import BEVY_MT_component_add, BEVY_MT_component_add_physics, BEVY_MT_component_add_rendering, BEVY_MT_component_context_menu, BEVY_MT_object_context_menu, export_menu
from .operator import BEVY_OT_add_component, BEVY_OT_copy_component_to_selected, BEVY_OT_copy_to_selected, BEVY_OT_duplicate_component, BEVY_OT_export_glb, BEVY_OT_lod_preset, BEVY_OT_move_component, BEVY_OT_remove_component, BEVY_OT_reset_component, BEVY_OT_validate
from .overlay import register_draw_handlers, unregister_draw_handlers
from .panel import BEVY_PT_object_properties, BEVY_PT_overlay, BEVY_PT_view_sidebar
from .preferences import BEVY_AP_preferences
from .property import BEVY_PG_component, BEVY_PG_object_data, BEVY_PG_viewport_settings
from .system import glTF2ExportUserExtension, save_sync, stop_panel_tracking

CLASSES = (BEVY_AP_preferences, BEVY_PG_component, BEVY_PG_object_data, BEVY_PG_viewport_settings, BEVY_OT_add_component, BEVY_OT_remove_component, BEVY_OT_duplicate_component, BEVY_OT_copy_component_to_selected, BEVY_OT_reset_component, BEVY_OT_move_component, BEVY_OT_lod_preset, BEVY_OT_copy_to_selected, BEVY_OT_validate, BEVY_OT_export_glb, BEVY_MT_component_add, BEVY_MT_component_add_physics, BEVY_MT_component_add_rendering, BEVY_MT_component_context_menu, BEVY_MT_object_context_menu, BEVY_PT_object_properties, BEVY_PT_view_sidebar, BEVY_PT_overlay, BEVY_GGT_collider_handles)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.bevy_component_data = PointerProperty(type=BEVY_PG_object_data)
    bpy.types.Scene.bevy_component_previews = PointerProperty(type=BEVY_PG_viewport_settings)
    bpy.types.TOPBAR_MT_file_export.append(export_menu)
    register_draw_handlers()
    if save_sync not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(save_sync)


def unregister():
    unregister_draw_handlers()
    stop_panel_tracking()
    if save_sync in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(save_sync)
    bpy.types.TOPBAR_MT_file_export.remove(export_menu)
    del bpy.types.Scene.bevy_component_previews
    del bpy.types.Object.bevy_component_data
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
