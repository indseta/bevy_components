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

from .metadata import WATTS_TO_LUMENS
from .probe import FILE_KINDS, ktx2_rgb9e5, ktx2_rgba16f
from .native import fog_source, is_native, native_components
from .system import collision_only_meshes, component_of, components_for, lightmap_uv_map

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
SKY_SAMPLES = 32
FILE_SUFFIXES = {"CUBEMAP": "reflection", "VOXELS": "irradiance", "LIGHTMAP": "lightmap"}
JOB_WORDS = {"SKY": "the sky", "LIGHTMAP": "lightmap", "CUBEMAP": "reflection probe", "VOXELS": "irradiance volume"}
LIGHTMAP_MARGIN = 2
LIGHTMAP_GAP = 4
LIGHTMAP_ANGLE = math.radians(66)
LIGHTMAP_UV_MAP = "lightmap"
SHARED_EXPONENT_MAX = 65408.0
DIRECTIONS = numpy.array(((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, -1, 0), (0, 1, 0)), dtype=numpy.float64)
TANGENTS = numpy.array(((0, 1, 0), (0, 1, 0), (1, 0, 0), (1, 0, 0), (1, 0, 0), (1, 0, 0)), dtype=numpy.float64)
CORNERS = numpy.array(((-1, -1), (1, -1), (1, 1), (-1, 1)), dtype=numpy.float64)
SKY_MATRIX = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
HIDDEN_RAYS = ("visible_diffuse", "visible_glossy", "visible_transmission", "visible_volume_scatter", "visible_shadow")
RUNNER = "import importlib, sys, types; package = types.ModuleType({package!r}); package.__path__ = [{path!r}]; sys.modules[{package!r}] = package; importlib.import_module({package!r} + '.bake').run({job!r})"


def box_matrix(obj, item):
    size_x, size_y, size_z = item.volume_size
    return obj.matrix_world @ Matrix(((size_x, 0, 0, 0), (0, 0, -size_z, 0), (0, size_y, 0, 0), (0, 0, 0, 1)))


def job_item(obj, job):
    if job["index"] >= 0:
        return obj.bevy_component_data.components[job["index"]]
    return next(item for item in native_components(obj) if FILE_KINDS.get(item.component_type) == job["kind"])


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


def _baked_lamps(objects):
    return sorted(obj.name for obj in objects if obj.type == "LIGHT" and obj.data.type != "AREA" and (item := component_of(obj, "LIGHT")) is not None and item.light_baked)


def sky_job(world, folder):
    name = f"{bpy.path.clean_name(world.name).lower()}_sky.ktx2"
    return {"world": world.name, "kind": "SKY", "path": str(Path(bpy.path.abspath(folder)) / name), "file": _probe_file(folder, name), "resolution": int(world.bevy_sky.bake_resolution)}


def baked_sky(world):
    return world is not None and world.library is None and hasattr(world, "bevy_sky") and world.bevy_sky.enabled


def lighting_jobs(objects, folder, only=None, world=None):
    objects = list(objects)
    jobs = [sky_job(world, folder)] if only is None and baked_sky(world) else []
    taken = set()
    for obj in sorted(objects, key=lambda obj: obj.name):
        if obj.library or not hasattr(obj, "bevy_component_data"):
            continue
        cards = list(enumerate(obj.bevy_component_data.components))
        natives = [(-1, item) for item in components_for(obj) if is_native(item) and item.component_type in FILE_KINDS]
        for index, item in cards + natives:
            if not item.enabled or item.component_type not in FILE_KINDS or (item.component_type == "LIGHTMAP" and obj.type != "MESH"):
                continue
            kind = FILE_KINDS[item.component_type]
            name = _file_name(obj, kind, taken)
            if only is not None and only != (obj.name, index):
                continue
            job = {"object": obj.name, "index": index, "kind": kind, "path": str(Path(bpy.path.abspath(folder)) / name), "file": _probe_file(folder, name)}
            if kind == "LIGHTMAP":
                uv_map = lightmap_uv_map(obj)
                job.update(resolution=int(item.lightmap_resolution), uv_map=uv_map.name if uv_map else None, baked_lamps=_baked_lamps(objects))
            elif kind == "CUBEMAP":
                job.update(matrix=[list(row) for row in box_matrix(obj, item)], resolution=int(item.bake_resolution))
            else:
                job.update(matrix=[list(row) for row in box_matrix(obj, item)], counts=list(item.bake_voxels))
            jobs.append(job)
    return jobs


