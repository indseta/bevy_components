import copy
import importlib.util
import json
import pathlib
import struct
import unittest
import zlib

MODULE = pathlib.Path(__file__).resolve().parents[1] / "addon" / "compression.py"
spec = importlib.util.spec_from_file_location("bevy_compression", MODULE)
compression = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compression)


def _png(width, height, color_type=2, transparency=False):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    rows = b"".join(b"\0" + b"\x80" * width * channels for _row in range(height))
    data = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
    if color_type == 3:
        data += chunk(b"PLTE", b"\xff\0\0")
    if transparency:
        data += chunk(b"tRNS", b"\0")
    return compression.PNG_SIGNATURE + data + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def _jpeg(width, height):
    return b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\0" + b"\0" * 9 + b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00" + b"\xff\xd9"


def _ktx2(width=64, height=64, levels=7, model=compression.ETC1S_MODEL, supercompression=compression.BASIS_LZ, transfer=compression.SRGB_TRANSFER, primaries=compression.BT709_PRIMARIES, channels=(0,)):
    dfd_offset = 80 + 24 * levels
    block = struct.pack("<IHH", 0, 2, 24 + 16 * len(channels)) + bytes([model, primaries, transfer, 0]) + b"\0" * 12
    block += b"".join(struct.pack("<HBB", 0, 63, channel) + b"\0" * 12 for channel in channels)
    dfd = struct.pack("<I", 4 + len(block)) + block
    header = compression.KTX2_IDENTIFIER + struct.pack("<9I", 0, 1, width, height, 0, 0, 1, levels, supercompression)
    header += struct.pack("<IIIIQQ", dfd_offset, len(dfd), 0, 0, 0, 0)
    return header + b"\0" * 24 * levels + dfd + b"\0" * 16


def _job(**values):
    defaults = {
        "name": "wood",
        "image": 0,
        "usage": "color",
        "codec": "etc1s",
        "data": b"",
        "mime_type": "image/png",
        "width": 64,
        "height": 64,
        "source_width": 64,
        "source_height": 64,
        "alpha": False,
        "mipmaps": True,
        "wrap": "wrap",
        "textures": [0],
    }
    return compression.TextureJob(**{**defaults, **values})


def _scene(images, materials, samplers=None, textures=None):
    binary = bytearray(b"mesh" * 3)
    gltf = {
        "asset": {"version": "2.0"},
        "extensionsUsed": ["KHR_texture_transform"],
        "buffers": [{"byteLength": 0}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 12}],
        "images": [],
        "textures": textures if textures is not None else [{"sampler": 0, "source": index} for index in range(len(images))],
        "samplers": samplers or [{"magFilter": 9729, "minFilter": 9987}],
        "materials": materials,
    }
    for index, (data, mime_type) in enumerate(images):
        binary += b"\0" * (-len(binary) % 4)
        gltf["bufferViews"].append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)})
        gltf["images"].append({"name": f"image_{index}", "mimeType": mime_type, "bufferView": len(gltf["bufferViews"]) - 1})
        binary += data
    gltf["buffers"][0]["byteLength"] = len(binary)
    return gltf, bytes(binary)


class TestGlb(unittest.TestCase):
    def test_round_trip(self):
        gltf = {"asset": {"version": "2.0"}, "nodes": [{"name": "Lamp ✦"}]}
        data = compression.write_glb(gltf, b"abcde")
        self.assertEqual(len(data) % 4, 0)
        self.assertEqual(struct.unpack_from("<I", data, 8)[0], len(data))
        read, binary = compression.read_glb(data)
        self.assertEqual(read, gltf)
        self.assertEqual(binary, b"abcde\0\0\0")
        self.assertIn(b"\\u2726", data)

    def test_rejects_other_files(self):
        with self.assertRaises(ValueError):
            compression.read_glb(_png(4, 4))
        with self.assertRaises(ValueError):
            compression.read_glb(b"glTF" + struct.pack("<II", 2, 400) + b"\0" * 12)


