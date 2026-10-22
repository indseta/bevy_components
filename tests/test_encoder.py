import importlib.util
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1] / "addon"
spec = importlib.util.spec_from_file_location("bevy_compression", ROOT / "compression.py")
compression = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compression)
spec = importlib.util.spec_from_file_location("bevy_encoder", ROOT / "encoder.py")
encoder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(encoder)


def _job(**values):
    defaults = {
        "name": "wood",
        "image": 0,
        "usage": "color",
        "codec": "etc1s",
        "data": b"png",
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


SETTINGS = {
    "etc1s_quality": 128,
    "etc1s_effort": 2,
    "uastc_quality": 2,
    "uastc_zstd": 18,
}


class TestDiscovery(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.directory.name) / encoder.EXECUTABLE
        self.path.write_text("")

    def tearDown(self):
        self.directory.cleanup()

    def test_configured_file_or_folder(self):
        self.assertEqual(encoder.find_encoder(str(self.path)), self.path)
        self.assertEqual(encoder.find_encoder(self.directory.name), self.path)
        self.assertIsNone(encoder.find_encoder(str(self.path.with_name("missing"))))

    def test_path_lookup(self):
        with mock.patch.object(encoder.shutil, "which", return_value=str(self.path)):
            self.assertEqual(encoder.find_encoder(), self.path)

    def test_install_locations(self):
        with mock.patch.object(encoder.shutil, "which", return_value=None), mock.patch.object(encoder, "_candidates", return_value=[self.path.with_name("missing"), self.path]):
            self.assertEqual(encoder.find_encoder(), self.path)
        with mock.patch.object(encoder.shutil, "which", return_value=None), mock.patch.object(encoder, "_candidates", return_value=[]):
            self.assertIsNone(encoder.find_encoder())

    def test_version(self):
        result = subprocess.CompletedProcess([], 0, stdout="ktx version: v4.4.2\n", stderr="")
        with mock.patch.object(encoder, "_run", return_value=result) as run:
            self.assertEqual(encoder.check_encoder(str(self.path)), (self.path, (4, 4, 2)))
            self.assertEqual(encoder.check_encoder(str(self.path)), (self.path, (4, 4, 2)))
        self.assertEqual(run.call_count, 1)

    def test_old_versions_are_rejected(self):
        result = subprocess.CompletedProcess([], 0, stdout="ktx version: v4.3.2\n", stderr="")
        with mock.patch.object(encoder, "_run", return_value=result):
            with self.assertRaisesRegex(encoder.EncoderError, "4.3.2 is too old"):
                encoder.check_encoder(str(self.path))

    def test_other_programs_are_rejected(self):
        result = subprocess.CompletedProcess([], 1, stdout="", stderr="unknown option")
        with mock.patch.object(encoder, "_run", return_value=result):
            with self.assertRaisesRegex(encoder.EncoderError, "not the KTX-Software ktx tool"):
                encoder.check_encoder(str(self.path))

    def test_missing_encoder(self):
        with mock.patch.object(encoder, "find_encoder", return_value=None):
            with self.assertRaisesRegex(encoder.EncoderError, "^KTX-Software was not found$"):
                encoder.check_encoder()
            with self.assertRaisesRegex(encoder.EncoderError, "not found at /opt/ktx"):
                encoder.check_encoder("/opt/ktx")

    def test_hint_names_the_download_and_preference(self):
        self.assertIn(encoder.DOWNLOAD_URL, encoder.HINT)
        self.assertIn("Preferences", encoder.HINT)


class TestCommands(unittest.TestCase):
    def test_etc1s_color(self):
        command = encoder.encode_command("ktx", _job(alpha=True, wrap="clamp"), SETTINGS, "in.png", "out.ktx2")
        self.assertEqual(command, ["ktx", "create", "--format", "R8G8B8A8_SRGB", "--assign-tf", "srgb", "--assign-primaries", "bt709", "--generate-mipmap", "--mipmap-wrap", "clamp", "--encode", "basis-lz", "--qlevel", "128", "--clevel", "2", "in.png", "out.ktx2"])

    def test_uastc_normal(self):
        command = encoder.encode_command("ktx", _job(usage="normal", codec="uastc", width=32, height=20, source_width=30, source_height=18), SETTINGS, "in.png", "out.ktx2")
        self.assertEqual(command, ["ktx", "create", "--format", "R8G8B8_UNORM", "--assign-tf", "linear", "--assign-primaries", "none", "--width", "32", "--height", "20", "--generate-mipmap", "--mipmap-wrap", "wrap", "--normalize", "--encode", "uastc", "--uastc-quality", "2", "--zstd", "18", "in.png", "out.ktx2"])

    def test_uastc_data_without_supercompression_or_mipmaps(self):
        command = encoder.encode_command("ktx", _job(usage="data", codec="uastc", mipmaps=False), {**SETTINGS, "uastc_zstd": 0}, "in.png", "out.ktx2")
        self.assertEqual(command, ["ktx", "create", "--format", "R8G8B8_UNORM", "--assign-tf", "linear", "--assign-primaries", "none", "--encode", "uastc", "--uastc-quality", "2", "in.png", "out.ktx2"])


class TestEncode(unittest.TestCase):
    def test_encodes_and_cleans_up(self):
        def run(command):
            pathlib.Path(command[-1]).write_bytes(pathlib.Path(command[-2]).read_bytes() + b" ktx2")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        progress = []
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(encoder, "_run", side_effect=run):
            results = encoder.encode("ktx", [_job(data=b"first"), _job(data=b"second", mime_type="image/jpeg")], SETTINGS, directory, progress=progress.append)
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [])
        self.assertEqual(results, [b"first ktx2", b"second ktx2"])
        self.assertEqual(progress, [1, 2])

    def test_reports_failures(self):
        result = subprocess.CompletedProcess([], 1, stdout="", stderr="warning: slow\nerror: unsupported input\n")
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(encoder, "_run", return_value=result):
            with self.assertRaisesRegex(encoder.EncoderError, "could not encode wood: error: unsupported input"):
                encoder.encode("ktx", [_job()], SETTINGS, directory)

    def test_reports_missing_programs(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(encoder, "_run", side_effect=FileNotFoundError("ktx")):
            with self.assertRaisesRegex(encoder.EncoderError, "Could not run ktx"):
                encoder.encode("ktx", [_job()], SETTINGS, directory)


if __name__ == "__main__":
    unittest.main()
