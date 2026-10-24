import functools
import json
import mimetypes
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix

from .changes import collection_users, relatives, revision, touch
from .collection import COLLECTION_KINDS, collections_changed, from_collection, with_collections
from .metadata import EXTRAS_KEY, FIELD_VALUES, SCHEMA_VERSION, SHADOW_DEFAULTS, WATTS_TO_LUMENS, addon_version, ambient_light_component, convert_value, field_data, json_fields, light_intensity, light_of, relative_path, serialize_component, serialize_scene, sky_component, tuple_fields, variant_names
from .native import MESH_TYPES, fog_source, physics_components, with_native
from .prefab import export_directory, filter_tree, instance_node, prefab_members, prefab_scene
from .project import game_folder
from .schema import SCHEMA_FILE, GameField, SchemaError, find_schema, parse_schema

LAYER_COUNT = 32
BEVY_AXES = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))
CLIPBOARD_TYPE = "bevy_components"
CLIPBOARD_VERSION = 1
SNAPSHOT_SKIPPED = {"rna_type", "text_link"}
DATA_GROUPS = {"LIGHT": "bevy_light", "SPEAKER": "bevy_speaker", "LIGHT_PROBE": "bevy_probe"}
PRESET_FOLDER = os.path.join("presets", "bevy_components")
TEXT_OBJECT = "bevy_object"
TEXT_COMPONENT = "bevy_component"
PANEL_EXPANDED = True
PANEL_DRAWN_EXPANDED = True
PROBLEM_CHANGES = [0, 0.0]
SCHEMA_CHECK_INTERVAL = 1.0

SUMMARY_LIMIT = 8192
JOINT_SETTINGS = "joint_"
_resolved = [None]
_skipped = [None]
_summaries = {}
_game_schema = {"checked": None, "key": None, "path": None, "types": {}, "error": ""}
_variant_items = {}


def redraw_viewports(_self=None, _context=None):
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def redraw_properties():
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "PROPERTIES":
                area.tag_redraw()


def redraw_status_bars():
    bpy.msgbus.publish_rna(key=(bpy.types.ViewLayer, "name"))


def panel_expanded():
    return PANEL_EXPANDED


def panel_header_drawn():
    global PANEL_DRAWN_EXPANDED
    PANEL_DRAWN_EXPANDED = False
    if not bpy.app.timers.is_registered(_apply_panel_state):
        bpy.app.timers.register(_apply_panel_state, first_interval=0.0)


def panel_body_drawn():
    global PANEL_DRAWN_EXPANDED
    PANEL_DRAWN_EXPANDED = True


def _apply_panel_state():
    global PANEL_EXPANDED
    if PANEL_EXPANDED != PANEL_DRAWN_EXPANDED:
        PANEL_EXPANDED = PANEL_DRAWN_EXPANDED
        redraw_viewports()
    return None


def stop_panel_tracking():
    if bpy.app.timers.is_registered(_apply_panel_state):
        bpy.app.timers.unregister(_apply_panel_state)


def overview_index(self):
    view_layer = bpy.context.view_layer
    active = view_layer.objects.active if view_layer is not None else None
    if active is None:
        return -1
    return next((index for index, obj in enumerate(self.id_data.objects) if obj == active), -1)


def select_overview_object(self, value):
    view_layer = bpy.context.view_layer
    objects = self.id_data.objects
    if view_layer is None or not 0 <= value < len(objects) or view_layer.objects.get(objects[value].name) is None:
        return
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    objects[value].select_set(True)
    view_layer.objects.active = objects[value]


@persistent
def problems_changed(*_arguments):
    PROBLEM_CHANGES[0] += 1
    PROBLEM_CHANGES[1] = time.monotonic()


def problem_changes():
    return tuple(PROBLEM_CHANGES)


@contextmanager
def resolving():
    if _resolved[0] is not None:
        yield
        return
    _resolved[0] = {}
    try:
        yield
    finally:
        _resolved[0] = None


def resolved(function):
    @functools.wraps(function)
    def wrapper(*arguments, **options):
        with resolving():
            return function(*arguments, **options)
    return wrapper


def components_for(obj):
    if not hasattr(obj, "bevy_component_data"):
        return []
    memo = _resolved[0]
    if memo is None:
        return _components(obj)
    found = memo.get(obj.as_pointer())
    if found is None:
        found = memo[obj.as_pointer()] = _components(obj)
    return list(found)


def _components(obj):
    return with_collections(obj, with_native(obj, [item for item in obj.bevy_component_data.components if item.enabled and item.component_type]))


def _summary(obj):
    key = revision(obj)
    found = _summaries.get(obj.session_uid)
    if found is None or found[0] != key:
        if len(_summaries) >= SUMMARY_LIMIT:
            _summaries.clear()
        items = components_for(obj)
        found = _summaries[obj.session_uid] = (key, frozenset(item.component_type for item in items), tuple(item.custom_type for item in items if item.component_type == "CUSTOM" and item.custom_type.strip()), tuple(item.as_pointer() for item in items if from_collection(item)))
    return found


