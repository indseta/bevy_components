import hashlib
import json
import os
import time
from array import array
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

from .files import snake_case
from .metadata import EXTRAS_KEY, SCHEMA_VERSION, addon_version, relative_path, serialize_items

FINGERPRINT_VERSION = 1
SCENE_NAME = "Bevy Prefab Export"
PREFAB_OPTIONS = ("include_lights", "include_cameras", "include_animations", "apply_modifiers", "texture_compression", "etc1s_quality", "etc1s_effort", "uastc_quality", "uastc_zstd")
NUMBERS = {"BOOLEAN", "INT", "FLOAT"}
SKIPPED = {"rna_type", "name_full", "original", "users", "session_uid", "tag", "is_evaluated", "is_runtime_data", "is_missing", "is_embedded_data", "is_library_indirect", "library", "library_weak_reference", "override_library", "preview", "use_fake_user", "use_extra_user", "is_dirty", "bindcode", "pixels", "select", "location", "width", "height", "dimensions", "node", "links", "internal_links", "parent", "asset_data", "users_collection", "users_scene", "bl_rna"}
MESH_ARRAYS = (
    ("vertices", "co", "f", 3),
    ("loops", "vertex_index", "i", 1),
    ("polygons", "loop_total", "i", 1),
    ("polygons", "material_index", "i", 1),
    ("corner_normals", "vector", "f", 3),
)

Export = namedtuple("Export", ("prefabs", "dropped", "directory", "scene", "collection"))

_active = None
_records = {}


def enabled_prefabs():
    return {collection for collection in bpy.data.collections if collection.bevy_prefab.enabled}


def prefab_of(obj):
    collection = obj.instance_collection if isinstance(obj, bpy.types.Object) and obj.instance_type == "COLLECTION" else None
    return collection if collection is not None and collection.bevy_prefab.enabled else None


def prefab_members(prefabs=None):
    return {obj for collection in (enabled_prefabs() if prefabs is None else prefabs) for obj in collection.all_objects}


def prefab_owner(obj):
    return next((collection for collection in sorted(enabled_prefabs(), key=lambda collection: collection.name_full) if any(member == obj for member in collection.all_objects)), None)


def prefab_instances(collection):
    return [obj for obj in bpy.data.objects if obj.instance_type == "COLLECTION" and obj.instance_collection == collection]


def prefab_toggled(self, context):
    collection = self.id_data
    scene = getattr(context, "scene", None)
    level = scene.bevy_glb_export.filepath.strip() if scene is not None and hasattr(scene, "bevy_glb_export") else ""
    if not self.enabled or self.filepath.strip() or not level or collection.library is not None:
        return
    path = Path(os.path.abspath(bpy.path.abspath(level))).parent / "prefabs" / f"{snake_case(collection.name) or 'prefab'}.glb"
    try:
        self.filepath = bpy.path.relpath(str(path)) if bpy.data.filepath else str(path)
    except ValueError:
        self.filepath = str(path)


def find_collection(name):
    return next((collection for collection in bpy.data.collections if collection.name_full == name), None) or bpy.data.collections.get(name)


def prefab_file(collection):
    path = collection.bevy_prefab.filepath.strip()
    return Path(os.path.abspath(bpy.path.abspath(path, library=collection.library))) if path else None


def instances(objects):
    found = {}
    for obj in objects:
        collection = prefab_of(obj)
        if collection is not None:
            found.setdefault(collection, []).append(obj)
    return found


def prefab_order(objects):
    order = []
    done = set()
    cycles = []
    for collection in instances(objects):
        if collection not in done:
            _visit(collection, [], order, done, cycles)
    return order, cycles


def _visit(collection, chain, order, done, cycles):
    chain.append(collection)
    for nested, objects in instances(collection.all_objects).items():
        if nested in chain:
            cycles.append((objects[0], chain[chain.index(nested):] + [nested]))
        elif nested not in done:
            _visit(nested, chain, order, done, cycles)
    chain.pop()
    done.add(collection)
    order.append(collection)


