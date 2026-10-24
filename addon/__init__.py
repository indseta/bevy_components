bl_info = {
    "name": "Bevy Components",
    "author": "Ask Indset",
    "version": (0, 5, 0),
    "blender": (4, 2, 0),
    "location": "Properties > Object > Components, Properties > Physics > Rigid Body > Bevy, Properties > Scene > Bevy Custom Components, Properties > Collection > Bevy Components and Bevy Prefab, Properties > World > Bevy Sky and Bevy Ambient Light, 3D Viewport > Sidebar > Bevy, 3D Viewport > Object > Bevy Components, 3D Viewport > Overlays",
    "description": "Add Bevy components to objects, preview them in the viewport and export scenes as GLB or BSN",
    "category": "Import-Export",
}

import bpy
from bpy.props import PointerProperty

from .collection import collections_changed
from .gizmo import BEVY_GGT_audio_handles, BEVY_GGT_collider_handles, BEVY_GGT_light_handles, BEVY_GGT_range_handles, stop_drag_tracking
from .menu import BEVY_MT_component_add, BEVY_MT_component_add_game, BEVY_MT_component_add_lighting, BEVY_MT_component_add_physics, BEVY_MT_component_add_presets, BEVY_MT_component_add_rendering, BEVY_MT_component_context_menu, BEVY_MT_component_remove_presets, BEVY_MT_object_context_menu, BEVY_MT_object_menu, BEVY_MT_select_by_component, bake_status, export_menu, export_status, object_menu, play_status, select_menu, text_header
from .operator import BEVY_FH_glb, BEVY_OT_add_component, BEVY_OT_add_constraint, BEVY_OT_apply_preset, BEVY_OT_apply_text, BEVY_OT_bake_lighting, BEVY_OT_cancel_bake, BEVY_OT_cancel_export, BEVY_OT_convert_to_native, BEVY_OT_copy_component, BEVY_OT_copy_component_to_selected, BEVY_OT_copy_components, BEVY_OT_copy_to_selected, BEVY_OT_define_fields, BEVY_OT_definition_add, BEVY_OT_definition_remove, BEVY_OT_duplicate_component, BEVY_OT_edit_as_text, BEVY_OT_export_all_scenes, BEVY_OT_export_bsn, BEVY_OT_export_glb, BEVY_OT_field_add, BEVY_OT_field_move, BEVY_OT_field_remove, BEVY_OT_fit_collider, BEVY_OT_lod_preset, BEVY_OT_move_component, BEVY_OT_paste_components, BEVY_OT_pick_file, BEVY_OT_pick_sound, BEVY_OT_play, BEVY_OT_reload_schema, BEVY_OT_remove_component, BEVY_OT_remove_preset, BEVY_OT_reset_component, BEVY_OT_save_preset, BEVY_OT_select_by_component, BEVY_OT_select_object, BEVY_OT_set_collision_layers, BEVY_OT_show_collection, BEVY_OT_show_game_output, BEVY_OT_stop_game, BEVY_OT_unwrap_lightmap, BEVY_OT_validate, export_on_save, stop_bakes, stop_exports, stop_games
from .overlay import register_draw_handlers, unregister_draw_handlers
from .panel import BEVY_PT_collection_components, BEVY_PT_collection_prefab, BEVY_PT_light, BEVY_PT_light_probe, BEVY_PT_material_fog, BEVY_PT_object_properties, BEVY_PT_overlay, BEVY_PT_physics_collisions, BEVY_PT_physics_joint, BEVY_PT_physics_rigid_body, BEVY_PT_scene_collision_layers, BEVY_PT_scene_definitions, BEVY_PT_speaker, BEVY_PT_view_export, BEVY_PT_view_overview, BEVY_PT_view_play, BEVY_PT_view_sidebar, BEVY_PT_world_ambient_light, BEVY_PT_world_sky, BEVY_UL_definitions, BEVY_UL_fields, BEVY_UL_objects, draw_visibility
from .preferences import BEVY_AP_preferences
from .property import BEVY_PG_ambient_light, BEVY_PG_bake_settings, BEVY_PG_bsn_export, BEVY_PG_collision_layers, BEVY_PG_component, BEVY_PG_definition, BEVY_PG_definitions, BEVY_PG_field, BEVY_PG_fog, BEVY_PG_game, BEVY_PG_glb_export, BEVY_PG_light, BEVY_PG_object, BEVY_PG_object_data, BEVY_PG_overview, BEVY_PG_physics, BEVY_PG_prefab, BEVY_PG_probe, BEVY_PG_sky, BEVY_PG_speaker, BEVY_PG_viewport_settings
from .system import glTF2ExportUserExtension, load_game_types, problems_changed, save_sync, stop_panel_tracking, stop_schema_updates
from .validation import stop_problem_counts

