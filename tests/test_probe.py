import importlib
import json
import pathlib
import struct
import sys
import types
import unittest
import zlib

ADDON = pathlib.Path(__file__).resolve().parents[1] / "addon"
ASSETS = pathlib.Path(__file__).resolve().parent / "blender" / "assets"
package = types.ModuleType("bevy_probe_addon")
package.__path__ = [str(ADDON)]
sys.modules.setdefault("bevy_probe_addon", package)
probe = importlib.import_module("bevy_probe_addon.probe")
compression = importlib.import_module("bevy_probe_addon.compression")

RGBA16F = 97
RGB9E5 = 123
BC6H = 143


def _ktx2(width=16, height=16, depth=0, faces=6, layers=0, vk_format=RGBA16F, levels=1):
    dfd_offset = 80 + 24 * levels
    block = struct.pack("<IHH", 0, 2, 24 + 16) + bytes([1, 1, 1, 0]) + b"\0" * 12 + struct.pack("<HBB", 0, 15, 0) + b"\0" * 12
    dfd = struct.pack("<I", 4 + len(block)) + block
    header = compression.KTX2_IDENTIFIER + struct.pack("<9I", vk_format, 2, width, height, depth, layers, faces, levels, 0)
    header += struct.pack("<IIIIQQ", dfd_offset, len(dfd), 0, 0, 0, 0)
    return header + b"\0" * 24 * levels + dfd


def _png(width, height):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\0" + b"\x80" * width * 3 for _row in range(height))
    return compression.PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def _volume(width=4, height=8, depth=12, **options):
    return _ktx2(width, height, depth, faces=1, **options)