class TestTextureUsage(unittest.TestCase):
    def test_slot_usage(self):
        self.assertEqual(compression.slot_usage("baseColorTexture"), "color")
        self.assertEqual(compression.slot_usage("emissiveTexture"), "color")
        self.assertEqual(compression.slot_usage("specularColorTexture"), "color")
        self.assertEqual(compression.slot_usage("normalTexture"), "normal")
        self.assertEqual(compression.slot_usage("clearcoatNormalTexture"), "normal")
        self.assertEqual(compression.slot_usage("metallicRoughnessTexture"), "data")
        self.assertEqual(compression.slot_usage("occlusionTexture"), "data")

    def test_texture_infos_include_extensions(self):
        material = {"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}, "extensions": {"KHR_materials_clearcoat": {"clearcoatNormalTexture": {"index": 1}}}}
        self.assertEqual([(slot, info["index"]) for slot, info in compression.texture_infos(material)], [("baseColorTexture", 0), ("clearcoatNormalTexture", 1)])

    def test_split_textures_with_two_usages(self):
        gltf = {
            "textures": [{"sampler": 0, "source": 0}, {"source": 1}],
            "materials": [
                {"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicRoughnessTexture": {"index": 1}}},
                {"pbrMetallicRoughness": {"baseColorTexture": {"index": 1}}, "occlusionTexture": {"index": 1}},
            ],
        }
        usages = compression.split_textures(gltf)
        self.assertEqual(usages, {0: "color", 1: "data", 2: "color"})
        self.assertEqual(gltf["textures"][2], {"source": 1})
        self.assertEqual(gltf["materials"][1]["pbrMetallicRoughness"]["baseColorTexture"]["index"], 2)
        self.assertEqual(gltf["materials"][1]["occlusionTexture"]["index"], 1)

    def test_unused_textures_are_color(self):
        self.assertEqual(compression.split_textures({"textures": [{"source": 0}]}), {0: "color"})


class TestImages(unittest.TestCase):
    def test_png_info(self):
        self.assertEqual(compression.image_info(_png(30, 18)), (30, 18, False))
        self.assertEqual(compression.image_info(_png(8, 4, color_type=6)), (8, 4, True))
        self.assertEqual(compression.image_info(_png(8, 4, color_type=4)), (8, 4, True))
        self.assertEqual(compression.image_info(_png(8, 4, color_type=3, transparency=True)), (8, 4, True))
        self.assertEqual(compression.image_info(_png(8, 4, color_type=3)), (8, 4, False))

    def test_jpeg_info(self):
        self.assertEqual(compression.image_info(_jpeg(640, 480)), (640, 480, False))

    def test_unknown_images(self):
        with self.assertRaises(ValueError):
            compression.image_info(b"RIFF0000WEBP")

    def test_payloads(self):
        gltf, binary = _scene([(_png(4, 4), "image/png")], [])
        self.assertEqual(compression.image_payload(gltf, binary, 0), (_png(4, 4), "image/png"))
        gltf["images"].append({"uri": "data:image/png;base64,iVBORw=="})
        self.assertEqual(compression.image_payload(gltf, binary, 1)[1], "image/png")
        gltf["images"].append({"uri": "wood.png"})
        with self.assertRaises(ValueError):
            compression.image_payload(gltf, binary, 2)


