import hashlib
import json

import bpy
import numpy
from mathutils import Vector

from .bake import box_matrix, job_item
from .native import fog_source
from .system import collision_only_meshes, component_of, lightmap_uv_map

GEOMETRY_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME"}
DIGITS = 5
DEPTH = 3
TOUCHING = 1e-4
ID_SKIPPED = {"animation_data"} | {property.identifier for property in bpy.types.ID.bl_rna.properties}
NODE_SKIPPED = {property.identifier for property in bpy.types.Node.bl_rna.properties} - {"mute"}
BOX_CORNERS = [Vector((x, y, z)) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)]
PART_WORDS = {
    "SKY": (("world", "the World"),),
    "LIGHTMAP": (("target", "the mesh"), ("meshes", "the meshes around it"), ("lamps", "the lamps"), ("world", "the World")),
    "CUBEMAP": (("target", "its box"), ("meshes", "the meshes in its box"), ("lamps", "the lamps"), ("world", "the World")),
    "VOXELS": (("target", "its box"), ("meshes", "the meshes in its box"), ("lamps", "the lamps"), ("world", "the World")),
}
BAKED_FILES = {"SKY": "cubemap", "LIGHTMAP": "lightmap", "CUBEMAP": "cubemap", "VOXELS": "voxel texture"}


def bake_record(scene, view_layer, depsgraph, job, cache):
    if job["kind"] == "SKY":
        parts = bake_parts(scene, view_layer, depsgraph, cache, world=bpy.data.worlds.get(job["world"]))
    else:
        obj = scene.objects[job["object"]]
        parts = bake_parts(scene, view_layer, depsgraph, cache, obj, job_item(obj, job))
    return json.dumps({"file": job["file"], **parts}, separators=(",", ":"))


def bake_parts(scene, view_layer, depsgraph, cache, obj=None, item=None, world=None):
    if obj is None:
        return {"world": _id_digest(world, cache)}
    if ("collision_only",) not in cache:
        cache[("collision_only",)] = collision_only_meshes(scene.objects)
    hidden = cache[("collision_only",)]
    geometry = [other for other in scene.objects if other.type in GEOMETRY_TYPES and _rendered(other, view_layer) and fog_source(other) is None and other not in hidden]
    if item.component_type == "LIGHTMAP":
        bounds, digest = _geometry(obj, depsgraph, cache)
        uv_map = lightmap_uv_map(obj)
        target = _digest(digest, uv_map.name if uv_map else None, _uv_digest(obj.evaluated_get(depsgraph).data, uv_map.name) if uv_map else None)
    else:
        matrix = box_matrix(obj, item)
        corners = numpy.array([tuple(matrix @ corner) for corner in BOX_CORNERS])
        bounds = (corners.min(axis=0), corners.max(axis=0))
        target = _digest(_rounded(numpy.array(matrix)))
    covered = []
    for other in geometry:
        if other == obj and item.component_type == "LIGHTMAP":
            continue
        other_bounds, digest = _geometry(other, depsgraph, cache)
        if _overlap(bounds, other_bounds):
            covered.append(digest)
    lamps = sorted(_lamp(lamp, cache) for lamp in scene.objects if lamp.type == "LIGHT" and _rendered(lamp, view_layer))
    return {"target": target, "meshes": _digest(sorted(covered)), "lamps": _digest(lamps), "world": _id_digest(scene.world, cache)}


def stale_message(record, kind, parts):
    changed = [word for part, word in PART_WORDS[kind] if part in record and record[part] != parts.get(part)]
    if not changed:
        return None
    words = changed[0] if len(changed) == 1 else f"{', '.join(changed[:-1])} and {changed[-1]}"
    return f"Baked before {words} changed, so the {BAKED_FILES[kind]} is out of date. Bake again"


def read_record(text, file):
    try:
        record = json.loads(text) if text else None
    except ValueError:
        return None
    return record if isinstance(record, dict) and record.get("file") == file else None


def _rendered(obj, view_layer):
    return not obj.hide_render and view_layer.objects.get(obj.name) == obj