def component_kinds(obj):
    return _summary(obj)[1] if hasattr(obj, "bevy_component_data") else frozenset()


def custom_types(obj):
    return _summary(obj)[2] if hasattr(obj, "bevy_component_data") else ()


def shared_items(obj):
    return _summary(obj)[3] if hasattr(obj, "bevy_component_data") else ()


def component_of(obj, kind):
    for item in components_for(obj):
        if item.component_type == kind:
            return item
    return None


def inherited(obj, kind):
    while obj is not None:
        item = component_of(obj, kind)
        if item is not None:
            return obj, item
        obj = obj.parent
    return None, None


def accepts(obj, kind):
    if isinstance(obj, bpy.types.Collection):
        return kind in COLLECTION_KINDS
    if kind == "LIGHT":
        return light_of(obj) is not None
    if kind == "LIGHTMAP":
        return getattr(obj, "type", None) == "MESH"
    return True


def lightmap_uv_map(obj):
    layers = obj.data.uv_layers if getattr(obj, "type", None) == "MESH" else ()
    return layers[1] if len(layers) > 1 else None


def children_map(objects):
    children = {}
    for obj in objects:
        if obj.parent is not None:
            children.setdefault(obj.parent, []).append(obj)
    return children


def subtree(obj, children, stop, instances=True):
    found = []
    pending = [(obj, None, children)]
    while pending:
        current, space, lookup = pending.pop()
        matrix = current.matrix_world if space is None else space @ current.matrix_world
        found.append((current, matrix))
        branches = [(child, space, lookup) for child in lookup.get(current, ())]
        collection = current.instance_collection if instances and current.instance_type == "COLLECTION" else None
        if collection is not None:
            members = set(collection.all_objects)
            inner = matrix @ Matrix.Translation(-collection.instance_offset)
            branches.extend((member, inner, children_map(members)) for member in members if member.parent not in members)
        pending.extend(branch for branch in branches if not stop(branch[0]))
    return found


def has_faces(obj):
    return obj.type in MESH_TYPES and (obj.type != "MESH" or len(obj.data.polygons) > 0)


def owns_mesh(obj, kind):
    return getattr(component_of(obj, kind), "shadows_own_mesh", False)


def mesh_sources(obj, children, kind, instances=True):
    found = subtree(obj, children, lambda child: component_of(child, kind) is not None and not owns_mesh(child, kind), instances)
    return [(source, matrix) for source, matrix in found if has_faces(source) and (source == obj or not owns_mesh(source, kind))]


def collider_sources(obj, children, item, instances=True):
    if getattr(item, "collider_own_mesh", False):
        return [(obj, obj.matrix_world)] if has_faces(obj) else []
    return mesh_sources(obj, children, "COLLIDER", instances)


def collision_only_meshes(objects):
    children = children_map(objects)
    hidden = set()
    for obj in objects:
        collider = component_of(obj, "COLLIDER")
        if collider is not None and collider.collider_collision_only:
            hidden.update(source for source, _matrix in collider_sources(obj, children, collider, instances=False))
    return hidden


def export_settings(scene):
    return scene.bevy_glb_export


def exported(obj, options):
    if options.visible_only and (not obj.visible_get() or obj.hide_viewport or all(collection.hide_viewport for collection in obj.users_collection)):
        return False
    return not options.renderable_only or not (obj.hide_render or all(collection.hide_render for collection in obj.users_collection))


def exported_objects(context, options, selected=None):
    objects = context.selected_objects if (options.selected_only if selected is None else selected) else context.scene.objects
    members = prefab_members()
    return [obj for obj in objects if exported(obj, options) and obj not in members]


def changes_mesh(obj):
    return any(modifier.type != "ARMATURE" and modifier.show_viewport for modifier in obj.modifiers)


def mesh_points(obj, children, depsgraph):
    inverse = obj.matrix_world.inverted_safe()
    points = []
    for source, matrix in mesh_sources(obj, children, "COLLIDER"):
        evaluated = source.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        if mesh is None:
            continue
        try:
            local = inverse @ matrix
            points.extend(tuple(local @ vertex.co) for vertex in mesh.vertices)
        finally:
            evaluated.to_mesh_clear()
    return points


def layer_names(scene):
    layers = getattr(scene, "bevy_collision_layers", None)
    return [getattr(layers, f"layer_{layer}").strip() if layers is not None else "" for layer in range(LAYER_COUNT)]


def blend_directory():
    return bpy.path.abspath("//") or os.getcwd()


def file_path(path):
    return Path(os.path.abspath(bpy.path.abspath(path)))


def scene_path(path, directory=None):
    if not path.strip():
        return ""
    return relative_path(str(file_path(path)), str(directory or blend_directory()))


