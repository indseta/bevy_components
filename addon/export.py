import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import bpy

from .compression import check_encoded, embed_textures, plan_textures, read_glb, write_glb
from .encoder import HINT, BackgroundEncode, EncoderError, check_encoder, encode
from .files import write_if_changed
from .gltf import LIMITS
from .prefab import collection_export, prefab_file, prefab_fingerprint, prefab_fresh, prefab_order, prefab_settings, remember_prefab, scene_export
from .preferences import encoder_path, texture_cache
from .probe import FILE_KINDS, embed_files
from .project import game_assets
from .property import EXPORT_OPTIONS
from .system import bevy_export, component_of, components_for, export_options, exported_objects, gltf_defaults, image_to_png, prop_export, redraw_status_bars, redraw_viewports
from .validation import check_game_paths, check_objects, check_scene, count, describe

EXPORT_LABEL = "Bevy glTF (.glb)"
PROGRESS_INTERVAL = 0.1
SKIPPED_SHOWN = 3
ENCODER_OPTIONS = ("etc1s_quality", "etc1s_effort", "uastc_quality", "uastc_zstd")
READ_ERROR = "Could not embed {name} in the scene: {reason}"

_exports = {}


class ExportError(Exception):
    pass


class ExportCancelled(ExportError):
    pass


def running_export():
    return next(iter(_exports), None)


def cancel_exports():
    for task in _exports:
        task.cancel()


def stop_exports():
    for task, (timer, job) in _exports.items():
        task.cancel()
        task.wait()
        bpy.context.window_manager.event_timer_remove(timer)
        job.release()
    _exports.clear()


def export_path(filepath):
    return Path(os.path.abspath(bpy.path.abspath(filepath))) if filepath else None


def glb_file(path):
    suffix = path.suffix.lower()
    return path if suffix == ".glb" else path.with_suffix(".glb") if suffix == ".gltf" else path.with_name(f"{path.name}.glb")


def remembered(scene):
    return scene.bevy_glb_export.filepath.strip() if scene is not None else ""


def again(scene):
    return SceneExport(scene, export_options(scene), scene.bevy_glb_export.filepath)


def remember(operator, scene):
    settings = scene.bevy_glb_export
    settings.filepath = blend_relative(export_path(operator.filepath))
    for name in EXPORT_OPTIONS:
        setattr(settings, name, getattr(operator, name))
    settings.gltf = json.dumps({name: getattr(operator, name) for name in gltf_defaults()}, sort_keys=True, separators=(",", ":"))


def recall(operator, scene, filepath=True):
    if filepath:
        operator.filepath = str(export_path(scene.bevy_glb_export.filepath))
    for name, value in vars(export_options(scene)).items():
        try:
            setattr(operator, name, value)
        except (AttributeError, TypeError, ValueError):
            pass


def blend_relative(path):
    if not bpy.data.filepath:
        return str(path)
    try:
        return bpy.path.relpath(str(path))
    except ValueError:
        return str(path)


def exports_world(options, collection=None):
    return collection is None and not prop_export(options)


def scene_issues(options, objects, destination, world=True):
    objects = list(objects)
    return check_objects(objects, destination=destination, animations=options.export_animations, modifiers=options.export_apply) + check_scene(objects, world=world) + check_game_paths(objects, destination, game_assets(bpy.context))


def start_export(job, context, background=False):
    job.check(context)
    job.export()
    if job.encoder is None:
        return job.write()
    jobs = job.texture_jobs()
    window_manager = context.window_manager
    if background and context.window is not None:
        job.task = BackgroundEncode(job.encoder, jobs, job.encoder_settings(), job.directory, cache=texture_cache(), check=check_encoded)
        _exports[job.task] = (window_manager.event_timer_add(PROGRESS_INTERVAL, window=context.window), job)
        redraw_status_bars()
        redraw_viewports()
        return None
    window_manager.progress_begin(0, max(len(jobs), 1))
    try:
        encoded = encode(job.encoder, jobs, job.encoder_settings(), job.directory, progress=window_manager.progress_update, cache=texture_cache(), check=check_encoded)
    except EncoderError as error:
        raise ExportError(f"Texture compression failed: {error}") from error
    finally:
        window_manager.progress_end()
    return job.write(encoded)


