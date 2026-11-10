import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy

MINIMUM_VERSION = (4, 4, 0)
DOWNLOAD_URL = "https://github.com/KhronosGroup/KTX-Software/releases"
HINT = f"Install KTX-Software 4.4 or newer from {DOWNLOAD_URL}, or set the ktx path under Preferences > Add-ons > Bevy Components"
EXECUTABLE = "ktx.exe" if sys.platform == "win32" else "ktx"
MAXIMUM_WORKERS = 4
MAXIMUM_PIXELS = MAXIMUM_WORKERS * 4096 * 4096
CACHE_LIMIT = 2 * 1024 ** 3
POLL_INTERVAL = 0.1
NICENESS = 10
COVERAGE_VERSION = 1
MAXIMUM_ALPHA_SCALE = 8.0

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
    if job.coverage:
        command += ["--levels", max(job.width, job.height).bit_length()]
    elif job.resized:
        command += ["--width", job.width, "--height", job.height]
    if job.mipmaps and not job.coverage:
        command += ["--generate-mipmap", "--mipmap-wrap", job.wrap]
    if job.normal:
        command += ["--normalize"]
    if job.codec == "etc1s":
        command += ["--encode", "basis-lz", "--qlevel", settings["etc1s_quality"], "--clevel", settings["etc1s_effort"]]
    else:
        command += ["--encode", "uastc", "--uastc-quality", settings["uastc_quality"]]
        if settings["uastc_zstd"] > 0:
            command += ["--zstd", settings["uastc_zstd"]]
    sources = list(source) if isinstance(source, (list, tuple)) else [source]
    return [str(part) for part in command + sources + [output]]


def decode_command(path, job, source, output):
    command = [path, "create", "--format", "R8G8B8A8_SRGB", "--assign-tf", "srgb", "--assign-primaries", "bt709"]
    if job.resized:
        command += ["--width", job.width, "--height", job.height, "--mipmap-wrap", job.wrap]
    return [str(part) for part in command + [source, output]]


def read_pixels(data):
    width, height = struct.unpack_from("<II", data, 20)
    supercompression = struct.unpack_from("<I", data, 44)[0]
    offset, length = struct.unpack_from("<QQ", data, 80)
    if data[:12] != b"\xabKTX 20\xbb\r\n\x1a\n" or supercompression != 0 or length != width * height * 4:
        raise ValueError("Not an uncompressed RGBA8 KTX2 file")
    return numpy.frombuffer(data, dtype=numpy.uint8, count=length, offset=offset).reshape(height, width, 4)


def write_png(pixels):
    height, width = pixels.shape[:2]
    rows = numpy.concatenate([numpy.zeros((height, 1), dtype=numpy.uint8), pixels.reshape(height, width * 4)], axis=1)

    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows.tobytes(), 1)) + chunk(b"IEND", b"")


def _linear(values):
    return numpy.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)


def _srgb(values):
    values = numpy.clip(values, 0.0, 1.0)
    return numpy.where(values <= 0.0031308, values * 12.92, 1.055 * values ** (1 / 2.4) - 0.055)


def _bytes(values):
    return numpy.rint(numpy.clip(values, 0.0, 1.0) * 255).astype(numpy.uint8)


def _shrink(values, axis):
    size = values.shape[axis]
    if size == 1:
        return values
    count = size // 2
    if size % 2 == 0:
        return values.reshape(values.shape[:axis] + (count, 2) + values.shape[axis + 1:]).mean(axis=axis + 1)
    step = size / count
    low = numpy.arange(count) * step
    shape = [-1 if dimension == axis else 1 for dimension in range(values.ndim)]
    total = 0
    for offset in range(4):
        index = numpy.floor(low).astype(numpy.int64) + offset
        weight = numpy.clip(numpy.minimum(index + 1, low + step) - numpy.maximum(index, low), 0, None) / step
        total = total + numpy.take(values, numpy.minimum(index, size - 1), axis=axis) * weight.reshape(shape)
    return total


def _halve(values):
    return _shrink(_shrink(values, 0), 1)


def alpha_scale(alpha, share, cutoff):
    if share == 0:
        return 1.0
    count = min(alpha.size, max(1, round(share * alpha.size)))
    threshold = numpy.partition(alpha.ravel(), alpha.size - count)[alpha.size - count]
    if threshold <= 0:
        return MAXIMUM_ALPHA_SCALE
    return min((cutoff + 0.5 / 255) / float(threshold), MAXIMUM_ALPHA_SCALE)


def coverage_levels(pixels, cutoff):
    levels = [pixels]
    alpha = pixels[..., 3].astype(numpy.float32) / 255
    colour = _linear(numpy.arange(256, dtype=numpy.float32) / 255)[pixels[..., :3]]
    share = numpy.count_nonzero(alpha >= numpy.float32(cutoff)) / alpha.size
    while max(alpha.shape) > 1:
        weighted = _halve(colour * alpha[..., None])
        plain = _halve(colour)
        alpha = _halve(alpha)
        covered = alpha[..., None] > 0
        colour = numpy.where(covered, weighted / numpy.where(covered, alpha[..., None], 1), plain)
        scaled = alpha * alpha_scale(alpha, share, cutoff)
        levels.append(numpy.concatenate([_bytes(_srgb(colour)), _bytes(scaled)[..., None]], axis=-1))
    return levels


def workers(jobs):
    largest = max((job.width * job.height for job in jobs), default=1)
    return max(1, min(len(jobs), MAXIMUM_WORKERS, (os.cpu_count() or 2) // 2, MAXIMUM_PIXELS // largest))


def cache_key(path, job, settings):
    digest = hashlib.sha256()
    for part in encode_command(path, job, settings, "", "")[:-2]:
        digest.update(part.encode("utf-8") + b"\0")
    if job.coverage:
        digest.update(f"coverage {COVERAGE_VERSION} {job.cutoff!r} {job.width}x{job.height} {job.wrap}".encode("utf-8") + b"\0")
    digest.update(job.data)
    return digest.hexdigest()


def _encode_job(path, job, settings, directory, index, cancel):
    if cancel.is_set():
        raise EncodingCancelled()
    source = directory / f"texture_{index}{'.jpg' if job.mime_type == 'image/jpeg' else '.png'}"
    output = directory / f"texture_{index}.ktx2"
    levels = []
    source.write_bytes(job.data)
    try:
        sources = source
        if job.coverage:
            _check_result(_run(decode_command(path, job, source, output), cancel=cancel), job, output)
            try:
                pixels = read_pixels(output.read_bytes())
            except (ValueError, struct.error) as error:
                raise EncoderError(f"KTX-Software could not decode {job.name}: {error}") from error
            output.unlink()
            for level, image in enumerate(coverage_levels(pixels, job.cutoff)):
                if cancel.is_set():
                    raise EncodingCancelled()
                levels.append(directory / f"texture_{index}_level_{level}.png")
                levels[-1].write_bytes(write_png(image))
            sources = levels
        result = _run(encode_command(path, job, settings, sources, output), cancel=cancel)
        _check_result(result, job, output)
        return output.read_bytes()
    except OSError as error:
        raise EncoderError(f"Could not run {path}: {error}") from error
    finally:
        source.unlink()
        output.unlink(missing_ok=True)
        for level in levels:
            level.unlink(missing_ok=True)


def _check_result(result, job, output):
    if result.returncode != 0 or not output.is_file():
        message = (result.stderr or result.stdout).strip().splitlines()
        raise EncoderError(f"KTX-Software could not encode {job.name}: {message[-1] if message else f'exit code {result.returncode}'}")


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
