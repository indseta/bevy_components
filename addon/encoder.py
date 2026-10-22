import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

MINIMUM_VERSION = (4, 4, 0)
DOWNLOAD_URL = "https://github.com/KhronosGroup/KTX-Software/releases"
HINT = f"Install KTX-Software 4.4 or newer from {DOWNLOAD_URL}, or set the ktx path under Preferences > Add-ons > Bevy Components"
EXECUTABLE = "ktx.exe" if sys.platform == "win32" else "ktx"
MAXIMUM_WORKERS = 4
MAXIMUM_PIXELS = MAXIMUM_WORKERS * 4096 * 4096
CACHE_LIMIT = 2 * 1024 ** 3
POLL_INTERVAL = 0.1
NICENESS = 10

_versions = {}


class EncoderError(Exception):
    pass


class EncodingCancelled(Exception):
    pass


def _candidates():
    if sys.platform == "win32":
        return [Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "KTX-Software" / "bin" / EXECUTABLE]
    if sys.platform == "darwin":
        return [Path("/usr/local/bin") / EXECUTABLE, Path("/opt/homebrew/bin") / EXECUTABLE]
    return [Path("/usr/local/bin") / EXECUTABLE, Path("/usr/bin") / EXECUTABLE, Path.home() / ".local" / "bin" / EXECUTABLE]


def find_encoder(configured=""):
    if configured:
        path = Path(configured).expanduser()
        if path.is_dir():
            path = path / EXECUTABLE
        return path if path.is_file() else None
    found = shutil.which(EXECUTABLE)
    if found:
        return Path(found)
    return next((path for path in _candidates() if path.is_file()), None)


def _run(command, cancel=None, **options):
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    arguments = [str(part) for part in command]
    if cancel is None:
        return subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=flags, **options)
    if sys.platform == "win32":
        flags |= subprocess.BELOW_NORMAL_PRIORITY_CLASS
    with subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=flags) as process:
        _lower_priority(process)
        while True:
            try:
                stdout, stderr = process.communicate(timeout=POLL_INTERVAL)
            except subprocess.TimeoutExpired:
                if cancel.is_set():
                    process.kill()
                    process.communicate()
                    raise EncodingCancelled() from None
                continue
            return subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)


def _lower_priority(process):
    if not hasattr(os, "setpriority"):
        return
    try:
        os.setpriority(os.PRIO_PROCESS, process.pid, min(os.getpriority(os.PRIO_PROCESS, 0) + NICENESS, 19))
    except OSError:
        return


def encoder_version(path):
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _versions:
        try:
            result = _run([path, "--version"], timeout=20)
        except (OSError, subprocess.SubprocessError) as error:
            raise EncoderError(f"Could not run {path}: {error}") from error
        match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", result.stdout + result.stderr)
        if result.returncode != 0 or match is None:
            raise EncoderError(f"{path} is not the KTX-Software ktx tool")
        _versions[key] = tuple(int(part) for part in match.groups())
    return _versions[key]


def check_encoder(configured=""):
    path = find_encoder(configured)
    if path is None:
        if configured:
            raise EncoderError(f"KTX-Software was not found at {configured}")
        raise EncoderError("KTX-Software was not found")
    version = encoder_version(path)
    if version < MINIMUM_VERSION:
        raise EncoderError(f"KTX-Software {'.'.join(map(str, version))} is too old, version {'.'.join(map(str, MINIMUM_VERSION))} or newer is needed")
    return path, version


def encode_command(path, job, settings, source, output):
    command = [path, "create", "--format", f"R8G8B8{'A8' if job.alpha else ''}_{'SRGB' if job.srgb else 'UNORM'}", "--assign-tf", "srgb" if job.srgb else "linear", "--assign-primaries", "bt709" if job.srgb else "none"]
    if job.resized:
        command += ["--width", job.width, "--height", job.height]
    if job.mipmaps:
        command += ["--generate-mipmap", "--mipmap-wrap", job.wrap]
    if job.normal:
        command += ["--normalize"]
    if job.codec == "etc1s":
        command += ["--encode", "basis-lz", "--qlevel", settings["etc1s_quality"], "--clevel", settings["etc1s_effort"]]
    else:
        command += ["--encode", "uastc", "--uastc-quality", settings["uastc_quality"]]
        if settings["uastc_zstd"] > 0:
            command += ["--zstd", settings["uastc_zstd"]]
    return [str(part) for part in command + [source, output]]


