import json
import os
import tempfile
from pathlib import Path

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper

from .bake import BackgroundBake, bake_command, bake_hidden, bake_jobs, bake_summary, baked_sky, lighting_jobs, sky_job, unwrap_lightmap
from .export import EXPORT_LABEL, PROGRESS_INTERVAL, ExportCancelled, ExportError, SceneExport, again, blend_relative, cancel_exports, export_path, exports_world, finish_export, glb_file, recall, remember, remembered, running_export, scene_issues, start_export
from .files import snake_case
from .fingerprint import bake_record
from .geometry import fit_shape
from .gltf import LIMITS, ExportGLTF2_Base, changed
from .metadata import PRIMITIVE_SHAPES, infer_fields
from .play import VIEWER_COMMAND, VIEW_VARIABLE, GameProcess, PlayError, game_command
from .prefab import find_collection
from .preferences import draw_encoder_status
from .probe import FILE_KINDS
from .project import game_assets, game_folder, play_target
from .property import AUDIO_FORMATS, COMPONENT_FILTERS, COMPONENT_LABELS, COMPONENT_TYPES, EVENTS_KEY, LAYER_COUNT, ExportOptions
from .schema import short_name
from .system import OLDER_GLTF_SETTINGS, TEXT_COMPONENT, TEXT_OBJECT, accepts, apply_definitions, apply_game_types, asset_path, children_map, clipboard_text, component_of, component_text, copy_component, copy_to_object, custom_components, default_clip, export_options, exported_objects, field_slot, file_path, find_definition, game_schema, game_types, linked_component, mesh_points, new_identifier, paste_components, preset_file, read_components, redraw_properties, redraw_status_bars, redraw_viewports, reset_fields, scene_definition, sky_lights_scene, touch_object, unlink_component, viewport_view, write_component_text, write_field
from .validation import body_kind, check_objects, check_scene, count, describe, draw_issues, draw_message, issue_row, issue_summary

ACCEPTED_OBJECTS = {
    "LIGHT": "light",
    "LIGHTMAP": "mesh",
}
IDENTITY_PROPERTIES = {
    "CUSTOM": {"custom_type"},
    "SCENE_REFERENCE": {"scene_file"},
    "ANIMATION": {"animation_clip"},
}
PICKED_FILES = {
    "scene_file": "*.glb;*.gltf",
    "probe_file": "*.ktx2",
}
OUTPUT_TEXT = "Bevy Game Output"

_bakes = {}
_games = {}
_played = {}


def running_bake():
    return next(iter(_bakes), None)


def running_game():
    return next((task for task in _games if task.running), None)


def last_game():
    return _played.get("game")


def stop_games():
    for task, timer in _games.items():
        task.stop()
        task.wait(5)
        if timer is not None:
            bpy.context.window_manager.event_timer_remove(timer)
    _games.clear()


def stop_bakes():
    for task, (timer, directory) in _bakes.items():
        task.cancel()
        task.wait()
        bpy.context.window_manager.event_timer_remove(timer)
        directory.cleanup()
    _bakes.clear()


def _editable(context):
    return context.object is not None and context.object.library is None


def _components(context, index):
    if not _editable(context) or not 0 <= index < len(context.object.bevy_component_data.components):
        return None
    return context.object.bevy_component_data.components


def _active_definition(context):
    if context.scene is None:
        return None
    library = context.scene.bevy_component_definitions
    if not 0 <= library.active_index < len(library.definitions):
        return None
    return library.definitions[library.active_index]


def _active_field(context):
    definition = _active_definition(context)
    if definition is None or not 0 <= definition.active_field < len(definition.fields):
        return None
    return definition.fields[definition.active_field]


def _unique(base, taken, separator):
    name = base
    number = 2
    while name in taken:
        name = f"{base}{separator}{number}"
        number += 1
    return name


def _missing_uv_maps(jobs):
    return [job["object"] for job in jobs if job["kind"] == "LIGHTMAP" and not job["uv_map"]]


def _targets(context):
    targets = [obj for obj in context.selected_objects if obj.library is None]
    if _editable(context) and context.object not in targets:
        targets.append(context.object)
    return targets


def _paste(operator, context, components, source):
    targets = _targets(context)
    pasted = [paste_components(obj, components, context.scene) for obj in targets]
    redraw_viewports()
    if not any(pasted):
        operator.report({"WARNING"}, f"None of the components in {source} fit the selected objects")
        return {"CANCELLED"}
    operator.report({"INFO"}, f"Added {count(max(pasted), 'component')} from {source} to {count(sum(1 for number in pasted if number), 'object')}")
    return {"FINISHED"}


def _text_area(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "TEXT_EDITOR":
                return area
    if bpy.app.background or context.window is None or context.screen is None:
        return None
    source = max(context.screen.areas, key=lambda area: area.width * area.height)
    windows = set(context.window_manager.windows)
    with context.temp_override(window=context.window, area=source, region=next((region for region in source.regions if region.type == "WINDOW"), None)):
        bpy.ops.screen.area_dupli("INVOKE_DEFAULT")
    window = next((window for window in context.window_manager.windows if window not in windows), None)
    if window is None:
        return None
    area = window.screen.areas[0]
    area.type = "TEXT_EDITOR"
    return area


def _show_scene_properties(context):
    areas = [context.area] if context.area and context.area.type == "PROPERTIES" else [area for area in context.screen.areas if area.type == "PROPERTIES"] if context.screen else []
    for area in areas[:1]:
        area.spaces.active.context = "SCENE"


class BEVY_OT_add_component(bpy.types.Operator):
    bl_idname = "bevy_components.add"
    bl_label = "Add Component"
    bl_description = "Add a Bevy component to the active object"
    bl_options = {"REGISTER", "UNDO"}

    component_type: EnumProperty(name="Component", items=COMPONENT_TYPES)
    type_path: StringProperty(name="Type Path", description="Custom component type defined in Properties > Scene", options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _editable(context)

    @classmethod
    def description(cls, context, properties):
        return f"Add {properties.type_path} to the active object" if properties.type_path else cls.bl_description

    def execute(self, context):
        obj = context.object
        items = obj.bevy_component_data.components
        defined = self.component_type == "CUSTOM" and self.type_path
        if not accepts(obj, self.component_type):
            self.report({"WARNING"}, f"{COMPONENT_LABELS[self.component_type][0]} only works on {ACCEPTED_OBJECTS[self.component_type]} objects")
            return {"CANCELLED"}
        if self.component_type != "CUSTOM" and any(existing.component_type == self.component_type for existing in items):
            self.report({"WARNING"}, f"{COMPONENT_LABELS[self.component_type][0]} is already on {obj.name}")
            return {"CANCELLED"}
        if defined and any(existing.component_type == "CUSTOM" and existing.custom_type == self.type_path for existing in items):
            self.report({"WARNING"}, f"{self.type_path} is already on {obj.name}")
            return {"CANCELLED"}
        item = items.add()
        item.component_type = self.component_type
        if defined:
            item.custom_type = self.type_path
        if self.component_type == "JOINT" and body_kind(obj) is not None:
            item.joint_body2 = obj
        if self.component_type == "ANIMATION":
            item.animation_clip = default_clip(obj)
        touch_object(obj)
        redraw_viewports()
        return {"FINISHED"}


class BEVY_OT_remove_component(bpy.types.Operator):
    bl_idname = "bevy_components.remove"
    bl_label = "Remove Component"
    bl_description = "Remove the component from the active object"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="Index")

    @classmethod
    def poll(cls, context):
        return _editable(context)

    def execute(self, context):
        items = _components(context, self.index)
        if items is None:
            return {"CANCELLED"}
        items.remove(self.index)
        touch_object(context.object)
        redraw_viewports()
        return {"FINISHED"}


class BEVY_OT_duplicate_component(bpy.types.Operator):
    bl_idname = "bevy_components.duplicate"
    bl_label = "Duplicate Component"
    bl_description = "Add a copy of the custom component below it"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="Index")

    @classmethod
    def poll(cls, context):
        return _editable(context)

    def execute(self, context):
        items = _components(context, self.index)
        if items is None:
            return {"CANCELLED"}
        if items[self.index].component_type != "CUSTOM":
            self.report({"WARNING"}, "Only custom components can be added more than once")
            return {"CANCELLED"}
        duplicate = items.add()
        copy_component(items[self.index], duplicate)
        items.move(len(items) - 1, self.index + 1)
        touch_object(context.object)
        redraw_viewports()
        return {"FINISHED"}


