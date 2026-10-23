import os
import re
import textwrap
from collections import namedtuple
from pathlib import Path, PurePosixPath

import bpy
from mathutils import Matrix, Quaternion, Vector

from .metadata import EXTRAS_KEY, component_errors, light_of, light_size, visibility_range_problems
from .property import AUDIO_FORMATS
from .probe import FILE_KINDS, FILE_LABELS, HEADER_LENGTH, check_texture, voxel_counts
from .reference import SCENE_EXTENSIONS, read_scenes
from .system import MESH_TYPES, children_map, component_of, components_for, file_path, has_faces, inherited, level_path, lightmap_uv_map, mesh_sources, object_actions, subtree

Issue = namedtuple("Issue", ("level", "obj", "item", "message"))
TextureCheck = namedtuple("TextureCheck", ("level", "message", "voxels"))

TYPE_PATH = re.compile(r"[A-Za-z_]\w*(::[A-Za-z_]\w*)*(<.+>)?")
WINDOWS_DRIVE = re.compile(r"[A-Za-z]:")
SHAPE_LABELS = {
    "TRIMESH": "Triangle Mesh",
    "CONVEX": "Convex Hull",
}
MISSING_FILES = {
    "REFLECTION_PROBE": "No cubemap, so the probe adds no reflections",
    "IRRADIANCE_VOLUME": "No voxel texture, so the volume adds no light",
    "LIGHTMAP": "No lightmap baked yet, so the mesh gets no baked light",
}
TEXTURE_CACHE_LIMIT = 256

_texture_checks = {}


def describe(issue):
    return f"{issue.obj.name}: {issue.message}"


def count(number, word):
    return f"{number} {word}" if number == 1 else f"{number} {word}s"


def issue_summary(issues):
    errors = sum(1 for issue in issues if issue.level == "ERROR")
    return ", ".join(count(number, word) for number, word in ((errors, "error"), (len(issues) - errors, "warning")) if number)


def draw_message(layout, text, icon="ERROR", width=300):
    scale = (bpy.context.preferences.system.ui_scale if bpy.context.preferences else 0.0) or 1.0
    column = layout.column(align=True)
    for index, line in enumerate(textwrap.wrap(text, max(20, int((width - 40) / (6 * scale))))):
        column.label(text=line, icon=icon if index == 0 else "BLANK1")


def draw_issues(layout, rows, limit, more, select=False, width=300):
    for level, name, message in rows[:limit]:
        icon = "CANCEL" if level == "ERROR" else "ERROR"
        if select:
            layout.operator("bevy_components.select_object", text=f"{name}: {message}", icon=icon).name = name
        else:
            draw_message(layout, f"{name}: {message}", icon, width)
    if len(rows) > limit:
        layout.label(text=f"{len(rows) - limit} more {more}", icon="BLANK1")


def check_objects(objects, level=None, animations=True):
    objects = list(objects)
    children = children_map(objects)
    exported = set(objects)
    issues = []
    for obj in objects:
        issues.extend(_object_issues(obj, children, exported, level, animations))
    issues.extend(_visibility_range_issues(objects))
    return issues


def check_object(obj, objects):
    objects = list(objects)
    return _object_issues(obj, children_map(objects), set(objects)) + _visibility_range_issues(objects, obj)