def object_actions(obj):
    found = set()
    for owner in (obj, getattr(obj.data, "shape_keys", None)):
        animation = getattr(owner, "animation_data", None)
        if animation is None:
            continue
        if animation.action is not None:
            found.add(animation.action.name)
        found.update(strip.action.name for track in animation.nla_tracks for strip in track.strips if strip.action is not None)
    return found


def default_clip(obj):
    animation = obj.animation_data
    if animation is not None and animation.action is not None:
        return animation.action.name
    return next(iter(sorted(object_actions(obj))), "")


def touch_object(obj):
    if isinstance(obj, bpy.types.Object):
        touch_objects([obj])


def touch_objects(objects):
    problems_changed()
    objects = list(objects)
    if objects:
        touch(relatives(objects))


@contextmanager
def bevy_export():
    previous = _skipped[0]
    _skipped[0] = skipped = []
    try:
        yield skipped
    finally:
        _skipped[0] = previous


def object_components(obj, directory=None, skipped=None):
    locate = functools.partial(scene_path, directory=directory)
    components = []
    for item in components_for(obj):
        try:
            component = serialize_component(item, locate)
        except ValueError as error:
            if skipped is not None:
                skipped.append(f"{obj.name}: {error}")
            continue
        if component is not None:
            components.append(component)
    return components


def component_index(obj, item):
    for index, other in enumerate(obj.bevy_component_data.components):
        if other == item:
            return index
    return -1


def copy_component(source, destination):
    for field in source.bl_rna.properties:
        if field.identifier in {"rna_type", "id_data", "text_link"}:
            continue
        if field.type == "COLLECTION":
            items = getattr(destination, field.identifier)
            items.clear()
            for item in getattr(source, field.identifier):
                copy_component(item, items.add())
            continue
        if field.is_readonly:
            continue
        value = getattr(source, field.identifier)
        try:
            setattr(destination, field.identifier, tuple(value) if field.type == "FLOAT" and field.is_array else value)
        except (TypeError, AttributeError):
            continue


def component_snapshot(item, owner, references=True):
    data = {}
    for prop in item.bl_rna.properties:
        name = prop.identifier
        if name in SNAPSHOT_SKIPPED:
            continue
        value = getattr(item, name)
        if prop.type == "COLLECTION":
            if len(value):
                data[name] = [component_snapshot(child, owner, references) for child in value]
        elif prop.is_readonly or not item.is_property_set(name):
            continue
        elif prop.type == "POINTER":
            data[name] = None if value is None else {"self": True} if value == owner else {"object": value.name} if references else None
        elif prop.type == "ENUM" and prop.is_enum_flag:
            data[name] = sorted(value)
        elif getattr(prop, "is_array", False):
            data[name] = list(value)
        else:
            data[name] = value
    data.update({name: item[name] for name in item.keys() if name not in item.bl_rna.properties and isinstance(item[name], (bool, int, float, str))})
    return data


def _pointer(value, owner):
    if not isinstance(value, dict):
        return None
    if value.get("self"):
        return owner
    return bpy.data.objects.get(value["object"]) if isinstance(value.get("object"), str) else None


def restore_component(item, data, owner):
    for name, value in data.items():
        prop = item.bl_rna.properties.get(name)
        if name in SNAPSHOT_SKIPPED:
            continue
        if prop is None:
            if isinstance(value, (bool, int, float, str)):
                item[name] = value
            continue
        if prop.type == "COLLECTION":
            children = getattr(item, name)
            children.clear()
            for child in value if isinstance(value, list) else ():
                if isinstance(child, dict):
                    restore_component(children.add(), child, owner)
            continue
        if prop.is_readonly:
            continue
        if prop.type == "POINTER":
            value = _pointer(value, owner)
        elif prop.type == "ENUM" and prop.is_enum_flag and isinstance(value, list):
            value = set(value)
        try:
            setattr(item, name, value)
        except (TypeError, ValueError, AttributeError):
            continue


def clipboard_text(obj, items, name=None, references=True, blender=None):
    data = {"type": CLIPBOARD_TYPE, "version": CLIPBOARD_VERSION}
    if name is not None:
        data["name"] = name
    data["components"] = [component_snapshot(item, obj, references) for item in items if item.component_type]
    if blender:
        data["blender"] = blender
    return json.dumps(data, indent=2, ensure_ascii=False)


def read_components(text):
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("type") != CLIPBOARD_TYPE or not isinstance(data.get("components"), list):
        return None
    blender = data.get("blender")
    return [component for component in data["components"] if isinstance(component, dict)], blender if isinstance(blender, dict) else {}