def workers(jobs):
    largest = max((job.width * job.height for job in jobs), default=1)
    return max(1, min(len(jobs), MAXIMUM_WORKERS, (os.cpu_count() or 2) // 2, MAXIMUM_PIXELS // largest))


def cache_key(path, job, settings):
    digest = hashlib.sha256()
    for part in encode_command(path, job, settings, "", "")[:-2]:
        digest.update(part.encode("utf-8") + b"\0")
    digest.update(job.data)
    return digest.hexdigest()


def _encode_job(path, job, settings, directory, index, cancel):
    if cancel.is_set():
        raise EncodingCancelled()
    source = directory / f"texture_{index}{'.jpg' if job.mime_type == 'image/jpeg' else '.png'}"
    output = directory / f"texture_{index}.ktx2"
    source.write_bytes(job.data)
    try:
        result = _run(encode_command(path, job, settings, source, output), cancel=cancel)
        if result.returncode != 0 or not output.is_file():
            message = (result.stderr or result.stdout).strip().splitlines()
            raise EncoderError(f"KTX-Software could not encode {job.name}: {message[-1] if message else f'exit code {result.returncode}'}")
        return output.read_bytes()
    except OSError as error:
        raise EncoderError(f"Could not run {path}: {error}") from error
    finally:
        source.unlink()
        output.unlink(missing_ok=True)


def _read_cache(cache, key):
    if cache is None:
        return None
    entry = Path(cache) / f"{key}.ktx2"
    try:
        data = entry.read_bytes()
        os.utime(entry)
    except OSError:
        return None
    return data


def _write_cache(cache, key, data):
    if cache is None:
        return
    entry = Path(cache) / f"{key}.ktx2"
    staging = entry.with_suffix(".tmp")
    try:
        staging.write_bytes(data)
        os.replace(staging, entry)
    except OSError:
        staging.unlink(missing_ok=True)


def prune_cache(cache, limit=CACHE_LIMIT):
    try:
        entries = sorted(((entry.stat(), entry) for entry in Path(cache).glob("*.ktx2")), key=lambda pair: pair[0].st_mtime, reverse=True)
        total = 0
        for status, entry in entries:
            total += status.st_size
            if total > limit:
                entry.unlink(missing_ok=True)
    except OSError:
        return


def encode(path, jobs, settings, directory, progress=None, cache=None, check=None, cancel=None):
    directory = Path(directory)
    cancel = threading.Event() if cancel is None else cancel
    keys = [cache_key(path, job, settings) for job in jobs]
    results = [_read_cache(cache, key) for key in keys]
    if check:
        results = [None if data is None or check(job, data) else data for job, data in zip(jobs, results)]
    pending = [index for index, data in enumerate(results) if data is None]
    done = len(jobs) - len(pending)
    if progress and done:
        progress(done)
    executor = ThreadPoolExecutor(max_workers=workers([jobs[index] for index in pending]))
    try:
        futures = {executor.submit(_encode_job, path, jobs[index], settings, directory, index, cancel): index for index in pending}
        for future in as_completed(futures):
            index = futures[future]
            results[index] = future.result()
            if not (check and check(jobs[index], results[index])):
                _write_cache(cache, keys[index], results[index])
            done += 1
            if progress:
                progress(done)
    finally:
        cancel.set()
        executor.shutdown(cancel_futures=True)
    if cache is not None:
        prune_cache(cache)
    return results


class BackgroundEncode:
    def __init__(self, path, jobs, settings, directory, cache=None, check=None):
        self.total = len(jobs)
        self.done = 0
        self.results = None
        self.error = None
        self.cancelled = False
        self._cancel = threading.Event()
        self._thread = threading.Thread(target=self._encode, args=(path, jobs, settings, directory, cache, check), name="bevy_components_encode", daemon=True)
        self._thread.start()

    @property
    def running(self):
        return self._thread.is_alive()

    def cancel(self):
        self.cancelled = True
        self._cancel.set()

    def wait(self, timeout=None):
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _progress(self, done):
        self.done = done

    def _encode(self, path, jobs, settings, directory, cache, check):
        try:
            self.results = encode(path, jobs, settings, directory, progress=self._progress, cache=cache, check=check, cancel=self._cancel)
        except Exception as error:
            self.error = error