class TestPlan(unittest.TestCase):
    def test_codecs_per_mode(self):
        materials = [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicRoughnessTexture": {"index": 1}}, "normalTexture": {"index": 2}, "emissiveTexture": {"index": 3}}]
        images = [(_png(16, 16), "image/png") for _index in range(4)]
        expected = {
            "ETC1S": ["etc1s", "etc1s", "etc1s", "etc1s"],
            "UASTC": ["uastc", "uastc", "uastc", "uastc"],
            "AUTOMATIC": ["etc1s", "uastc", "uastc", "etc1s"],
        }
        for mode, codecs in expected.items():
            gltf, binary = _scene(images, copy.deepcopy(materials))
            jobs = compression.plan_textures(gltf, binary, mode)
            self.assertEqual([job.codec for job in jobs], codecs, mode)
            self.assertEqual([job.usage for job in jobs], ["color", "data", "normal", "color"], mode)

    def test_automatic_uses_uastc_for_pixel_art(self):
        gltf, binary = _scene([(_png(8, 8), "image/png")], [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}], samplers=[{"magFilter": 9728, "minFilter": 9984}])
        self.assertEqual([job.codec for job in compression.plan_textures(gltf, binary, "AUTOMATIC")], ["uastc"])
        gltf, binary = _scene([(_png(8, 8), "image/png")], [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}], samplers=[{"magFilter": 9728, "minFilter": 9984}])
        self.assertEqual([job.codec for job in compression.plan_textures(gltf, binary, "ETC1S")], ["etc1s"])

    def test_shared_images_become_one_job(self):
        textures = [{"sampler": 0, "source": 0}, {"sampler": 0, "source": 0}]
        materials = [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}, {"pbrMetallicRoughness": {"baseColorTexture": {"index": 1, "extensions": {"KHR_texture_transform": {"scale": [4, 4]}}}}}]
        gltf, binary = _scene([(_png(16, 16, color_type=6), "image/png")], materials, textures=textures)
        jobs = compression.plan_textures(gltf, binary, "ETC1S")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].textures, [0, 1])
        self.assertTrue(jobs[0].alpha)

    def test_sizes_alpha_and_sampling(self):
        materials = [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}, "normalTexture": {"index": 1}}]
        samplers = [{"magFilter": 9729, "minFilter": 9729, "wrapS": 33071}, {"wrapS": 33648}]
        textures = [{"sampler": 0, "source": 0}, {"sampler": 1, "source": 1}]
        gltf, binary = _scene([(_png(30, 18), "image/png"), (_png(64, 64, color_type=6), "image/png")], materials, samplers=samplers, textures=textures)
        color, normal = compression.plan_textures(gltf, binary, "UASTC")
        self.assertEqual((color.width, color.height, color.resized, color.mipmaps, color.wrap, color.srgb), (32, 20, True, False, "clamp", True))
        self.assertEqual((normal.width, normal.height, normal.resized, normal.mipmaps, normal.wrap, normal.srgb, normal.normal, normal.alpha), (64, 64, False, True, "reflect", False, True, False))

    def test_converts_other_image_types(self):
        textures = [{"sampler": 0, "extensions": {"EXT_texture_webp": {"source": 0}}}]
        gltf, binary = _scene([(b"RIFF0000WEBPVP8 ", "image/webp")], [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}], textures=textures)
        with self.assertRaises(ValueError):
            compression.plan_textures(copy.deepcopy(gltf), binary, "ETC1S")
        converted = []
        jobs = compression.plan_textures(gltf, binary, "ETC1S", convert=lambda data, mime_type: converted.append(mime_type) or _png(12, 12))
        self.assertEqual(converted, ["image/webp"])
        self.assertEqual((jobs[0].mime_type, jobs[0].width), ("image/png", 12))

    def test_external_images_are_rejected(self):
        gltf, binary = _scene([], [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}], textures=[{"source": 0}])
        gltf["images"].append({"uri": "wood.png"})
        with self.assertRaises(ValueError):
            compression.plan_textures(gltf, binary, "ETC1S")