def _struct_snapshot(struct, owner, references):
    data = {}
    for prop in struct.bl_rna.properties:
        if prop.identifier == "rna_type" or prop.is_readonly:
            continue
        value = getattr(struct, prop.identifier)
        if prop.type == "POINTER":
            data[prop.identifier] = None if value is None else {"self": True} if value == owner else {"object": value.name} if references else None
        elif getattr(prop, "is_array", False):
            data[prop.identifier] = list(value)
        else:
            data[prop.identifier] = value
    return data


def _restore_struct(struct, data, owner):
    for name, value in data.items():
        prop = struct.bl_rna.properties.get(name)
        if prop is None or prop.is_readonly or name == "rna_type":
            continue
        try:
            setattr(struct, name, _pointer(value, owner) if prop.type == "POINTER" else value)
        except (TypeError, ValueError, AttributeError):
            continue


def _replace_group(group, data, owner, replaced=lambda name: True):
    for name in group.bl_rna.properties.keys():
        if name != "rna_type" and replaced(name):
            group.property_unset(name)
    for name in list(group.keys()):
        if replaced(name):
            del group[name]
    restore_component(group, {name: value for name, value in data.items() if replaced(name)}, owner)


def blender_snapshot(obj, references=True, physics_only=False):
    data = {}
    if obj.rigid_body is not None:
        data["rigid_body"] = _struct_snapshot(obj.rigid_body, obj, references)
    if obj.rigid_body_constraint is not None and not physics_only:
        data["rigid_body_constraint"] = _struct_snapshot(obj.rigid_body_constraint, obj, references)
    if data:
        data["bevy_physics"] = component_snapshot(obj.bevy_physics, obj, references)
    if physics_only:
        return data
    settings = obj.bevy_object
    if obj.type in MESH_TYPES and not (obj.visible_shadow and settings.receive_shadows):
        data["shadows"] = {"cast": obj.visible_shadow, "receive": settings.receive_shadows}
    if settings.autoplay:
        data["autoplay"] = {"speed": settings.speed}
    group = DATA_GROUPS.get(obj.type)
    if group is not None and hasattr(obj.data, group):
        data[group] = component_snapshot(getattr(obj.data, group), obj, references)
    if obj.bevy_component_data.leave_out:
        data["leave_out"] = True
    return data


def has_blender_settings(obj):
    return obj.rigid_body is not None or obj.rigid_body_constraint is not None or obj.type in DATA_GROUPS or obj.bevy_component_data.leave_out or obj.bevy_object.autoplay or obj.type in MESH_TYPES and not (obj.visible_shadow and obj.bevy_object.receive_shadows)


def blender_count(data):
    return len([key for key in data if key not in {"bevy_physics", "leave_out"}])


def _with_active(obj, operator):
    view_layer = bpy.context.view_layer
    if view_layer is None or view_layer.objects.get(obj.name) != obj:
        return
    previous = view_layer.objects.active
    view_layer.objects.active = obj
    try:
        operator()
    except RuntimeError:
        pass
    finally:
        view_layer.objects.active = previous


def _add_constraint():
    if bpy.context.scene.rigidbody_world is None:
        bpy.ops.rigidbody.world_add()
    bpy.ops.rigidbody.constraint_add()


def paste_blender(obj, data):
    if obj.library is not None:
        return 0
    pasted = 0
    pasted_body = False
    pasted_joint = False
    body = data.get("rigid_body")
    if isinstance(body, dict) and obj.type == "MESH":
        if obj.rigid_body is None:
            _with_active(obj, bpy.ops.rigidbody.object_add)
        if obj.rigid_body is not None:
            _restore_struct(obj.rigid_body, body, obj)
            pasted_body = True
            pasted += 1
    constraint = data.get("rigid_body_constraint")
    if isinstance(constraint, dict):
        if obj.rigid_body_constraint is None:
            _with_active(obj, _add_constraint)
        if obj.rigid_body_constraint is not None:
            _restore_struct(obj.rigid_body_constraint, constraint, obj)
            pasted_joint = True
            pasted += 1
    if (pasted_body or pasted_joint) and isinstance(data.get("bevy_physics"), dict):
        _replace_group(obj.bevy_physics, data["bevy_physics"], obj, lambda name: pasted_joint if name.startswith(JOINT_SETTINGS) else pasted_body)
    shadows = data.get("shadows")
    if isinstance(shadows, dict) and obj.type in MESH_TYPES:
        obj.visible_shadow = bool(shadows.get("cast", True))
        obj.bevy_object.receive_shadows = bool(shadows.get("receive", True))
        pasted += 1
    autoplay = data.get("autoplay")
    if isinstance(autoplay, dict) and isinstance(autoplay.get("speed", 1.0), (int, float)):
        obj.bevy_object.autoplay = True
        obj.bevy_object.speed = autoplay.get("speed", 1.0)
        pasted += 1
    group = DATA_GROUPS.get(obj.type)
    if group is not None and isinstance(data.get(group), dict) and obj.data.library is None and hasattr(obj.data, group):
        _replace_group(getattr(obj.data, group), data[group], obj)
        touch_owner(obj.data)
        pasted += 1
    if data.get("leave_out") is True:
        obj.bevy_component_data.leave_out = True
    return pasted


