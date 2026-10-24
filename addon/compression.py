import base64
import copy
import json
import struct
from dataclasses import dataclass

BASISU = "KHR_texture_basisu"
WEBP = "EXT_texture_webp"
KTX2_MIME_TYPE = "image/ktx2"
KTX2_IDENTIFIER = b"\xabKTX 20\xbb\r\n\x1a\n"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
ETC1S_MODEL = 163
UASTC_MODEL = 166
BASIS_LZ = 1
LINEAR_TRANSFER = 1
SRGB_TRANSFER = 2
UNSPECIFIED_PRIMARIES = 0
BT709_PRIMARIES = 1
COLOR_SLOTS = {"baseColorTexture", "emissiveTexture", "diffuseTexture", "specularGlossinessTexture", "specularColorTexture", "sheenColorTexture"}
MIPMAP_FILTERS = {9984, 9985, 9986, 9987}
NEAREST_FILTER = 9728
WRAP_MODES = {
    33071: "clamp",
    33648: "reflect",
    10497: "wrap",
}


@dataclass
class TextureJob:
    name: str
    image: int
    usage: str
    codec: str
    data: bytes
    mime_type: str
    width: int
    height: int
    source_width: int
    source_height: int
    alpha: bool
    mipmaps: bool
    wrap: str
    textures: list

    @property
    def srgb(self):
        return self.usage == "color"

    @property
    def normal(self):
        return self.usage == "normal"

    @property
    def resized(self):
        return (self.width, self.height) != (self.source_width, self.source_height)


def read_glb(data):
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("Not a GLB file")
    version, length = struct.unpack_from("<II", data, 4)
    if version != 2 or length > len(data):
        raise ValueError("Unsupported GLB version or truncated file")
    gltf = None
    binary = b""
    offset = 12
    while offset + 8 <= length:
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8:offset + 8 + chunk_length]
        if chunk_type == JSON_CHUNK and gltf is None:
            gltf = json.loads(chunk)
        elif chunk_type == BIN_CHUNK and not binary:
            binary = bytes(chunk)
        offset += 8 + chunk_length
    if gltf is None:
        raise ValueError("GLB file has no JSON chunk")
    return gltf, binary


def write_glb(gltf, binary):
    text = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    chunks = struct.pack("<II", len(text), JSON_CHUNK) + text
    if binary:
        binary += b"\0" * (-len(binary) % 4)
        chunks += struct.pack("<II", len(binary), BIN_CHUNK) + binary
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


def texture_infos(value, slot=None):
    if isinstance(value, dict):
        if slot and slot.endswith("Texture") and isinstance(value.get("index"), int):
            yield slot, value
        for key, child in value.items():
            yield from texture_infos(child, key)
    elif isinstance(value, list):
        for child in value:
            yield from texture_infos(child, slot)


def slot_usage(slot):
    if "normal" in slot.lower():
        return "normal"
    if slot in COLOR_SLOTS:
        return "color"
    return "data"


def split_textures(gltf):
    textures = gltf.get("textures", [])
    owners = {}
    for material in gltf.get("materials", []):
        for slot, info in texture_infos(material):
            key = (info["index"], slot_usage(slot))
            if key not in owners:
                if any(index == info["index"] for index, _usage in owners):
                    textures.append(copy.deepcopy(textures[info["index"]]))
                    owners[key] = len(textures) - 1
                else:
                    owners[key] = info["index"]
            info["index"] = owners[key]
    usages = {texture: usage for (_index, usage), texture in owners.items()}
    for index in range(len(textures)):
        usages.setdefault(index, "color")
    return usages


def texture_source(texture):
    if "source" in texture:
        return texture["source"]
    return texture.get("extensions", {}).get(WEBP, {}).get("source")