def bake_summary(jobs):
    numbers = [(kind, sum(1 for job in jobs if job["kind"] == kind), word) for kind, word in JOB_WORDS.items()]
    parts = [word if kind == "SKY" else f"{number} {word}" if number == 1 else f"{number} {word}s" for kind, number, word in numbers if number]
    return " and ".join(parts) if len(parts) < 3 else f"{', '.join(parts[:-1])} and {parts[-1]}"


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


def shared_exponents(values):
    colors = numpy.clip(numpy.nan_to_num(numpy.asarray(values, dtype=numpy.float64)[..., :3]), 0.0, SHARED_EXPONENT_MAX)
    largest = colors.max(axis=-1)
    exponents = numpy.floor(numpy.log2(numpy.maximum(largest, 2.0 ** -16))) + 16
    exponents += numpy.floor(largest / 2.0 ** (exponents - 24) + 0.5) >= 512
    mantissas = numpy.floor(colors / 2.0 ** (exponents - 24)[..., None] + 0.5).astype(numpy.uint32)
    packed = mantissas[..., 0] | mantissas[..., 1] << 9 | mantissas[..., 2] << 18 | exponents.astype(numpy.uint32) << 27
    return numpy.ascontiguousarray(packed, dtype="<u4").tobytes()


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


def _flags(collection, name):
    values = numpy.empty(len(collection), dtype=bool)
    collection.foreach_get(name, values)
    return values