def prefab_settings(options):
    return {name: getattr(options, name) for name in PREFAB_OPTIONS}


def prefab_fingerprint(collection, settings, scene):
    digest = hashlib.sha256()
    seen = {}
    _update(digest, (FINGERPRINT_VERSION, SCHEMA_VERSION, addon_version(), str(prefab_file(collection)), tuple(collection.instance_offset), sorted(settings.items())))
    animated = False
    for obj in sorted(collection.all_objects, key=lambda obj: obj.name_full):
        if obj.mode == "EDIT":
            obj.update_from_editmode()
        animated = _object_digest(obj, digest, seen) or animated
    if animated:
        _update(digest, (scene.frame_current, scene.render.fps, scene.render.fps_base))
    return digest.hexdigest()[:16]


def prefab_fresh(collection, target, fingerprint):
    try:
        stat = target.stat()
    except OSError:
        return False
    return _record(collection) == {"fingerprint": fingerprint, "size": stat.st_size, "mtime": stat.st_mtime_ns}


def remember_prefab(collection, target, fingerprint):
    stat = target.stat()
    record = {"fingerprint": fingerprint, "size": stat.st_size, "mtime": stat.st_mtime_ns}
    if collection.library is None:
        collection.bevy_prefab.exported = json.dumps(record, sort_keys=True)
    else:
        _records[collection.name_full] = record


def _record(collection):
    if collection.library is not None:
        return _records.get(collection.name_full)
    try:
        return json.loads(collection.bevy_prefab.exported or "{}")
    except ValueError:
        return None


def _update(digest, value):
    digest.update(repr(value).encode("utf-8") + b"\0")


def _flat(value):
    try:
        return tuple(_flat(item) for item in value)
    except TypeError:
        return value


def _id_properties(owner, skipped=()):
    values = []
    for key in sorted(owner.keys()):
        if key in skipped:
            continue
        value = owner[key]
        values.append((key, value.to_dict() if hasattr(value, "to_dict") else value.to_list() if hasattr(value, "to_list") else _identity(value, {}) if isinstance(value, bpy.types.ID) else value))
    return tuple(values)


def _components(obj):
    items = [item for item in obj.bevy_component_data.components if item.enabled and item.component_type]
    try:
        return serialize_items(items, lambda path: str(Path(os.path.abspath(bpy.path.abspath(path, library=obj.library)))) if path.strip() else "")
    except ValueError as error:
        return str(error)


def _object_digest(obj, digest, seen):
    nested = prefab_of(obj)
    parent = obj.parent.name_full if obj.parent else None
    _update(digest, (obj.name_full, obj.type, parent, obj.parent_type, obj.parent_bone, _flat(obj.matrix_world), obj.hide_render, obj.hide_viewport, obj.instance_type, obj.instance_collection.name_full if obj.instance_collection else None, str(prefab_file(nested)) if nested else None, _components(obj), _id_properties(obj, {EXTRAS_KEY, "bevy_component_data"})))
    _update(digest, (_identity(obj.data, seen), tuple((slot.link, _identity(slot.material, seen)) for slot in obj.material_slots)))
    _update(digest, tuple((modifier.type, _rna(modifier, seen, 1), _id_properties(modifier)) for modifier in obj.modifiers))
    _update(digest, tuple((constraint.type, _rna(constraint, seen, 1)) for constraint in obj.constraints))
    animations = [owner.animation_data for owner in (obj, getattr(obj.data, "shape_keys", None)) if getattr(owner, "animation_data", None) is not None]
    _update(digest, tuple(_rna(animation, seen, 2) for animation in animations))
    return bool(animations)


