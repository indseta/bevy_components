import importlib.util
import json
import pathlib
import struct
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "addon" / "reference.py"
WINDMILL = ROOT / "importer" / "tests" / "assets" / "props" / "windmill.glb"
spec = importlib.util.spec_from_file_location("bevy_reference", MODULE)
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


def glb(gltf):
    data = json.dumps(gltf).encode()
    data += b" " * (-len(data) % 4)
    return b"glTF" + struct.pack("<II", 2, 20 + len(data)) + struct.pack("<I4s", len(data), b"JSON") + data


def cube(minimum=(-1, -1, -1), maximum=(1, 1, 1)):
    return {"accessors": [{"min": list(minimum), "max": list(maximum)}], "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]}


def rounded(bounds):
    return None if bounds is None else tuple(tuple(round(value, 5) for value in corner) for corner in bounds)


class TestSceneBounds(unittest.TestCase):
    def test_windmill_fixture(self):
        scenes = reference.read_scenes(WINDMILL)
        self.assertEqual(len(scenes), 1)
        self.assertEqual(rounded(scenes[0]), ((-1.2, 0.0, -0.3), (1.2, 3.0, 0.45)))

    def test_node_transforms_reach_children(self):
        gltf = {
            **cube(),
            "nodes": [
                {"translation": [10, 0, 0], "scale": [2, 2, 2], "children": [1]},
                {"mesh": 0, "rotation": [0, 0, 0.7071068, 0.7071068], "translation": [0, 1, 0]},
                {"mesh": 0, "matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -5, 0, 0, 1]},
            ],
            "scenes": [{"nodes": [0]}, {"nodes": [2]}, {"nodes": []}],
        }
        self.assertEqual([rounded(bounds) for bounds in reference.scene_bounds(gltf)], [((8.0, 0.0, -2.0), (12.0, 4.0, 2.0)), ((-6.0, -1.0, -1.0), (-4.0, 1.0, 1.0)), None])

    def test_gltf_json_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "rock.gltf"
            path.write_text(json.dumps({**cube((0, 0, 0), (1, 2, 3)), "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}]}))
            self.assertEqual(rounded(reference.read_scenes(path)[0]), ((0.0, 0.0, 0.0), (1.0, 2.0, 3.0)))

    def test_invalid_files(self):
        cases = {
            "truncated": b"glTF\x02\x00",
            "binary": b"\xff\xfe\x00",
            "no_json": glb({})[:16] + b"BIN\x00" + glb({})[20:],
            "missing_accessor": glb({"meshes": [{"primitives": [{"attributes": {"POSITION": 3}}]}], "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}]}),
            "cycle": glb({"nodes": [{"children": [1]}, {"children": [0]}], "scenes": [{"nodes": [0]}]}),
            "bad_scene": glb({"scenes": [{"nodes": 5}]}),
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, data in cases.items():
                path = pathlib.Path(directory) / f"{name}.glb"
                path.write_bytes(data)
                with self.assertRaises(ValueError, msg=name):
                    reference.read_scenes(path)
            with self.assertRaises(OSError):
                reference.read_scenes(pathlib.Path(directory) / "missing.glb")

    def test_changed_files_are_read_again(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "prop.glb"
            path.write_bytes(b"glTF\x02")
            with self.assertRaises(ValueError):
                reference.read_scenes(path)
            path.write_bytes(glb({"nodes": [], "scenes": [{}, {}]}))
            self.assertEqual(reference.read_scenes(path), [None, None])
            self.assertIs(reference.read_scenes(path), reference.read_scenes(path))

    def test_cache_stays_small(self):
        with tempfile.TemporaryDirectory() as directory:
            for index in range(reference.CACHE_LIMIT + 5):
                path = pathlib.Path(directory) / f"prop_{index}.glb"
                path.write_bytes(glb({"scenes": []}))
                reference.read_scenes(path)
        self.assertLessEqual(len(reference._scenes), reference.CACHE_LIMIT)


if __name__ == "__main__":
    unittest.main()