def image_payload(gltf, binary, index):
    image = gltf["images"][index]
    if "bufferView" in image:
        view = gltf["bufferViews"][image["bufferView"]]
        if view.get("buffer", 0) != 0:
            raise ValueError(f"Image {image.get('name', index)} is not stored in the GLB")
        start = view.get("byteOffset", 0)
        return binary[start:start + view["byteLength"]], image.get("mimeType", "")
    uri = image.get("uri", "")
    if uri.startswith("data:") and ";base64," in uri:
        header, payload = uri[5:].split(";base64,", 1)
        return base64.b64decode(payload), header
    raise ValueError(f"Image {image.get('name', index)} is not embedded in the GLB")


def image_info(data):
    if data[:8] == PNG_SIGNATURE:
        width, height, _depth, color_type = struct.unpack_from(">IIBB", data, 16)
        return width, height, color_type in (4, 6) or _png_has_chunk(data, b"tRNS")
    if data[:2] == b"\xff\xd8":
        return (*_jpeg_size(data), False)
    raise ValueError("Unsupported image format")


def _png_has_chunk(data, kind):
    offset = 8
    while offset + 8 <= len(data):
        length, chunk = struct.unpack_from(">I4s", data, offset)
        if chunk == kind:
            return True
        if chunk == b"IDAT":
            return False
        offset += 12 + length
    return False


