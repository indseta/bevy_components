import os
import re
import textwrap
import time
from collections import namedtuple
from pathlib import Path, PurePosixPath

import bpy
from mathutils import Matrix, Quaternion, Vector

from .bsn import BsnError, crate_root, custom_literal, file_state, inside
from .fingerprint import bake_parts, read_record, stale_message
from .gizmo import PRIMITIVE_SHAPES
from .metadata import EXTRAS_KEY, component_errors, light_of, light_size, serialize_component, visibility_range_problems
from .property import AUDIO_FORMATS
from .probe import FILE_KINDS, FILE_LABELS, HEADER_LENGTH, check_texture, voxel_counts
from .project import game_assets
from .reference import SCENE_EXTENSIONS, read_scenes
from .system import MESH_TYPES, children_map, component_of, components_for, export_settings, exported, file_path, game_types, has_faces, inherited, lightmap_uv_map, mesh_sources, object_actions, problem_changes, redraw_properties, redraw_viewports, scene_path, subtree

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
SHADER_MIXES = {"MIX_SHADER", "ADD_SHADER"}
GLTF_MIXES = {"BSDF_TRANSPARENT", "LIGHT_PATH"}
UNLIT_SHADERS = {"EMISSION", "BACKGROUND"}
PROCEDURAL_NODES = {"AMBIENT_OCCLUSION", "BEVEL", "CAMERA", "FRESNEL", "HAIR_INFO", "LAYER_WEIGHT", "LIGHT_PATH", "NEW_GEOMETRY", "OBJECT_INFO", "PARTICLE_INFO", "POINT_INFO", "SCRIPT", "TANGENT", "TEX_COORD", "WIREFRAME"}
AMBIENT_WITH_SKY = "Bevy Ambient Light takes the World color, which the Bevy Sky's environment light already gives, so meshes get the World's light twice"
PROBLEM_DELAY = 0.5

_texture_checks = {}
_problem_counts = {}


def describe(issue):
    return issue.message if issue.obj is None else f"{issue.obj.name}: {issue.message}"


def issue_row(issue):
    return (issue.level, None if issue.obj is None else issue.obj.name, issue.message)


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
        if select and name is not None:
            layout.operator("bevy_components.select_object", text=f"{name}: {message}", icon=icon).name = name
        else:
            draw_message(layout, message if name is None else f"{name}: {message}", icon, width)
    if len(rows) > limit:
        layout.label(text=f"{len(rows) - limit} more {more}", icon="BLANK1")


def problem_count(scene):
    version, _changed = problem_changes()
    counted = _problem_counts.get(scene.as_pointer())
    if (counted is None or counted[0] != version) and not bpy.app.timers.is_registered(_recount_problems):
        bpy.app.timers.register(_recount_problems, first_interval=0.0 if counted is None else PROBLEM_DELAY)
    return counted[1] if counted is not None else None


def count_problems(scenes):
    version, _changed = problem_changes()
    changed = False
    for scene in scenes:
        settings = export_settings(scene)
        objects = [obj for obj in scene.objects if exported(obj, settings)]
        issues = check_objects(objects, modifiers=settings.apply_modifiers) + (check_scene(objects) if scene == bpy.context.scene else check_world(scene.world))
        errors = sum(1 for issue in issues if issue.level == "ERROR")
        counted = (version, (errors, len(issues) - errors))
        changed = changed or _problem_counts.get(scene.as_pointer(), (None, None))[1] != counted[1]
        _problem_counts[scene.as_pointer()] = counted
    return changed


def _recount_problems():
    _version, changed = problem_changes()
    waited = time.monotonic() - changed
    if waited < PROBLEM_DELAY:
        return PROBLEM_DELAY - waited
    windows = bpy.context.window_manager.windows if bpy.context.window_manager else ()
    scenes = list({window.scene.as_pointer(): window.scene for window in windows}.values()) or [bpy.context.scene]
    if count_problems([scene for scene in scenes if scene is not None]):
        redraw_properties()
        redraw_viewports()
    return None


def stop_problem_counts():
    if bpy.app.timers.is_registered(_recount_problems):
        bpy.app.timers.unregister(_recount_problems)
    _problem_counts.clear()


def draw_problem_count(layout, scene):
    counted = problem_count(scene)
    if counted is None:
        return
    errors, warnings = counted
    row = layout.row(align=True)
    row.emboss = "NONE"
    if not errors and not warnings:
        row.operator("bevy_components.validate", text="", icon="CHECKMARK")
        return
    if errors:
        row.operator("bevy_components.validate", text=str(errors), icon="CANCEL")
    if warnings:
        row.operator("bevy_components.validate", text=str(warnings), icon="ERROR")


