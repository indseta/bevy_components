import importlib.util
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zlib
from unittest import mock

import numpy

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


    def test_coverage_levels_replace_generated_mipmaps(self):
        job = _job(alpha=True, cutoff=0.3, width=64, height=32, source_width=60, source_height=30)
        command = encoder.encode_command("ktx", job, SETTINGS, ["0.png", "1.png"], "out.ktx2")
        self.assertEqual(command, ["ktx", "create", "--format", "R8G8B8A8_SRGB", "--assign-tf", "srgb", "--assign-primaries", "bt709", "--levels", "7", "--encode", "basis-lz", "--qlevel", "128", "--clevel", "2", "0.png", "1.png", "out.ktx2"])
        command = encoder.decode_command("ktx", job, "in.png", "raw.ktx2")
        self.assertEqual(command, ["ktx", "create", "--format", "R8G8B8A8_SRGB", "--assign-tf", "srgb", "--assign-primaries", "bt709", "--width", "64", "--height", "32", "--mipmap-wrap", "wrap", "in.png", "raw.ktx2"])
        self.assertEqual(encoder.decode_command("ktx", _job(alpha=True, cutoff=0.3), "in.png", "raw.ktx2")[-4:], ["--assign-primaries", "bt709", "in.png", "raw.ktx2"])


LEAF = (40, 160, 50)


def _leaves(width, height, seed=1):
    random = numpy.random.default_rng(seed)
    y, x = numpy.mgrid[0:height, 0:width]
    alpha = numpy.zeros((height, width))
    for centre_x, centre_y, radius in random.uniform((0, 0, 1.5), (width, height, 4.0), (width * height // 64, 3)):
        alpha = numpy.maximum(alpha, numpy.clip(2.0 - numpy.hypot(x - centre_x, y - centre_y) / radius, 0.0, 1.0))
    pixels = numpy.zeros((height, width, 4), dtype=numpy.uint8)
    pixels[...] = (255, 0, 0, 0)
    pixels[alpha > 0, :3] = LEAF
    pixels[..., 3] = numpy.rint(alpha * 255)
    return pixels


def _covered(pixels, cutoff=0.3):
    return numpy.count_nonzero(pixels[..., 3] / 255 >= cutoff) / pixels[..., 3].size


def _read_png(data):
    width, height = struct.unpack_from(">II", data, 16)
    offset = 8
    payload = b""
    while offset < len(data):
        length, kind = struct.unpack_from(">I4s", data, offset)
        if kind == b"IDAT":
            payload += data[offset + 8:offset + 8 + length]
        offset += 12 + length
    rows = numpy.frombuffer(zlib.decompress(payload), dtype=numpy.uint8).reshape(height, width * 4 + 1)
    return rows[:, 1:].reshape(height, width, 4)


def _raw_ktx2(pixels):
    height, width = pixels.shape[:2]
    header = b"\xabKTX 20\xbb\r\n\x1a\n" + struct.pack("<9I", 43, 1, width, height, 0, 0, 1, 1, 0) + struct.pack("<IIIIQQ", 0, 0, 0, 0, 0, 0)
    return header + struct.pack("<QQQ", len(header) + 24, pixels.size, pixels.size) + pixels.tobytes()


class TestCoverage(unittest.TestCase):
    def test_levels_keep_the_share_of_texels_above_the_cutoff(self):
        pixels = _leaves(256, 256)
        levels = encoder.coverage_levels(pixels, 0.3)
        self.assertTrue(numpy.array_equal(levels[0], pixels))
        self.assertEqual(len(levels), 9)
        for level in levels:
            if level.shape[0] >= 16:
                self.assertAlmostEqual(_covered(level) / _covered(pixels), 1.0, delta=0.01)
        alpha = pixels[..., 3] / 255
        drift = []
        for _level in range(4):
            alpha = encoder._halve(alpha)
            drift.append(numpy.count_nonzero(alpha >= 0.3) / alpha.size / _covered(pixels))
        self.assertGreater(max(abs(share - 1.0) for share in drift), 0.1)

    def test_levels_match_the_ktx2_mipmap_sizes(self):
        levels = encoder.coverage_levels(_leaves(100, 60), 0.5)
        self.assertEqual([level.shape for level in levels], [(60, 100, 4), (30, 50, 4), (15, 25, 4), (7, 12, 4), (3, 6, 4), (1, 3, 4), (1, 1, 4)])

    def test_transparent_colour_does_not_bleed_into_leaves(self):
        for level in encoder.coverage_levels(_leaves(64, 64), 0.3)[1:]:
            visible = level[..., 3] > 0
            self.assertTrue(numpy.all(numpy.abs(level[visible, :3].astype(int) - LEAF) <= 1))

    def test_alpha_scale(self):
        alpha = numpy.array([0.0, 0.1, 0.2, 0.6])
        self.assertAlmostEqual(encoder.alpha_scale(alpha, 0.5, 0.3), (0.3 + 0.5 / 255) / 0.2)
        self.assertAlmostEqual(encoder.alpha_scale(alpha, 0.25, 0.3), (0.3 + 0.5 / 255) / 0.6)
        self.assertEqual(encoder.alpha_scale(alpha, 0.0, 0.3), 1.0)
        self.assertEqual(encoder.alpha_scale(alpha, 1.0, 0.3), encoder.MAXIMUM_ALPHA_SCALE)

    def test_png_and_raw_ktx2_round_trip(self):
        pixels = _leaves(12, 8)
        self.assertTrue(numpy.array_equal(_read_png(encoder.write_png(pixels)), pixels))
        self.assertTrue(numpy.array_equal(encoder.read_pixels(_raw_ktx2(pixels)), pixels))
        with self.assertRaises(ValueError):
            encoder.read_pixels(_raw_ktx2(pixels)[:-4] + b"")

    def test_coverage_jobs_encode_their_own_levels(self):
        pixels = _leaves(16, 8)
        commands = []

        def run(command, **_options):
            commands.append(command)
            if "--levels" in command:
                commands[-1] = [_read_png(pathlib.Path(part).read_bytes()) for part in command if part.endswith(".png")]
                pathlib.Path(command[-1]).write_bytes(b"encoded")
            else:
                pathlib.Path(command[-1]).write_bytes(_raw_ktx2(pixels))
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        job = _job(alpha=True, cutoff=0.3, width=16, height=8, source_width=16, source_height=8)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(encoder, "_run", side_effect=run):
            self.assertEqual(encoder.encode("ktx", [job], SETTINGS, directory), [b"encoded"])
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [])
        self.assertEqual(commands[0][-2:], [str(pathlib.Path(directory) / "texture_0.png"), str(pathlib.Path(directory) / "texture_0.ktx2")])
        self.assertEqual([level.shape[:2] for level in commands[1]], [(8, 16), (4, 8), (2, 4), (1, 2), (1, 1)])
        self.assertTrue(numpy.array_equal(commands[1][0], pixels))

    def test_undecodable_textures_are_reported(self):
        def run(command, **_options):
            pathlib.Path(command[-1]).write_bytes(b"not a ktx2 file")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(encoder, "_run", side_effect=run):
            with self.assertRaisesRegex(encoder.EncoderError, "could not decode wood"):
                encoder.encode("ktx", [_job(alpha=True, cutoff=0.3)], SETTINGS, directory)
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [])


