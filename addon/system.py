import bpy
from bpy.app.handlers import persistent

from .metadata import EXTRAS_KEY, serialize_items


def redraw_viewports(_self=None, _context=None):
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def components_for(obj):
    if not hasattr(obj, "bevy_component_data"):
        return []
    return [item for item in obj.bevy_component_data.components if item.enabled]


def component_of(obj, kind):
    for item in components_for(obj):
        if item.component_type == kind:
            return item
    return None


def sync_object(obj):
    if not obj or not isinstance(obj, bpy.types.Object) or obj.library:
        return
    data = getattr(obj, "bevy_component_data", None)
    if not data:
        return
    items = components_for(obj)
    if items:
        try:
            obj[EXTRAS_KEY] = serialize_items(items)
        except ValueError:
            obj.pop(EXTRAS_KEY, None)
    else:
        obj.pop(EXTRAS_KEY, None)


def component_index(obj, item):
    for index, other in enumerate(obj.bevy_component_data.components):
        if other == item:
            return index
    return -1


def copy_component(source, destination):
    for field in source.bl_rna.properties:
        if field.identifier in {"rna_type", "id_data"} or field.is_readonly:
            continue
        value = getattr(source, field.identifier)
        try:
            setattr(destination, field.identifier, tuple(value) if field.type == "FLOAT" and field.is_array else value)
        except (TypeError, AttributeError):
            continue


def sync_changed(self, context):
    obj = getattr(self, "id_data", None)
    if isinstance(obj, bpy.types.Object):
        sync_object(obj)
        redraw_viewports()


@persistent
def save_sync(_scene):
    for obj in bpy.data.objects:
        sync_object(obj)


class glTF2ExportUserExtension:
    def gather_node_hook(self, gltf2_node, _blender_object, _export_settings):
        _remove_extra(gltf2_node, "bevy_component_data")

    def gather_scene_hook(self, gltf2_scene, _blender_scene, _export_settings):
        _remove_extra(gltf2_scene, "bevy_component_previews")


def _remove_extra(gltf2_element, key):
    if isinstance(gltf2_element.extras, dict):
        gltf2_element.extras.pop(key, None)
        if not gltf2_element.extras:
            gltf2_element.extras = None