def check_objects(objects, destination=None, animations=True, modifiers=True):
    objects = list(objects)
    children = children_map(objects)
    exported = set(objects)
    materials = set()
    assets = game_assets(bpy.context)
    issues = []
    for obj in objects:
        issues.extend(_object_issues(obj, children, exported, destination, animations, modifiers, materials, assets))
    issues.extend(_visibility_range_issues(objects))
    return issues


def check_object(obj, objects, modifiers=True):
    objects = list(objects)
    return _object_issues(obj, children_map(objects), set(objects), modifiers=modifiers, assets=game_assets(bpy.context)) + _visibility_range_issues(objects, obj)



def check_game_paths(objects, destination, assets):
    if assets is None:
        return []
    issues = [] if destination is None or inside(destination, assets) else [Issue("WARNING", None, None, f"{destination.name} is outside {assets}, so the game cannot load it")]
    for obj in objects:
        for item in components_for(obj):
            if item.component_type == "SCENE_REFERENCE" and item.scene_file.strip() and not inside(file_path(item.scene_file), assets):
                issues.append(Issue("WARNING", obj, item, f"{file_path(item.scene_file).name} is outside the game's assets folder, so the game cannot load it"))
    return issues


def check_bsn(objects, root):
    issues = []
    for obj in objects:
        for item in components_for(obj):
            if item.component_type == "CUSTOM" and not component_errors(item):
                component = serialize_component(item)
                untyped = [field.name for field in item.fields if item.use_fields and field.field_type == "ENUM" and not field.rust_type.strip()]
                if untyped:
                    issues.append(Issue("ERROR", obj, item, f"Set the Enum Type of {', '.join(untyped)} in Properties > Scene > Bevy Custom Components, which the BSN export needs to write the variant"))
                    continue
                try:
                    custom_literal(component["type_path"], component["data"], enums=component.get("enums"))
                except BsnError as error:
                    issues.append(Issue("ERROR", obj, item, str(error)))
            elif item.component_type == "SCENE_REFERENCE" and item.scene_file.strip():
                path = file_path(item.scene_file)
                if path.suffix.lower() != ".glb" and not inside(path, root):
                    issues.append(Issue("ERROR", obj, item, f"{path.name} is outside {root.name}, and the export only copies .glb files in. Move it into {root.name}"))
        if obj.type == "MESH" and any(modifier.type == "ARMATURE" for modifier in obj.modifiers):
            issues.append(Issue("WARNING", obj, None, "BSN scenes leave out skins, so the mesh does not follow its armature"))
        shape_keys = getattr(obj.data, "shape_keys", None) if obj.type == "MESH" else None
        if shape_keys is not None and len(shape_keys.key_blocks) > 1:
            issues.append(Issue("WARNING", obj, None, "BSN scenes leave out shape key weights"))
    return issues


def check_rust_file(rust_file, strict=False):
    name = rust_file.name
    if crate_root(rust_file):
        return [Issue("ERROR", None, None, f"{name} is a crate root, so exporting would replace your game's code. Pick a file of its own, such as src/scene.rs")]
    try:
        state = file_state(rust_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError):
        state = "foreign"
    if state == "foreign":
        holds = "the module declarations of its folder" if name.lower() == "mod.rs" else "its code"
        message = f"{name} was not written by the BSN export, so exporting replaces {holds}"
    elif state == "edited":
        message = f"{name} was edited since the last export, which replaces those edits"
    else:
        return []
    if strict:
        return [Issue("ERROR", None, None, f"{message}. Export from File > Export > Bevy Scene (BSN) to replace it")]
    return [Issue("WARNING", None, None, message)]