def finish_export(job, context):
    task = job.task
    if task in _exports:
        timer, _job = _exports.pop(task)
        context.window_manager.event_timer_remove(timer)
    redraw_status_bars()
    redraw_viewports()
    if task.cancelled:
        raise ExportCancelled("Cancelled the Bevy scene export")
    if task.error is not None:
        raise ExportError(f"Texture compression failed: {task.error}")
    return job.write(task.results)


def _read_file(path):
    return Path(bpy.path.abspath(path)).read_bytes()


def _has_probes(objects):
    return any(item.component_type in FILE_KINDS for obj in objects for item in components_for(obj))


def _embeds_sky(scene):
    world = scene.world if scene is not None else None
    return world is not None and hasattr(world, "bevy_sky") and world.bevy_sky.enabled and bool(world.bevy_sky.sky_file.strip())


def _embed(gltf, binary):
    try:
        return embed_files(gltf, binary, read=_read_file)
    except OSError as error:
        raise ExportError(READ_ERROR.format(name=Path(error.filename or "").name or "a probe file", reason=error.strerror)) from error


def _texture_bytes(jobs):
    return sum(len(data) for data in {job.image: job.data for job in jobs}.values())


def _write(path, data):
    try:
        write_if_changed(path, data)
    except OSError as error:
        raise ExportError(f"Could not write {path}: {error}") from error


def _names(objects):
    shown = ", ".join(obj.name for obj in objects[:SKIPPED_SHOWN])
    return f"{shown} and {len(objects) - SKIPPED_SHOWN} more" if len(objects) > SKIPPED_SHOWN else shown


def _skipped_message(skipped):
    shown = "; ".join(skipped[:SKIPPED_SHOWN])
    more = f" and {len(skipped) - SKIPPED_SHOWN} more" if len(skipped) > SKIPPED_SHOWN else ""
    return f"Left out {len(skipped)} Bevy component{'s' if len(skipped) != 1 else ''} that cannot export: {shown}{more}. See Validate All Objects"