class BEVY_OT_copy_component_to_selected(bpy.types.Operator):
    bl_idname = "bevy_components.copy_component_to_selected"
    bl_label = "Copy Component to Selected"
    bl_description = "Copy the component to the other selected objects, replacing one of the same type"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="Index")

    @classmethod
    def poll(cls, context):
        return _editable(context) and len(context.selected_objects) > 1

    def execute(self, context):
        items = _components(context, self.index)
        if items is None:
            return {"CANCELLED"}
        source = items[self.index]
        count = 0
        for obj in context.selected_objects:
            if obj == context.object or obj.library or not accepts(obj, source.component_type):
                continue
            destination = obj.bevy_component_data.components
            target = next((item for item in destination if item.component_type == source.component_type and (source.component_type != "CUSTOM" or item.custom_type == source.custom_type)), None)
            copy_to_object(source, destination.add() if target is None else target, obj)
            touch_object(obj)
            count += 1
        redraw_viewports()
        self.report({"INFO"}, f"Copied {COMPONENT_LABELS[source.component_type][0]} to {count} objects")
        return {"FINISHED"}


class BEVY_OT_reset_component(bpy.types.Operator):
    bl_idname = "bevy_components.reset"
    bl_label = "Reset Component"
    bl_description = "Reset the component's settings to their defaults"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="Index")

    @classmethod
    def poll(cls, context):
        return _editable(context)

    def execute(self, context):
        items = _components(context, self.index)
        if items is None:
            return {"CANCELLED"}
        item = items[self.index]
        typed = item.component_type == "CUSTOM" and item.use_fields
        kept = {"rna_type", "name", "component_type", "enabled", "show_expanded", "show_layers", "show_velocity", "show_dynamics", "show_shadows", "text_link"} | IDENTITY_PROPERTIES.get(item.component_type, set()) | ({"use_fields"} if typed else set())
        for field in item.bl_rna.properties:
            if field.identifier not in kept and field.type != "COLLECTION" and not field.is_readonly:
                item.property_unset(field.identifier)
        item.pop(EVENTS_KEY, None)
        if typed:
            reset_fields(item, find_definition(context.scene, item.custom_type))
        touch_object(context.object)
        redraw_viewports()
        return {"FINISHED"}


class BEVY_OT_move_component(bpy.types.Operator):
    bl_idname = "bevy_components.move"
    bl_label = "Move Component"
    bl_description = "Change the component's place in the list"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="Index")
    direction: EnumProperty(name="Direction", items=[
        ("UP", "Up", "Move the component up one place"),
        ("DOWN", "Down", "Move the component down one place"),
        ("FIRST", "First", "Move the component to the top"),
        ("LAST", "Last", "Move the component to the bottom"),
    ])

    @classmethod
    def poll(cls, context):
        return _editable(context)

    def execute(self, context):
        items = _components(context, self.index)
        if items is None:
            return {"CANCELLED"}
        target = {"UP": self.index - 1, "DOWN": self.index + 1, "FIRST": 0, "LAST": len(items) - 1}[self.direction]
        target = max(0, min(target, len(items) - 1))
        if target == self.index:
            return {"CANCELLED"}
        items.move(self.index, target)
        touch_object(context.object)
        return {"FINISHED"}


class BEVY_OT_lod_preset(bpy.types.Operator):
    bl_idname = "bevy_components.lod_preset"
    bl_label = "Apply LOD Preset"
    bl_description = "Set fade distances that crossfade with the neighbouring levels of detail"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="Index")
    preset: EnumProperty(name="Preset", items=[
        ("NEAR", "LOD0", "Visible from 0 to 25 m"),
        ("MID", "LOD1", "Visible from 20 to 85 m"),
        ("FAR", "LOD2", "Visible from 80 to 260 m"),
    ])

    @classmethod
    def poll(cls, context):
        return _editable(context)

    def execute(self, context):
        items = _components(context, self.index)
        if items is None or items[self.index].component_type != "VISIBILITY_RANGE":
            return {"CANCELLED"}
        item = items[self.index]
        fade_in_start, fade_in_end, fade_out_start, fade_out_end = {
            "NEAR": (0.0, 0.0, 20.0, 25.0),
            "MID": (20.0, 25.0, 80.0, 85.0),
            "FAR": (80.0, 85.0, 250.0, 260.0),
        }[self.preset]
        item.fade_in_start = fade_in_start
        item.fade_in_end = fade_in_end
        item.fade_out_start = fade_out_start
        item.fade_out_end = fade_out_end
        touch_object(context.object)
        redraw_viewports()
        return {"FINISHED"}


class BEVY_OT_set_collision_layers(bpy.types.Operator):
    bl_idname = "bevy_components.set_collision_layers"
    bl_label = "Set Collision Layers"
    bl_description = "Turn every collision layer in the row on or off"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="Index")
    layers: EnumProperty(name="Layers", items=[
        ("MEMBERSHIPS", "Belongs To", "Collision layers the collider is on"),
        ("FILTERS", "Collides With", "Collision layers the collider touches"),
    ])
    enable: BoolProperty(name="Enable", default=True)

    @classmethod
    def poll(cls, context):
        return _editable(context)

    def execute(self, context):
        items = _components(context, self.index)
        if items is None or items[self.index].component_type != "COLLIDER":
            return {"CANCELLED"}
        setattr(items[self.index], f"collider_{self.layers.lower()}", (self.enable,) * LAYER_COUNT)
        touch_object(context.object)
        redraw_viewports()
        return {"FINISHED"}


class BEVY_OT_fit_collider(bpy.types.Operator):
    bl_idname = "bevy_components.fit_collider"
    bl_label = "Fit to Mesh"
    bl_description = "Set the collider's size and offset from the bounds of the meshes on and under the object"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="Index")

    @classmethod
    def poll(cls, context):
        return _editable(context)

    def execute(self, context):
        items = _components(context, self.index)
        if items is None or items[self.index].component_type != "COLLIDER" or items[self.index].collider_shape not in PRIMITIVE_SHAPES:
            return {"CANCELLED"}
        item = items[self.index]
        points = mesh_points(context.object, children_map(context.scene.objects), context.evaluated_depsgraph_get())
        if not points:
            self.report({"WARNING"}, "No mesh on this object or under it to fit")
            return {"CANCELLED"}
        for key, value in fit_shape(item.collider_shape, points).items():
            setattr(item, f"collider_{key}", value)
        touch_object(context.object)
        redraw_viewports()
        return {"FINISHED"}