class TestEmbed(unittest.TestCase):
    def test_images_become_ktx2(self):
        materials = [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}, "normalTexture": {"index": 1}}]
        textures = [{"sampler": 0, "source": 0}, {"sampler": 0, "extensions": {"EXT_texture_webp": {"source": 1}}}]
        images = [(_png(16, 16), "image/png"), (_png(16, 16, color_type=6), "image/png")]
        gltf, binary = _scene(images, materials, textures=textures)
        gltf["extensionsUsed"].append("EXT_texture_webp")
        jobs = compression.plan_textures(gltf, binary, "AUTOMATIC")
        encoded = [_ktx2(16, 16, 5), _ktx2(16, 16, 5, model=compression.UASTC_MODEL, supercompression=2, transfer=1, primaries=0)]
        gltf, binary = compression.embed_textures(gltf, binary, jobs, encoded)
        self.assertEqual([texture["extensions"] for texture in gltf["textures"]], [{"KHR_texture_basisu": {"source": 0}}, {"KHR_texture_basisu": {"source": 1}}])
        self.assertTrue(all("source" not in texture for texture in gltf["textures"]))
        self.assertEqual([image["mimeType"] for image in gltf["images"]], ["image/ktx2", "image/ktx2"])
        self.assertEqual([image["name"] for image in gltf["images"]], ["image_0", "image_1"])
        self.assertEqual([compression.image_payload(gltf, binary, index)[0] for index in range(2)], encoded)
        self.assertTrue(all(view["byteOffset"] % 16 == 0 for view in gltf["bufferViews"]))
        self.assertEqual(binary[:12], b"mesh" * 3)
        self.assertNotIn(compression.PNG_SIGNATURE, binary)
        self.assertEqual(gltf["buffers"][0]["byteLength"], len(binary))
        self.assertEqual(gltf["extensionsUsed"], ["KHR_texture_transform", "KHR_texture_basisu"])
        self.assertEqual(gltf["extensionsRequired"], ["KHR_texture_basisu"])
        json.dumps(gltf)

    def test_split_images_get_their_own_ktx2(self):
        materials = [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicRoughnessTexture": {"index": 0}}}]
        gltf, binary = _scene([(_png(16, 16), "image/png")], materials)
        jobs = compression.plan_textures(gltf, binary, "AUTOMATIC")
        self.assertEqual([(job.image, job.usage) for job in jobs], [(0, "color"), (0, "data")])
        gltf, binary = compression.embed_textures(gltf, binary, jobs, [_ktx2(16, 16, 5), _ktx2(16, 16, 5, transfer=1, primaries=0)])
        self.assertEqual(len(gltf["images"]), 2)
        self.assertEqual([texture["extensions"]["KHR_texture_basisu"]["source"] for texture in gltf["textures"]], [0, 1])
        self.assertEqual(gltf["materials"][0]["pbrMetallicRoughness"]["metallicRoughnessTexture"]["index"], 1)

    def test_scenes_without_textures_are_unchanged(self):
        gltf, binary = _scene([], [])
        before = copy.deepcopy(gltf)
        self.assertEqual(compression.embed_textures(gltf, binary, [], []), (before, binary))


class TestKtx2(unittest.TestCase):
    def test_info(self):
        info = compression.ktx2_info(_ktx2(32, 20, 6, channels=(0, 15)))
        self.assertEqual((info["width"], info["height"], info["levels"], info["model"], info["transfer"], info["primaries"], info["channels"]), (32, 20, 6, compression.ETC1S_MODEL, compression.SRGB_TRANSFER, compression.BT709_PRIMARIES, [0, 15]))

    def test_full_mip_count(self):
        self.assertEqual(compression.full_mip_count(64, 64), 7)
        self.assertEqual(compression.full_mip_count(32, 20), 6)
        self.assertEqual(compression.full_mip_count(4, 4), 3)

    def test_check_encoded(self):
        self.assertIsNone(compression.check_encoded(_job(), _ktx2()))
        self.assertIsNone(compression.check_encoded(_job(codec="uastc", usage="normal", mipmaps=False), _ktx2(levels=1, model=compression.UASTC_MODEL, supercompression=2, transfer=1, primaries=0)))
        self.assertIn("invalid KTX2", compression.check_encoded(_job(), b"not a texture"))
        self.assertIn("ETC1S", compression.check_encoded(_job(), _ktx2(model=compression.UASTC_MODEL)))
        self.assertIn("32x32", compression.check_encoded(_job(), _ktx2(32, 32, 6)))
        self.assertIn("color space", compression.check_encoded(_job(), _ktx2(transfer=1)))
        self.assertIn("color space", compression.check_encoded(_job(usage="data"), _ktx2(transfer=1)))
        self.assertIn("mipmap", compression.check_encoded(_job(), _ktx2(levels=1)))


if __name__ == "__main__":
    unittest.main()
