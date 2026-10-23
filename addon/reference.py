import json
import os
import struct
from pathlib import Path

SCENE_EXTENSIONS = (".glb", ".gltf")
CACHE_LIMIT = 64
IDENTITY = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]

_scenes = {}


def read_scenes(path):
    path = str(path)
    status = os.stat(path)
    key = (status.st_mtime_ns, status.st_size)
    cached = _scenes.pop(path, None)
    if cached is None or cached[0] != key:
        try:
            cached = (key, scene_bounds(_read_gltf(Path(path).read_bytes())))
        except ValueError as error:
            cached = (key, error)
    if len(_scenes) >= CACHE_LIMIT:
        _scenes.pop(next(iter(_scenes)))
    _scenes[path] = cached
    if isinstance(cached[1], ValueError):
        raise cached[1]
    return cached[1]


def _read_gltf(data):
    if data[:4] != b"glTF":
        try:
            return json.loads(data)
        except UnicodeDecodeError as error:
            raise ValueError("Not a glTF file") from error
    if len(data) < 20:
        raise ValueError("Truncated GLB file")
    length, kind = struct.unpack_from("<I4s", data, 12)
    if kind != b"JSON":
        raise ValueError("GLB file has no JSON chunk")
    return json.loads(data[20:20 + length])


def scene_bounds(gltf):
    try:
        nodes = gltf.get("nodes", [])
        meshes = gltf.get("meshes", [])
        accessors = gltf.get("accessors", [])
        found = []
        for scene in gltf.get("scenes", []):
            points = []
            pending = [(index, IDENTITY, 0) for index in scene.get("nodes", [])]
            while pending:
                index, parent, depth = pending.pop()
                if depth > len(nodes):
                    raise ValueError("Node hierarchy has a cycle")
                node = nodes[index]
                matrix = _multiply(parent, _local(node))
                if "mesh" in node:
                    for primitive in meshes[node["mesh"]]["primitives"]:
                        accessor = accessors[primitive["attributes"]["POSITION"]]
                        points.extend(_transform(matrix, corner) for corner in _corners(accessor["min"], accessor["max"]))
                pending.extend((child, matrix, depth + 1) for child in node.get("children", []))
            found.append(_bounds(points))
        return found
    except (AttributeError, KeyError, IndexError, TypeError) as error:
        raise ValueError(f"Invalid glTF scene: {error!r}") from error


def _local(node):
    if "matrix" in node:
        values = [float(value) for value in node["matrix"]]
        return [[values[column * 4 + row] for column in range(4)] for row in range(4)]
    x, y, z, w = [float(value) for value in node.get("rotation", (0.0, 0.0, 0.0, 1.0))]
    scale = [float(value) for value in node.get("scale", (1.0, 1.0, 1.0))]
    translation = [float(value) for value in node.get("translation", (0.0, 0.0, 0.0))]
    rotation = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    return [[rotation[row][column] * scale[column] for column in range(3)] + [translation[row]] for row in range(3)] + [[0.0, 0.0, 0.0, 1.0]]


def _multiply(first, second):
    return [[sum(first[row][index] * second[index][column] for index in range(4)) for column in range(4)] for row in range(4)]


def _transform(matrix, point):
    return tuple(sum(matrix[row][index] * point[index] for index in range(3)) + matrix[row][3] for row in range(3))


def _corners(minimum, maximum):
    return [(x, y, z) for x in (minimum[0], maximum[0]) for y in (minimum[1], maximum[1]) for z in (minimum[2], maximum[2])]


def _bounds(points):
    if not points:
        return None
    return tuple(min(point[axis] for point in points) for axis in range(3)), tuple(max(point[axis] for point in points) for axis in range(3))