CLASSES = (BEVY_AP_preferences, BEVY_PG_field, BEVY_PG_component, BEVY_PG_object_data, BEVY_PG_physics, BEVY_PG_object, BEVY_PG_light, BEVY_PG_speaker, BEVY_PG_fog, BEVY_PG_probe, BEVY_PG_collision_layers, BEVY_PG_definition, BEVY_PG_definitions, BEVY_PG_ambient_light, BEVY_PG_sky, BEVY_PG_game, BEVY_PG_bake_settings, BEVY_PG_glb_export, BEVY_PG_bsn_export, BEVY_PG_prefab, BEVY_PG_overview, BEVY_PG_viewport_settings, BEVY_OT_add_component, BEVY_OT_remove_component, BEVY_OT_duplicate_component, BEVY_OT_copy_component_to_selected, BEVY_OT_reset_component, BEVY_OT_move_component, BEVY_OT_lod_preset, BEVY_OT_set_collision_layers, BEVY_OT_fit_collider, BEVY_OT_pick_sound, BEVY_OT_pick_file, BEVY_OT_define_fields, BEVY_OT_reload_schema, BEVY_OT_definition_add, BEVY_OT_definition_remove, BEVY_OT_field_add, BEVY_OT_field_remove, BEVY_OT_field_move, BEVY_OT_copy_to_selected, BEVY_OT_copy_component, BEVY_OT_copy_components, BEVY_OT_paste_components, BEVY_OT_save_preset, BEVY_OT_apply_preset, BEVY_OT_remove_preset, BEVY_OT_edit_as_text, BEVY_OT_apply_text, BEVY_OT_select_by_component, BEVY_OT_select_object, BEVY_OT_show_collection, BEVY_OT_validate, BEVY_OT_convert_to_native, BEVY_OT_add_constraint, BEVY_OT_cancel_export, BEVY_OT_export_glb, BEVY_OT_export_bsn, BEVY_OT_export_all_scenes, BEVY_FH_glb, BEVY_OT_unwrap_lightmap, BEVY_OT_cancel_bake, BEVY_OT_bake_lighting, BEVY_OT_stop_game, BEVY_OT_show_game_output, BEVY_OT_play, BEVY_MT_component_add, BEVY_MT_component_add_game, BEVY_MT_component_add_physics, BEVY_MT_component_add_rendering, BEVY_MT_component_add_lighting, BEVY_MT_component_add_presets, BEVY_MT_component_remove_presets, BEVY_MT_component_context_menu, BEVY_MT_object_context_menu, BEVY_MT_object_menu, BEVY_MT_select_by_component, BEVY_UL_definitions, BEVY_UL_fields, BEVY_UL_objects, BEVY_PT_object_properties, BEVY_PT_view_sidebar, BEVY_PT_view_overview, BEVY_PT_view_export, BEVY_PT_view_play, BEVY_PT_scene_definitions, BEVY_PT_scene_collision_layers, BEVY_PT_collection_components, BEVY_PT_collection_prefab, BEVY_PT_world_sky, BEVY_PT_world_ambient_light, BEVY_PT_physics_rigid_body, BEVY_PT_physics_collisions, BEVY_PT_physics_joint, BEVY_PT_light, BEVY_PT_speaker, BEVY_PT_light_probe, BEVY_PT_material_fog, BEVY_PT_overlay, BEVY_GGT_collider_handles, BEVY_GGT_range_handles, BEVY_GGT_light_handles, BEVY_GGT_audio_handles)
HANDLERS = ("depsgraph_update_post", "undo_post", "redo_post", "load_post")
VISIBILITY_PANELS = ("OBJECT_PT_visibility", "CYCLES_OBJECT_PT_visibility")


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.bevy_component_data = PointerProperty(type=BEVY_PG_object_data)
    bpy.types.Object.bevy_physics = PointerProperty(type=BEVY_PG_physics)
    bpy.types.Object.bevy_object = PointerProperty(type=BEVY_PG_object)
    bpy.types.Light.bevy_light = PointerProperty(type=BEVY_PG_light)
    bpy.types.Speaker.bevy_speaker = PointerProperty(type=BEVY_PG_speaker)
    bpy.types.LightProbe.bevy_probe = PointerProperty(type=BEVY_PG_probe)
    bpy.types.Material.bevy_fog = PointerProperty(type=BEVY_PG_fog)
    bpy.types.Scene.bevy_component_previews = PointerProperty(type=BEVY_PG_viewport_settings)
    bpy.types.Scene.bevy_component_definitions = PointerProperty(type=BEVY_PG_definitions)
    bpy.types.Scene.bevy_collision_layers = PointerProperty(type=BEVY_PG_collision_layers)
    bpy.types.Scene.bevy_bake_settings = PointerProperty(type=BEVY_PG_bake_settings)
    bpy.types.Scene.bevy_glb_export = PointerProperty(type=BEVY_PG_glb_export)
    bpy.types.Scene.bevy_bsn_export = PointerProperty(type=BEVY_PG_bsn_export)
    bpy.types.Scene.bevy_component_overview = PointerProperty(type=BEVY_PG_overview)
    bpy.types.Scene.bevy_game = PointerProperty(type=BEVY_PG_game)
    bpy.types.World.bevy_ambient_light = PointerProperty(type=BEVY_PG_ambient_light)
    bpy.types.World.bevy_sky = PointerProperty(type=BEVY_PG_sky)
    bpy.types.Collection.bevy_component_data = PointerProperty(type=BEVY_PG_object_data)
    bpy.types.Collection.bevy_prefab = PointerProperty(type=BEVY_PG_prefab)
    bpy.types.TOPBAR_MT_file_export.append(export_menu)
    bpy.types.STATUSBAR_HT_header.prepend(export_status)
    bpy.types.STATUSBAR_HT_header.prepend(bake_status)
    bpy.types.STATUSBAR_HT_header.prepend(play_status)
    bpy.types.VIEW3D_MT_object.append(object_menu)
    bpy.types.VIEW3D_MT_object_context_menu.append(object_menu)
    bpy.types.VIEW3D_MT_select_object.append(select_menu)
    bpy.types.TEXT_HT_header.append(text_header)
    for name in VISIBILITY_PANELS:
        if hasattr(bpy.types, name):
            getattr(bpy.types, name).append(draw_visibility)
    register_draw_handlers()
    if save_sync not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(save_sync)
    if load_game_types not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_game_types)
    if export_on_save not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(export_on_save)
    for name in HANDLERS:
        for handler in (problems_changed, collections_changed):
            if handler not in getattr(bpy.app.handlers, name):
                getattr(bpy.app.handlers, name).append(handler)


