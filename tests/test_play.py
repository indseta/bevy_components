import importlib.util
import os
import pathlib
import stat
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

MODULE = pathlib.Path(__file__).resolve().parents[1] / "addon" / "play.py"
spec = importlib.util.spec_from_file_location("bevy_play", MODULE)
play = importlib.util.module_from_spec(spec)
spec.loader.exec_module(play)

POSIX = os.name == "posix"


def python(code):
    return [sys.executable, "-c", textwrap.dedent(code)]


def program(folder, name, code):
    path = pathlib.Path(folder) / name
    path.write_text(f"#!{sys.executable}\n{textwrap.dedent(code)}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def alive(pid):
    try:
        status = pathlib.Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return False
    return status.rsplit(")", 1)[1].split()[0] != "Z"


def finished(task):
    if not task.wait(20):
        task.stop()
        raise AssertionError("the game did not finish")
    return task


def until(check, timeout=20):
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.02)


class FolderTests(unittest.TestCase):
    def test_game_folders_need_a_cargo_project(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(play.PlayError, "does not exist"):
                play.check_game_folder(pathlib.Path(folder) / "missing")
            with self.assertRaisesRegex(play.PlayError, "has no Cargo.toml"):
                play.check_game_folder(folder)
            (pathlib.Path(folder) / "Cargo.toml").write_text("[package]\n")
            self.assertEqual(play.check_game_folder(folder), pathlib.Path(folder))
            with self.assertRaisesRegex(play.PlayError, "has no viewer example"):
                play.check_viewer_folder(folder)
            (pathlib.Path(folder) / "examples").mkdir()
            (pathlib.Path(folder) / "examples" / "viewer.rs").write_text("fn main() {}\n")
            self.assertEqual(play.check_viewer_folder(folder), pathlib.Path(folder))

    def test_the_importer_has_the_viewer_example(self):
        play.check_viewer_folder(MODULE.parents[1] / "importer")


class CommandTests(unittest.TestCase):
    def test_the_scene_placeholder_becomes_the_exported_file(self):
        with tempfile.TemporaryDirectory() as folder:
            command = play.game_command(f"\"{sys.executable}\" -m game --scene={{scene}} {{scene}}", folder, pathlib.Path(folder) / "assets" / "my level.glb")
        scene = str(pathlib.Path(folder) / "assets" / "my level.glb")
        self.assertEqual(command, [sys.executable, "-m", "game", f"--scene={scene}", scene])
        self.assertTrue(play.needs_scene(play.VIEWER_COMMAND))
        self.assertFalse(play.needs_scene(play.DEFAULT_COMMAND))

    def test_bad_commands_explain_what_to_do(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(play.PlayError, "empty"):
                play.game_command("  ", folder)
            with self.assertRaisesRegex(play.PlayError, "Could not read"):
                play.game_command("cargo run \"--features", folder)
            with self.assertRaisesRegex(play.PlayError, "export the scene once"):
                play.game_command(play.VIEWER_COMMAND, folder)
            with self.assertRaisesRegex(play.PlayError, "Could not find no_such_program_here"):
                play.game_command("no_such_program_here --release", folder)

    @unittest.skipUnless(POSIX, "uses an executable script")
    def test_programs_are_found_in_the_project_and_in_cargo_home(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as cargo_home:
            local = program(folder, "run_game", "print('hi')\n")
            self.assertEqual(play.game_command("./run_game --fast", folder), [str(pathlib.Path(folder) / "." / "run_game"), "--fast"])
            self.assertEqual(play.find_program(str(local), "/"), str(local))
            (pathlib.Path(cargo_home) / "bin").mkdir()
            cargo = program(pathlib.Path(cargo_home) / "bin", "cargo", "print('cargo')\n")
            with mock.patch.dict(os.environ, {"PATH": folder, "CARGO_HOME": cargo_home}):
                self.assertEqual(play.find_program("cargo", folder), str(cargo))
                self.assertIsNone(play.find_program("rustc", folder))


class OutputTests(unittest.TestCase):
    def test_lines_lose_their_colors(self):
        self.assertEqual(play.clean_line("\x1b[33m WARN\x1b[0m \x1b[2mbevy\x1b[0m: hi  \n"), " WARN bevy: hi")

    def test_log_lines_are_shortened_for_the_panel(self):
        self.assertEqual(play.short_line("2026-10-24T01:23:16.316246Z  INFO bevy_pbr::cluster: GPU clustering is supported"), "GPU clustering is supported")
        self.assertEqual(play.short_line("2026-10-24T01:23:16.879145Z  WARN bevy_components_importer::system: speaker: Audio Player has no sound file"), "WARN speaker: Audio Player has no sound file")
        self.assertEqual(play.short_line("   Compiling my_game v0.1.0"), "Compiling my_game v0.1.0")

    def test_importer_warnings_are_picked_out_of_the_log(self):
        line = "2026-10-23T10:00:00.123456Z  WARN bevy_components_importer::system: crate: Invalid visibility range"
        self.assertEqual(play.importer_warning(line), "crate: Invalid visibility range")
        self.assertEqual(play.importer_warning("WARN bevy_components_importer: Lamp: Ambient light belongs on the scene, not on an object"), "Lamp: Ambient light belongs on the scene, not on an object")
        self.assertIsNone(play.importer_warning("2026-10-23T10:00:00Z  WARN bevy_render: crate: Something else"))
        self.assertIsNone(play.importer_warning("2026-10-23T10:00:00Z  INFO bevy_components_importer: crate: Loaded"))

    def test_warnings_split_at_the_longest_object_name(self):
        names = ["Cube", "Cube: Base", "Lamp"]
        self.assertEqual(play.split_warning("Cube: Base: Invalid mass", names), ("Cube: Base", "Invalid mass"))
        self.assertEqual(play.split_warning("Cube: Invalid mass", names), ("Cube", "Invalid mass"))
        self.assertEqual(play.split_warning("Unnamed object: Invalid mass", names), (None, "Unnamed object: Invalid mass"))


class GameProcessTests(unittest.TestCase):
    def test_output_warnings_and_the_view_reach_the_panel(self):
        warning = "\x1b[33m WARN\x1b[0m bevy_components_importer::system: crate: Invalid mass"
        code = f"""
            import os, sys
            print(os.environ.get("{play.VIEW_VARIABLE}"))
            print(os.environ.get("NO_COLOR"), os.getcwd())
            for _ in range(2):
                print({warning!r})
            print("from stderr", file=sys.stderr)
        """
        with tempfile.TemporaryDirectory() as folder:
            task = finished(play.GameProcess(python(code), folder, "game", {play.VIEW_VARIABLE: "1,2,3,0,0,0,1"}))
        lines = task.output()
        self.assertEqual(lines[0], "1,2,3,0,0,0,1")
        self.assertEqual(lines[1], f"1 {os.path.realpath(folder)}")
        self.assertIn("from stderr", lines)
        self.assertEqual(task.game_warnings(), ["crate: Invalid mass"])
        self.assertEqual(task.code, 0)
        self.assertFalse(task.running or task.failed or task.stopped or task.building)
        self.assertEqual(task.tail(1), ["from stderr"])

    def test_only_the_latest_lines_are_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            task = finished(play.GameProcess(python(f"for index in range({play.OUTPUT_LINES + 50}): print(index)"), folder, "game"))
        self.assertEqual(len(task.output()), play.OUTPUT_LINES)
        self.assertEqual(task.output()[-1], str(play.OUTPUT_LINES + 49))

    def test_panics_and_errors_explain_why_the_game_stopped(self):
        panic = """
            import sys
            print("thread 'main' panicked at src/main.rs:3:5:")
            print("No scene file at levels/missing.glb")
            sys.exit(101)
        """
        with tempfile.TemporaryDirectory() as folder:
            task = finished(play.GameProcess(python(panic), folder, "game"))
            self.assertTrue(task.failed)
            self.assertEqual((task.code, task.problem()), (101, "No scene file at levels/missing.glb"))
            task = finished(play.GameProcess(python("import sys; print('Compiling game'); print('error[E0425]: cannot find value `x`'); sys.exit(1)"), folder, "game"))
            self.assertEqual(task.problem(), "error[E0425]: cannot find value `x`")
            task = finished(play.GameProcess(python("import sys; sys.exit(3)"), folder, "game"))
            self.assertEqual(task.problem(), "no output")

    @unittest.skipUnless(POSIX, "uses an executable script")
    def test_cargo_builds_until_it_runs_the_game(self):
        with tempfile.TemporaryDirectory() as folder:
            go = pathlib.Path(folder) / "go"
            cargo = program(folder, "cargo", f"""
                import os, time
                print("   Compiling game v0.1.0", flush=True)
                while not os.path.exists({str(go)!r}):
                    time.sleep(0.01)
                print("     Running `target/debug/game`", flush=True)
                print("game started", flush=True)
            """)
            task = play.GameProcess([cargo, "run"], folder, "game")
            until(lambda: task.output())
            self.assertTrue(task.building and task.running)
            go.touch()
            finished(task)
            self.assertFalse(task.building)
            self.assertEqual(task.output()[-1], "game started")
            self.assertFalse(play.GameProcess(python("print('     Running `x`')"), folder, "game").building)

    @unittest.skipUnless(sys.platform.startswith("linux"), "reads /proc")
    def test_stop_ends_the_game_and_what_it_started(self):
        code = """
            import subprocess, sys, time
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            print(child.pid, flush=True)
            time.sleep(60)
        """
        with tempfile.TemporaryDirectory() as folder:
            task = play.GameProcess(python(code), folder, "game")
            until(lambda: task.output())
            child = int(task.output()[0])
            self.assertTrue(alive(child))
            task.stop()
            finished(task)
        self.assertTrue(task.stopped)
        self.assertFalse(task.failed)
        until(lambda: not alive(child))

    @unittest.skipUnless(POSIX, "uses POSIX signals")
    def test_games_that_ignore_stop_are_killed(self):
        code = """
            import signal, time
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            print("ready", flush=True)
            time.sleep(60)
        """
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(play, "KILL_DELAY", 0.2):
            task = play.GameProcess(python(code), folder, "game")
            until(lambda: task.output())
            started = time.monotonic()
            task.stop()
            finished(task)
        self.assertLess(time.monotonic() - started, 10)
        self.assertTrue(task.stopped)


if __name__ == "__main__":
    unittest.main()
