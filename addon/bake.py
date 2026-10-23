import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
from collections import deque
from contextlib import contextmanager
from pathlib import Path

import bpy
import numpy
from mathutils import Matrix

from .probe import FILE_KINDS, ktx2_rgba16f

PACKAGE = "bevy_components_bake"
PROGRESS_PREFIX = "BEVY_BAKE_PROGRESS"
SAMPLES_PREFIX = "BEVY_BAKE_SAMPLES"
ERROR_PREFIX = "BEVY_BAKE_ERROR"
SAMPLES = re.compile(r"Sample (\d+)/(\d+)")
TEMPORARY_VARIABLES = ("TMPDIR", "TEMP", "TMP")
SUPERSAMPLING = 2
FACE_SCALE = 0.02
PANORAMA_SCALE = 4
NICENESS = 10
FILE_SUFFIXES = {"CUBEMAP": "reflection", "VOXELS": "irradiance"}
DIRECTIONS = numpy.array(((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, -1, 0), (0, 1, 0)), dtype=numpy.float64)
TANGENTS = numpy.array(((0, 1, 0), (0, 1, 0), (1, 0, 0), (1, 0, 0), (1, 0, 0), (1, 0, 0)), dtype=numpy.float64)
CORNERS = numpy.array(((-1, -1), (1, -1), (1, 1), (-1, 1)), dtype=numpy.float64)
HIDDEN_RAYS = ("visible_diffuse", "visible_glossy", "visible_transmission", "visible_volume_scatter", "visible_shadow")
RUNNER = "import importlib, sys, types; package = types.ModuleType({package!r}); package.__path__ = [{path!r}]; sys.modules[{package!r}] = package; importlib.import_module({package!r} + '.bake').run({job!r})"


def box_matrix(obj, item):
    size_x, size_y, size_z = item.volume_size
    return obj.matrix_world @ Matrix(((size_x, 0, 0, 0), (0, 0, -size_z, 0), (0, size_y, 0, 0), (0, 0, 0, 1)))


def _file_name(obj, kind, taken):
    base = f"{bpy.path.clean_name(obj.name).lower()}_{FILE_SUFFIXES[kind]}"
    name = base
    number = 2
    while name in taken:
        name = f"{base}_{number}"
        number += 1
    taken.add(name)
    return f"{name}.ktx2"


def _probe_file(folder, name):
    if not folder.startswith("//"):
        return str(Path(folder) / name)
    return folder + name if folder.endswith(("/", "\\")) else f"{folder}/{name}"


def probe_jobs(objects, folder, only=None):
    jobs = []
    taken = set()
    for obj in sorted(objects, key=lambda obj: obj.name):
        if obj.library or not hasattr(obj, "bevy_component_data"):
            continue
        for index, item in enumerate(obj.bevy_component_data.components):
            if not item.enabled or item.component_type not in FILE_KINDS:
                continue
            kind = FILE_KINDS[item.component_type]
            name = _file_name(obj, kind, taken)
            if only is not None and only != (obj.name, index):
                continue
            job = {"object": obj.name, "index": index, "kind": kind, "matrix": [list(row) for row in box_matrix(obj, item)], "path": str(Path(bpy.path.abspath(folder)) / name), "file": _probe_file(folder, name)}
            if kind == "CUBEMAP":
                job["resolution"] = int(item.bake_resolution)
            else:
                job["counts"] = list(item.bake_voxels)
            jobs.append(job)
    return jobs


def cube_directions(size):
    coordinates = (numpy.arange(size) + 0.5) / size * 2 - 1
    x, y = numpy.meshgrid(coordinates, coordinates)
    one = numpy.ones_like(x)
    faces = ((one, -y, -x), (-one, -y, x), (x, one, y), (x, -one, -y), (x, -y, one), (-x, -y, -one))
    return numpy.stack([numpy.stack(face, axis=-1) for face in faces])


def probe_directions(size, matrix):
    probe = cube_directions(size) * numpy.array((1.0, 1.0, -1.0))
    world = probe @ numpy.array(matrix.to_3x3()).T
    return world / numpy.linalg.norm(world, axis=-1, keepdims=True)


