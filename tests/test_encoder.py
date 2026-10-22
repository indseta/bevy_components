import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
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


if __name__ == "__main__":
    unittest.main()