class BEVY_OT_pick_sound(bpy.types.Operator):
    bl_idname = "bevy_components.pick_sound"
    bl_label = "Pick Sound"
    bl_description = "Pick a sound file inside your game's assets folder"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="Index", options={"HIDDEN", "SKIP_SAVE"})
    filepath: StringProperty(name="File Path", subtype="FILE_PATH", options={"SKIP_SAVE"})
    filter_glob: StringProperty(default=";".join(f"*{extension}" for extension in AUDIO_FORMATS), options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _editable(context)

    def invoke(self, context, event):
        items = _components(context, self.index)
        if items is None or items[self.index].component_type != "AUDIO_PLAYER":
            return {"CANCELLED"}
        assets = game_assets(context)
        if assets is not None and not self.filepath:
            current = items[self.index].audio_path.strip()
            self.filepath = str(assets / current) if current and (assets / current).is_file() else _folder_path(assets / "sounds" if (assets / "sounds").is_dir() else assets)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        items = _components(context, self.index)
        if items is None or items[self.index].component_type != "AUDIO_PLAYER" or not self.filepath:
            return {"CANCELLED"}
        path, root = asset_path(bpy.path.abspath(self.filepath))
        if root is None:
            self.report({"WARNING"}, f"{path} is not inside an assets folder, so only its name was used")
        items[self.index].audio_path = path
        return {"FINISHED"}


class BEVY_OT_pick_file(bpy.types.Operator):
    bl_idname = "bevy_components.pick_file"
    bl_label = "Pick File"
    bl_description = "Pick the file, starting in the game's assets folder when a game project is set"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="Index", options={"HIDDEN", "SKIP_SAVE"})
    target: EnumProperty(name="Target", items=[
        ("scene_file", "Scene File", "The glTF file of a Scene Reference"),
        ("probe_file", "Probe File", "The KTX2 file of a Reflection Probe, Irradiance Volume or Lightmap"),
    ], options={"HIDDEN", "SKIP_SAVE"})
    filepath: StringProperty(name="File Path", subtype="FILE_PATH", options={"SKIP_SAVE"})
    filter_glob: StringProperty(default="*.glb;*.gltf;*.ktx2", options={"HIDDEN", "SKIP_SAVE"})
    relative_path: BoolProperty(name="Relative Path", description="Store the path relative to the .blend file", default=True)

    @classmethod
    def poll(cls, context):
        return _editable(context)

    def _item(self, context):
        items = _components(context, self.index)
        if items is None:
            return None
        item = items[self.index]
        accepted = item.component_type == "SCENE_REFERENCE" if self.target == "scene_file" else item.component_type in FILE_KINDS
        return item if accepted else None

    def invoke(self, context, event):
        item = self._item(context)
        if item is None:
            return {"CANCELLED"}
        self.filter_glob = PICKED_FILES[self.target]
        current = getattr(item, self.target).strip()
        assets = game_assets(context)
        if current:
            self.filepath = str(file_path(current))
        elif assets is not None and assets.is_dir():
            self.filepath = _folder_path(assets)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        item = self._item(context)
        if item is None or not self.filepath:
            return {"CANCELLED"}
        setattr(item, self.target, blend_relative(Path(bpy.path.abspath(self.filepath))) if self.relative_path else bpy.path.abspath(self.filepath))
        return {"FINISHED"}


class BEVY_OT_define_fields(bpy.types.Operator):
    bl_idname = "bevy_components.define_fields"
    bl_label = "Define Fields"
    bl_description = "Edit the fields of this custom component type in Properties > Scene, defining them from its data the first time"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="Index")

    @classmethod
    def poll(cls, context):
        return _editable(context) and context.scene is not None

    def execute(self, context):
        items = _components(context, self.index)
        if items is None or items[self.index].component_type != "CUSTOM":
            return {"CANCELLED"}
        item = items[self.index]
        if not item.custom_type.strip():
            self.report({"WARNING"}, "Give the component a type path first")
            return {"CANCELLED"}
        if item.custom_type in game_types():
            self.report({"WARNING"}, f"{item.custom_type} gets its fields from your game")
            return {"CANCELLED"}
        library = context.scene.bevy_component_definitions
        definition = scene_definition(context.scene, item.custom_type)
        if definition is None:
            if item.use_fields:
                fields = [(field.identifier, field.name, field.field_type, field.variants, field.rust_type, field_slot(field)) for field in item.fields]
            else:
                try:
                    fields = [("", name, kind, "", "", value) for name, kind, value in infer_fields(json.loads(item.custom_json))]
                except (json.JSONDecodeError, ValueError) as error:
                    self.report({"ERROR"}, f"Cannot define fields for {item.custom_type}: {error}")
                    return {"CANCELLED"}
            definition = library.definitions.add()
            for identifier, name, kind, variants, rust_type, value in fields:
                field = definition.fields.add()
                field.identifier = identifier or new_identifier()
                field.name = name
                field.field_type = kind
                field.variants = variants
                field.rust_type = rust_type
                write_field(field, value)
            definition.name = item.custom_type
        library.active_index = list(library.definitions).index(definition)
        apply_definitions(context.scene)
        _show_scene_properties(context)
        return {"FINISHED"}


class BEVY_OT_reload_schema(bpy.types.Operator):
    bl_idname = "bevy_components.reload_schema"
    bl_label = "Reload Game Components"
    bl_description = "Read the components your game wrote to its schema file again, and update the objects that use them"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        schema = game_schema(force=True)
        apply_game_types()
        if schema["error"]:
            self.report({"WARNING"}, schema["error"])
        elif schema["path"] is None:
            self.report({"INFO"}, "No game components found. Add BlenderSchemaPlugin to your game and run it once")
        else:
            self.report({"INFO"}, f"Read {len(schema['types'])} game components from {schema['path'].name}")
        return {"FINISHED"}


class BEVY_OT_definition_add(bpy.types.Operator):
    bl_idname = "bevy_components.definition_add"
    bl_label = "Add Custom Component Type"
    bl_description = "Define a custom component type and its fields, to add to objects from Add Component"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        library = context.scene.bevy_component_definitions
        active = _active_definition(context)
        crate = (active.name.rpartition("::")[0] if active is not None else "") or "my_game"
        taken = {definition.name for definition in library.definitions} | {item.custom_type for _obj, item in custom_components(context.scene)}
        definition = library.definitions.add()
        definition.name = _unique(f"{crate}::MyComponent", taken, "")
        library.active_index = len(library.definitions) - 1
        return {"FINISHED"}


class BEVY_OT_definition_remove(bpy.types.Operator):
    bl_idname = "bevy_components.definition_remove"
    bl_label = "Remove Custom Component Type"
    bl_description = "Remove the definition. Objects keep the component, edited as JSON with the same values"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_definition(context) is not None

    def execute(self, context):
        scene = context.scene
        library = scene.bevy_component_definitions
        type_path = library.definitions[library.active_index].name
        library.definitions.remove(library.active_index)
        library.active_index = min(library.active_index, len(library.definitions) - 1)
        if find_definition(scene, type_path) is None:
            for obj, item in list(custom_components(scene, type_path)):
                if unlink_component(item):
                    touch_object(obj)
        apply_definitions(scene)
        return {"FINISHED"}


class BEVY_OT_field_add(bpy.types.Operator):
    bl_idname = "bevy_components.field_add"
    bl_label = "Add Field"
    bl_description = "Add a field to the custom component type and to every object that has it"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_definition(context) is not None

    def execute(self, context):
        definition = _active_definition(context)
        taken = {field.name for field in definition.fields}
        field = definition.fields.add()
        field.identifier = new_identifier()
        field.name = _unique("field", taken, "_")
        definition.active_field = len(definition.fields) - 1
        apply_definitions(context.scene)
        return {"FINISHED"}


class BEVY_OT_field_remove(bpy.types.Operator):
    bl_idname = "bevy_components.field_remove"
    bl_label = "Remove Field"
    bl_description = "Remove the field from the custom component type and from every object that has it"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_field(context) is not None

    def execute(self, context):
        definition = _active_definition(context)
        definition.fields.remove(definition.active_field)
        definition.active_field = min(definition.active_field, len(definition.fields) - 1)
        apply_definitions(context.scene)
        return {"FINISHED"}


class BEVY_OT_field_move(bpy.types.Operator):
    bl_idname = "bevy_components.field_move"
    bl_label = "Move Field"
    bl_description = "Change the field's place in the custom component type"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(name="Direction", items=[
        ("UP", "Up", "Move the field up one place"),
        ("DOWN", "Down", "Move the field down one place"),
    ])

    @classmethod
    def poll(cls, context):
        return _active_field(context) is not None

    def execute(self, context):
        definition = _active_definition(context)
        target = definition.active_field + (-1 if self.direction == "UP" else 1)
        if not 0 <= target < len(definition.fields):
            return {"CANCELLED"}
        definition.fields.move(definition.active_field, target)
        definition.active_field = target
        apply_definitions(context.scene)
        return {"FINISHED"}