def _jpeg_size(data):
    offset = 2
    while offset + 9 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        if marker == 0xFF:
            offset += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        length = struct.unpack_from(">H", data, offset + 2)[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack_from(">HH", data, offset + 5)
            return width, height
        offset += 2 + length
    raise ValueError("JPEG image has no size")


def _round_up(value):
    return max(4, (value + 3) // 4 * 4)


def _codec(mode, usage, nearest):
    if mode == "ETC1S":
        return "etc1s"
    if mode == "UASTC":
        return "uastc"
    return "etc1s" if usage == "color" and not nearest else "uastc"


def _sampling(gltf, texture):
    samplers = gltf.get("samplers", [])
    sampler = samplers[texture["sampler"]] if isinstance(texture.get("sampler"), int) and texture["sampler"] < len(samplers) else {}
    return sampler.get("minFilter", 9987) in MIPMAP_FILTERS, WRAP_MODES.get(sampler.get("wrapS", 10497), "wrap"), sampler.get("magFilter") == NEAREST_FILTER


def plan_textures(gltf, binary, mode, convert=None):
    usages = split_textures(gltf)
    jobs = {}
    payloads = {}
    for index, texture in enumerate(gltf.get("textures", [])):
        image = texture_source(texture)
        if image is None or gltf["images"][image].get("mimeType") == KTX2_MIME_TYPE:
            continue
        if image not in payloads:
            data, mime_type = image_payload(gltf, binary, image)
            if mime_type not in ("image/png", "image/jpeg"):
                if convert is None:
                    raise ValueError(f"Image {gltf['images'][image].get('name', image)} uses unsupported type {mime_type or 'unknown'}")
                data, mime_type = convert(data, mime_type), "image/png"
            payloads[image] = (data, mime_type, *image_info(data))
        data, mime_type, width, height, alpha = payloads[image]
        usage = usages[index]
        mipmaps, wrap, nearest = _sampling(gltf, texture)
        codec = _codec(mode, usage, nearest)
        key = (image, usage, mipmaps, wrap, codec)
        if key not in jobs:
            name = gltf["images"][image].get("name", f"image_{image}")
            jobs[key] = TextureJob(name=name, image=image, usage=usage, codec=codec, data=data, mime_type=mime_type, width=_round_up(width), height=_round_up(height), source_width=width, source_height=height, alpha=alpha and usage != "normal", mipmaps=mipmaps, wrap=wrap, textures=[])
        jobs[key].textures.append(index)
    return list(jobs.values())


def embed_textures(gltf, binary, jobs, encoded):
    if not jobs:
        return gltf, binary
    images = gltf.setdefault("images", [])
    views = gltf.setdefault("bufferViews", [])
    replacements = {}
    claimed = set()
    for job, data in zip(jobs, encoded):
        original = images[job.image]
        image = job.image
        view = original.get("bufferView")
        if image in claimed:
            images.append({})
            image = len(images) - 1
            view = None
        if view is None:
            views.append({"buffer": 0, "byteLength": 0})
            view = len(views) - 1
        claimed.add(job.image)
        replacements[view] = data
        images[image] = {"bufferView": view, "mimeType": KTX2_MIME_TYPE, **({"name": original["name"]} if "name" in original else {})}
        for index in job.textures:
            texture = gltf["textures"][index]
            texture.pop("source", None)
            extensions = texture.setdefault("extensions", {})
            extensions.pop(WEBP, None)
            extensions[BASISU] = {"source": image}
    rebuilt = bytearray()
    for index, view in enumerate(views):
        if view.get("buffer", 0) != 0:
            continue
        start = view.get("byteOffset", 0)
        data = replacements.get(index, binary[start:start + view.get("byteLength", 0)])
        rebuilt += b"\0" * (-len(rebuilt) % 16)
        view["byteOffset"] = len(rebuilt)
        view["byteLength"] = len(data)
        rebuilt += data
    buffers = gltf.setdefault("buffers", [{}])
    buffers[0]["byteLength"] = len(rebuilt)
    uses_webp = any(WEBP in texture.get("extensions", {}) for texture in gltf.get("textures", []))
    for key in ("extensionsUsed", "extensionsRequired"):
        names = [name for name in gltf.get(key, []) if name != WEBP or uses_webp]
        gltf[key] = names + ([BASISU] if BASISU not in names else [])
    return gltf, bytes(rebuilt)


def ktx2_info(data):
    if data[:12] != KTX2_IDENTIFIER:
        raise ValueError("Not a KTX2 file")
    vk_format, _type_size, width, height, depth, layers, faces, levels, supercompression = struct.unpack_from("<9I", data, 12)
    dfd_offset = struct.unpack_from("<I", data, 48)[0]
    model, primaries, transfer = data[dfd_offset + 12:dfd_offset + 15]
    block_size = struct.unpack_from("<H", data, dfd_offset + 10)[0]
    channels = [data[dfd_offset + 4 + 24 + sample * 16 + 3] & 0x0F for sample in range((block_size - 24) // 16)]
    return {
        "format": vk_format,
        "width": width,
        "height": height,
        "depth": depth,
        "layers": layers,
        "faces": faces,
        "levels": max(levels, 1),
        "supercompression": supercompression,
        "model": model,
        "primaries": primaries,
        "transfer": transfer,
        "channels": channels,
    }


def full_mip_count(width, height):
    return max(width, height).bit_length()


def check_encoded(job, data):
    try:
        info = ktx2_info(data)
    except (ValueError, struct.error) as error:
        return f"{job.name}: the encoder wrote an invalid KTX2 file ({error})"
    expected = (ETC1S_MODEL, BASIS_LZ) if job.codec == "etc1s" else (UASTC_MODEL, None)
    if info["model"] != expected[0] or (expected[1] is not None and info["supercompression"] != expected[1]):
        return f"{job.name}: the encoder did not write {job.codec.upper()} data"
    if (info["width"], info["height"]) != (job.width, job.height):
        return f"{job.name}: the encoder wrote {info['width']}x{info['height']} instead of {job.width}x{job.height}"
    if (info["transfer"], info["primaries"]) != ((SRGB_TRANSFER, BT709_PRIMARIES) if job.srgb else (LINEAR_TRANSFER, UNSPECIFIED_PRIMARIES)):
        return f"{job.name}: the encoder wrote the wrong color space"
    if info["levels"] != (full_mip_count(job.width, job.height) if job.mipmaps else 1):
        return f"{job.name}: the encoder wrote {info['levels']} mipmap levels"
    return None