def unregister():
    stop_exports()
    stop_bakes()
    stop_games()
    unregister_draw_handlers()
    stop_panel_tracking()
    stop_schema_updates()
    stop_drag_tracking()
    if load_game_types in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_game_types)
    if export_on_save in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.remove(export_on_save)
    stop_problem_counts()
    for name in HANDLERS:
        for handler in (problems_changed, collections_changed):
            if handler in getattr(bpy.app.handlers, name):
                getattr(bpy.app.handlers, name).remove(handler)
    if save_sync in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(save_sync)
    for name in VISIBILITY_PANELS:
        if hasattr(bpy.types, name):
            getattr(bpy.types, name).remove(draw_visibility)
    bpy.types.TEXT_HT_header.remove(text_header)
    bpy.types.VIEW3D_MT_select_object.remove(select_menu)
    bpy.types.VIEW3D_MT_object_context_menu.remove(object_menu)
    bpy.types.VIEW3D_MT_object.remove(object_menu)
    bpy.types.STATUSBAR_HT_header.remove(play_status)
    bpy.types.STATUSBAR_HT_header.remove(bake_status)
    bpy.types.STATUSBAR_HT_header.remove(export_status)
    bpy.types.TOPBAR_MT_file_export.remove(export_menu)
    del bpy.types.Collection.bevy_prefab
    del bpy.types.Collection.bevy_component_data
    del bpy.types.World.bevy_sky
    del bpy.types.World.bevy_ambient_light
    del bpy.types.Scene.bevy_game
    del bpy.types.Scene.bevy_component_overview
    del bpy.types.Scene.bevy_bsn_export
    del bpy.types.Scene.bevy_glb_export
    del bpy.types.Scene.bevy_bake_settings
    del bpy.types.Scene.bevy_collision_layers
    del bpy.types.Scene.bevy_component_definitions
    del bpy.types.Scene.bevy_component_previews
    del bpy.types.Material.bevy_fog
    del bpy.types.LightProbe.bevy_probe
    del bpy.types.Speaker.bevy_speaker
    del bpy.types.Light.bevy_light
    del bpy.types.Object.bevy_object
    del bpy.types.Object.bevy_physics
    del bpy.types.Object.bevy_component_data
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
