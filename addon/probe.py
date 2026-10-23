import json
import struct
from pathlib import Path

from .compression import KTX2_IDENTIFIER, KTX2_MIME_TYPE, ktx2_info
from .metadata import EXTRAS_KEY

FILE_KINDS = {
    "REFLECTION_PROBE": "CUBEMAP",
    "IRRADIANCE_VOLUME": "VOXELS",
    "LIGHTMAP": "LIGHTMAP",
}
FILE_LABELS = {
    "CUBEMAP": "Cubemap",
    "VOXELS": "Voxels",
    "LIGHTMAP": "Lightmap",
}
FILE_COMPONENTS = {"reflection_probe", "irradiance_volume", "lightmap", "sky"}
HEADER_LENGTH = 65536
BASIS_FORMAT = 0
FIRST_BLOCK_FORMAT = 131
LAST_BLOCK_FORMAT = 184
FIRST_EXTENSION_FORMAT = 1000000000
MAX_CUBEMAP_SIZE = 8192
LINEAR_FILTER = 9729
CLAMP_TO_EDGE = 33071
ALIGNMENT = 16
RGBA16F = 97
RGB9E5 = 123
FLOAT_SAMPLE = 0xC0
EXPONENT_SAMPLE = 0x20
HALF_FLOAT_LIMITS = (0xBF800000, 0x3F800000)
MANTISSA_LIMITS = (0, 0x2100)
EXPONENT_LIMITS = (15, 31)
HALF_FLOAT_SAMPLES = tuple((index * 16, 15, channel | FLOAT_SAMPLE, *HALF_FLOAT_LIMITS) for index, channel in enumerate((0, 1, 2, 15)))
SHARED_EXPONENT_SAMPLES = tuple(sample for channel in range(3) for sample in ((channel * 9, 8, channel, *MANTISSA_LIMITS), (27, 4, channel | EXPONENT_SAMPLE, *EXPONENT_LIMITS)))
WRITER = b"KTXwriter\0Bevy Components\0"


def check_texture(data, kind):
    try:
        info = ktx2_info(data)
    except (ValueError, struct.error, IndexError):
        return "ERROR", "is not a KTX2 file"
    width, height, depth = info["width"], info["height"], info["depth"]
    if info["format"] == BASIS_FORMAT:
        return "ERROR", "is Basis Universal, which Bevy only loads for materials. Save it uncompressed, such as RGBA16F"
    if kind == "CUBEMAP":
        if info["faces"] != 6 or info["layers"] > 1:
            return "ERROR", "is not a cubemap"
        if width != height or width & (width - 1) or width > MAX_CUBEMAP_SIZE:
            return "ERROR", f"is {width} × {height}, but Bevy only filters square cubemaps whose size is a power of two, such as 256"
        summary = f"{width} × {width} cubemap"
    elif kind == "LIGHTMAP":
        if info["faces"] != 1 or info["layers"] > 1 or depth > 1:
            return "ERROR", "is not a 2D texture"
        summary = f"{width} × {height} lightmap"
    else:
        if info["faces"] != 1 or info["layers"] > 1 or depth < 1:
            return "ERROR", "is not a 3D texture"
        if height % 2 or depth % 3:
            return "ERROR", f"is {width} × {height} × {depth}, but an irradiance volume of X × Y × Z voxels is X × 2Y × 3Z texels"
        summary = f"{width} × {height // 2} × {depth // 3} voxels"
    if FIRST_BLOCK_FORMAT <= info["format"] <= LAST_BLOCK_FORMAT or info["format"] >= FIRST_EXTENSION_FORMAT:
        return "WARNING", f"{summary} in a block-compressed format, so the scene fails to load on GPUs without it"
    return None, summary


def ktx2_rgba16f(width, height, data, depth=0, faces=1):
    return _ktx2(RGBA16F, 2, 8, HALF_FLOAT_SAMPLES, width, height, data, depth, faces)