class BEVY_OT_copy_to_selected(bpy.types.Operator):
    bl_idname = "bevy_components.copy_to_selected"
    bl_label = "Copy Components to Selected"
    bl_description = "Replace the components of the other selected objects with the active object's components"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and len(context.selected_objects) > 1

    def execute(self, context):
        source = context.object
        count = 0
        for obj in context.selected_objects:
            if obj == source or obj.library:
                continue
            destination = obj.bevy_component_data.components
            destination.clear()
            for item in source.bevy_component_data.components:
                if accepts(obj, item.component_type):
                    copy_to_object(item, destination.add(), obj)
            touch_object(obj)
            count += 1
        redraw_viewports()
        self.report({"INFO"}, f"Copied components to {count} objects")
        return {"FINISHED"}


class BEVY_OT_copy_component(bpy.types.Operator):
    bl_idname = "bevy_components.copy_component"
    bl_label = "Copy Component"
    bl_description = "Copy the component to the clipboard, to paste it onto objects in any .blend file"

    index: IntProperty(name="Index")

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def execute(self, context):
        items = context.object.bevy_component_data.components
        if not 0 <= self.index < len(items) or not items[self.index].component_type:
            return {"CANCELLED"}
        context.window_manager.clipboard = clipboard_text(context.object, [items[self.index]])
        self.report({"INFO"}, f"Copied {COMPONENT_LABELS[items[self.index].component_type][0]}")
        return {"FINISHED"}


class BEVY_OT_copy_components(bpy.types.Operator):
    bl_idname = "bevy_components.copy_components"
    bl_label = "Copy Components"
    bl_description = "Copy the active object's components to the clipboard, to paste them onto objects in any .blend file"

    @classmethod
    def poll(cls, context):
        return context.object is not None and any(item.component_type for item in context.object.bevy_component_data.components)

    def execute(self, context):
        items = [item for item in context.object.bevy_component_data.components if item.component_type]
        context.window_manager.clipboard = clipboard_text(context.object, items)
        self.report({"INFO"}, f"Copied {count(len(items), 'component')}")
        return {"FINISHED"}


class BEVY_OT_paste_components(bpy.types.Operator):
    bl_idname = "bevy_components.paste_components"
    bl_label = "Paste Components"
    bl_description = "Add the components on the clipboard to the selected objects, replacing ones of the same type"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_targets(context))

    def execute(self, context):
        components = read_components(context.window_manager.clipboard)
        if not components:
            self.report({"WARNING"}, "The clipboard holds no Bevy components. Copy some with Copy Components first")
            return {"CANCELLED"}
        return _paste(self, context, components, "the clipboard")


class BEVY_OT_save_preset(bpy.types.Operator):
    bl_idname = "bevy_components.save_preset"
    bl_label = "Save Components as Preset"
    bl_description = "Save the active object's components as a preset that every .blend file lists under Add Component > Presets"

    name: StringProperty(name="Name", description="Name of the preset. Saving under the name of an existing preset replaces it", default="My Preset")

    @classmethod
    def poll(cls, context):
        if context.object is None or not any(item.component_type for item in context.object.bevy_component_data.components):
            cls.poll_message_set("The active object has no components to save")
            return False
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, title="Save Components as Preset", confirm_text="Save")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "name")
        if self.name.strip() and preset_file(self.name).is_file():
            draw_message(layout, "Replaces the preset of this name", icon="INFO")

    def execute(self, context):
        if not self.name.strip():
            self.report({"ERROR"}, "Give the preset a name")
            return {"CANCELLED"}
        obj = context.object
        path = preset_file(self.name)
        try:
            path.write_text(clipboard_text(obj, obj.bevy_component_data.components, name=self.name.strip(), references=False), encoding="utf-8")
        except OSError as error:
            self.report({"ERROR"}, f"Could not save the preset: {error.strerror or error}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Saved preset {self.name.strip()} to {path}")
        return {"FINISHED"}


class BEVY_OT_apply_preset(bpy.types.Operator):
    bl_idname = "bevy_components.apply_preset"
    bl_label = "Apply Preset"
    bl_description = "Add the preset's components to the selected objects, replacing ones of the same type"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(name="Preset", subtype="FILE_PATH", options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(_targets(context))

    def execute(self, context):
        path = Path(self.filepath)
        try:
            components = read_components(path.read_text(encoding="utf-8"))
        except OSError as error:
            self.report({"ERROR"}, f"Could not read the preset: {error.strerror or error}")
            return {"CANCELLED"}
        if not components:
            self.report({"ERROR"}, f"{path.name} is not a Bevy Components preset")
            return {"CANCELLED"}
        return _paste(self, context, components, f"preset {bpy.path.display_name(path.stem)}")


class BEVY_OT_remove_preset(bpy.types.Operator):
    bl_idname = "bevy_components.remove_preset"
    bl_label = "Remove Preset"
    bl_description = "Delete the preset file, for every .blend file"

    filepath: StringProperty(name="Preset", subtype="FILE_PATH", options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event, title="Remove Preset", message=f"Delete {Path(self.filepath).name}?", confirm_text="Remove", icon="WARNING")

    def execute(self, context):
        try:
            Path(self.filepath).unlink()
        except OSError as error:
            self.report({"ERROR"}, f"Could not remove the preset: {error.strerror or error}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Removed preset {Path(self.filepath).name}")
        return {"FINISHED"}


class BEVY_OT_edit_as_text(bpy.types.Operator):
    bl_idname = "bevy_components.edit_as_text"
    bl_label = "Edit as Text"
    bl_description = "Open the component's data as JSON in a Text Editor, then write it back with Apply to Component in its header"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="Index")

    @classmethod
    def poll(cls, context):
        return _editable(context)

    def execute(self, context):
        items = _components(context, self.index)
        if items is None or items[self.index].component_type != "CUSTOM":
            return {"CANCELLED"}
        obj = context.object
        item = items[self.index]
        if not item.text_link or any(other.text_link == item.text_link for other in items if other != item):
            item.text_link = new_identifier()
        text = next((text for text in bpy.data.texts if text.get(TEXT_OBJECT) == obj and text.get(TEXT_COMPONENT) == item.text_link), None)
        if text is None:
            text = bpy.data.texts.new(f"{obj.name} {short_name(item.custom_type) or 'Component'}.json")
            text[TEXT_OBJECT] = obj
            text[TEXT_COMPONENT] = item.text_link
        text.from_string(component_text(item))
        text.cursor_set(0)
        area = _text_area(context)
        if area is None:
            self.report({"INFO"}, f"Opened {text.name}, show it in a Text Editor")
            return {"FINISHED"}
        area.spaces.active.text = text
        area.spaces.active.top = 0
        return {"FINISHED"}


class BEVY_OT_apply_text(bpy.types.Operator):
    bl_idname = "bevy_components.apply_text"
    bl_label = "Apply to Component"
    bl_description = "Write this JSON back into the custom component it was opened from"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        text = getattr(context.space_data, "text", None) if context.space_data is not None else None
        return text is not None and TEXT_COMPONENT in text

    def execute(self, context):
        text = context.space_data.text
        obj, item = linked_component(text)
        if item is None:
            self.report({"ERROR"}, f"The component {text.name} was opened from is gone")
            return {"CANCELLED"}
        if obj.library is not None:
            self.report({"ERROR"}, f"{obj.name} is linked from another file")
            return {"CANCELLED"}
        error = write_component_text(item, text.as_string())
        if error is not None:
            self.report({"ERROR"}, f"Cannot apply {text.name}: {error}")
            return {"CANCELLED"}
        touch_object(obj)
        redraw_viewports()
        redraw_properties()
        self.report({"INFO"}, f"Applied {text.name} to {obj.name}")
        return {"FINISHED"}