def _same_component(item, data):
    return item.component_type == data.get("component_type") and (item.component_type != "CUSTOM" or item.custom_type == data.get("custom_type", item.bl_rna.properties["custom_type"].default))


def paste_components(obj, components, scene, blender=None):
    items = obj.bevy_component_data.components
    pasted = paste_blender(obj, blender) if blender else 0
    for data in components:
        kind = data.get("component_type")
        if not isinstance(kind, str) or not accepts(obj, kind):
            continue
        index = next((index for index, item in enumerate(items) if _same_component(item, data)), None)
        if index is not None:
            items.remove(index)
        item = items.add()
        try:
            item.component_type = kind
        except TypeError:
            items.remove(len(items) - 1)
            continue
        if index is not None:
            items.move(len(items) - 1, index)
            item = items[index]
        restore_component(item, data, obj)
        if item.component_type == "CUSTOM":
            definition = find_definition(scene, item.custom_type)
            if definition is not None:
                link_component(item, definition)
        pasted += 1
    touch_object(obj)
    return pasted


def preset_folder(create=False):
    return Path(bpy.utils.user_resource("SCRIPTS", path=PRESET_FOLDER, create=create))


def preset_file(name):
    return preset_folder(create=True) / f"{bpy.path.clean_name(name.strip()).strip('_').lower() or 'preset'}.json"


def presets():
    folder = preset_folder()
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("type") == CLIPBOARD_TYPE and isinstance(data.get("components"), list):
            found.append((str(data.get("name") or bpy.path.display_name(path.stem)), path))
    return sorted(found, key=lambda preset: preset[0].lower())


def copy_to_object(source, destination, obj):
    copy_component(source, destination)
    for prop in ("joint_body1", "joint_body2"):
        if getattr(destination, prop) == source.id_data:
            setattr(destination, prop, obj)


def data_users(data):
    if isinstance(data, bpy.types.Collection):
        return collection_users(data)
    if isinstance(data, bpy.types.Material):
        return [obj for obj in bpy.data.objects if any(slot.material == data for slot in obj.material_slots)]
    return [obj for obj in bpy.data.objects if data is not None and obj.data == data]


def touch_owner(owner):
    if isinstance(owner, bpy.types.Collection):
        collections_changed()
    touch_objects([owner] if isinstance(owner, bpy.types.Object) else data_users(owner))


def touch_changed(self, context):
    touch_owner(getattr(self, "id_data", None))
    redraw_viewports()


def _light_owner(self):
    owner = getattr(self, "id_data", None)
    if isinstance(owner, bpy.types.Light):
        return owner, next(iter(data_users(owner)), None)
    return light_of(owner), owner


def light_intensity_toggled(self, context):
    light, obj = _light_owner(self)
    if self.light_use_intensity and light is not None and not self.is_property_set("light_intensity"):
        self.light_intensity = light_intensity(light, obj)
    touch_changed(self, context)


def light_bias_toggled(self, context):
    light = _light_owner(self)[0]
    if self.light_use_bias and light is not None and light.type in SHADOW_DEFAULTS and not self.is_property_set("light_depth_bias"):
        depth, normal, near = SHADOW_DEFAULTS[light.type]
        self.light_depth_bias = depth
        self.light_normal_bias = normal
        if near is not None:
            self.light_near_clip = near
    touch_changed(self, context)


def _uses_nodes(world):
    return world.node_tree is not None and (bpy.app.version >= (5, 0, 0) or world.use_nodes)


def world_background(world):
    if not _uses_nodes(world):
        return None
    output = next((node for node in world.node_tree.nodes if node.bl_idname == "ShaderNodeOutputWorld" and node.is_active_output), None)
    surface = output.inputs.get("Surface") if output is not None else None
    if surface is None or not surface.is_linked:
        return None
    background = surface.links[0].from_node
    if background.bl_idname != "ShaderNodeBackground" or background.inputs["Color"].is_linked or background.inputs["Strength"].is_linked:
        return None
    return background


def world_color(world):
    if not _uses_nodes(world):
        return tuple(world.color), 1.0
    background = world_background(world)
    if background is None:
        return None
    return tuple(background.inputs["Color"].default_value)[:3], float(background.inputs["Strength"].default_value)


def ambient_light(world):
    settings = world.bevy_ambient_light
    if not settings.use_world_color:
        return tuple(settings.color), float(settings.brightness)
    color, strength = world_color(world) or (tuple(world.color), 1.0)
    return color, strength * WATTS_TO_LUMENS


def sky_lights_scene(world):
    sky = getattr(world, "bevy_sky", None)
    return sky is not None and sky.enabled and sky.environment_light and bool(sky.sky_file.strip())