def _object_issues(obj, children, exported, level=None, animations=True):
    issues = []
    custom_types = set()
    for item in components_for(obj):
        issues.extend(Issue("ERROR", obj, item, error) for error in component_errors(item))
        if item.component_type == "COLLIDER":
            issues.extend(Issue("WARNING", obj, item, message) for message in _collider_warnings(obj, item, children))
        elif item.component_type == "RIGID_BODY":
            issues.extend(Issue("WARNING", obj, item, message) for message in _rigid_body_warnings(obj, item, children))
        elif item.component_type == "VISIBILITY_RANGE":
            issues.extend(Issue("WARNING", obj, item, message) for message in _visibility_range_warnings(obj, item, children))
        elif item.component_type == "SHADOWS":
            issues.extend(Issue("WARNING", obj, item, message) for message in _shadows_warnings(obj, item, children))
        elif item.component_type == "AUDIO_PLAYER":
            issues.extend(Issue("WARNING", obj, item, message) for message in _audio_warnings(item))
        elif item.component_type == "JOINT":
            issues.extend(Issue("WARNING", obj, item, message) for message in _joint_warnings(obj, item, exported))
        elif item.component_type == "SCENE_REFERENCE" and item.scene_file.strip():
            issues.extend(_scene_reference_issues(obj, item, level))
        elif item.component_type == "ANIMATION":
            issues.extend(Issue("WARNING", obj, item, message) for message in _animation_warnings(obj, item, children, animations))
        elif item.component_type == "LIGHTMAP":
            issues.extend(_lightmap_issues(obj, item))
        elif item.component_type in FILE_KINDS:
            check = texture_check(obj, item)
            if check.level is not None:
                issues.append(Issue(check.level, obj, item, check.message))
        elif item.component_type == "FOG_VOLUME" and item.fog_density <= 0:
            issues.append(Issue("WARNING", obj, item, "Density is 0, so the fog is invisible"))
        elif item.component_type == "LIGHT":
            issues.extend(Issue("WARNING", obj, item, message) for message in _light_warnings(obj, item))
        elif item.component_type == "CUSTOM" and item.custom_type.strip():
            if not TYPE_PATH.fullmatch(item.custom_type):
                issues.append(Issue("WARNING", obj, item, f"\"{item.custom_type}\" is not a Rust type path such as my_game::Health"))
            if item.custom_type in custom_types:
                issues.append(Issue("WARNING", obj, item, f"Added more than once, but an entity holds only one {item.custom_type}"))
            custom_types.add(item.custom_type)
    light = light_of(obj)
    if light is not None and light.type == "AREA" and not any(item.component_type == "LIGHT" for item in obj.bevy_component_data.components):
        issues.append(Issue("WARNING", obj, None, "glTF leaves out area lights. Add a Light component to export this one as a Bevy rectangle light"))
    return issues


def texture_check(obj, item):
    if not item.probe_file.strip():
        return TextureCheck("WARNING", MISSING_FILES[item.component_type], None)
    kind = FILE_KINDS[item.component_type]
    path = Path(bpy.path.abspath(item.probe_file, library=obj.library))
    try:
        stat = path.stat()
    except OSError:
        stat = None
    if stat is None or not path.is_file():
        return TextureCheck("ERROR", f"{FILE_LABELS[kind]} file {path.name} was not found", None)
    key = (str(path), kind, stat.st_mtime_ns, stat.st_size)
    if key not in _texture_checks:
        try:
            with path.open("rb") as file:
                header = file.read(HEADER_LENGTH)
        except OSError as error:
            return TextureCheck("ERROR", f"Could not read {path.name}: {error.strerror}", None)
        level, message = check_texture(header, kind)
        if len(_texture_checks) >= TEXTURE_CACHE_LIMIT:
            _texture_checks.clear()
        _texture_checks[key] = TextureCheck(level, message if level is None else f"{path.name} {message}", voxel_counts(header) if kind == "VOXELS" else None)
    return _texture_checks[key]


def _collider_warnings(obj, item, children):
    warnings = []
    targets = [obj]
    if item.collider_shape in SHAPE_LABELS:
        sources = [source for source, _matrix in mesh_sources(obj, children, "COLLIDER")]
        if not sources:
            warnings.append(f"No mesh on this object or under it, so no {SHAPE_LABELS[item.collider_shape]} collider is built")
        if item.collider_shape == "TRIMESH":
            bodies = [owner for owner, body in (inherited(source, "RIGID_BODY") for source in sources) if body is not None and body.rigid_body_kind == "DYNAMIC"]
            if bodies:
                warnings.append("Triangle meshes collide poorly on Dynamic bodies, use Convex Hull" if bodies[0] == obj else f"Triangle meshes collide poorly on Dynamic bodies such as {bodies[0].name}, use Convex Hull")
        targets = [source for source, _matrix in mesh_sources(obj, children, "COLLIDER", instances=False)]
    for target in targets:
        ancestor = _uneven_scale_ancestor(target)
        if ancestor is not None:
            warnings.append(f"{'This' if target == obj else target.name} is rotated inside {ancestor.name}, which is scaled unevenly, so the game sizes its collider wrong. Apply scale to {ancestor.name}")
            break
    return warnings