class BEVY_OT_select_by_component(bpy.types.Operator):
    bl_idname = "bevy_components.select_by_component"
    bl_label = "Select by Bevy Component"
    bl_description = "Select the visible objects that have a Bevy component of this type"
    bl_options = {"REGISTER", "UNDO"}

    component_type: EnumProperty(name="Component", items=COMPONENT_FILTERS)
    type_path: StringProperty(name="Type Path", description="Only custom components with this type path", options={"SKIP_SAVE"})
    extend: BoolProperty(name="Extend", description="Add to the selection instead of replacing it", default=False, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.view_layer is not None and context.mode == "OBJECT"

    def execute(self, context):
        found = [obj for obj in context.view_layer.objects if obj.visible_get() and not obj.hide_select and self._matches(obj)]
        name = self.type_path or COMPONENT_LABELS.get(self.component_type, ("Bevy components",))[0]
        if not found:
            self.report({"INFO"}, f"No visible objects have {name}")
            return {"CANCELLED"}
        if not self.extend:
            for obj in context.selected_objects:
                obj.select_set(False)
        for obj in found:
            obj.select_set(True)
        if context.view_layer.objects.active not in found:
            context.view_layer.objects.active = found[0]
        self.report({"INFO"}, f"Selected {count(len(found), 'object')} with {name}")
        return {"FINISHED"}

    def _matches(self, obj):
        items = obj.bevy_component_data.components
        if self.component_type == "ALL":
            return len(items) > 0
        return any(item.component_type == self.component_type and (not self.type_path or item.custom_type == self.type_path) for item in items)


class BEVY_OT_select_object(bpy.types.Operator):
    bl_idname = "bevy_components.select_object"
    bl_label = "Select Object"
    bl_description = "Select the object and make it active"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(name="Object")

    @classmethod
    def poll(cls, context):
        return context.view_layer is not None

    def execute(self, context):
        obj = context.view_layer.objects.get(self.name)
        if obj is None:
            self.report({"WARNING"}, f"{self.name} is not in the current view layer")
            return {"CANCELLED"}
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


class BEVY_OT_validate(bpy.types.Operator):
    bl_idname = "bevy_components.validate"
    bl_label = "Validate Components"
    bl_description = "Check every object for problems that block export or that make the scene behave differently in Bevy"

    def execute(self, context):
        settings = export_options(context.scene)
        objects = list(exported_objects(context, settings, limited=False))
        issues = check_objects(objects, modifiers=settings.export_apply) + check_scene(objects)
        for issue in issues:
            print("Bevy Components:", describe(issue))
        if not issues:
            self.report({"INFO"}, "All Bevy components are valid")
            return {"FINISHED"}
        if context.window is not None and not bpy.app.background:
            rows = [(issue.level, issue.obj.name, issue.message) for issue in issues]
            context.window_manager.popup_menu(lambda menu, _context: draw_issues(menu.layout, rows, 20, "in the system console", select=True), title=f"Bevy Components: {issue_summary(issues)}", icon="CANCEL" if any(level == "ERROR" for level, _name, _message in rows) else "ERROR")
        errors = [issue for issue in issues if issue.level == "ERROR"]
        if errors:
            self.report({"ERROR"}, f"{count(len(errors), 'problem')} {'blocks' if len(errors) == 1 else 'block'} export: {describe(errors[0])}")
            return {"CANCELLED"}
        self.report({"WARNING"}, f"{count(len(issues), 'warning')}: {describe(issues[0])}")
        return {"FINISHED"}


class BEVY_OT_cancel_export(bpy.types.Operator):
    bl_idname = "bevy_components.cancel_export"
    bl_label = "Cancel Export"
    bl_description = "Stop compressing textures and keep the previous file"

    @classmethod
    def poll(cls, context):
        return running_export() is not None

    def execute(self, context):
        cancel_exports()
        redraw_status_bars()
        return {"FINISHED"}


def _export_key(operator):
    return (operator.filepath, operator.collection, operator.export_animations, operator.export_apply, *(getattr(operator, name) for name in LIMITS))


def _draw_compression(operator, layout, context):
    header, body = layout.panel("BEVY_export_texture_compression")
    header.label(text="Texture Compression")
    if body:
        body.prop(operator, "texture_compression", text="Mode")
        if operator.texture_compression in {"ETC1S", "AUTOMATIC"}:
            column = body.column(align=True)
            column.prop(operator, "etc1s_quality")
            column.prop(operator, "etc1s_effort", text="Effort")
        if operator.texture_compression in {"UASTC", "AUTOMATIC"}:
            column = body.column(align=True)
            column.prop(operator, "uastc_quality")
            column.prop(operator, "uastc_zstd", text="Supercompression")
        if operator.texture_compression != "DISABLED":
            draw_encoder_status(body, context)


def _draw_checks(operator, layout, context, key, find):
    checks = getattr(operator, "_checks", None)
    if checks is None or checks[0] != key:
        checks = (key, find())
        try:
            operator._checks = checks
        except AttributeError:
            pass
    issues = checks[1]
    header, body = layout.panel("BEVY_export_checks")
    header.label(text="Checks")
    if issues:
        header.label(text=issue_summary(issues), icon="CANCEL" if any(issue.level == "ERROR" for issue in issues) else "ERROR")
    if body:
        if issues:
            draw_issues(body, [issue_row(issue) for issue in issues], 6, "in Validate All Objects", width=context.region.width if context.region else 300)
        else:
            body.label(text="No problems found", icon="CHECKMARK")


def _draw_bevy(operator, layout, context):
    collection = _drawn_collection(operator, context)
    header, body = layout.panel("BEVY_export_bevy")
    header.label(text="Bevy")
    if body:
        if collection is None:
            body.prop(operator, "export_on_save")
        _draw_compression(operator, body, context)
        _draw_checks(operator, body, context, (*_export_key(operator), collection), lambda: scene_issues(operator, _exported_objects(operator, context, collection), export_path(operator.filepath), world=exports_world(operator, collection)))


def _drawn_collection(operator, context):
    if operator.collection:
        return find_collection(operator.collection)
    if getattr(context.space_data, "type", None) == "PROPERTIES":
        return getattr(context, "collection", None)
    return None


def _exported_objects(operator, context, collection=None):
    return list(collection.all_objects) if collection is not None else exported_objects(context, operator)


def _folder_path(path):
    return os.path.join(str(path), "")


def _game_default(context, extension):
    folder = game_folder(context)
    if folder is None or context.scene is None:
        return None
    name = snake_case(context.scene.name) or "scene"
    levels = folder / "assets" / "levels"
    try:
        levels.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return levels / f"{name}{extension}"


def _report_all(operator, messages):
    for kinds, message in messages:
        operator.report(kinds, message)


class BEVY_OT_export_gltf(bpy.types.Operator, ExportGLTF2_Base, ExportHelper, ExportOptions):
    bl_idname = "export_scene.bevy_gltf"
    bl_label = "Export Bevy glTF"
    bl_description = "Export the scene as a GLB with the options of Blender's glTF export, plus the objects' Bevy components, the prefabs it uses and compressed textures"

    filename_ext = ".glb"
    filter_glob: StringProperty(default="*.glb", options={"HIDDEN"})
    export_format: EnumProperty(name="Format", description="Bevy exports write GLB files", items=(("GLB", "glTF Binary (.glb)", "One file with the meshes, textures and Bevy components packed in"),), default="GLB")
    export_extras: changed("export_extras", default=True)
    export_apply: changed("export_apply", default=True)
    export_lights: changed("export_lights", default=True)
    export_anim_slide_to_zero: changed("export_anim_slide_to_zero", default=True)
    use_active_scene: changed("use_active_scene", default=True)
    will_save_settings: changed("will_save_settings", description="Remember the file and these settings, so this dialog opens with them and Export Again, Export on Save and Play write the same file. Leave it off for a one-off export", default=True, options={"SKIP_SAVE"})
    again: BoolProperty(name="Export Again", description="Export to the file the last export wrote, with the settings it used, without the file dialog", default=False, options={"HIDDEN", "SKIP_SAVE"})

    _interactive = False
    _job = None
    _shown = None

    @classmethod
    def poll(cls, context):
        if "io_scene_gltf2" not in context.preferences.addons:
            cls.poll_message_set("Enable Blender's glTF 2.0 add-on to export")
            return False
        if running_export() is not None:
            cls.poll_message_set("A Bevy glTF export is still compressing textures")
            return False
        return context.scene is not None

    @classmethod
    def description(cls, context, properties):
        if properties.collection:
            return f"Export {properties.collection} to {Path(properties.filepath).name or 'its file'}, with the prefabs inside it, using {'the scene' if properties.again else 'these'} export settings"
        if not properties.again:
            return cls.bl_description
        path = remembered(context.scene)
        if not path:
            return f"Export the scene once with File > Export > {EXPORT_LABEL}, then export it again here with one click"
        return f"Export the scene again to {path} with the settings the last export used, without the file dialog"

    def draw(self, context):
        ExportGLTF2_Base.draw(self, context)
        _draw_bevy(self, self.layout, context)

    def invoke(self, context, event):
        self._interactive = True
        if self.again or self.collection:
            return self.execute(context)
        if not self.properties.is_property_set("filepath"):
            if remembered(context.scene):
                recall(self, context.scene)
            else:
                if OLDER_GLTF_SETTINGS in context.scene:
                    recall(self, context.scene, filepath=False)
                if (default := _game_default(context, self.filename_ext)) is not None:
                    self.filepath = str(default)
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        collection = find_collection(self.collection) if self.collection else None
        if self.collection and collection is None:
            self.report({"ERROR"}, f"No collection named {self.collection}")
            return {"CANCELLED"}
        if self.again:
            if collection is None and not remembered(context.scene):
                self.report({"ERROR"}, f"Nothing to export again yet, export the scene once with File > Export > {EXPORT_LABEL}")
                return {"CANCELLED"}
            recall(self, context.scene, filepath=collection is None)
        if not self.filepath.strip():
            self.report({"ERROR"}, "Pick a file to export the scene to")
            return {"CANCELLED"}
        self.filepath = str(glb_file(export_path(self.filepath)))
        if collection is None and self.will_save_settings:
            remember(self, context.scene)
        self._job = SceneExport(context.scene, self, self.filepath, collection)
        try:
            messages = start_export(self._job, context, self._interactive)
        except ExportError as error:
            return self._failed(error)
        if messages is None:
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}
        return self._finish(messages)

    def modal(self, context, event):
        task = self._job.task
        if task.running:
            if task.done != self._shown:
                self._shown = task.done
                redraw_status_bars()
            return {"PASS_THROUGH"}
        try:
            messages = finish_export(self._job, context)
        except ExportCancelled as error:
            self._job.release()
            self.report({"INFO"}, str(error))
            return {"CANCELLED"}
        except ExportError as error:
            return self._failed(error)
        return self._finish(messages)

    def cancel(self, context):
        task = self._job.task if self._job is not None else None
        if task is None:
            return
        task.cancel()
        task.wait()
        try:
            finish_export(self._job, context)
        except ExportError:
            pass
        self._job.release()

    def _failed(self, error):
        self._job.release()
        self.report({"ERROR"}, str(error))
        return {"CANCELLED"}

    def _finish(self, messages):
        self._job.release()
        _report_all(self, messages)
        return {"FINISHED"}


