import mimetypes
import tempfile
from pathlib import Path

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix

from .metadata import EXTRAS_KEY, serialize_items

MESH_TYPES = {"MESH", "CURVE", "SURFACE", "FONT"}
PANEL_EXPANDED = True
PANEL_DRAWN_EXPANDED = True


def redraw_viewports(_self=None, _context=None):
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def panel_expanded():
    return PANEL_EXPANDED


def panel_header_drawn():
    global PANEL_DRAWN_EXPANDED
    PANEL_DRAWN_EXPANDED = False
    if not bpy.app.timers.is_registered(_apply_panel_state):
        bpy.app.timers.register(_apply_panel_state, first_interval=0.0)


def panel_body_drawn():
    global PANEL_DRAWN_EXPANDED
    PANEL_DRAWN_EXPANDED = True


def _apply_panel_state():
    global PANEL_EXPANDED
    if PANEL_EXPANDED != PANEL_DRAWN_EXPANDED:
        PANEL_EXPANDED = PANEL_DRAWN_EXPANDED
        redraw_viewports()
    return None


def stop_panel_tracking():
    if bpy.app.timers.is_registered(_apply_panel_state):
        bpy.app.timers.unregister(_apply_panel_state)


def components_for(obj):
    if not hasattr(obj, "bevy_component_data"):
        return []
    return [item for item in obj.bevy_component_data.components if item.enabled and item.component_type]


def component_of(obj, kind):
    for item in components_for(obj):
        if item.component_type == kind:
            return item
    return None


def inherited(obj, kind):
    while obj is not None:
        item = component_of(obj, kind)
        if item is not None:
            return obj, item
        obj = obj.parent
    return None, None


def children_map(objects):
    children = {}
    for obj in objects:
        if obj.parent is not None:
            children.setdefault(obj.parent, []).append(obj)
    return children


def subtree(obj, children, stop, instances=True):
    found = []
    pending = [(obj, None, children)]
    while pending:
        current, space, lookup = pending.pop()
        matrix = current.matrix_world if space is None else space @ current.matrix_world
        found.append((current, matrix))
        branches = [(child, space, lookup) for child in lookup.get(current, ())]
        collection = current.instance_collection if instances and current.instance_type == "COLLECTION" else None
        if collection is not None:
            members = set(collection.all_objects)
            inner = matrix @ Matrix.Translation(-collection.instance_offset)
            branches.extend((member, inner, children_map(members)) for member in members if member.parent not in members)
        pending.extend(branch for branch in branches if not stop(branch[0]))
    return found


def has_faces(obj):
    return obj.type in MESH_TYPES and (obj.type != "MESH" or len(obj.data.polygons) > 0)


def mesh_sources(obj, children, kind, instances=True):
    return [(source, matrix) for source, matrix in subtree(obj, children, lambda child: component_of(child, kind) is not None, instances) if has_faces(source)]


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


def image_to_png(data, mime_type):
    with tempfile.TemporaryDirectory(prefix="bevy_components_") as directory:
        source = Path(directory) / f"source{mimetypes.guess_extension(mime_type) or '.image'}"
        target = Path(directory) / "image.png"
        source.write_bytes(data)
        image = bpy.data.images.load(str(source), check_existing=False)
        try:
            image.filepath_raw = str(target)
            image.file_format = "PNG"
            image.save()
        finally:
            bpy.data.images.remove(image)
        return target.read_bytes()


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