def _rna(struct, seen, depth):
    values = []
    for prop in struct.bl_rna.properties:
        name = prop.identifier
        if name in SKIPPED or name.startswith("show_"):
            continue
        try:
            value = getattr(struct, name)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
        if prop.type in NUMBERS:
            values.append((name, _flat(value)))
        elif prop.type == "ENUM":
            values.append((name, tuple(sorted(value)) if isinstance(value, set) else value))
        elif prop.type == "STRING":
            values.append((name, value))
        elif prop.type == "POINTER" and (value is None or isinstance(value, bpy.types.ID)):
            values.append((name, _identity(value, seen)))
        elif prop.type == "POINTER" and depth > 0:
            values.append((name, _rna(value, seen, depth - 1)))
        elif prop.type == "COLLECTION" and depth > 0:
            values.append((name, tuple(_rna(item, seen, depth - 1) for item in value)))
    return tuple(values)


def _identity(value, seen):
    if value is None:
        return None
    if value in seen:
        return seen[value]
    seen[value] = value.name_full
    if isinstance(value, bpy.types.Mesh):
        result = _mesh(value, seen)
    elif isinstance(value, bpy.types.Image):
        result = _image(value)
    elif isinstance(value, bpy.types.NodeTree):
        result = _tree(value, seen)
    elif isinstance(value, bpy.types.Action):
        result = _action(value)
    elif isinstance(value, (bpy.types.Object, bpy.types.Collection, bpy.types.Scene, bpy.types.Text, bpy.types.Library)):
        result = value.name_full
    else:
        result = _rna(value, seen, 2)
    digest = hashlib.sha256()
    _update(digest, (value.name_full, result))
    seen[value] = digest.hexdigest()
    return seen[value]


def _mesh(mesh, seen):
    digest = hashlib.sha256()
    for collection, field, code, size in MESH_ARRAYS:
        items = getattr(mesh, collection, None)
        if items is None:
            continue
        data = array(code, [0]) * (len(items) * size)
        items.foreach_get(field, data)
        digest.update(data.tobytes())
    for layer in mesh.uv_layers:
        data = array("f", [0.0]) * (len(layer.uv) * 2)
        layer.uv.foreach_get("vector", data)
        _update(digest, layer.name)
        digest.update(data.tobytes())
    for attribute in mesh.color_attributes:
        data = array("f", [0.0]) * (len(attribute.data) * 4)
        attribute.data.foreach_get("color", data)
        _update(digest, (attribute.name, attribute.domain))
        digest.update(data.tobytes())
    keys = mesh.shape_keys
    for block in keys.key_blocks if keys is not None else ():
        data = array("f", [0.0]) * (len(block.data) * 3)
        block.data.foreach_get("co", data)
        _update(digest, (block.name, block.value, block.mute, block.relative_key.name, block.slider_min, block.slider_max))
        digest.update(data.tobytes())
    _update(digest, tuple(_identity(material, seen) for material in mesh.materials))
    return digest.hexdigest()


def _image(image):
    path = bpy.path.abspath(image.filepath, library=image.library) if image.filepath else ""
    try:
        stat = os.stat(path) if path else None
    except OSError:
        stat = None
    generated = (image.generated_type, image.generated_width, image.generated_height, tuple(image.generated_color)) if image.source == "GENERATED" else None
    return (image.source, path, (stat.st_mtime_ns, stat.st_size) if stat else None, image.packed_file.size if image.packed_file else None, time.monotonic_ns() if image.is_dirty else None, image.colorspace_settings.name, image.alpha_mode, generated)


def _tree(tree, seen):
    nodes = tuple((node.bl_idname, node.name, _rna(node, seen, 1)) for node in sorted(tree.nodes, key=lambda node: node.name))
    links = tuple(sorted((link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier, link.is_muted) for link in tree.links))
    return nodes, links


def _curves(action):
    if getattr(action, "layers", None):
        return [curve for layer in action.layers for strip in layer.strips for bag in strip.channelbags for curve in bag.fcurves]
    return list(getattr(action, "fcurves", ()))


def _action(action):
    digest = hashlib.sha256()
    for curve in _curves(action):
        points = curve.keyframe_points
        _update(digest, (curve.data_path, curve.array_index, curve.extrapolation, curve.mute, tuple(point.interpolation for point in points)))
        for field in ("co", "handle_left", "handle_right"):
            data = array("f", [0.0]) * (len(points) * 2)
            points.foreach_get(field, data)
            digest.update(data.tobytes())
    return digest.hexdigest()