class BEVY_OT_export_all_scenes(bpy.types.Operator):
    bl_idname = "bevy_components.export_all_scenes"
    bl_label = "Export All Scenes"
    bl_description = "Export every scene in this file to its own GLB, with the settings its last export used. Scenes that were never exported are skipped"

    @classmethod
    def poll(cls, context):
        if running_export() is not None:
            cls.poll_message_set("A Bevy glTF export is still compressing textures")
            return False
        if context.window is None:
            cls.poll_message_set("Exporting every scene needs a Blender window")
            return False
        return True

    def execute(self, context):
        window = context.window
        active = window.scene
        exported = []
        skipped = []
        failed = []
        try:
            for scene in bpy.data.scenes:
                if not remembered(scene):
                    skipped.append(scene.name)
                    continue
                window.scene = scene
                job = again(scene)
                try:
                    for _kinds, message in start_export(job, context):
                        print(f"Bevy Components: {scene.name}: {message}")
                except ExportError as error:
                    failed.append((scene.name, str(error)))
                    continue
                finally:
                    job.release()
                exported.append(scene.name)
        finally:
            window.scene = active
        for name, error in failed:
            print(f"Bevy Components: Could not export {name}: {error}")
        note = f". Skipped {', '.join(skipped)}, export {'it' if len(skipped) == 1 else 'each'} once with File > Export > {EXPORT_LABEL}" if skipped else ""
        if failed:
            self.report({"ERROR"}, f"Could not export {count(len(failed), 'scene')}, {failed[0][0]}: {failed[0][1]}{note}")
            return {"CANCELLED"} if not exported else {"FINISHED"}
        if not exported:
            self.report({"WARNING"}, f"No scene was exported yet{note}")
            return {"CANCELLED"}
        self.report({"WARNING"} if skipped else {"INFO"}, f"Exported {count(len(exported), 'scene')}: {', '.join(exported)}{note}")
        return {"FINISHED"}


class BEVY_FH_gltf(bpy.types.FileHandler):
    bl_idname = "BEVY_FH_gltf"
    bl_label = "Bevy glTF"
    bl_export_operator = BEVY_OT_export_gltf.bl_idname
    bl_file_extensions = ".glb"

    @classmethod
    def poll_drop(cls, context):
        return False


@persistent
def export_on_save(path):
    scene = bpy.context.scene
    if path != bpy.data.filepath or scene is None or not hasattr(scene, "bevy_glb_export"):
        return
    if not scene.bevy_glb_export.export_on_save or not remembered(scene):
        return
    try:
        bpy.ops.export_scene.bevy_gltf("INVOKE_DEFAULT", again=True)
    except RuntimeError as error:
        message = str(error).removeprefix("Error: ").strip()
        print("Bevy Components: Export on Save failed:", message)
        if not bpy.app.background:
            bpy.context.window_manager.popup_menu(lambda menu, _context, text=message: menu.layout.label(text=text), title="Export on Save failed", icon="ERROR")


class BEVY_OT_unwrap_lightmap(bpy.types.Operator):
    bl_idname = "bevy_components.unwrap_lightmap"
    bl_label = "Unwrap Lightmap UVs"
    bl_description = "Unwrap the mesh into its second UV map, which Bevy reads lightmaps with, adding the map when the mesh has fewer than two. Islands are spaced a few pixels apart at the lightmap's Bake Size"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is None or obj.type != "MESH" or obj.library is not None or obj.data.library is not None:
            cls.poll_message_set("Select a mesh of this file to unwrap")
            return False
        if context.mode != "OBJECT":
            cls.poll_message_set("Switch to Object Mode to unwrap lightmap UVs")
            return False
        return True

    def execute(self, context):
        obj = context.object
        item = component_of(obj, "LIGHTMAP")
        size = int(item.lightmap_resolution) if item is not None else 512
        try:
            layer = unwrap_lightmap(context.view_layer, obj, size)
        except RuntimeError as error:
            self.report({"ERROR"}, f"Could not unwrap {obj.name}: {error}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Unwrapped {obj.name} into UV map {layer.name} for a {size} px lightmap")
        return {"FINISHED"}


class BEVY_OT_cancel_bake(bpy.types.Operator):
    bl_idname = "bevy_components.cancel_bake"
    bl_label = "Cancel Bake"
    bl_description = "Stop baking lighting. Lightmaps and probes that already finished keep their new files"

    @classmethod
    def poll(cls, context):
        return running_bake() is not None

    def execute(self, context):
        for task in _bakes:
            task.cancel()
        redraw_status_bars()
        return {"FINISHED"}


