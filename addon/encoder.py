import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MINIMUM_VERSION = (4, 4, 0)
DOWNLOAD_URL = "https://github.com/KhronosGroup/KTX-Software/releases"
HINT = f"Install KTX-Software 4.4 or newer from {DOWNLOAD_URL}, or set the ktx path under Preferences > Add-ons > Bevy Components"
EXECUTABLE = "ktx.exe" if sys.platform == "win32" else "ktx"

_versions = {}


class EncoderError(Exception):
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


def _run(command, **options):
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run([str(part) for part in command], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=flags, **options)


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


def encode(path, jobs, settings, directory, progress=None):
    results = []
    directory = Path(directory)
    for index, job in enumerate(jobs):
        source = directory / f"texture_{index}{'.jpg' if job.mime_type == 'image/jpeg' else '.png'}"
        output = directory / f"texture_{index}.ktx2"
        source.write_bytes(job.data)
        try:
            result = _run(encode_command(path, job, settings, source, output))
        except OSError as error:
            raise EncoderError(f"Could not run {path}: {error}") from error
        if result.returncode != 0 or not output.is_file():
            message = (result.stderr or result.stdout).strip().splitlines()
            raise EncoderError(f"KTX-Software could not encode {job.name}: {message[-1] if message else f'exit code {result.returncode}'}")
        results.append(output.read_bytes())
        source.unlink()
        output.unlink()
        if progress:
            progress(index + 1)
    return results