def _scene(*components_per_node):
    nodes = [{"name": f"node_{index}", "extras": {"bevy_components": json.dumps({"version": 1, "components": components}, separators=(",", ":"))}} for index, components in enumerate(components_per_node)]
    gltf = {"asset": {"version": "2.0"}, "nodes": nodes + [{"name": "plain"}], "images": [{"bufferView": 0, "mimeType": "image/png"}], "textures": [{"source": 0}], "samplers": [{}], "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 5}], "buffers": [{"byteLength": 5}]}
    return gltf, b"\x89PNG!"


def _components(gltf, index):
    return json.loads(gltf["nodes"][index]["extras"]["bevy_components"])["components"]


class TestTextureChecks(unittest.TestCase):
    def test_cubemaps(self):
        self.assertEqual(probe.check_texture(_ktx2(256, 256), "CUBEMAP"), (None, "256 × 256 cubemap"))
        self.assertEqual(probe.check_texture(_ktx2(96, 96), "CUBEMAP"), ("ERROR", "is 96 × 96, but Bevy only filters square cubemaps whose size is a power of two, such as 256"))
        self.assertEqual(probe.check_texture(_ktx2(64, 32), "CUBEMAP")[0], "ERROR")
        self.assertEqual(probe.check_texture(_ktx2(16384, 16384), "CUBEMAP")[0], "ERROR")
        self.assertEqual(probe.check_texture(_ktx2(faces=1), "CUBEMAP"), ("ERROR", "is not a cubemap"))
        self.assertEqual(probe.check_texture(_ktx2(layers=2), "CUBEMAP"), ("ERROR", "is not a cubemap"))

    def test_irradiance_volumes(self):
        self.assertEqual(probe.check_texture(_volume(), "VOXELS"), (None, "4 × 4 × 4 voxels"))
        self.assertEqual(probe.check_texture(_volume(4, 7, 12), "VOXELS"), ("ERROR", "is 4 × 7 × 12, but an irradiance volume of X × Y × Z voxels is X × 2Y × 3Z texels"))
        self.assertEqual(probe.check_texture(_volume(4, 8, 10), "VOXELS")[0], "ERROR")
        self.assertEqual(probe.check_texture(_ktx2(4, 8, 0, faces=1), "VOXELS"), ("ERROR", "is not a 3D texture"))
        self.assertEqual(probe.check_texture(_ktx2(16, 16), "VOXELS"), ("ERROR", "is not a 3D texture"))
        self.assertEqual(probe.voxel_counts(_volume(6, 4, 9)), (6, 2, 3))
        self.assertIsNone(probe.voxel_counts(_ktx2()))
        self.assertIsNone(probe.voxel_counts(b"not ktx2"))

    def test_lightmaps(self):
        self.assertEqual(probe.check_texture(_ktx2(512, 256, faces=1), "LIGHTMAP"), (None, "512 × 256 lightmap"))
        self.assertEqual(probe.check_texture(_ktx2(), "LIGHTMAP"), ("ERROR", "is not a 2D texture"))
        self.assertEqual(probe.check_texture(_volume(), "LIGHTMAP"), ("ERROR", "is not a 2D texture"))
        self.assertEqual(probe.check_texture(_ktx2(faces=1, layers=3), "LIGHTMAP"), ("ERROR", "is not a 2D texture"))
        self.assertEqual(probe.check_texture(_ktx2(64, 64, faces=1, vk_format=BC6H), "LIGHTMAP"), ("WARNING", "64 × 64 lightmap in a block-compressed format, so the scene fails to load on GPUs without it"))

    def test_formats_bevy_cannot_load_everywhere(self):
        self.assertEqual(probe.check_texture(_ktx2(vk_format=0), "CUBEMAP")[0], "ERROR")
        self.assertEqual(probe.check_texture(_ktx2(vk_format=BC6H), "CUBEMAP"), ("WARNING", "16 × 16 cubemap in a block-compressed format, so the scene fails to load on GPUs without it"))
        self.assertEqual(probe.check_texture(_volume(vk_format=1000066000), "VOXELS")[0], "WARNING")
        self.assertEqual(probe.check_texture(_ktx2(vk_format=122), "CUBEMAP"), (None, "16 × 16 cubemap"))

    def test_other_files(self):
        for data in (b"", b"\x89PNG\r\n\x1a\n" + b"\0" * 100, _ktx2()[:60]):
            self.assertEqual(probe.check_texture(data, "CUBEMAP"), ("ERROR", "is not a KTX2 file"))


def _parts(data):
    dfd_offset, dfd_length = struct.unpack_from("<II", data, 48)
    data_offset, data_length = struct.unpack_from("<QQ", data, 80)
    return data[:48], data[dfd_offset:dfd_offset + dfd_length], data[data_offset:data_offset + data_length], data_offset


class TestWriting(unittest.TestCase):
    def test_rgba16f_matches_ktx_software(self):
        for name, size in (("probe_cubemap.ktx2", (16, 16, 0, 6)), ("irradiance_volume.ktx2", (2, 4, 6, 1))):
            reference = (ASSETS / name).read_bytes()
            header, dfd, pixels, _offset = _parts(reference)
            width, height, depth, faces = size
            written = probe.ktx2_rgba16f(width, height, pixels, depth=depth, faces=faces)
            self.assertEqual(_parts(written)[:3], (header, dfd, pixels), name)
            self.assertEqual(_parts(written)[3] % 8, 0, name)
            self.assertEqual(len(written), _parts(written)[3] + len(pixels), name)

    def test_rgb9e5_matches_ktx_software(self):
        reference = (ASSETS / "ground_lightmap.ktx2").read_bytes()
        header, dfd, pixels, _offset = _parts(reference)
        written = probe.ktx2_rgb9e5(16, 16, pixels)
        self.assertEqual(_parts(written)[:3], (header, dfd, pixels))
        self.assertEqual(_parts(written)[3] % 4, 0)
        self.assertEqual(len(written), _parts(written)[3] + len(pixels))
        self.assertEqual(probe.check_texture(written, "LIGHTMAP"), (None, "16 × 16 lightmap"))
        info = compression.ktx2_info(written)
        self.assertEqual((info["format"], info["model"], info["primaries"], info["transfer"], info["levels"], info["supercompression"]), (RGB9E5, 1, 1, 1, 1, 0))

    def test_written_probes_pass_the_checks(self):
        self.assertEqual(probe.check_texture(probe.ktx2_rgba16f(32, 32, bytes(32 * 32 * 8 * 6), faces=6), "CUBEMAP"), (None, "32 × 32 cubemap"))
        self.assertEqual(probe.check_texture(probe.ktx2_rgba16f(8, 8, bytes(8 * 8 * 24 * 8), depth=24), "VOXELS"), (None, "8 × 4 × 8 voxels"))
        info = compression.ktx2_info(probe.ktx2_rgba16f(4, 4, bytes(4 * 4 * 8)))
        self.assertEqual((info["format"], info["model"], info["primaries"], info["transfer"], info["channels"], info["levels"], info["supercompression"]), (RGBA16F, 1, 1, 1, [0, 1, 2, 15], 1, 0))


class TestEmbedding(unittest.TestCase):
    def test_files_become_textures_once(self):
        cubemap = _ktx2() + b"c"
        voxels = _volume() + b"v"
        lightmap = _ktx2(faces=1) + b"l"
        files = {"/scenes/room.ktx2": cubemap, "/scenes/gi.ktx2": voxels, "/scenes/floor.ktx2": lightmap}
        reads = []
        gltf, binary = _scene([{"type": "reflection_probe", "size": [1, 1, 1], "file": "/scenes/room.ktx2"}, {"type": "custom", "type_path": "game::Tag", "data": {"file": "kept"}}], [{"type": "irradiance_volume", "file": "/scenes/gi.ktx2"}, {"type": "reflection_probe", "file": "/scenes/room.ktx2"}], [{"type": "reflection_probe", "file": None}, {"type": "lightmap", "bicubic": False, "file": "/scenes/floor.ktx2"}])
        self.assertTrue(probe.needs_embedding(gltf))
        gltf, binary = probe.embed_files(gltf, binary, lambda path: reads.append(path) or files[path])
        self.assertEqual(reads, ["/scenes/room.ktx2", "/scenes/gi.ktx2", "/scenes/floor.ktx2"])
        self.assertEqual(_components(gltf, 0), [{"type": "reflection_probe", "size": [1, 1, 1], "texture": 1}, {"type": "custom", "type_path": "game::Tag", "data": {"file": "kept"}}])
        self.assertEqual(_components(gltf, 1), [{"type": "irradiance_volume", "texture": 2}, {"type": "reflection_probe", "texture": 1}])
        self.assertEqual(_components(gltf, 2), [{"type": "reflection_probe", "texture": None}, {"type": "lightmap", "bicubic": False, "texture": 3}])
        self.assertNotIn("extras", gltf["nodes"][3])
        self.assertEqual(gltf["textures"][1:], [{"sampler": 1, "source": 1}, {"sampler": 1, "source": 2}, {"sampler": 1, "source": 3}])
        self.assertEqual(gltf["samplers"][1], {"magFilter": 9729, "minFilter": 9729, "wrapS": 33071, "wrapT": 33071})
        self.assertEqual(gltf["images"][1:], [{"bufferView": 1, "mimeType": "image/ktx2", "name": "room"}, {"bufferView": 2, "mimeType": "image/ktx2", "name": "gi"}, {"bufferView": 3, "mimeType": "image/ktx2", "name": "floor"}])
        for image, data in ((1, cubemap), (2, voxels), (3, lightmap)):
            self.assertEqual(compression.image_payload(gltf, binary, image), (data, "image/ktx2"))
            self.assertEqual(gltf["bufferViews"][image]["byteOffset"] % 16, 0)
        self.assertEqual(binary[:5], b"\x89PNG!")
        self.assertEqual(gltf["buffers"], [{"byteLength": len(binary)}])
        self.assertFalse(probe.needs_embedding(gltf))

    def test_the_sky_on_the_scene_shares_textures_with_nodes(self):
        gltf, binary = _scene([{"type": "reflection_probe", "file": "/scenes/sky.ktx2"}])
        gltf["scenes"] = [{"nodes": [0], "extras": {"bevy_components": json.dumps({"version": 1, "components": [{"type": "ambient_light", "brightness": 0.0}, {"type": "sky", "brightness": 683.0, "environment_light": None, "file": "/scenes/sky.ktx2"}]}), "other": 1}}]
        reads = []
        self.assertTrue(probe.needs_embedding({"scenes": gltf["scenes"]}))
        gltf, binary = probe.embed_files(gltf, binary, lambda path: reads.append(path) or _ktx2())
        self.assertEqual(reads, ["/scenes/sky.ktx2"])
        self.assertEqual(json.loads(gltf["scenes"][0]["extras"]["bevy_components"])["components"], [{"type": "ambient_light", "brightness": 0.0}, {"type": "sky", "brightness": 683.0, "environment_light": None, "texture": 1}])
        self.assertEqual(gltf["scenes"][0]["extras"]["other"], 1)
        self.assertEqual(_components(gltf, 0), [{"type": "reflection_probe", "texture": 1}])
        self.assertFalse(probe.needs_embedding(gltf))

    def test_probes_without_files_only_lose_the_path(self):
        gltf, binary = _scene([{"type": "irradiance_volume", "file": None}])
        embedded, embedded_binary = probe.embed_files(gltf, binary, lambda path: self.fail(path))
        self.assertEqual(_components(embedded, 0), [{"type": "irradiance_volume", "texture": None}])
        self.assertEqual((len(embedded["images"]), len(embedded["samplers"]), embedded_binary), (1, 1, binary))

    def test_scenes_without_buffers_get_one(self):
        gltf = {"asset": {"version": "2.0"}, "nodes": [{"name": "probe", "extras": {"bevy_components": json.dumps({"version": 1, "components": [{"type": "reflection_probe", "file": "room.ktx2"}]})}}]}
        gltf, binary = probe.embed_files(gltf, b"", lambda path: b"ktx2")
        self.assertEqual((gltf["buffers"], gltf["bufferViews"], binary), ([{"byteLength": 4}], [{"buffer": 0, "byteOffset": 0, "byteLength": 4}], b"ktx2"))

    def test_other_scenes_are_untouched(self):
        gltf, binary = _scene([{"type": "collider", "shape": "cuboid"}])
        self.assertFalse(probe.needs_embedding(gltf))
        self.assertEqual(probe.embed_files(json.loads(json.dumps(gltf)), binary, lambda path: self.fail(path)), (gltf, binary))

    def test_plan_textures_skips_embedded_ktx2(self):
        gltf, binary = _scene([{"type": "reflection_probe", "file": "room.ktx2"}])
        png = _png(8, 8)
        gltf["bufferViews"][0]["byteLength"] = len(png)
        gltf, binary = probe.embed_files(gltf, png, lambda path: _ktx2())
        jobs = compression.plan_textures(gltf, binary, "UASTC", convert=lambda data, mime_type: self.fail(mime_type))
        self.assertEqual([job.textures for job in jobs], [[0]])


if __name__ == "__main__":
    unittest.main()