def sample_panorama(panorama, directions):
    height, width = panorama.shape[:2]
    u = 0.5 + numpy.arctan2(directions[..., 0], -directions[..., 2]) / (2 * math.pi)
    v = 0.5 + numpy.arcsin(numpy.clip(directions[..., 1], -1.0, 1.0)) / math.pi
    x = u * width - 0.5
    y = numpy.clip(v * height - 0.5, 0, height - 1)
    x0 = numpy.floor(x).astype(numpy.int64)
    y0 = numpy.floor(y).astype(numpy.int64)
    fx = (x - x0)[..., None]
    fy = (y - y0)[..., None]
    x1 = (x0 + 1) % width
    x0 %= width
    y1 = numpy.minimum(y0 + 1, height - 1)
    top = panorama[y0, x0] * (1 - fx) + panorama[y0, x1] * fx
    bottom = panorama[y1, x0] * (1 - fx) + panorama[y1, x1] * fx
    return top * (1 - fy) + bottom * fy


def voxel_centers(counts, matrix):
    grid = numpy.stack(numpy.meshgrid(*[(numpy.arange(count) + 0.5) / count - 0.5 for count in counts], indexing="ij"), axis=-1)
    points = grid.transpose(2, 1, 0, 3).reshape(-1, 3)
    return points @ numpy.array(matrix.to_3x3()).T + numpy.array(matrix.translation)


def voxel_quads(counts, matrix):
    centers = voxel_centers(counts, matrix)
    spacing = min(numpy.linalg.norm(numpy.array(matrix.to_3x3().col[axis])) / count for axis, count in enumerate(counts))
    half = max(spacing * FACE_SCALE, 1e-4)
    bitangents = numpy.cross(DIRECTIONS, TANGENTS)
    offsets = DIRECTIONS[:, None, :] + CORNERS[None, :, 0, None] * TANGENTS[:, None, :] + CORNERS[None, :, 1, None] * bitangents[:, None, :]
    return (centers[:, None, None, :] + offsets[None] * half).reshape(-1, 4, 3)


def atlas(values, counts):
    count_x, count_y, count_z = counts
    cube = values.reshape(count_z, count_y, count_x, 3, 2, 3).transpose(3, 0, 4, 1, 2, 5).reshape(3 * count_z, 2 * count_y, count_x, 3)
    return numpy.concatenate((cube, numpy.ones(cube.shape[:-1] + (1,))), axis=-1)


def half_floats(values):
    return numpy.ascontiguousarray(values, dtype="<f2").tobytes()