def scene_components(world):
    components = []
    if world.bevy_ambient_light.enabled:
        color, brightness = ambient_light(world)
        components.append(ambient_light_component(color, brightness, world.bevy_ambient_light.baked))
    elif sky_lights_scene(world):
        components.append(ambient_light_component((1.0, 1.0, 1.0), 0.0, False))
    if world.bevy_sky.enabled:
        components.append(sky_component(world.bevy_sky))
    return components


def new_identifier():
    return uuid.uuid4().hex


def schema_setting():
    addon = bpy.context.preferences.addons.get(__package__) if bpy.context.preferences else None
    preferences = addon.preferences if addon is not None else None
    return preferences.schema_path.strip() if preferences is not None else ""


def _schema_path():
    setting = schema_setting()
    if setting:
        return file_path(setting)
    folder = game_folder(bpy.context)
    if folder is not None and (folder / SCHEMA_FILE).is_file():
        return folder / SCHEMA_FILE
    return find_schema(blend_directory())


def game_schema(force=False):
    now = time.monotonic()
    if not force and _game_schema["checked"] is not None and now - _game_schema["checked"] < SCHEMA_CHECK_INTERVAL:
        return _game_schema
    _game_schema["checked"] = now
    path = _schema_path()
    try:
        stat = path.stat() if path is not None else None
    except OSError:
        stat = None
    key = (str(path), stat.st_mtime_ns if stat else None, stat.st_size if stat else None)
    if key == _game_schema["key"] and not force:
        return _game_schema
    types = {}
    error = f"{path.name} was not found" if path is not None and stat is None else ""
    if stat is not None:
        try:
            types = parse_schema(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SchemaError) as exception:
            error = f"{path.name} cannot be read. {exception}"
    _game_schema.update(key=key, path=path, types=types, error=error)
    if not bpy.app.timers.is_registered(_apply_game_types):
        bpy.app.timers.register(_apply_game_types, first_interval=0.0)
    return _game_schema


def game_types():
    return game_schema()["types"]


def apply_game_types():
    for scene in bpy.data.scenes:
        apply_definitions(scene)
    redraw_properties()


def _apply_game_types():
    apply_game_types()
    return None


def schema_setting_changed(_self, _context):
    game_schema(force=True)


def stop_schema_updates():
    if bpy.app.timers.is_registered(_apply_game_types):
        bpy.app.timers.unregister(_apply_game_types)


@persistent
def load_game_types(*_args):
    game_schema(force=True)
    stop_schema_updates()
    apply_game_types()


def scene_definition(scene, type_path):
    if scene is None or not type_path.strip() or not hasattr(scene, "bevy_component_definitions"):
        return None
    for definition in scene.bevy_component_definitions.definitions:
        if definition.name == type_path:
            return definition
    return None


def find_definition(scene, type_path):
    if not type_path.strip():
        return None
    return game_types().get(type_path) or scene_definition(scene, type_path)


def type_path_suggestions(_self, context, _edit_text):
    scene = getattr(context, "scene", None)
    names = set(game_types())
    if scene is not None and hasattr(scene, "bevy_component_definitions"):
        names.update(definition.name for definition in scene.bevy_component_definitions.definitions if definition.name.strip())
    return sorted(names)


def variant_items(self, _context):
    names = tuple(variant_names(self.variants))
    if names not in _variant_items:
        _variant_items[names] = [(name, name, "", index) for index, name in enumerate(names)] or [("NONE", "No Variants", "Add variants to the field first", 0)]
    return _variant_items[names]


def variant_index(self):
    names = variant_names(self.variants)
    return names.index(self.string_value) if self.string_value in names else 0


def set_variant(self, value):
    names = variant_names(self.variants)
    if 0 <= value < len(names):
        self.string_value = names[value]


def field_slot(field):
    value = getattr(field, FIELD_VALUES[field.field_type])
    return value if isinstance(value, (bool, int, float, str)) else tuple(value)


def write_field(field, value):
    setattr(field, FIELD_VALUES[field.field_type], value)


def _field_layout(fields):
    return [(field.identifier, field.name, field.field_type, field.variants, field.rust_type) for field in fields]