def unwrap_lightmap(view_layer, obj, size):
    mesh = obj.data
    layers = mesh.uv_layers
    if not len(layers):
        layers.new(name="UVMap")
    if len(layers) < 2:
        layers.new(name=LIGHTMAP_UV_MAP, do_init=False)
    states = [(collection, name, _flags(collection, name)) for collection in (mesh.vertices, mesh.edges, mesh.polygons) for name in ("select", "hide")]
    with _selection(view_layer, obj), _changed((layers, "active_index", 1)):
        for collection, name, _values in states:
            collection.foreach_set(name, numpy.full(len(collection), name == "select", dtype=bool))
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            bpy.ops.uv.smart_project(angle_limit=LIGHTMAP_ANGLE, margin_method="FRACTION", island_margin=LIGHTMAP_GAP / size, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")
    for collection, name, values in states:
        collection.foreach_set(name, values)
    mesh.update()
    return layers[1]


def _bake_pixels(view_layer, obj, image, pass_filter, margin=0, uv_layer=""):
    with _selection(view_layer, obj):
        bpy.ops.object.bake(type="DIFFUSE", pass_filter=pass_filter, margin=margin, margin_type="EXTEND", use_clear=True, target="IMAGE_TEXTURES", use_selected_to_active=False, uv_layer=uv_layer)
    return _image_pixels(image)


@contextmanager
def _bake_target(obj, image):
    material = bpy.data.materials.new("bevy_bake_lightmap")
    added = not obj.material_slots
    if added:
        obj.data.materials.append(material)
    empty = [slot for slot in obj.material_slots if slot.material is None]
    for slot in empty:
        slot.material = material
    materials = list({slot.material for slot in obj.material_slots})
    nodes = []
    try:
        with _changed(*((target, "use_nodes", True) for target in materials if not target.use_nodes)):
            for target in materials:
                tree = target.node_tree.nodes
                node = tree.new("ShaderNodeTexImage")
                node.image = image
                nodes.append((tree, node, tree.active))
                tree.active = node
            try:
                yield
            finally:
                for tree, node, previous in nodes:
                    tree.remove(node)
                    if previous is not None:
                        tree.active = previous
    finally:
        for slot in empty:
            slot.material = None
        if added:
            obj.data.materials.clear()
        bpy.data.materials.remove(material)


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


def bake_lightmap(scene, view_layer, job):
    obj = scene.objects[job["object"]]
    if not job["uv_map"] or job["uv_map"] not in obj.data.uv_layers:
        raise RuntimeError(f"{obj.name} has no second UV map for its lightmap")
    size = job["resolution"]
    image = bpy.data.images.new("bevy_bake_lightmap", size, size, alpha=True, float_buffer=True)
    try:
        with _bake_target(obj, image):
            pixels = _bake_pixels(view_layer, obj, image, {"INDIRECT"}, LIGHTMAP_MARGIN, job["uv_map"])
            lamps = [lamp for lamp in scene.objects if lamp.type == "LIGHT" and not lamp.hide_render and lamp.name not in job["baked_lamps"]]
            with _changed(*((lamp, "hide_render", True) for lamp in lamps)):
                pixels = pixels + _bake_pixels(view_layer, obj, image, {"DIRECT"}, LIGHTMAP_MARGIN, job["uv_map"])
    finally:
        bpy.data.images.remove(image)
    return ktx2_rgb9e5(size, size, shared_exponents(pixels[::-1] * WATTS_TO_LUMENS))


def _render_panorama(scene, view_layer, location, size):
    camera_data = bpy.data.cameras.new("bevy_bake_camera")
    camera_data.type = "PANO"
    camera_data.panorama_type = "EQUIRECTANGULAR"
    camera_data.clip_start = 0.001
    camera_data.clip_end = 100000.0
    camera = bpy.data.objects.new("bevy_bake_camera", camera_data)
    camera.matrix_world = Matrix.Translation(location)
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
    return panorama


def _cubemap(panorama, size, matrix):
    faces = sample_panorama(panorama, probe_directions(size, matrix))
    values = numpy.concatenate((faces, numpy.ones(faces.shape[:-1] + (1,))), axis=-1)
    return ktx2_rgba16f(size, size, half_floats(values), faces=6)


def bake_cubemap(scene, view_layer, job):
    size = job["resolution"]
    matrix = Matrix(job["matrix"])
    return _cubemap(_render_panorama(scene, view_layer, matrix.translation, size), size, matrix)


def bake_sky(scene, job):
    size = job["resolution"]
    sky = bpy.data.scenes.new("bevy_bake_sky")
    try:
        sky.world = bpy.data.worlds[job["world"]]
        sky.render.engine = "CYCLES"
        sky.cycles.samples = min(scene.cycles.samples, SKY_SAMPLES)
        sky.cycles.device = scene.cycles.device
        sky.cycles.use_denoising = False
        panorama = _render_panorama(sky, sky.view_layers[0], (0.0, 0.0, 0.0), size)
    finally:
        bpy.data.scenes.remove(sky)
    return _cubemap(panorama, size, SKY_MATRIX)


def _render_changes(scene, camera, size, path):
    render = scene.render
    image = render.image_settings
    changes = [(scene, "camera", camera), (render, "resolution_x", size * PANORAMA_SCALE), (render, "resolution_y", size * PANORAMA_SCALE // 2), (render, "resolution_percentage", 100), (render, "pixel_aspect_x", 1.0), (render, "pixel_aspect_y", 1.0), (render, "use_border", False), (render, "film_transparent", False), (render, "use_motion_blur", False), (render, "use_compositing", False), (render, "use_sequencer", False), (render, "filepath", str(path))]
    if hasattr(image, "media_type"):
        changes.append((image, "media_type", "IMAGE"))
    return changes + [(image, "file_format", "OPEN_EXR"), (image, "color_mode", "RGBA"), (image, "color_depth", "32")]


def bake_hidden(scene):
    hidden = collision_only_meshes(scene.objects)
    return sorted(obj.name for obj in scene.objects if not obj.hide_render and (fog_source(obj) is not None or obj in hidden))


def bake_jobs(scene, view_layer, jobs, samples, lamp_direct, hidden=None):
    unseen = [(scene.objects[name], "hide_render", True) for name in (bake_hidden(scene) if hidden is None else hidden) if name in scene.objects and not scene.objects[name].hide_render]
    with _changed((scene.render, "engine", "CYCLES"), (scene.cycles, "samples", samples), *unseen):
        for job in jobs:
            if job["kind"] == "SKY":
                data = bake_sky(scene, job)
            elif job["kind"] == "LIGHTMAP":
                data = bake_lightmap(scene, view_layer, job)
            elif job["kind"] == "CUBEMAP":
                data = bake_cubemap(scene, view_layer, job)
            else:
                data = bake_voxels(scene, view_layer, job, lamp_direct)
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
            for done, _job in enumerate(bake_jobs(scene, view_layer, settings["jobs"], settings["samples"], settings["lamp_direct"], settings.get("hidden")), start=1):
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
            self.error = f"Blender stopped after baking {self.done} of {self.total}: {self._output[-1] if self._output else 'no output'}"

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