def _image_pixels(image):
    pixels = numpy.empty(image.size[0] * image.size[1] * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape(image.size[1], image.size[0], 4)


@contextmanager
def _changed(*changes):
    saved = [(owner, name, getattr(owner, name)) for owner, name, _value in changes]
    try:
        for owner, name, value in changes:
            setattr(owner, name, value)
        yield
    finally:
        for owner, name, value in saved:
            setattr(owner, name, value)


@contextmanager
def _selection(view_layer, active):
    selected = [obj for obj in view_layer.objects if obj.select_get()]
    previous = view_layer.objects.active
    for obj in selected:
        obj.select_set(False)
    active.select_set(True)
    view_layer.objects.active = active
    try:
        yield
    finally:
        active.select_set(False)
        for obj in selected:
            if obj.name in view_layer.objects:
                obj.select_set(True)
        view_layer.objects.active = previous


def _bake_pixels(view_layer, obj, image, pass_filter):
    with _selection(view_layer, obj):
        bpy.ops.object.bake(type="DIFFUSE", pass_filter=pass_filter, margin=0, use_clear=True, target="IMAGE_TEXTURES", use_selected_to_active=False)
    return _image_pixels(image)


def bake_voxels(scene, view_layer, job, lamp_direct):
    counts = job["counts"]
    quads = voxel_quads(counts, Matrix(job["matrix"]))
    total = len(quads)
    columns = math.ceil(math.sqrt(total))
    rows = math.ceil(total / columns)
    width, height = columns * SUPERSAMPLING, rows * SUPERSAMPLING
    mesh = bpy.data.meshes.new("bevy_bake_voxels")
    mesh.from_pydata(quads.reshape(-1, 3).tolist(), [], numpy.arange(total * 4).reshape(total, 4).tolist())
    blocks = numpy.arange(total)
    corners = numpy.stack([blocks % columns, blocks // columns], axis=-1)[:, None, :] + (CORNERS[None] + 1) / 2
    uv = mesh.uv_layers.new(name="bake")
    uv.data.foreach_set("uv", (corners / numpy.array((columns, rows))).reshape(-1).astype(numpy.float32))
    image = bpy.data.images.new("bevy_bake_voxels", width, height, alpha=True, float_buffer=True)
    material = bpy.data.materials.new("bevy_bake_voxels")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    shader = nodes.new("ShaderNodeBsdfDiffuse")
    shader.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    output = nodes.new("ShaderNodeOutputMaterial")
    material.node_tree.links.new(shader.outputs[0], output.inputs["Surface"])
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    nodes.active = texture
    mesh.materials.append(material)
    obj = bpy.data.objects.new("bevy_bake_voxels", mesh)
    for name in HIDDEN_RAYS:
        setattr(obj, name, False)
    scene.collection.objects.link(obj)
    try:
        if lamp_direct:
            pixels = _bake_pixels(view_layer, obj, image, {"DIRECT", "INDIRECT"})
        else:
            pixels = _bake_pixels(view_layer, obj, image, {"INDIRECT"})
            lamps = [lamp for lamp in scene.objects if lamp.type == "LIGHT" and not lamp.hide_render]
            with _changed(*((lamp, "hide_render", True) for lamp in lamps)):
                pixels = pixels + _bake_pixels(view_layer, obj, image, {"DIRECT"})
    finally:
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)
        bpy.data.materials.remove(material)
        bpy.data.images.remove(image)
    faces = pixels.reshape(rows, SUPERSAMPLING, columns, SUPERSAMPLING, 4).mean(axis=(1, 3)).reshape(-1, 4)[:total, :3]
    values = atlas(faces.reshape(-1, 6, 3), counts)
    return ktx2_rgba16f(counts[0], 2 * counts[1], half_floats(values), depth=3 * counts[2])


def bake_cubemap(scene, view_layer, job):
    size = job["resolution"]
    matrix = Matrix(job["matrix"])
    camera_data = bpy.data.cameras.new("bevy_bake_camera")
    camera_data.type = "PANO"
    camera_data.panorama_type = "EQUIRECTANGULAR"
    camera_data.clip_start = 0.001
    camera_data.clip_end = 100000.0
    camera = bpy.data.objects.new("bevy_bake_camera", camera_data)
    camera.matrix_world = Matrix.Translation(matrix.translation)
    scene.collection.objects.link(camera)
    try:
        with tempfile.TemporaryDirectory(prefix="bevy_components_bake_") as directory:
            path = Path(directory) / "probe.exr"
            with _changed(*_render_changes(scene, camera, size, path)):
                bpy.ops.render.render(write_still=True, layer=view_layer.name, scene=scene.name)
            image = bpy.data.images.load(str(path))
            try:
                panorama = _image_pixels(image)[..., :3].astype(numpy.float64)
            finally:
                bpy.data.images.remove(image)
    finally:
        bpy.data.objects.remove(camera)
        bpy.data.cameras.remove(camera_data)
    faces = sample_panorama(panorama, probe_directions(size, matrix))
    values = numpy.concatenate((faces, numpy.ones(faces.shape[:-1] + (1,))), axis=-1)
    return ktx2_rgba16f(size, size, half_floats(values), faces=6)


def _render_changes(scene, camera, size, path):
    render = scene.render
    image = render.image_settings
    changes = [(scene, "camera", camera), (render, "resolution_x", size * PANORAMA_SCALE), (render, "resolution_y", size * PANORAMA_SCALE // 2), (render, "resolution_percentage", 100), (render, "pixel_aspect_x", 1.0), (render, "pixel_aspect_y", 1.0), (render, "use_border", False), (render, "film_transparent", False), (render, "use_motion_blur", False), (render, "use_compositing", False), (render, "use_sequencer", False), (render, "filepath", str(path))]
    if hasattr(image, "media_type"):
        changes.append((image, "media_type", "IMAGE"))
    return changes + [(image, "file_format", "OPEN_EXR"), (image, "color_mode", "RGBA"), (image, "color_depth", "32")]


def bake_jobs(scene, view_layer, jobs, samples, lamp_direct):
    with _changed((scene.render, "engine", "CYCLES"), (scene.cycles, "samples", samples)):
        for job in jobs:
            data = bake_cubemap(scene, view_layer, job) if job["kind"] == "CUBEMAP" else bake_voxels(scene, view_layer, job, lamp_direct)
            path = Path(job["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            staging = path.with_name(f".{path.name}.tmp")
            staging.write_bytes(data)
            os.replace(staging, path)
            yield job


def _print_samples(text):
    match = SAMPLES.search(text)
    if match:
        print(f"{SAMPLES_PREFIX} {match[1]} {match[2]}", flush=True)


def run(job_path):
    settings = json.loads(Path(job_path).read_text(encoding="utf-8"))
    scene = bpy.data.scenes.get(settings["scene"]) or bpy.context.scene
    view_layer = scene.view_layers.get(settings["view_layer"]) or scene.view_layers[0]
    bpy.app.handlers.render_stats.append(_print_samples)
    try:
        with bpy.context.temp_override(scene=scene, view_layer=view_layer):
            for done, _job in enumerate(bake_jobs(scene, view_layer, settings["jobs"], settings["samples"], settings["lamp_direct"]), start=1):
                print(f"{PROGRESS_PREFIX} {done}", flush=True)
    except Exception as error:
        print(f"{ERROR_PREFIX} {error}", flush=True)
        raise


def bake_command(binary, blend, job_path):
    return [binary, "--background", str(blend), "--python-exit-code", "1", "--python-expr", RUNNER.format(package=PACKAGE, path=str(Path(__file__).parent), job=str(job_path))]


class BackgroundBake:
    def __init__(self, command, total, scratch=None):
        self.total = total
        self.done = 0
        self.fraction = 0.0
        self.error = None
        self.cancelled = False
        self._output = deque(maxlen=20)
        flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == "win32" else 0
        environment = {**os.environ, **{name: str(scratch) for name in TEMPORARY_VARIABLES}} if scratch is not None else None
        self._process = subprocess.Popen([str(part) for part in command], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=environment, creationflags=flags)
        _lower_priority(self._process)
        self._thread = threading.Thread(target=self._read, name="bevy_components_bake", daemon=True)
        self._thread.start()

    @property
    def running(self):
        return self._thread.is_alive()

    def cancel(self):
        self.cancelled = True
        if self._process.poll() is None:
            self._process.kill()

    def wait(self, timeout=None):
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _read(self):
        with self._process.stdout as output:
            self._parse(output)
        code = self._process.wait()
        if self.cancelled or self.error is not None:
            return
        if code != 0:
            self.error = f"Blender stopped with exit code {code}: {self._output[-1] if self._output else 'no output'}"
        elif self.done < self.total:
            self.error = f"Blender stopped after {self.done} of {self.total} probes: {self._output[-1] if self._output else 'no output'}"

    def _parse(self, output):
        for line in output:
            if line.startswith(PROGRESS_PREFIX):
                self.done = int(line.split()[1])
                self.fraction = 0.0
            elif line.startswith(SAMPLES_PREFIX):
                sample, samples = (int(value) for value in line.split()[1:3])
                self.fraction = min(sample / max(samples, 1), 1.0)
            elif line.startswith(ERROR_PREFIX):
                self.error = line[len(ERROR_PREFIX):].strip()
            elif line.strip():
                self._output.append(line.strip())


def _lower_priority(process):
    if not hasattr(os, "setpriority"):
        return
    try:
        os.setpriority(os.PRIO_PROCESS, process.pid, min(os.getpriority(os.PRIO_PROCESS, 0) + NICENESS, 19))
    except OSError:
        return