def _fake_run(command, **_options):
    pathlib.Path(command[-1]).write_bytes(pathlib.Path(command[-2]).read_bytes() + b" ktx2")
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


class TestEncode(unittest.TestCase):
    def test_encodes_and_cleans_up(self):
        run = _fake_run
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

    def test_encodes_textures_side_by_side(self):
        barrier = threading.Barrier(2, timeout=5)

        def run(command, **options):
            barrier.wait()
            return _fake_run(command, **options)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(encoder, "_run", side_effect=run), mock.patch.object(encoder.os, "cpu_count", return_value=8):
            results = encoder.encode("ktx", [_job(data=b"first"), _job(data=b"second")], SETTINGS, directory)
        self.assertEqual(results, [b"first ktx2", b"second ktx2"])

    def test_workers_leave_cores_and_memory_for_each_encoder(self):
        with mock.patch.object(encoder.os, "cpu_count", return_value=16):
            self.assertEqual([encoder.workers([_job()] * count) for count in (0, 1, 3, 10)], [1, 1, 3, 4])
            self.assertEqual(encoder.workers([_job(width=4096, height=4096)] * 10), 4)
            self.assertEqual(encoder.workers([_job()] * 9 + [_job(width=8192, height=4096)]), 2)
            self.assertEqual(encoder.workers([_job()] * 9 + [_job(width=8192, height=8192)]), 1)
        with mock.patch.object(encoder.os, "cpu_count", return_value=None):
            self.assertEqual(encoder.workers([_job()] * 10), 1)

    def test_failures_stop_the_remaining_textures(self):
        calls = []

        def run(command, **_options):
            calls.append(command)
            time.sleep(0.05)
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="error: broken")
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(encoder, "_run", side_effect=run), mock.patch.object(encoder.os, "cpu_count", return_value=2):
            with self.assertRaisesRegex(encoder.EncoderError, "could not encode wood: error: broken"):
                encoder.encode("ktx", [_job(data=bytes([index])) for index in range(5)], SETTINGS, directory)
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [])
        self.assertLessEqual(len(calls), 2)

    def test_reports_missing_programs(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(encoder, "_run", side_effect=FileNotFoundError("ktx")):
            with self.assertRaisesRegex(encoder.EncoderError, "Could not run ktx"):
                encoder.encode("ktx", [_job()], SETTINGS, directory)

    def test_a_failure_stops_the_other_encoders(self):
        def command(path, job, settings, source, output):
            return [sys.executable, "-c", "import sys; sys.exit('error: broken')" if job.name == "broken" else "import time; time.sleep(60)"]
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(encoder, "encode_command", side_effect=command), mock.patch.object(encoder.os, "cpu_count", return_value=8):
            with self.assertRaisesRegex(encoder.EncoderError, "could not encode broken: error: broken"):
                encoder.encode("ktx", [_job(name="slow"), _job(name="broken", data=b"other")], SETTINGS, directory)
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [])
        self.assertLess(time.monotonic() - started, 30)


SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]


class TestBackground(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.work = pathlib.Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_cancel_kills_the_process(self):
        cancel = threading.Event()
        timer = threading.Timer(0.3, cancel.set)
        timer.start()
        started = time.monotonic()
        with self.assertRaises(encoder.EncodingCancelled):
            encoder._run(SLEEP, cancel=cancel)
        timer.join()
        self.assertLess(time.monotonic() - started, 30)

    def test_output_is_captured_while_waiting_for_cancel(self):
        result = encoder._run([sys.executable, "-c", "import sys; print('out'); sys.exit('error: broken')"], cancel=threading.Event())
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, "out\n", "error: broken\n"))

    def test_results_and_progress(self):
        with mock.patch.object(encoder, "_run", side_effect=_fake_run):
            task = encoder.BackgroundEncode("ktx", [_job(data=b"first"), _job(data=b"second")], SETTINGS, self.work)
            self.assertTrue(task.wait(30))
        self.assertFalse(task.running)
        self.assertEqual((task.done, task.total, task.results, task.error, task.cancelled), (2, 2, [b"first ktx2", b"second ktx2"], None, False))
        self.assertEqual(list(self.work.iterdir()), [])

    def test_errors_are_kept(self):
        result = subprocess.CompletedProcess([], 1, stdout="", stderr="error: broken")
        with mock.patch.object(encoder, "_run", return_value=result):
            task = encoder.BackgroundEncode("ktx", [_job()], SETTINGS, self.work)
            self.assertTrue(task.wait(30))
        self.assertIsNone(task.results)
        self.assertIsInstance(task.error, encoder.EncoderError)
        self.assertIn("could not encode wood: error: broken", str(task.error))

    def test_cancel_stops_running_and_waiting_textures(self):
        with mock.patch.object(encoder, "encode_command", return_value=SLEEP), mock.patch.object(encoder.os, "cpu_count", return_value=4):
            task = encoder.BackgroundEncode("ktx", [_job(data=bytes([index])) for index in range(5)], SETTINGS, self.work)
            deadline = time.monotonic() + 30
            while len(list(self.work.iterdir())) < 2 and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(task.running)
            task.cancel()
            self.assertTrue(task.wait(30))
        self.assertTrue(task.cancelled)
        self.assertIsInstance(task.error, encoder.EncodingCancelled)
        self.assertIsNone(task.results)
        self.assertEqual(task.done, 0)
        self.assertEqual(list(self.work.iterdir()), [])


