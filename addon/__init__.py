bl_info = {
    "name": "Bevy Components",
    "author": "Ask Indset",
    "version": (0, 4, 0),
    "blender": (4, 2, 0),
    "location": "Properties > Object > Components, Properties > Scene > Bevy Custom Components, Properties > World > Bevy Ambient Light, 3D Viewport > Sidebar > Bevy, 3D Viewport > Overlays",
    "description": "Add Bevy components to objects, preview them in the viewport and export scenes as GLB or BSN",
    "category": "Import-Export",
}

import bpy
from bpy.props import PointerProperty

from .gizmo import BEVY_GGT_audio_handles, BEVY_GGT_collider_handles
from .menu import BEVY_MT_component_add, BEVY_MT_component_add_animation, BEVY_MT_component_add_audio, BEVY_MT_component_add_game, BEVY_MT_component_add_physics, BEVY_MT_component_add_rendering, BEVY_MT_component_add_scene, BEVY_MT_component_context_menu, BEVY_MT_object_context_menu, bake_status, export_menu, export_status
from .operator import BEVY_OT_add_component, BEVY_OT_bake_lighting, BEVY_OT_cancel_bake, BEVY_OT_cancel_export, BEVY_OT_copy_component_to_selected, BEVY_OT_copy_to_selected, BEVY_OT_define_fields, BEVY_OT_definition_add, BEVY_OT_definition_remove, BEVY_OT_duplicate_component, BEVY_OT_export_bsn, BEVY_OT_export_glb, BEVY_OT_field_add, BEVY_OT_field_move, BEVY_OT_field_remove, BEVY_OT_lod_preset, BEVY_OT_move_component, BEVY_OT_pick_sound, BEVY_OT_reload_schema, BEVY_OT_remove_component, BEVY_OT_reset_component, BEVY_OT_select_object, BEVY_OT_set_collision_layers, BEVY_OT_unwrap_lightmap, BEVY_OT_validate, stop_bakes, stop_exports
from .overlay import register_draw_handlers, unregister_draw_handlers
from .panel import BEVY_PT_object_properties, BEVY_PT_overlay, BEVY_PT_scene_definitions, BEVY_PT_view_export, BEVY_PT_view_sidebar, BEVY_PT_world_ambient_light, BEVY_UL_definitions, BEVY_UL_fields
from .preferences import BEVY_AP_preferences
from .property import BEVY_PG_ambient_light, BEVY_PG_bake_settings, BEVY_PG_bsn_export, BEVY_PG_component, BEVY_PG_definition, BEVY_PG_definitions, BEVY_PG_field, BEVY_PG_glb_export, BEVY_PG_object_data, BEVY_PG_viewport_settings
from .system import glTF2ExportUserExtension, load_game_types, save_sync, stop_panel_tracking, stop_schema_updates

CLASSES = (BEVY_AP_preferences, BEVY_PG_field, BEVY_PG_component, BEVY_PG_object_data, BEVY_PG_definition, BEVY_PG_definitions, BEVY_PG_ambient_light, BEVY_PG_bake_settings, BEVY_PG_glb_export, BEVY_PG_bsn_export, BEVY_PG_viewport_settings, BEVY_OT_add_component, BEVY_OT_remove_component, BEVY_OT_duplicate_component, BEVY_OT_copy_component_to_selected, BEVY_OT_reset_component, BEVY_OT_move_component, BEVY_OT_lod_preset, BEVY_OT_set_collision_layers, BEVY_OT_pick_sound, BEVY_OT_define_fields, BEVY_OT_reload_schema, BEVY_OT_definition_add, BEVY_OT_definition_remove, BEVY_OT_field_add, BEVY_OT_field_remove, BEVY_OT_field_move, BEVY_OT_copy_to_selected, BEVY_OT_select_object, BEVY_OT_validate, BEVY_OT_cancel_export, BEVY_OT_export_glb, BEVY_OT_export_bsn, BEVY_OT_unwrap_lightmap, BEVY_OT_cancel_bake, BEVY_OT_bake_lighting, BEVY_MT_component_add, BEVY_MT_component_add_game, BEVY_MT_component_add_physics, BEVY_MT_component_add_rendering, BEVY_MT_component_add_audio, BEVY_MT_component_add_animation, BEVY_MT_component_add_scene, BEVY_MT_component_context_menu, BEVY_MT_object_context_menu, BEVY_UL_definitions, BEVY_UL_fields, BEVY_PT_object_properties, BEVY_PT_view_sidebar, BEVY_PT_view_export, BEVY_PT_scene_definitions, BEVY_PT_world_ambient_light, BEVY_PT_overlay, BEVY_GGT_collider_handles, BEVY_GGT_audio_handles)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.bevy_component_data = PointerProperty(type=BEVY_PG_object_data)
    bpy.types.Scene.bevy_component_previews = PointerProperty(type=BEVY_PG_viewport_settings)
    bpy.types.Scene.bevy_component_definitions = PointerProperty(type=BEVY_PG_definitions)
    bpy.types.Scene.bevy_bake_settings = PointerProperty(type=BEVY_PG_bake_settings)
    bpy.types.Scene.bevy_glb_export = PointerProperty(type=BEVY_PG_glb_export)
    bpy.types.Scene.bevy_bsn_export = PointerProperty(type=BEVY_PG_bsn_export)
    bpy.types.World.bevy_ambient_light = PointerProperty(type=BEVY_PG_ambient_light)
    bpy.types.TOPBAR_MT_file_export.append(export_menu)
    bpy.types.STATUSBAR_HT_header.prepend(export_status)
    bpy.types.STATUSBAR_HT_header.prepend(bake_status)
    register_draw_handlers()
    if save_sync not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(save_sync)
    if load_game_types not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_game_types)


def unregister():
    stop_exports()
    stop_bakes()
    unregister_draw_handlers()
    stop_panel_tracking()
    stop_schema_updates()
    if load_game_types in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_game_types)
    if save_sync in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(save_sync)
    bpy.types.STATUSBAR_HT_header.remove(bake_status)
    bpy.types.STATUSBAR_HT_header.remove(export_status)
    bpy.types.TOPBAR_MT_file_export.remove(export_menu)
    del bpy.types.World.bevy_ambient_light
    del bpy.types.Scene.bevy_bsn_export
    del bpy.types.Scene.bevy_glb_export
    del bpy.types.Scene.bevy_bake_settings
    del bpy.types.Scene.bevy_component_definitions
    del bpy.types.Scene.bevy_component_previews
    del bpy.types.Object.bevy_component_data
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