class SceneExport:
    def __init__(self, scene, options, filepath, collection=None):
        self.scene = scene
        self.options = SimpleNamespace(**{name: getattr(options, name) for name in (*gltf_defaults(), *EXPORT_OPTIONS)})
        self.path = export_path(filepath)
        self.collection = collection
        self.objects = []
        self.issues = []
        self.skipped = []
        self.prefabs = []
        self.textures = []
        self.encoder = None
        self.task = None
        self._directory = None
        self._scene = None
        self._own = None

    @property
    def directory(self):
        return self._directory.name if self._directory is not None else None

    def encoder_settings(self):
        return {name: getattr(self.options, name) for name in ENCODER_OPTIONS}

    def texture_jobs(self):
        return [job for prefab in self.prefabs for job in prefab.jobs] + self.textures

    def check(self, context):
        if not hasattr(bpy.ops.export_scene, "gltf"):
            raise ExportError("Blender glTF exporter is unavailable")
        self.objects = list(self.collection.all_objects) if self.collection is not None else exported_objects(context, self.options)
        self.issues = scene_issues(self.options, self.objects, self.path, world=exports_world(self.options, self.collection))
        errors = [issue for issue in self.issues if issue.level == "ERROR"]
        if errors:
            raise ExportError(f"Cannot export: {describe(errors[0])}")
        if self.options.texture_compression != "DISABLED":
            try:
                self.encoder, _version = check_encoder(encoder_path(context))
            except EncoderError as error:
                raise ExportError(f"{error}. {HINT}") from error

    def export(self):
        collection = self.collection
        settings = prefab_settings(self.options)
        own = collection is not None and collection.bevy_prefab.enabled and prefab_file(collection) == self.path
        self._own = prefab_fingerprint(collection, settings, self.scene) if own else None
        self._directory = tempfile.TemporaryDirectory(prefix="bevy_components_")
        for nested in prefab_order(self.objects)[0]:
            target = prefab_file(nested)
            fingerprint = prefab_fingerprint(nested, settings, self.scene)
            if prefab_fresh(nested, target, fingerprint):
                continue
            path = Path(self.directory) / f"prefab_{len(self.prefabs)}.glb"
            self._export_gltf(path, nested, target.parent)
            gltf, binary = _embed(*read_glb(path.read_bytes()))
            self.prefabs.append(SimpleNamespace(collection=nested, target=target, fingerprint=fingerprint, gltf=gltf, binary=binary, jobs=[]))
        path = Path(self.directory) / "scene.glb"
        self._export_gltf(path, collection, self.path.parent, center=self.options.at_collection_center and self._own is None)
        if self.encoder is None and not _has_probes(self.objects) and not _embeds_sky(self.scene):
            self._scene = path.read_bytes()
            return
        gltf, binary = _embed(*read_glb(path.read_bytes()))
        self._scene = SimpleNamespace(gltf=gltf, binary=binary)
        if self.encoder is None:
            return
        try:
            for prefab in self.prefabs:
                prefab.jobs = plan_textures(prefab.gltf, prefab.binary, self.options.texture_compression, convert=image_to_png)
            self.textures = plan_textures(gltf, binary, self.options.texture_compression, convert=image_to_png)
        except ValueError as error:
            raise ExportError(f"Texture compression failed: {error}") from error

    def write(self, encoded=()):
        everything = self.texture_jobs()
        for job, data in zip(everything, encoded):
            problem = check_encoded(job, data)
            if problem:
                raise ExportError(f"Texture compression failed: {problem}")
        before = sum(_texture_bytes(prefab.jobs) for prefab in self.prefabs) + _texture_bytes(self.textures)
        start = 0
        for prefab in self.prefabs:
            prefab.gltf, prefab.binary = embed_textures(prefab.gltf, prefab.binary, prefab.jobs, encoded[start:start + len(prefab.jobs)])
            start += len(prefab.jobs)
        for prefab in self.prefabs:
            _write(prefab.target, write_glb(prefab.gltf, prefab.binary))
            remember_prefab(prefab.collection, prefab.target, prefab.fingerprint)
        if isinstance(self._scene, bytes):
            _write(self.path, self._scene)
        else:
            _write(self.path, write_glb(*embed_textures(self._scene.gltf, self._scene.binary, self.textures, encoded[start:])))
        if self._own is not None:
            remember_prefab(self.collection, self.path, self._own)
        return self._messages(everything, before, encoded)

    def release(self):
        if self._directory is not None:
            self._directory.cleanup()
        self._directory = None
        self._scene = None
        self.task = None
        self.prefabs = []
        self.textures = []

    def _export_gltf(self, path, collection, directory, center=False):
        settings = {name: getattr(self.options, name) for name in gltf_defaults()}
        if collection is not None:
            settings.update(dict.fromkeys(LIMITS, False), use_active_scene=True)
        properties = bpy.ops.export_scene.gltf.get_rna_type().properties
        settings = {name: value for name, value in settings.items() if name != "export_format" and name in properties and value != properties[name].default}
        settings["export_format"] = "GLB"
        try:
            with bevy_export() as export, collection_export(collection, self.scene, directory, center) if collection is not None else scene_export(directory):
                result = bpy.ops.export_scene.gltf(filepath=str(path), check_existing=False, **settings)
        except Exception as error:
            raise ExportError(f"GLB export failed: {error}") from error
        if "FINISHED" not in result:
            raise ExportError("GLB export failed")
        self.skipped.extend(export.skipped)

    def _messages(self, everything, before, encoded):
        note = f" and {count(len(self.prefabs), 'prefab')}" if self.prefabs else ""
        summary = f"{self.path}{note}"
        messages = []
        resized = sorted({job.name for job in everything if job.resized})
        if resized:
            messages.append(({"WARNING"}, f"Resized {', '.join(resized)} to a multiple of 4 pixels, as KTX2 textures need"))
        if everything:
            messages.append(({"INFO"}, f"Exported Bevy scene with {len(everything)} KTX2 textures ({before // 1024} KB to {sum(len(data) for data in encoded) // 1024} KB): {summary}"))
        else:
            messages.append(({"INFO"}, f"Exported Bevy scene: {summary}"))
        if self.skipped:
            messages.append(({"WARNING"}, _skipped_message(self.skipped)))
        lights = [obj for obj in self.objects if obj.type == "LIGHT" and component_of(obj, "LIGHT") is not None] if not self.options.export_lights else []
        if lights:
            messages.append(({"WARNING"}, f"Left out {_names(lights)}, which {'has a Light component' if len(lights) == 1 else 'have Light components'}, because Punctual Lights is off. Tick Include > Punctual Lights to export {'it' if len(lights) == 1 else 'them'}"))
        for issue in self.issues:
            print("Bevy Components:", describe(issue))
        if self.issues:
            messages.append(({"WARNING"}, f"Exported with {count(len(self.issues), 'warning')}, see Validate All Objects: {describe(self.issues[0])}"))
        return messages