class TestCache(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.work = pathlib.Path(self.directory.name) / "work"
        self.cache = pathlib.Path(self.directory.name) / "cache"
        self.work.mkdir()
        self.cache.mkdir()

    def tearDown(self):
        self.directory.cleanup()

    def _encode(self, jobs, settings=SETTINGS, check=None):
        progress = []
        with mock.patch.object(encoder, "_run", side_effect=_fake_run) as run:
            results = encoder.encode("ktx", jobs, settings, self.work, progress=progress.append, cache=self.cache, check=check)
        return results, run.call_count, progress

    def test_unchanged_textures_are_reused(self):
        jobs = [_job(data=b"first"), _job(data=b"second")]
        self.assertEqual(self._encode(jobs), ([b"first ktx2", b"second ktx2"], 2, [1, 2]))
        self.assertEqual(self._encode(jobs), ([b"first ktx2", b"second ktx2"], 0, [2]))
        self.assertEqual(self._encode([jobs[0], _job(data=b"third")]), ([b"first ktx2", b"third ktx2"], 1, [1, 2]))
        self.assertEqual(len(list(self.cache.glob("*.ktx2"))), 3)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_settings_and_usage_change_the_key(self):
        job = _job(data=b"first")
        keys = {encoder.cache_key("ktx", job, SETTINGS), encoder.cache_key("ktx", job, {**SETTINGS, "etc1s_quality": 64}), encoder.cache_key("ktx", _job(data=b"first", usage="data"), SETTINGS), encoder.cache_key("other/ktx", job, SETTINGS)}
        self.assertEqual(len(keys), 4)
        self.assertEqual(encoder.cache_key("ktx", job, SETTINGS), encoder.cache_key("ktx", _job(data=b"first", name="other", image=3), SETTINGS))

    def test_coverage_and_cutoff_change_the_key(self):
        keys = {encoder.cache_key("ktx", _job(data=b"first", alpha=True, cutoff=cutoff, width=width, source_width=width), SETTINGS) for cutoff in (None, 0.3, 0.5) for width in (60, 64)}
        self.assertEqual(len(keys), 5)

    def test_rejected_results_are_not_kept(self):
        job = _job(data=b"first")
        self.assertEqual(self._encode([job], check=lambda job, data: "broken")[1], 1)
        self.assertEqual(list(self.cache.iterdir()), [])
        (self.cache / f"{encoder.cache_key('ktx', job, SETTINGS)}.ktx2").write_bytes(b"corrupt")
        self.assertEqual(self._encode([job], check=lambda job, data: "corrupt" if data == b"corrupt" else None)[:2], ([b"first ktx2"], 1))
        self.assertEqual((self.cache / f"{encoder.cache_key('ktx', job, SETTINGS)}.ktx2").read_bytes(), b"first ktx2")

    def test_least_recently_used_entries_are_pruned(self):
        for index, name in enumerate(("old", "middle", "new")):
            entry = self.cache / f"{name}.ktx2"
            entry.write_bytes(b"x" * 10)
            os.utime(entry, (1000 + index, 1000 + index))
        encoder.prune_cache(self.cache, limit=25)
        self.assertEqual(sorted(entry.name for entry in self.cache.iterdir()), ["middle.ktx2", "new.ktx2"])
        encoder.prune_cache(self.cache / "missing")


@unittest.skipUnless(os.environ.get("BEVY_COMPONENTS_REQUIRE_KTX") or encoder.find_encoder(), "KTX-Software is not installed")
class TestCoverageEncoding(unittest.TestCase):
    def test_encoded_levels_keep_their_coverage(self):
        path, _version = encoder.check_encoder()
        pixels = _leaves(256, 256)
        for codec in ("etc1s", "uastc"):
            job = _job(name="leaves", codec=codec, data=encoder.write_png(pixels), alpha=True, cutoff=0.3, width=256, height=256, source_width=256, source_height=256)
            with tempfile.TemporaryDirectory() as directory:
                data = encoder.encode(path, [job], SETTINGS, directory)[0]
                self.assertIsNone(compression.check_encoded(job, data))
                source = pathlib.Path(directory) / "leaves.ktx2"
                output = pathlib.Path(directory) / "rgba.ktx2"
                source.write_bytes(data)
                result = encoder._run([path, "transcode", "--target", "rgba8", source, output])
                self.assertEqual(result.returncode, 0, result.stderr)
                decoded = output.read_bytes()
            for level in range(5):
                offset, length = struct.unpack_from("<QQ", decoded, 80 + 24 * level)
                size = 256 >> level
                image = numpy.frombuffer(decoded, dtype=numpy.uint8, count=length, offset=offset).reshape(size, size, 4)
                self.assertAlmostEqual(_covered(image) / _covered(pixels), 1.0, delta=0.05, msg=f"{codec} level {level}")


if __name__ == "__main__":
    unittest.main()