@contextmanager
def scene_export(directory):
    global _active
    prefabs = enabled_prefabs()
    _active = Export(prefabs, prefab_members(prefabs), directory, None, None)
    try:
        yield
    finally:
        _active = None


@contextmanager
def collection_export(collection, source, directory):
    global _active
    window = bpy.context.window
    if window is None:
        raise RuntimeError("Exporting a collection needs a Blender window")
    previous = window.scene
    active = {layer.name: layer.active_layer_collection.collection for layer in previous.view_layers}
    scene = bpy.data.scenes.new(SCENE_NAME)
    scene.collection.children.link(collection)
    scene.frame_current = source.frame_current
    scene.render.fps = source.render.fps
    scene.render.fps_base = source.render.fps_base
    _active = Export(enabled_prefabs(), set(), directory, scene, collection)
    window.scene = scene
    try:
        with bpy.context.temp_override(window=window, scene=scene, view_layer=scene.view_layers[0]):
            yield scene
    finally:
        window.scene = previous
        _active = None
        bpy.data.scenes.remove(scene)
        _restore_active(previous, active)


def _restore_active(scene, active):
    for layer in scene.view_layers:
        found = _layer_collection(layer.layer_collection, active.get(layer.name))
        if found is not None:
            layer.active_layer_collection = found


def _layer_collection(layer_collection, collection):
    if layer_collection.collection == collection:
        return layer_collection
    for child in layer_collection.children:
        found = _layer_collection(child, collection)
        if found is not None:
            return found
    return None


def export_directory():
    return _active.directory if _active is not None else None


def filter_tree(vtree):
    if _active is None:
        return
    for uuid in list(vtree.roots):
        _filter(vtree, uuid, False)


def _filter(vtree, uuid, duplicate):
    node = vtree.nodes[uuid]
    obj = node.blender_object
    if not duplicate and obj in _active.dropped:
        node.keep_tag = False
    prefab = isinstance(obj, bpy.types.Object) and node.blender_bone is None and obj.instance_type == "COLLECTION" and obj.instance_collection in _active.prefabs
    for child in node.children:
        inside = node.children_type.get(child) == node.CHILDREN_IS_IN_COLLECTION
        if prefab and inside:
            _drop(vtree, child)
        else:
            _filter(vtree, child, duplicate or inside)


def _drop(vtree, uuid):
    node = vtree.nodes[uuid]
    node.keep_tag = False
    for child in node.children:
        _drop(vtree, child)


def instance_node(gltf2_node, obj):
    if _active is None or not isinstance(obj, bpy.types.Object) or obj.instance_type != "COLLECTION" or obj.instance_collection not in _active.prefabs:
        return None
    collection = obj.instance_collection
    offset = collection.instance_offset
    rotation = Quaternion((gltf2_node.rotation[3], *gltf2_node.rotation[:3])) if gltf2_node.rotation else Quaternion()
    scale = gltf2_node.scale or (1.0, 1.0, 1.0)
    translation = Vector(gltf2_node.translation or (0.0, 0.0, 0.0)) + rotation @ Vector((offset.x * scale[0], offset.z * scale[1], -offset.y * scale[2]))
    gltf2_node.translation = list(translation) if any(translation) else None
    path = prefab_file(collection)
    try:
        located = relative_path(str(path), str(_active.directory)) if path is not None and _active.directory is not None else ""
    except ValueError:
        located = ""
    return {"type": "scene_reference", "path": located, "scene": 0, "prefab": collection.name_full}


def prefab_scene(gltf2_scene, blender_scene):
    if _active is None or _active.scene is None or blender_scene != _active.scene:
        return
    collection = _active.collection
    gltf2_scene.name = collection.name
    offset = collection.instance_offset
    shift = (offset.x, offset.z, -offset.y)
    if any(shift):
        for node in gltf2_scene.nodes:
            node.translation = [part - moved for part, moved in zip(node.translation or (0.0, 0.0, 0.0), shift)]
