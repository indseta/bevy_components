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
    return obj.bevy_component_data.components


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
    if len(data.components):
        try:
            obj[EXTRAS_KEY] = serialize_items(data.components)
        except ValueError:
            obj.pop(EXTRAS_KEY, None)
    else:
        obj.pop(EXTRAS_KEY, None)


def sync_changed(self, context):
    obj = getattr(self, "id_data", None)
    if isinstance(obj, bpy.types.Object):
        sync_object(obj)
        redraw_viewports()


@persistent
def save_sync(_scene):
    for obj in bpy.data.objects:
        sync_object(obj)
