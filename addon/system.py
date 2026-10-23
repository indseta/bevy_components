import json
import mimetypes
import os
import tempfile
import time
import uuid
from pathlib import Path

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix

from .metadata import EXTRAS_KEY, FIELD_VALUES, SHADOW_DEFAULTS, WATTS_TO_LUMENS, ambient_light_component, convert_value, field_data, json_fields, light_intensity, light_of, relative_path, serialize_items, serialize_scene, sky_component, variant_names
from .schema import GameField, SchemaError, find_schema, parse_schema

MESH_TYPES = {"MESH", "CURVE", "SURFACE", "FONT"}
LAYER_COUNT = 32
PANEL_EXPANDED = True
PANEL_DRAWN_EXPANDED = True
SCHEMA_CHECK_INTERVAL = 1.0

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


def components_for(obj):
    if not hasattr(obj, "bevy_component_data"):
        return []
    return [item for item in obj.bevy_component_data.components if item.enabled and item.component_type]


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


def mesh_sources(obj, children, kind, instances=True):
    return [(source, matrix) for source, matrix in subtree(obj, children, lambda child: component_of(child, kind) is not None, instances) if has_faces(source)]


def export_settings(scene):
    if scene.bevy_bsn_export.rust_file.strip() and not scene.bevy_glb_export.filepath.strip():
        return scene.bevy_bsn_export
    return scene.bevy_glb_export


def exported(obj, options):
    if options.visible_only and (not obj.visible_get() or obj.hide_viewport or all(collection.hide_viewport for collection in obj.users_collection)):
        return False
    return not options.renderable_only or not (obj.hide_render or all(collection.hide_render for collection in obj.users_collection))


def exported_objects(context, options, selected=None):
    objects = context.selected_objects if (options.selected_only if selected is None else selected) else context.scene.objects
    return [obj for obj in objects if exported(obj, options)]


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


def sync_object(obj, directory=None):
    if not obj or not isinstance(obj, bpy.types.Object) or obj.library:
        return
    data = getattr(obj, "bevy_component_data", None)
    if not data:
        return
    items = components_for(obj)
    if items:
        try:
            obj[EXTRAS_KEY] = serialize_items(items, lambda path: scene_path(path, directory))
        except ValueError:
            obj.pop(EXTRAS_KEY, None)
    else:
        obj.pop(EXTRAS_KEY, None)


def component_index(obj, item):
    for index, other in enumerate(obj.bevy_component_data.components):
        if other == item:
            return index
    return -1


def copy_component(source, destination):
    for field in source.bl_rna.properties:
        if field.identifier in {"rna_type", "id_data"}:
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


def copy_to_object(source, destination, obj):
    copy_component(source, destination)
    for prop in ("joint_body1", "joint_body2"):
        if getattr(destination, prop) == source.id_data:
            setattr(destination, prop, obj)


def sync_changed(self, context):
    obj = getattr(self, "id_data", None)
    if isinstance(obj, bpy.types.Object):
        sync_object(obj)
        redraw_viewports()


def light_intensity_toggled(self, context):
    obj = getattr(self, "id_data", None)
    light = light_of(obj)
    if self.light_use_intensity and light is not None and not self.is_property_set("light_intensity"):
        self.light_intensity = light_intensity(light, obj)
    sync_changed(self, context)


def light_bias_toggled(self, context):
    light = light_of(getattr(self, "id_data", None))
    if self.light_use_bias and light is not None and light.type in SHADOW_DEFAULTS and not self.is_property_set("light_depth_bias"):
        depth, normal, near = SHADOW_DEFAULTS[light.type]
        self.light_depth_bias = depth
        self.light_normal_bias = normal
        if near is not None:
            self.light_near_clip = near
    sync_changed(self, context)


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


def game_schema(force=False):
    now = time.monotonic()
    if not force and _game_schema["checked"] is not None and now - _game_schema["checked"] < SCHEMA_CHECK_INTERVAL:
        return _game_schema
    _game_schema["checked"] = now
    setting = schema_setting()
    path = file_path(setting) if setting else find_schema(blend_directory())
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
    for obj in scene.objects:
        if obj.library:
            continue
        for item in obj.bevy_component_data.components:
            if item.component_type == "CUSTOM" and (type_path is None or item.custom_type == type_path):
                yield obj, item


def apply_definitions(scene):
    changed = set()
    for obj, item in list(custom_components(scene)):
        definition = find_definition(scene, item.custom_type)
        if definition is not None and link_component(item, definition):
            changed.add(obj)
    for obj in changed:
        sync_object(obj)
    redraw_viewports()


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
    sync_changed(self, context)


def field_changed(self, context):
    owner = self.id_data
    if isinstance(owner, bpy.types.Scene):
        apply_definitions(owner)
    else:
        sync_changed(self, context)


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
def save_sync(_scene):
    for obj in bpy.data.objects:
        sync_object(obj)


def asset_path(path):
    path = Path(path)
    folders = [parent for parent in path.parents if parent.name.lower() == "assets"]
    if not folders:
        return path.name, None
    root = next((folder for folder in folders if (folder.parent / "Cargo.toml").is_file()), folders[0])
    return path.relative_to(root).as_posix(), root


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
    def gather_node_hook(self, gltf2_node, _blender_object, _export_settings):
        _remove_extra(gltf2_node, "bevy_component_data")

    def gather_scene_hook(self, gltf2_scene, blender_scene, _export_settings):
        _remove_extra(gltf2_scene, "bevy_component_previews")
        _remove_extra(gltf2_scene, "bevy_component_definitions")
        _remove_extra(gltf2_scene, "bevy_collision_layers")
        _remove_extra(gltf2_scene, "bevy_bake_settings")
        _remove_extra(gltf2_scene, "bevy_glb_export")
        _remove_extra(gltf2_scene, "bevy_bsn_export")
        world = getattr(blender_scene, "world", None)
        components = scene_components(world) if world is not None and hasattr(world, "bevy_sky") else []
        if components:
            gltf2_scene.extras = {**(gltf2_scene.extras or {}), EXTRAS_KEY: serialize_scene(components)}


def _remove_extra(gltf2_element, key):
    if isinstance(gltf2_element.extras, dict):
        gltf2_element.extras.pop(key, None)
        if not gltf2_element.extras:
            gltf2_element.extras = None