def ktx2_rgb9e5(width, height, data):
    return _ktx2(RGB9E5, 4, 4, SHARED_EXPONENT_SAMPLES, width, height, data)


def _ktx2(vk_format, type_size, texel_size, samples, width, height, data, depth=0, faces=1):
    packed = b"".join(struct.pack("<HBB4xII", *sample) for sample in samples)
    block = struct.pack("<IHH4B4x8B", 0, 2, 24 + len(packed), 1, 1, 1, 0, texel_size, 0, 0, 0, 0, 0, 0, 0) + packed
    dfd = struct.pack("<I", 4 + len(block)) + block
    kvd = struct.pack("<I", len(WRITER)) + WRITER
    kvd += b"\0" * (-len(kvd) % 4)
    dfd_offset = 80 + 24
    kvd_offset = dfd_offset + len(dfd)
    data_offset = kvd_offset + len(kvd)
    data_offset += -data_offset % texel_size
    header = KTX2_IDENTIFIER + struct.pack("<9I", vk_format, type_size, width, height, depth, 0, faces, 1, 0)
    header += struct.pack("<IIIIQQ", dfd_offset, len(dfd), kvd_offset, len(kvd), 0, 0)
    header += struct.pack("<QQQ", data_offset, len(data), len(data))
    body = header + dfd + kvd
    return body + b"\0" * (data_offset - len(body)) + bytes(data)


def voxel_counts(data):
    try:
        info = ktx2_info(data)
    except (ValueError, struct.error, IndexError):
        return None
    if info["faces"] != 1 or info["depth"] < 3 or info["height"] % 2 or info["depth"] % 3:
        return None
    return info["width"], info["height"] // 2, info["depth"] // 3


def _components(node):
    extras = node.get("extras")
    if not isinstance(extras, dict) or not isinstance(extras.get(EXTRAS_KEY), str):
        return None
    try:
        data = json.loads(extras[EXTRAS_KEY])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("components"), list) else None


def _file_components(data):
    return [component for component in data["components"] if isinstance(component, dict) and component.get("type") in FILE_COMPONENTS and "file" in component]


def _holders(gltf):
    return [*gltf.get("nodes", []), *gltf.get("scenes", [])]


def needs_embedding(gltf):
    return any((data := _components(holder)) is not None and _file_components(data) for holder in _holders(gltf))


def embed_files(gltf, binary, read):
    textures = {}
    appended = bytearray(binary)
    sampler = None
    for holder in _holders(gltf):
        data = _components(holder)
        if data is None or not _file_components(data):
            continue
        for component in _file_components(data):
            path = component.pop("file")
            if path and path not in textures:
                payload = read(path)
                if sampler is None:
                    gltf.setdefault("samplers", []).append({"magFilter": LINEAR_FILTER, "minFilter": LINEAR_FILTER, "wrapS": CLAMP_TO_EDGE, "wrapT": CLAMP_TO_EDGE})
                    sampler = len(gltf["samplers"]) - 1
                appended += b"\0" * (-len(appended) % ALIGNMENT)
                views = gltf.setdefault("bufferViews", [])
                views.append({"buffer": 0, "byteOffset": len(appended), "byteLength": len(payload)})
                appended += payload
                images = gltf.setdefault("images", [])
                images.append({"bufferView": len(views) - 1, "mimeType": KTX2_MIME_TYPE, "name": Path(path).stem})
                gltf.setdefault("textures", []).append({"sampler": sampler, "source": len(images) - 1})
                textures[path] = len(gltf["textures"]) - 1
            component["texture"] = textures.get(path) if path else None
        holder["extras"][EXTRAS_KEY] = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    if not textures:
        return gltf, binary
    buffers = gltf.setdefault("buffers", [])
    if not buffers:
        buffers.append({})
    buffers[0]["byteLength"] = len(appended)
    return gltf, bytes(appended)