def _object_issues(obj, children, exported, destination=None, animations=True, modifiers=True, materials=None, assets=None):
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
        elif item.component_type == "NAVIGATION":
            issues.extend(Issue("WARNING", obj, item, message) for message in _navigation_warnings(obj, item, children))
        elif item.component_type == "AUDIO_PLAYER":
            issues.extend(Issue("WARNING", obj, item, message) for message in _audio_warnings(item, assets))
        elif item.component_type == "JOINT":
            issues.extend(Issue("WARNING", obj, item, message) for message in _joint_warnings(obj, item, exported))
        elif item.component_type == "SCENE_REFERENCE" and item.scene_file.strip():
            issues.extend(_scene_reference_issues(obj, item, destination))
        elif item.component_type == "ANIMATION":
            issues.extend(Issue("WARNING", obj, item, message) for message in _animation_warnings(obj, item, children, animations))
        elif item.component_type == "LIGHTMAP":
            issues.extend(_lightmap_issues(obj, item, modifiers))
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
            game_type = game_types().get(item.custom_type)
            if item.use_fields and game_type is not None and game_type.others and not game_type.has_default:
                names = ", ".join(name for name, _rust_type in game_type.others)
                issues.append(Issue("WARNING", obj, item, f"Blender cannot set {names}, so the game needs #[reflect(Default)] on {item.custom_type} to fill them in"))
    light = light_of(obj)
    if light is not None and light.type == "AREA" and not any(item.component_type == "LIGHT" for item in obj.bevy_component_data.components):
        issues.append(Issue("WARNING", obj, None, "glTF leaves out area lights. Add a Light component to export this one as a Bevy rectangle light"))
    shape_keys = obj.data.shape_keys if obj.type == "MESH" else None
    if modifiers and len(obj.modifiers) and shape_keys is not None and len(shape_keys.key_blocks) > 1:
        issues.append(Issue("WARNING", obj, None, "glTF leaves out the shape keys of meshes with modifiers. Apply the modifiers, or turn off Apply Modifiers"))
    issues.extend(Issue("WARNING", obj, None, message) for message in material_warnings(obj, materials))
    return issues


def material_warnings(obj, seen=None):
    seen = set() if seen is None else seen
    warnings = []
    if obj.type not in MESH_TYPES:
        return warnings
    for slot in obj.material_slots:
        if slot.material is None or slot.material in seen:
            continue
        seen.add(slot.material)
        message = _material_warning(slot.material)
        if message:
            warnings.append(message)
    return warnings


def _material_warning(material):
    tree = material.node_tree if bpy.app.version >= (5, 0, 0) or material.use_nodes else None
    output = next((node for node in tree.nodes if node.type == "OUTPUT_MATERIAL" and node.is_active_output), None) if tree is not None else None
    if output is None or not output.inputs["Surface"].is_linked:
        return None
    shaders = _upstream(output.inputs["Surface"])
    if any(node.type in SHADER_MIXES and not (node.type == "MIX_SHADER" and {link.from_node.type for socket in node.inputs for link in socket.links} & GLTF_MIXES) for node in shaders):
        return f"Material {material.name} mixes shaders, which glTF flattens into one"
    principled = [node for node in shaders if node.type == "BSDF_PRINCIPLED"]
    if not principled:
        return None if any(node.type in UNLIT_SHADERS for node in shaders) else f"Material {material.name} has no Principled BSDF, so glTF exports it plain white"
    names = list(dict.fromkeys(socket.name for node in principled for socket in node.inputs if socket.is_linked and _procedural(socket)))
    if not names:
        return None
    listed = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}" if len(names) <= 3 else f"{', '.join(names[:2])} and {len(names) - 2} more inputs"
    return f"Material {material.name} drives {listed} with procedural nodes, which glTF leaves out. Bake them to images"


def _upstream(socket):
    found = set()
    pending = [link.from_node for link in socket.links if not link.is_muted]
    while pending:
        node = pending.pop()
        if node in found:
            continue
        found.add(node)
        pending.extend(link.from_node for entry in node.inputs for link in entry.links if not link.is_muted)
        if node.type == "GROUP" and node.node_tree is not None:
            pending.extend(node.node_tree.nodes)
    return found


def _procedural(socket):
    nodes = _upstream(socket)
    return not any(node.type == "TEX_IMAGE" for node in nodes) and any(node.type in PROCEDURAL_NODES or node.type.startswith("TEX_") for node in nodes)


def check_world(world):
    if world is None or not hasattr(world, "bevy_sky") or not world.bevy_sky.enabled:
        return []
    issues = []
    check = sky_check(world)
    if check.level is not None:
        issues.append(Issue(check.level, None, None, f"Bevy Sky: {check.message}"))
    if ambient_doubles_sky(world):
        issues.append(Issue("WARNING", None, None, AMBIENT_WITH_SKY))
    return issues


def check_scene(objects):
    return check_world(bpy.context.scene.world) + stale_bakes(objects)