def _json_object(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return dict(json_fields(data))


def _default(source):
    return source.default if isinstance(source, GameField) else field_slot(source)


def _converted(source, values, key):
    value = convert_value(source.field_type, values[key]) if key in values else None
    if source.field_type == "ENUM" and value not in variant_names(source.variants):
        return None
    return value


def link_component(item, definition, keep_values=True):
    if keep_values and item.use_fields and _field_layout(item.fields) == _field_layout(definition.fields):
        return False
    typed = keep_values and item.use_fields
    by_identifier = {field.identifier: field_slot(field) for field in item.fields if field.identifier} if typed else {}
    by_name = {field.name: field_slot(field) for field in item.fields} if typed else {}
    leftovers = _json_object(item.custom_json) if keep_values else {}
    values = []
    for source in definition.fields:
        default = _default(source)
        kept = _converted(source, by_identifier, source.identifier)
        loaded = _converted(source, leftovers, source.name)
        renamed = _converted(source, by_name, source.name)
        if kept is not None and kept != default:
            values.append(kept)
        elif loaded is not None:
            values.append(loaded)
            leftovers.pop(source.name)
        elif renamed is not None and source.identifier not in by_identifier:
            values.append(renamed)
        else:
            values.append(default)
    item.fields.clear()
    for source, value in zip(definition.fields, values):
        field = item.fields.add()
        field.identifier = source.identifier
        field.name = source.name
        field.field_type = source.field_type
        field.variants = source.variants
        field.rust_type = source.rust_type
        write_field(field, value)
    if keep_values and leftovers != _json_object(item.custom_json):
        item.custom_json = json.dumps(leftovers, ensure_ascii=False)
    item.use_fields = True
    return True


def unlink_component(item):
    if not item.use_fields:
        return False
    data = field_data(item.fields)
    if isinstance(data, dict):
        data = {**data, **{name: value for name, value in _json_object(item.custom_json).items() if name not in data}}
    item.custom_json = json.dumps(data, ensure_ascii=False)
    item.fields.clear()
    item.use_fields = False
    return True


def custom_components(scene, type_path=None):
    for owner in [*scene.objects, *scene.collection.children_recursive]:
        if owner.library:
            continue
        for item in owner.bevy_component_data.components:
            if item.component_type == "CUSTOM" and (type_path is None or item.custom_type == type_path):
                yield owner, item


def apply_definitions(scene):
    changed = set()
    for owner, item in list(custom_components(scene)):
        definition = find_definition(scene, item.custom_type)
        if definition is not None and link_component(item, definition):
            changed.add(owner)
    for owner in changed:
        touch_owner(owner)
    redraw_viewports()


def component_text(item):
    if item.use_fields:
        return json.dumps(field_data(item.fields), indent=2, ensure_ascii=False) + "\n"
    try:
        return json.dumps(json.loads(item.custom_json), indent=2, ensure_ascii=False) + "\n"
    except json.JSONDecodeError:
        return item.custom_json


def linked_component(text):
    obj = text.get(TEXT_OBJECT)
    link = text.get(TEXT_COMPONENT)
    if not isinstance(obj, (bpy.types.Object, bpy.types.Collection)) or not isinstance(link, str) or not link:
        return None, None
    return obj, next((item for item in obj.bevy_component_data.components if item.component_type == "CUSTOM" and item.text_link == link), None)


def write_component_text(item, source):
    try:
        data = json.loads(source)
    except json.JSONDecodeError as error:
        return f"Line {error.lineno}, column {error.colno}: {error.msg}"
    if not item.use_fields:
        item.custom_json = json.dumps(data, ensure_ascii=False)
        return None
    if tuple_fields(field.name for field in item.fields):
        data = json_fields(data)
    elif not isinstance(data, dict):
        return f"{item.custom_type} has fields, so its data must be a JSON object"
    names = {field.name for field in item.fields}
    unknown = [name for name in data if name not in names]
    if unknown:
        place = "your game's schema" if item.custom_type in game_types() else "Properties > Scene > Bevy Custom Components"
        return f"{', '.join(unknown)} {'is not a field' if len(unknown) == 1 else 'are not fields'} of {item.custom_type}. Its fields are set in {place}"
    values = []
    for field in item.fields:
        if field.name not in data:
            continue
        value = convert_value(field.field_type, data[field.name])
        if value is None:
            return f"{field.name} needs a value of type {field.bl_rna.properties['field_type'].enum_items[field.field_type].name}"
        if field.field_type == "ENUM" and value not in variant_names(field.variants):
            return f"{field.name} needs one of {', '.join(variant_names(field.variants))}"
        values.append((field, value))
    for field, value in values:
        write_field(field, value)
    return None


def reset_fields(item, definition):
    if definition is not None:
        link_component(item, definition, keep_values=False)
        return
    for field in item.fields:
        for slot in FIELD_VALUES.values():
            field.property_unset(slot)


def custom_type_changed(self, context):
    if self.component_type == "CUSTOM":
        definition = find_definition(getattr(context, "scene", None), self.custom_type)
        if definition is not None:
            link_component(self, definition)
        else:
            unlink_component(self)
    touch_changed(self, context)


def field_changed(self, context):
    owner = self.id_data
    if isinstance(owner, bpy.types.Scene):
        apply_definitions(owner)
    else:
        touch_changed(self, context)


def definition_renamed(self, context):
    if not self.name.strip():
        return
    previous = self.linked_name
    self.linked_name = self.name
    scene = self.id_data
    if previous and previous != self.name and previous not in game_types():
        for _obj, item in list(custom_components(scene, previous)):
            if item.use_fields:
                item.custom_type = self.name
    apply_definitions(scene)


@persistent
def save_cleanup(_scene):
    for obj in bpy.data.objects:
        if obj.library is None and EXTRAS_KEY in obj:
            del obj[EXTRAS_KEY]


def bevy_view(view_matrix):
    location, rotation, _scale = (BEVY_AXES @ view_matrix.inverted()).decompose()
    return ",".join(f"{value:.6g}" for value in (*location, rotation.x, rotation.y, rotation.z, rotation.w))


def viewport_view(context):
    space = getattr(context, "space_data", None)
    if space is not None and space.type == "VIEW_3D" and space.region_3d is not None:
        return bevy_view(space.region_3d.view_matrix)
    screen = getattr(context, "screen", None)
    for area in screen.areas if screen is not None else ():
        if area.type == "VIEW_3D" and area.spaces.active.region_3d is not None:
            return bevy_view(area.spaces.active.region_3d.view_matrix)
    return None


def image_to_png(data, mime_type):
    with tempfile.TemporaryDirectory(prefix="bevy_components_") as directory:
        source = Path(directory) / f"source{mimetypes.guess_extension(mime_type) or '.image'}"
        target = Path(directory) / "image.png"
        source.write_bytes(data)
        image = bpy.data.images.load(str(source), check_existing=False)
        try:
            image.filepath_raw = str(target)
            image.file_format = "PNG"
            image.save()
        finally:
            bpy.data.images.remove(image)
        return target.read_bytes()


class glTF2ExportUserExtension:
    def gather_tree_filter_tag_hook(self, vtree, _export_settings):
        filter_tree(vtree)

    def gather_node_hook(self, gltf2_node, blender_object, export_settings):
        _remove_extra(gltf2_node, "bevy_component_data")
        _remove_extra(gltf2_node, "bevy_physics")
        _remove_extra(gltf2_node, "bevy_object")
        _remove_extra(gltf2_node, "bevy_prefab")
        _light_extras(gltf2_node)
        reference = instance_node(gltf2_node, blender_object)
        _component_extras(gltf2_node, blender_object, export_settings, [reference] if reference is not None else [])
        if fog_source(blender_object) is not None:
            gltf2_node.mesh = None

    def gather_material_hook(self, gltf2_material, _blender_material, _export_settings):
        _remove_extra(gltf2_material, "bevy_fog")

    def gather_scene_hook(self, gltf2_scene, blender_scene, _export_settings):
        _remove_extra(gltf2_scene, "bevy_component_previews")
        _remove_extra(gltf2_scene, "bevy_component_definitions")
        _remove_extra(gltf2_scene, "bevy_collision_layers")
        _remove_extra(gltf2_scene, "bevy_bake_settings")
        _remove_extra(gltf2_scene, "bevy_glb_export")
        _remove_extra(gltf2_scene, "bevy_bsn_export")
        _remove_extra(gltf2_scene, "bevy_gltf_export_settings")
        _remove_extra(gltf2_scene, "bevy_component_overview")
        _remove_extra(gltf2_scene, "bevy_game")
        prefab_scene(gltf2_scene, blender_scene)
        world = getattr(blender_scene, "world", None)
        components = (scene_components(world) if world is not None and hasattr(world, "bevy_sky") else []) + physics_components(blender_scene)
        gltf2_scene.extras = {**(gltf2_scene.extras or {}), EXTRAS_KEY: serialize_scene(components, addon_version())}


def _component_extras(gltf2_node, obj, export_settings, extra):
    if obj is None or not hasattr(obj, "bevy_component_data") or _skipped[0] is None and not export_settings.get("gltf_extras"):
        return
    with resolving():
        components = object_components(obj, export_directory() or os.path.dirname(export_settings.get("gltf_filepath", "")) or None, _skipped[0]) + extra
    if components:
        extras = gltf2_node.extras if isinstance(gltf2_node.extras, dict) else {}
        gltf2_node.extras = {**extras, EXTRAS_KEY: json.dumps({"version": SCHEMA_VERSION, "components": components}, separators=(",", ":"), ensure_ascii=False)}
    else:
        _remove_extra(gltf2_node, EXTRAS_KEY)


def _light_extras(gltf2_node):
    extension = gltf2_node.extensions.get("KHR_lights_punctual") if isinstance(gltf2_node.extensions, dict) else None
    light = getattr(extension, "extension", {}).get("light") if extension is not None else None
    data = getattr(light, "extension", None)
    extras = data.get("extras") if isinstance(data, dict) else None
    if isinstance(extras, dict):
        extras.pop("bevy_light", None)
        if not extras:
            data.pop("extras")


def _remove_extra(gltf2_element, key):
    if isinstance(gltf2_element.extras, dict):
        gltf2_element.extras.pop(key, None)
        if not gltf2_element.extras:
            gltf2_element.extras = None
