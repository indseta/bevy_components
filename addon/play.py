import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
from collections import deque
from pathlib import Path

SCENE_PLACEHOLDER = "{scene}"
DEFAULT_COMMAND = "cargo run"
VIEWER_COMMAND = "cargo run --example viewer -- {scene}"
VIEWER_EXAMPLE = Path("examples") / "viewer.rs"
OUTPUT_LINES = 2000
KILL_DELAY = 3.0
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
CARGO_LAUNCH = re.compile(r"^\s*Running `")
ERROR_LINE = re.compile(r"^(error\b|ERROR\b)")
PANIC_LINE = re.compile(r"panicked at ")
IMPORTER_WARNING = re.compile(r"\bWARN\b.*?\bbevy_components_importer[\w:]*: (?P<message>.+)$")
LOG_PREFIX = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z\s+(?P<level>[A-Z]+)\s+[\w:]+: ")
VIEW_VARIABLE = "BEVY_COMPONENTS_VIEW"
QUIET_ENVIRONMENT = {
    "NO_COLOR": "1",
    "CARGO_TERM_COLOR": "never",
    "CARGO_TERM_PROGRESS_WHEN": "never",
}


class PlayError(Exception):
    pass


def check_game_folder(folder):
    path = Path(folder)
    if not path.is_dir():
        raise PlayError(f"The game project folder {path} does not exist")
    if not (path / "Cargo.toml").is_file():
        raise PlayError(f"{path} has no Cargo.toml, pick the folder of your game's Cargo project")
    return path


def check_viewer_folder(folder):
    path = Path(folder)
    if not (path / VIEWER_EXAMPLE).is_file() or not (path / "Cargo.toml").is_file():
        raise PlayError(f"{path} has no viewer example, pick the bevy_components_importer folder")
    return path


def split_command(command):
    if os.name != "nt":
        return shlex.split(command)
    return [part[1:-1] if len(part) > 1 and part[0] == part[-1] == "\"" else part for part in shlex.split(command, posix=False)]


def find_program(name, folder):
    if "/" in name or "\\" in name:
        path = Path(name) if Path(name).is_absolute() else Path(folder) / name
        return str(path) if path.is_file() else None
    found = shutil.which(name)
    if found:
        return found
    cargo_bin = Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo") / "bin"
    for candidate in (cargo_bin / name, cargo_bin / f"{name}.exe"):
        if candidate.is_file():
            return str(candidate)
    return None


def needs_scene(command):
    return SCENE_PLACEHOLDER in command


def game_command(command, folder, scene=None):
    try:
        parts = split_command(command)
    except ValueError as error:
        raise PlayError(f"Could not read the run command: {error}")
    if not parts:
        raise PlayError("The run command is empty")
    if needs_scene(command) and scene is None:
        raise PlayError("The run command needs {scene}, export the scene once with File > Export > Bevy glTF (.glb)")
    program = find_program(parts[0], folder)
    if program is None:
        raise PlayError(f"Could not find {parts[0]}. Install Rust from rustup.rs, or put the full path to {parts[0]} in the run command")
    return [program] + [part.replace(SCENE_PLACEHOLDER, str(scene)) for part in parts[1:]]


def clean_line(line):
    return ANSI.sub("", line).rstrip()


def short_line(line):
    match = LOG_PREFIX.match(line)
    if match is None:
        return line.strip()
    message = line[match.end():].strip()
    return f"{match.group('level')} {message}" if match.group("level") in ("WARN", "ERROR") else message


def importer_warning(line):
    match = IMPORTER_WARNING.search(line)
    return match.group("message").strip() if match else None


def split_warning(text, names):
    name = next((name for name in sorted(names, key=len, reverse=True) if text.startswith(f"{name}: ")), None)
    return (name, text[len(name) + 2:]) if name is not None else (None, text)


class GameProcess:
    def __init__(self, command, folder, name, environment=None):
        self.name = name
        self.lines = deque(maxlen=OUTPUT_LINES)
        self.warnings = []
        self.code = None
        self.stopped = False
        self.building = Path(command[0]).stem.lower() == "cargo"
        self.changes = 0
        self._lock = threading.Lock()
        windows = os.name == "nt"
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if windows else 0
        self._process = subprocess.Popen([str(part) for part in command], cwd=str(folder), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env={**os.environ, **QUIET_ENVIRONMENT, **(environment or {})}, start_new_session=not windows, creationflags=flags)
        self._thread = threading.Thread(target=self._read, name="bevy_components_play", daemon=True)
        self._thread.start()

    @property
    def running(self):
        return self._thread.is_alive()

    @property
    def failed(self):
        return not self.running and not self.stopped and self.code not in (None, 0)

    def output(self):
        with self._lock:
            return list(self.lines)

    def tail(self, count):
        with self._lock:
            return list(self.lines)[-count:]

    def game_warnings(self):
        with self._lock:
            return list(self.warnings)

    def problem(self):
        lines = self.output()
        for index, line in enumerate(lines):
            if ERROR_LINE.match(line) or ((log := LOG_PREFIX.match(line)) is not None and log.group("level") == "ERROR"):
                return line
            if PANIC_LINE.search(line):
                return lines[index + 1].strip() if index + 1 < len(lines) and lines[index + 1].strip() else line
        return next((line for line in reversed(lines) if line.strip()), "no output")

    def stop(self):
        if not self.running:
            return
        self.stopped = True
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self._process.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            return
        self._signal(signal.SIGTERM)
        timer = threading.Timer(KILL_DELAY, self._signal, args=(signal.SIGKILL,))
        timer.daemon = True
        timer.start()

    def wait(self, timeout=None):
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _signal(self, number):
        if not self.running:
            return
        try:
            os.killpg(self._process.pid, number)
        except (ProcessLookupError, PermissionError):
            return

    def _read(self):
        with self._process.stdout as output:
            for line in output:
                text = clean_line(line)
                warning = importer_warning(text)
                with self._lock:
                    self.lines.append(text)
                    if warning is not None and warning not in self.warnings:
                        self.warnings.append(warning)
                    self.changes += 1
                if self.building and CARGO_LAUNCH.match(text):
                    self.building = False
        self.code = self._process.wait()
        self.changes += 1