def stale_bakes(objects):
    scene = bpy.context.scene
    world = scene.world
    baked = []
    if world is not None and hasattr(world, "bevy_sky") and world.bevy_sky.enabled:
        record = read_record(world.bevy_sky.bake_fingerprint, world.bevy_sky.sky_file)
        if record is not None:
            baked.append((None, None, "SKY", record))
    for obj in objects:
        if scene.objects.get(obj.name) != obj:
            continue
        for item in components_for(obj):
            if item.component_type in FILE_KINDS and (record := read_record(item.bake_fingerprint, item.probe_file)) is not None:
                baked.append((obj, item, FILE_KINDS[item.component_type], record))
    if not baked:
        return []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    cache = {}
    issues = []
    for obj, item, kind, record in baked:
        message = stale_message(record, kind, bake_parts(scene, bpy.context.view_layer, depsgraph, cache, obj, item, world))
        if message is not None:
            issues.append(Issue("WARNING", obj, item, message if obj is not None else f"Bevy Sky: {message}"))
    return issues


def ambient_doubles_sky(world):
    ambient = world.bevy_ambient_light
    return world.bevy_sky.enabled and world.bevy_sky.environment_light and ambient.enabled and ambient.use_world_color


def sky_check(world):
    if not world.bevy_sky.sky_file.strip():
        return TextureCheck("WARNING", "No cubemap baked yet, so Bevy shows no sky", None)
    return _file_check(world.bevy_sky.sky_file, "CUBEMAP", world.library)


def texture_check(obj, item):
    if not item.probe_file.strip():
        return TextureCheck("WARNING", MISSING_FILES[item.component_type], None)
    return _file_check(item.probe_file, FILE_KINDS[item.component_type], obj.library)


def _file_check(filepath, kind, library):
    path = Path(bpy.path.abspath(filepath, library=library))
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
    elif item.collider_collision_only and not mesh_sources(obj, children, "COLLIDER"):
        warnings.append("Collision Only finds no mesh on this object or under it to hide")
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
            warnings.append(f"{body.name} is not exported with this scene, so the joint holds nothing")
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


def _navigation_warnings(obj, item, children):
    if item.navigation_kind == "IGNORED" or mesh_sources(obj, children, "NAVIGATION"):
        return []
    tagged = subtree(obj, children, lambda child: component_of(child, "NAVIGATION") is not None)
    if any(collider is not None and collider.collider_shape in PRIMITIVE_SHAPES for collider in (component_of(source, "COLLIDER") for source, _matrix in tagged)):
        return []
    return ["No mesh or collider on this object or under it to tag for navigation"]


def _audio_warnings(item, assets=None):
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
    if not warnings and assets is not None and not (assets / path).is_file():
        warnings.append(f"No file at {path} in the game's assets folder")
    return warnings


def _scene_reference_issues(obj, item, destination):
    path = file_path(item.scene_file)
    try:
        scene_path(item.scene_file, None if destination is None else destination.parent)
    except ValueError:
        return [Issue("ERROR", obj, item, f"{path.name} is on another drive than the exported scene, so the game cannot load it")]
    if path.suffix.lower() not in SCENE_EXTENSIONS:
        return [Issue("WARNING", obj, item, f"{path.name} is not a .glb or .gltf file")]
    if destination is not None and path == Path(os.path.abspath(destination)):
        return [Issue("WARNING", obj, item, "Spawns the exported scene inside itself, so the game skips it")]
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


def _lightmap_issues(obj, item, modifiers=True):
    if obj.type != "MESH":
        return [Issue("WARNING", obj, item, "Only meshes use lightmaps, so it is not exported")]
    issues = []
    if lightmap_uv_map(obj) is None:
        issues.append(Issue("WARNING", obj, item, "No second UV map, which Bevy reads lightmaps with. Click Unwrap Lightmap UVs"))
    baked = next((modifier for modifier in obj.modifiers if modifier.show_render and not (modifiers and modifier.show_viewport)), None)
    exported = next((modifier for modifier in obj.modifiers if modifiers and modifier.show_viewport and not modifier.show_render), None)
    if baked is not None:
        issues.append(Issue("WARNING", obj, item, f"Bake includes the {baked.name} modifier but the export leaves it out, so the lightmap may not fit. {'Show it in the viewport' if modifiers else 'Turn on Apply Modifiers'}"))
    elif exported is not None:
        issues.append(Issue("WARNING", obj, item, f"Export includes the {exported.name} modifier but the bake leaves it out, so the lightmap may not fit. Enable it in renders"))
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