def _rigid_body_warnings(obj, item, children):
    warnings = []
    if item.rigid_body_kind == "DYNAMIC" and not any(_has_collider(member) for member, _matrix in subtree(obj, children, lambda child: component_of(child, "RIGID_BODY") is not None)):
        warnings.append("Dynamic body has no collider on it or under it, so it has no mass and collides with nothing")
    parent, body = inherited(obj.parent, "RIGID_BODY")
    if body is not None and body.rigid_body_kind != "STATIC":
        warnings.append(f"Moves on its own instead of with {parent.name}. Remove this Rigid Body to make {parent.name} one compound body")
    if item.rigid_body_kind == "DYNAMIC" and all(item.rigid_body_lock_translation) and all(item.rigid_body_lock_rotation):
        warnings.append("Every axis is locked, so the body never moves. Use a Static or Kinematic body instead")
    return warnings


def body_kind(obj):
    body = component_of(obj, "RIGID_BODY")
    if body is not None:
        return body.rigid_body_kind
    _parent, inherited_body = inherited(obj.parent, "RIGID_BODY")
    if component_of(obj, "COLLIDER") is not None and inherited_body is None:
        return "STATIC"
    return None


def _joint_warnings(obj, item, exported):
    bodies = [body for body in (item.joint_body1, item.joint_body2) if body is not None]
    if not bodies:
        return ["Connects nothing. Pick Body 1, Body 2 or both"]
    if len(bodies) == 2 and bodies[0] == bodies[1]:
        return [f"Connects {bodies[0].name} to itself"]
    warnings = []
    kinds = []
    for body in bodies:
        kind = body_kind(body)
        kinds.append(kind)
        if body not in exported:
            warnings.append(f"{body.name} is not exported with this level, so the joint holds nothing")
        elif kind is None:
            parent, _owner = inherited(body.parent, "RIGID_BODY")
            warnings.append(f"{body.name} is part of {parent.name}'s body, so pick {parent.name}" if parent is not None else f"{body.name} has no Rigid Body or Collider, so the joint holds nothing")
    if not warnings and all(kind == "STATIC" for kind in kinds):
        warnings.append("Both ends are static, so the joint does nothing" if len(bodies) == 2 else f"{bodies[0].name} is static, so pinning it does nothing")
    return warnings


def _visibility_range_warnings(obj, item, children):
    warnings = []
    if not mesh_sources(obj, children, "VISIBILITY_RANGE"):
        warnings.append("No mesh on this object or under it to show or hide")
    if not component_errors(item) and item.fade_out_end <= item.fade_in_start:
        warnings.append(f"Never visible, because Fade Out End is {item.fade_out_end:g} m")
    return warnings


def _shadows_warnings(obj, item, children):
    if not mesh_sources(obj, children, "SHADOWS"):
        return ["No mesh on this object or under it to cast or receive shadows"]
    return []


def _audio_warnings(item):
    path = item.audio_path.strip()
    if not path:
        return ["No sound file, so nothing plays"]
    warnings = []
    if "\\" in path or path.startswith(("/", "../")) or WINDOWS_DRIVE.match(path):
        warnings.append(f"\"{path}\" is not a path inside your game's assets folder, such as sounds/fire.ogg")
    extension = PurePosixPath(path.replace("\\", "/")).suffix.lower()
    if not extension:
        warnings.append("The sound file has no extension, so Bevy cannot tell how to load it")
    elif extension not in AUDIO_FORMATS:
        warnings.append(f"Bevy cannot play {extension} files, use .ogg, .wav, .mp3 or .flac")
    return warnings


def _scene_reference_issues(obj, item, level):
    path = file_path(item.scene_file)
    try:
        level_path(item.scene_file, None if level is None else level.parent)
    except ValueError:
        return [Issue("ERROR", obj, item, f"{path.name} is on another drive than the level, so the game cannot load it")]
    if path.suffix.lower() not in SCENE_EXTENSIONS:
        return [Issue("WARNING", obj, item, f"{path.name} is not a .glb or .gltf file")]
    if level is not None and path == Path(os.path.abspath(level)):
        return [Issue("WARNING", obj, item, "Spawns the exported level inside itself, so the game skips it")]
    try:
        scenes = read_scenes(path)
    except OSError:
        return [Issue("WARNING", obj, item, f"No file at {item.scene_file}")]
    except ValueError:
        return [Issue("WARNING", obj, item, f"{path.name} is not a valid glTF file")]
    if item.scene_index >= len(scenes):
        return [Issue("WARNING", obj, item, f"{path.name} has {count(len(scenes), 'scene')}, numbered from 0")]
    return []