def _overlap(first, second):
    return first is not None and second is not None and bool(numpy.all(first[0] <= second[1] + TOUCHING) and numpy.all(second[0] <= first[1] + TOUCHING))


def _geometry(obj, depsgraph, cache):
    key = ("geometry", obj.name)
    if key not in cache:
        evaluated = obj.evaluated_get(depsgraph)
        matrix = numpy.array(evaluated.matrix_world)
        topology = b""
        if obj.type == "MESH":
            mesh = evaluated.data
            points = numpy.empty(len(mesh.vertices) * 3)
            mesh.vertices.foreach_get("co", points)
            points = points.reshape(-1, 3)
            loops = numpy.empty(len(mesh.loops), dtype=numpy.int32)
            mesh.loops.foreach_get("vertex_index", loops)
            starts = numpy.empty(len(mesh.polygons), dtype=numpy.int32)
            mesh.polygons.foreach_get("loop_start", starts)
            topology = loops.tobytes() + starts.tobytes()
        else:
            points = numpy.array([tuple(corner) for corner in evaluated.bound_box])
        placed = points @ matrix[:3, :3].T + matrix[:3, 3]
        bounds = (placed.min(axis=0), placed.max(axis=0)) if len(placed) else None
        materials = [[slot.link, _id_digest(slot.material, cache)] for slot in obj.material_slots]
        cache[key] = (bounds, _digest(obj.name, obj.type, _rounded(matrix), _rounded(points), topology, materials))
    return cache[key]


def _uv_digest(mesh, name):
    layer = mesh.uv_layers.get(name)
    if layer is None:
        return None
    uvs = numpy.empty(len(layer.data) * 2)
    layer.data.foreach_get("uv", uvs)
    return _digest(_rounded(uvs))


def _lamp(lamp, cache):
    item = component_of(lamp, "LIGHT")
    return _digest(lamp.name, _rounded(numpy.array(lamp.matrix_world)), _id_digest(lamp.data, cache), item is not None and item.light_baked)


def _id_digest(data, cache):
    if data is None:
        return None
    key = ("id", data.as_pointer())
    if key not in cache:
        cache[key] = _digest(type(data).__name__, data.name, _struct(data, ID_SKIPPED, 0, frozenset()))
    return cache[key]


def _tree(tree, visiting):
    if tree.name in visiting:
        return None
    visiting = visiting | {tree.name}
    nodes = [[node.name, node.bl_idname, _struct(node, NODE_SKIPPED, 0, visiting), [[socket.identifier, _plain(getattr(socket, "default_value", None), 0, visiting)] for socket in node.inputs if not socket.is_linked]] for node in sorted(tree.nodes, key=lambda node: node.name)]
    links = sorted([link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier] for link in tree.links if link.is_valid and not link.is_muted)
    return [nodes, links]


def _struct(struct, skipped, depth, visiting):
    values = []
    for prop in struct.bl_rna.properties:
        name = prop.identifier
        if name == "rna_type" or name in skipped or name.startswith("bevy_"):
            continue
        try:
            value = getattr(struct, name)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
        values.append([name, _plain(value, depth, visiting)])
    return values


def _plain(value, depth, visiting):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return round(value, DIGITS) + 0.0
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, bpy.types.NodeTree):
        return ["tree", value.name, _tree(value, visiting)]
    if isinstance(value, bpy.types.Image):
        return ["image", value.name, value.filepath, value.source]
    if isinstance(value, bpy.types.ID):
        return [type(value).__name__, value.name]
    if isinstance(value, bpy.types.bpy_struct):
        return _struct(value, (), depth + 1, visiting) if depth < DEPTH else None
    try:
        return [_plain(entry, depth, visiting) for entry in value]
    except TypeError:
        return repr(value)


def _rounded(values):
    return (numpy.round(numpy.asarray(values, dtype=numpy.float64), DIGITS) + 0.0).tobytes()


def _digest(*values):
    hasher = hashlib.sha256()
    for value in values:
        hasher.update(value if isinstance(value, bytes) else json.dumps(value, separators=(",", ":")).encode())
        hasher.update(b"\0")
    return hasher.hexdigest()[:16]