class BEVY_OT_bake_lighting(bpy.types.Operator):
    bl_idname = "bevy_components.bake_lighting"
    bl_label = "Bake Lighting"
    bl_description = "Render the Bevy Sky and every enabled Lightmap, Reflection Probe and Irradiance Volume in the scene with Cycles and save them as KTX2 files, in the background while you keep working"
    bl_options = {"REGISTER", "UNDO"}

    object_name: StringProperty(name="Object", options={"HIDDEN", "SKIP_SAVE"})
    index: IntProperty(name="Index", default=-1, options={"HIDDEN", "SKIP_SAVE"})
    sky: BoolProperty(name="Sky", description="Bake only the World's Bevy Sky", default=False, options={"HIDDEN", "SKIP_SAVE"})

    _interactive = False
    _directory = None
    _task = None
    _jobs = ()
    _folder = ""
    _shown = None

    @classmethod
    def poll(cls, context):
        if running_bake() is not None:
            cls.poll_message_set("Bevy lighting is still baking")
            return False
        if context.mode != "OBJECT":
            cls.poll_message_set("Switch to Object Mode to bake lighting")
            return False
        return context.scene is not None

    @classmethod
    def description(cls, context, properties):
        if properties.sky:
            return "Render the World into a cubemap with Cycles and save it as a KTX2 file, in the background while you keep working. Folder and Export Again are set in Bake Lighting"
        if properties.object_name:
            return "Render this component's lighting with Cycles and save it as a KTX2 file, in the background while you keep working. Samples, folder and Export Again are set in Bake Lighting"
        return cls.bl_description

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        settings = context.scene.bevy_bake_settings
        layout.prop(settings, "samples")
        layout.prop(settings, "folder")
        layout.prop(settings, "lamp_direct")
        layout.prop(settings, "export_again")
        width = context.region.width if context.region else 300
        if settings.export_again != "NONE" and not remembered(context.scene):
            draw_message(layout, f"Nothing to export again yet, export the scene once with File > Export > {EXPORT_LABEL}", width=width)
        jobs = self._find_jobs(context)
        if not jobs:
            draw_message(layout, "No Bevy Sky or enabled Lightmaps, Reflection Probes or Irradiance Volumes in this scene", icon="ERROR", width=width)
            return
        if settings.folder.startswith("//") and not bpy.data.filepath:
            draw_message(layout, "Save the .blend file first, or pick a folder that does not start with //", icon="ERROR", width=width)
        missing = _missing_uv_maps(jobs)
        if missing:
            draw_message(layout, f"{missing[0]} has no second UV map for its lightmap. Click Unwrap Lightmap UVs on its Lightmap", icon="ERROR", width=width)
        row = layout.row()
        row.active = False
        row.label(text=f"Bakes {bake_summary(jobs)}", icon="INFO")
        world = context.scene.world
        ambient = world.bevy_ambient_light if world is not None else None
        lightmaps = [job for job in jobs if job["kind"] == "LIGHTMAP"]
        if lightmaps:
            lamps = len(lightmaps[0]["baked_lamps"])
            draw_message(layout, f"Lightmaps hold sky light, bounced light and the direct light of lamps marked Baked in their Light component, {count(lamps, 'lamp') if lamps else 'none'} here. Bevy lights the meshes with the other lamps", icon="INFO", width=width)
            if (ambient is None or not ambient.enabled or not ambient.baked) and not sky_lights_scene(world):
                draw_message(layout, "Bevy's ambient light adds to the sky light baked into lightmaps. Turn on Bevy Ambient Light and its Baked option in World properties", icon="INFO", width=width)
        elif any(job["kind"] == "VOXELS" for job in jobs) and ambient is not None and ambient.enabled:
            draw_message(layout, "Bevy Ambient Light adds to the sky light baked into irradiance volumes. Turn it off in World properties unless the scene needs it outside the volumes", icon="INFO", width=width)

    def invoke(self, context, event):
        self._interactive = True
        if self.object_name:
            return self.execute(context)
        return context.window_manager.invoke_props_dialog(self, width=400, title="Bake Lighting", confirm_text="Bake")

    def execute(self, context):
        settings = context.scene.bevy_bake_settings
        if not settings.folder.strip():
            self.report({"ERROR"}, "Pick a folder for the baked lighting files")
            return {"CANCELLED"}
        if settings.folder.startswith("//") and not bpy.data.filepath:
            self.report({"ERROR"}, "Save the .blend file first, or pick a bake folder that does not start with //")
            return {"CANCELLED"}
        context.view_layer.update()
        self._jobs = self._find_jobs(context)
        self._folder = settings.folder
        if not self._jobs:
            self.report({"ERROR"}, "No Bevy Sky or enabled Lightmaps, Reflection Probes or Irradiance Volumes to bake")
            return {"CANCELLED"}
        missing = _missing_uv_maps(self._jobs)
        if missing:
            self.report({"ERROR"}, f"{missing[0]} has no second UV map for its lightmap. Click Unwrap Lightmap UVs on its Lightmap")
            return {"CANCELLED"}
        depsgraph = context.evaluated_depsgraph_get()
        cache = {}
        for job in self._jobs:
            job["fingerprint"] = bake_record(context.scene, context.view_layer, depsgraph, job, cache)
        if self._interactive and context.window is not None and bpy.app.binary_path:
            return self._start(context, settings, bpy.app.binary_path)
        window_manager = context.window_manager
        window_manager.progress_begin(0, len(self._jobs))
        done = 0
        try:
            for done, _job in enumerate(bake_jobs(context.scene, context.view_layer, self._jobs, settings.samples, settings.lamp_direct), start=1):
                window_manager.progress_update(done)
        except (RuntimeError, OSError) as error:
            return self._failed(error, self._store_files(done))
        finally:
            window_manager.progress_end()
        return self._finish(context, self._store_files(done))

    def modal(self, context, event):
        if self._task.running:
            if self._task.done != self._shown:
                self._shown = self._task.done
                redraw_status_bars()
            return {"PASS_THROUGH"}
        self._stop_background(context)
        stored = self._store_files(self._task.done)
        if self._task.cancelled:
            self.report({"INFO"}, f"Cancelled baking lighting after {bake_summary(stored)}" if stored else "Cancelled baking lighting")
            result = {"FINISHED"} if stored else {"CANCELLED"}
        elif self._task.error is not None:
            result = self._failed(self._task.error, stored)
        else:
            result = self._finish(context, stored)
        self._release()
        return result

    def cancel(self, context):
        if self._task is None:
            return
        self._task.cancel()
        self._task.wait()
        self._stop_background(context)
        self._release()

    def _find_jobs(self, context):
        settings = context.scene.bevy_bake_settings
        world = context.scene.world
        if self.sky:
            return [sky_job(world, settings.folder)] if baked_sky(world) else []
        return lighting_jobs(context.scene.objects, settings.folder, only=(self.object_name, self.index) if self.object_name else None, world=world)

    def _start(self, context, settings, binary):
        self._directory = tempfile.TemporaryDirectory(prefix="bevy_components_bake_")
        blend = Path(self._directory.name) / "scene.blend"
        job_path = Path(self._directory.name) / "bake.json"
        try:
            bpy.ops.wm.save_as_mainfile(filepath=str(blend), copy=True, check_existing=False)
            job_path.write_text(json.dumps({"scene": context.scene.name, "view_layer": context.view_layer.name, "samples": settings.samples, "lamp_direct": settings.lamp_direct, "hidden": bake_hidden(context.scene), "jobs": self._jobs}), encoding="utf-8")
            self._task = BackgroundBake(bake_command(binary, blend, job_path), len(self._jobs), scratch=self._directory.name)
        except (RuntimeError, OSError) as error:
            self._release()
            self.report({"ERROR"}, f"Could not start baking: {error}")
            return {"CANCELLED"}
        window_manager = context.window_manager
        _bakes[self._task] = (window_manager.event_timer_add(PROGRESS_INTERVAL, window=context.window), self._directory)
        window_manager.modal_handler_add(self)
        redraw_status_bars()
        return {"RUNNING_MODAL"}

    def _stop_background(self, context):
        if self._task in _bakes:
            timer, _directory = _bakes.pop(self._task)
            context.window_manager.event_timer_remove(timer)
        redraw_status_bars()
        redraw_properties()

    def _release(self):
        self._directory.cleanup()
        self._directory = None
        self._task = None

    def _store_files(self, done):
        stored = []
        for job in self._jobs[:done]:
            if job["kind"] == "SKY":
                world = bpy.data.worlds.get(job["world"])
                if world is not None and world.library is None:
                    world.bevy_sky.sky_file = job["file"]
                    world.bevy_sky.bake_fingerprint = job.get("fingerprint", "")
                    stored.append(job)
                continue
            obj = bpy.data.objects.get(job["object"])
            items = obj.bevy_component_data.components if obj is not None and obj.library is None else ()
            matching = [item for item in items if FILE_KINDS.get(item.component_type) == job["kind"]]
            item = items[job["index"]] if job["index"] < len(items) and items[job["index"]] in matching else matching[0] if len(matching) == 1 else None
            if item is not None:
                item.probe_file = job["file"]
                item.bake_fingerprint = job.get("fingerprint", "")
                stored.append(job)
        return stored

    def _failed(self, error, stored):
        self.report({"ERROR"}, f"Baking lighting failed after {bake_summary(stored)}: {error}" if stored else f"Baking lighting failed: {error}")
        return {"FINISHED"} if stored else {"CANCELLED"}

    def _finish(self, context, stored):
        self.report({"INFO"}, f"Baked {bake_summary(stored)} into {self._folder}")
        if context.scene.bevy_bake_settings.export_again != "NONE":
            try:
                bpy.ops.export_scene.bevy_gltf("INVOKE_DEFAULT" if self._interactive else "EXEC_DEFAULT", again=True)
            except RuntimeError as error:
                self.report({"WARNING"}, f"Baked {bake_summary(stored)}, but could not export again: {str(error).removeprefix('Error: ').strip()}")
        return {"FINISHED"}