def _animation_warnings(obj, item, children, animations):
    clip = item.animation_clip
    if not clip.strip():
        return ["No clip picked, so nothing plays"]
    if clip not in bpy.data.actions:
        return [f"No action named {clip}"]
    warnings = []
    root = obj
    while root.parent is not None:
        root = root.parent
    if not any(clip in object_actions(member) for member, _matrix in subtree(root, children, lambda child: False, instances=False)):
        warnings.append(f"{clip} animates nothing on or under {'this object' if root == obj else root.name}, so nothing plays")
    if not animations:
        warnings.append("Include Animations is off in the export, so nothing plays")
    return warnings


def _lightmap_issues(obj, item):
    if obj.type != "MESH":
        return [Issue("WARNING", obj, item, "Only meshes use lightmaps, so it is not exported")]
    issues = []
    if lightmap_uv_map(obj) is None:
        issues.append(Issue("WARNING", obj, item, "No second UV map, which Bevy reads lightmaps with. Click Unwrap Lightmap UVs"))
    modifier = next((modifier for modifier in obj.modifiers if modifier.show_render), None)
    if modifier is not None:
        issues.append(Issue("WARNING", obj, item, f"Bake includes the {modifier.name} modifier but the export leaves it out, so the lightmap may not fit. Apply the modifier"))
    check = texture_check(obj, item)
    if check.level is not None:
        issues.append(Issue(check.level, obj, item, check.message))
    return issues


def _light_warnings(obj, item):
    light = light_of(obj)
    if light is None:
        return ["Only lights use this component, so it is not exported"]
    warnings = []
    if item.light_volumetric and light.type != "AREA" and not light.use_shadow:
        warnings.append("Volumetric needs Shadows, or the light makes no light shafts")
    if light.type == "AREA" and light.shape in {"DISK", "ELLIPSE"}:
        width, height = light_size(light)
        warnings.append(f"Bevy area lights are rectangles, so this {light.shape.lower()} becomes a {width:g} × {height:g} m rectangle")
    if light.type == "SPOT" and light.use_square:
        warnings.append("Bevy spot lights are round, so this square spot becomes round")
    return warnings


def _visibility_range_issues(objects, only=None):
    if only is not None and component_of(only, "VISIBILITY_RANGE") is None:
        return []
    groups = {}
    for obj in objects:
        if only is not None and "visibility_range" not in str(obj.get(EXTRAS_KEY, "")) and obj != only:
            continue
        item = component_of(obj, "VISIBILITY_RANGE")
        if item is not None and not component_errors(item):
            groups.setdefault(_range_origin(obj, item), []).append((obj, item))
    issues = []
    for members in groups.values():
        if len(members) < 2:
            continue
        lookup = {obj.name: (obj, item) for obj, item in members}
        for name, message in visibility_range_problems([(obj.name, (item.fade_in_start, item.fade_in_end, item.fade_out_start, item.fade_out_end)) for obj, item in members]):
            obj, item = lookup[name]
            if only is None or obj == only:
                issues.append(Issue("WARNING", obj, item, message))
    return issues


def _range_origin(obj, item):
    point = obj.matrix_world.translation
    if item.use_aabb and obj.type in MESH_TYPES:
        point = obj.matrix_world @ (sum((Vector(corner) for corner in obj.bound_box), Vector()) / 8)
    return tuple(round(value, 3) for value in point)


def _has_collider(obj):
    if component_of(obj, "COLLIDER") is not None:
        return True
    _owner, collider = inherited(obj, "COLLIDER")
    return collider is not None and collider.collider_shape in SHAPE_LABELS and has_faces(obj)


def _uneven_scale_ancestor(obj):
    if obj.parent is None:
        return None
    chain = []
    current = obj
    while current is not None:
        chain.append(current)
        current = current.parent
    rotation = Quaternion()
    scale = Vector((1.0, 1.0, 1.0))
    for node in reversed(chain):
        local = node.matrix_world if node.parent is None else node.parent.matrix_world.inverted_safe() @ node.matrix_world
        _translation, local_rotation, local_scale = local.decompose()
        rotation = rotation @ local_rotation
        scale = Vector([total * part for total, part in zip(scale, local_scale)])
    actual = obj.matrix_world.to_3x3()
    approximated = rotation.to_matrix() @ Matrix.Diagonal(scale)
    size = max(1.0, max(abs(value) for row in actual for value in row))
    if all(abs(first - second) <= 0.001 * size for row, other in zip(actual, approximated) for first, second in zip(row, other)):
        return None
    for ancestor in chain[1:]:
        values = [abs(value) for value in ancestor.matrix_local.to_scale()]
        if max(values) > 1.001 * min(values):
            return ancestor
    return obj.parent