class BEVY_OT_stop_game(bpy.types.Operator):
    bl_idname = "bevy_components.stop_game"
    bl_label = "Stop Game"
    bl_description = "Stop the game that Play started"

    @classmethod
    def poll(cls, context):
        return running_game() is not None

    def execute(self, context):
        for task in _games:
            task.stop()
        redraw_status_bars()
        return {"FINISHED"}


class BEVY_OT_show_game_output(bpy.types.Operator):
    bl_idname = "bevy_components.show_game_output"
    bl_label = "Show Game Output"
    bl_description = "Open everything the game printed in a Text Editor"

    @classmethod
    def poll(cls, context):
        return last_game() is not None

    def execute(self, context):
        text = bpy.data.texts.get(OUTPUT_TEXT) or bpy.data.texts.new(OUTPUT_TEXT)
        text.from_string("\n".join(last_game().output()))
        if context.window is None or bpy.app.background:
            return {"FINISHED"}
        areas = [area for area in context.screen.areas if area.type == "TEXT_EDITOR"] if context.screen else []
        if not areas:
            bpy.ops.wm.window_new()
            areas = context.window_manager.windows[-1].screen.areas[:1]
            areas[0].type = "TEXT_EDITOR"
        areas[0].spaces.active.text = text
        areas[0].spaces.active.show_syntax_highlight = False
        areas[0].spaces.active.top = max(len(text.lines) - 40, 0)
        return {"FINISHED"}


class BEVY_OT_play(bpy.types.Operator):
    bl_idname = "bevy_components.play"
    bl_label = "Play"
    bl_description = "Export the scene again and run the game from its project folder, or open the scene in the importer's viewer when no game project is set. The game gets the 3D Viewport's view to start from"

    _interactive = False
    _timer = None
    _task = None
    _job = None
    _folder = None
    _command = ""
    _view = None
    _shown = None

    @classmethod
    def poll(cls, context):
        if running_export() is not None:
            cls.poll_message_set("A Bevy glTF export is still compressing textures")
            return False
        return context.scene is not None

    def invoke(self, context, event):
        self._interactive = context.window is not None and not bpy.app.background
        return self.execute(context)

    def execute(self, context):
        try:
            self._folder, self._command = play_target(context)
        except PlayError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        if not remembered(context.scene):
            self.report({"ERROR"}, f"Export the scene once with File > Export > {EXPORT_LABEL}, then Play exports it again each time")
            return {"CANCELLED"}
        for task in _games:
            task.stop()
        self._view = viewport_view(context)
        if not self._export(context):
            return {"CANCELLED"}
        if self._job is None and not self._start(context):
            return {"CANCELLED"}
        if not self._interactive:
            self.report({"INFO"}, f"Started {self._task.name}: {self._command}")
            return {"FINISHED"}
        self._timer = context.window_manager.event_timer_add(PROGRESS_INTERVAL, window=context.window)
        if self._task is not None:
            _games[self._task] = self._timer
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if self._task is None:
            if self._job.task.running:
                return {"PASS_THROUGH"}
            if not self._exported(context):
                self._stop_timer(context)
                return {"CANCELLED"}
            if not self._start(context):
                self._stop_timer(context)
                return {"CANCELLED"}
            _games[self._task] = self._timer
            return {"PASS_THROUGH"}
        if self._task.running:
            if self._task.changes != self._shown:
                self._shown = self._task.changes
                redraw_status_bars()
                redraw_viewports()
            return {"PASS_THROUGH"}
        self._stop_timer(context)
        _games.pop(self._task, None)
        redraw_status_bars()
        redraw_viewports()
        if self._task.stopped:
            self.report({"INFO"}, f"Stopped {self._task.name}")
        elif self._task.failed:
            self.report({"ERROR"}, f"{self._task.name} stopped with exit code {self._task.code}: {self._task.problem()}")
        else:
            self.report({"INFO"}, f"{self._task.name} closed")
        return {"FINISHED"}

    def cancel(self, context):
        if self._job is not None and self._job.task is not None:
            self._job.task.cancel()
            self._job.task.wait()
            try:
                finish_export(self._job, context)
            except ExportError:
                pass
            self._job.release()
            self._job = None
        if self._task is not None:
            self._task.stop()
            _games.pop(self._task, None)
        self._stop_timer(context)

    def _export(self, context):
        job = again(context.scene)
        try:
            messages = start_export(job, context, self._interactive)
        except ExportError as error:
            job.release()
            self.report({"ERROR"}, f"Play stopped because the export failed: {error}")
            return False
        if messages is None:
            self._job = job
            return True
        job.release()
        _report_all(self, messages)
        return True

    def _exported(self, context):
        job, self._job = self._job, None
        try:
            messages = finish_export(job, context)
        except ExportCancelled:
            self.report({"ERROR"}, "Play stopped because the export did not finish")
            return False
        except ExportError as error:
            self.report({"ERROR"}, f"Play stopped because the export failed: {error}")
            return False
        finally:
            job.release()
        _report_all(self, messages)
        return True

    def _start(self, context):
        glb = remembered(context.scene)
        scene = export_path(glb) if glb else None
        name = self._folder.name if self._command != VIEWER_COMMAND else "The viewer"
        environment = {VIEW_VARIABLE: self._view} if self._view else {}
        try:
            self._task = GameProcess(game_command(self._command, self._folder, scene), self._folder, name, environment)
        except (PlayError, OSError) as error:
            self.report({"ERROR"}, f"Could not start the game: {error}")
            return False
        _games[self._task] = None
        _played["game"] = self._task
        redraw_status_bars()
        redraw_viewports()
        return True

    def _stop_timer(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
