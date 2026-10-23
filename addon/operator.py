import json
import os
import tempfile
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper

from .compression import check_encoded, embed_textures, plan_textures, read_glb, write_glb
from .encoder import HINT, BackgroundEncode, EncoderError, check_encoder, encode
from .metadata import infer_fields
from .preferences import draw_encoder_status, encoder_path, texture_cache
from .property import AUDIO_FORMATS, COMPONENT_LABELS, COMPONENT_TYPES, LAYER_COUNT
from .system import apply_definitions, asset_path, copy_component, copy_to_object, custom_components, default_clip, field_slot, find_definition, image_to_png, new_identifier, redraw_status_bars, redraw_viewports, reset_fields, sync_object, unlink_component, write_field
from .validation import body_kind, check_objects, count, describe, draw_issues, issue_summary

TEXTURE_COMPRESSION = [
    ("DISABLED", "Disabled", "Export ordinary embedded textures"),
    ("ETC1S", "ETC1S", "Compress every texture as ETC1S KTX2, for the smallest files"),
    ("UASTC", "UASTC", "Compress every texture as UASTC KTX2, for the best quality"),
    ("AUTOMATIC", "Automatic", "UASTC for normal maps, data textures such as metallic-roughness and pixel art with Closest sampling, ETC1S for other color textures"),
]
PROGRESS_INTERVAL = 0.1
IDENTITY_PROPERTIES = {
    "CUSTOM": {"custom_type"},
    "SCENE_REFERENCE": {"scene_file"},
    "ANIMATION": {"animation_clip"},
}

_exports = {}


def running_export():
    return next(iter(_exports), None)


def stop_exports():
    for task, (timer, directory) in _exports.items():
        task.cancel()
        task.wait()
        bpy.context.window_manager.event_timer_remove(timer)
        directory.cleanup()
    _exports.clear()


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


def _export_path(filepath):
    return Path(os.path.abspath(bpy.path.abspath(filepath))) if filepath else None


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

    def execute(self, context):
        obj = context.object
        items = obj.bevy_component_data.components
        defined = self.component_type == "CUSTOM" and self.type_path
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
        sync_object(obj)
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
        sync_object(context.object)
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
        sync_object(context.object)
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
            if obj == context.object or obj.library:
                continue
            destination = obj.bevy_component_data.components
            target = next((item for item in destination if item.component_type == source.component_type and (source.component_type != "CUSTOM" or item.custom_type == source.custom_type)), None)
            copy_to_object(source, destination.add() if target is None else target, obj)
            sync_object(obj)
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
        kept = {"rna_type", "name", "component_type", "enabled", "show_expanded", "show_layers", "show_velocity", "show_dynamics"} | IDENTITY_PROPERTIES.get(item.component_type, set()) | ({"use_fields"} if typed else set())
        for field in item.bl_rna.properties:
            if field.identifier not in kept and field.type != "COLLECTION" and not field.is_readonly:
                item.property_unset(field.identifier)
        if typed:
            reset_fields(item, find_definition(context.scene, item.custom_type))
        sync_object(context.object)
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
        sync_object(context.object)
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
        sync_object(context.object)
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
        sync_object(context.object)
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
        library = context.scene.bevy_component_definitions
        definition = find_definition(context.scene, item.custom_type)
        if definition is None:
            if item.use_fields:
                fields = [(field.identifier, field.name, field.field_type, field_slot(field)) for field in item.fields]
            else:
                try:
                    fields = [("", name, kind, value) for name, kind, value in infer_fields(json.loads(item.custom_json))]
                except (json.JSONDecodeError, ValueError) as error:
                    self.report({"ERROR"}, f"Cannot define fields for {item.custom_type}: {error}")
                    return {"CANCELLED"}
            definition = library.definitions.add()
            for identifier, name, kind, value in fields:
                field = definition.fields.add()
                field.identifier = identifier or new_identifier()
                field.name = name
                field.field_type = kind
                write_field(field, value)
            definition.name = item.custom_type
        library.active_index = list(library.definitions).index(definition)
        apply_definitions(context.scene)
        _show_scene_properties(context)
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
                    sync_object(obj)
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
                copy_to_object(item, destination.add(), obj)
            sync_object(obj)
            count += 1
        redraw_viewports()
        self.report({"INFO"}, f"Copied components to {count} objects")
        return {"FINISHED"}


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
    bl_description = "Check every object for problems that block export or that make the level behave differently in Bevy"

    def execute(self, context):
        issues = check_objects(bpy.data.objects)
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
        for task in _exports:
            task.cancel()
        redraw_status_bars()
        return {"FINISHED"}


class BEVY_OT_export_glb(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.bevy_components_glb"
    bl_label = "Bevy Level (.glb)"
    bl_description = "Export the scene and its Bevy components as one GLB file"
    bl_options = {"REGISTER"}

    filename_ext = ".glb"
    filter_glob: StringProperty(default="*.glb", options={"HIDDEN"})
    selected_only: BoolProperty(name="Selected Objects Only", default=False)
    include_lights: BoolProperty(name="Include Lights", default=True)
    include_cameras: BoolProperty(name="Include Cameras", default=False)
    include_animations: BoolProperty(name="Include Animations", default=False)
    texture_compression: EnumProperty(name="Texture Compression", description="Convert textures to KTX2 with KTX-Software and embed them in the GLB", items=TEXTURE_COMPRESSION, default="DISABLED")
    etc1s_quality: IntProperty(name="ETC1S Quality", description="Higher keeps more detail in ETC1S textures and makes them larger", default=128, min=1, max=255)
    etc1s_effort: IntProperty(name="ETC1S Effort", description="Higher encodes ETC1S textures more slowly with slightly better quality", default=2, min=0, max=6)
    uastc_quality: IntProperty(name="UASTC Quality", description="Higher encodes UASTC textures more slowly with better quality", default=2, min=0, max=4)
    uastc_zstd: IntProperty(name="UASTC Supercompression", description="Zstandard level that shrinks UASTC textures in the file, 0 turns it off", default=18, min=0, max=22)

    _interactive = False
    _directory = None
    _level = None
    _task = None
    _shown = None
    _issues = ()

    @classmethod
    def poll(cls, context):
        if running_export() is not None:
            cls.poll_message_set("A Bevy level export is still compressing textures")
            return False
        return True

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        header, body = layout.panel("BEVY_export_include")
        header.label(text="Include")
        if body:
            body.prop(self, "selected_only")
            body.prop(self, "include_lights")
            body.prop(self, "include_cameras")
            body.prop(self, "include_animations")
        header, body = layout.panel("BEVY_export_texture_compression")
        header.label(text="Texture Compression")
        if body:
            body.prop(self, "texture_compression", text="Mode")
            if self.texture_compression in {"ETC1S", "AUTOMATIC"}:
                column = body.column(align=True)
                column.prop(self, "etc1s_quality")
                column.prop(self, "etc1s_effort", text="Effort")
            if self.texture_compression in {"UASTC", "AUTOMATIC"}:
                column = body.column(align=True)
                column.prop(self, "uastc_quality")
                column.prop(self, "uastc_zstd", text="Supercompression")
            if self.texture_compression != "DISABLED":
                draw_encoder_status(body, context)
        key = (self.selected_only, self.include_animations, self.filepath)
        checks = getattr(self, "_checks", None)
        if checks is None or checks[0] != key:
            checks = (key, check_objects(context.selected_objects if self.selected_only else bpy.data.objects, level=_export_path(self.filepath), animations=self.include_animations))
            self._checks = checks
        issues = checks[1]
        header, body = layout.panel("BEVY_export_checks")
        header.label(text="Checks")
        if issues:
            header.label(text=issue_summary(issues), icon="CANCEL" if any(issue.level == "ERROR" for issue in issues) else "ERROR")
        if body:
            if issues:
                draw_issues(body, [(issue.level, issue.obj.name, issue.message) for issue in issues], 6, "in Validate All Objects", width=context.region.width if context.region else 300)
            else:
                body.label(text="No problems found", icon="CHECKMARK")

    def invoke(self, context, event):
        self._interactive = True
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        if not hasattr(bpy.ops.export_scene, "gltf"):
            self.report({"ERROR"}, "Blender glTF exporter is unavailable")
            return {"CANCELLED"}
        objects = context.selected_objects if self.selected_only else bpy.data.objects
        level = _export_path(self.filepath)
        issues = check_objects(objects, level=level, animations=self.include_animations)
        errors = [issue for issue in issues if issue.level == "ERROR"]
        if errors:
            self.report({"ERROR"}, f"Cannot export: {describe(errors[0])}")
            return {"CANCELLED"}
        self._issues = issues
        encoder = None
        if self.texture_compression != "DISABLED":
            try:
                encoder, _version = check_encoder(encoder_path(context))
            except EncoderError as error:
                self.report({"ERROR"}, f"{error}. {HINT}")
                return {"CANCELLED"}
        for obj in objects:
            sync_object(obj, level.parent if level else None)
        if encoder is None:
            result = self._export_gltf(Path(self.filepath))
            if "FINISHED" in result:
                self.report({"INFO"}, f"Exported Bevy level: {self.filepath}")
                self._report_warnings()
            return result
        self._directory = tempfile.TemporaryDirectory(prefix="bevy_components_")
        result = self._compress(context, encoder)
        if "RUNNING_MODAL" not in result:
            self._release()
        return result

    def modal(self, context, event):
        if self._task.running:
            if self._task.done != self._shown:
                self._shown = self._task.done
                redraw_status_bars()
            return {"PASS_THROUGH"}
        self._stop_background(context)
        if self._task.cancelled:
            self.report({"INFO"}, "Cancelled the Bevy level export")
            result = {"CANCELLED"}
        elif self._task.error is not None:
            result = self._failed(self._task.error)
        else:
            result = self._finish(self._task.results)
        self._release()
        return result

    def cancel(self, context):
        self._task.cancel()
        self._task.wait()
        self._stop_background(context)
        self._release()

    def _export_gltf(self, path):
        try:
            return bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", export_extras=True, use_selection=self.selected_only, export_lights=self.include_lights, export_cameras=self.include_cameras, export_animations=self.include_animations, export_anim_slide_to_zero=True, check_existing=False)
        except Exception as error:
            self.report({"ERROR"}, f"GLB export failed: {error}")
            return {"CANCELLED"}

    def _compress(self, context, encoder):
        path = Path(self._directory.name) / "level.glb"
        result = self._export_gltf(path)
        if "FINISHED" not in result:
            return result
        try:
            gltf, binary = read_glb(path.read_bytes())
            jobs = plan_textures(gltf, binary, self.texture_compression, convert=image_to_png)
        except ValueError as error:
            return self._failed(error)
        self._level = (gltf, binary, jobs)
        settings = {
            "etc1s_quality": self.etc1s_quality,
            "etc1s_effort": self.etc1s_effort,
            "uastc_quality": self.uastc_quality,
            "uastc_zstd": self.uastc_zstd,
        }
        window_manager = context.window_manager
        if self._interactive and context.window is not None:
            self._task = BackgroundEncode(encoder, jobs, settings, self._directory.name, cache=texture_cache(), check=check_encoded)
            _exports[self._task] = (window_manager.event_timer_add(PROGRESS_INTERVAL, window=context.window), self._directory)
            window_manager.modal_handler_add(self)
            redraw_status_bars()
            return {"RUNNING_MODAL"}
        window_manager.progress_begin(0, max(len(jobs), 1))
        try:
            encoded = encode(encoder, jobs, settings, self._directory.name, progress=window_manager.progress_update, cache=texture_cache(), check=check_encoded)
        except EncoderError as error:
            return self._failed(error)
        finally:
            window_manager.progress_end()
        return self._finish(encoded)

    def _stop_background(self, context):
        if self._task in _exports:
            timer, _directory = _exports.pop(self._task)
            context.window_manager.event_timer_remove(timer)
        redraw_status_bars()

    def _release(self):
        self._directory.cleanup()
        self._directory = None
        self._level = None
        self._task = None

    def _report_warnings(self):
        for issue in self._issues:
            print("Bevy Components:", describe(issue))
        if self._issues:
            self.report({"WARNING"}, f"Exported with {count(len(self._issues), 'warning')}, see Validate All Objects: {describe(self._issues[0])}")

    def _failed(self, error):
        self.report({"ERROR"}, f"Texture compression failed: {error}")
        return {"CANCELLED"}

    def _finish(self, encoded):
        gltf, binary, jobs = self._level
        for job, data in zip(jobs, encoded):
            problem = check_encoded(job, data)
            if problem:
                return self._failed(problem)
        before = sum(len(data) for data in {job.image: job.data for job in jobs}.values())
        gltf, binary = embed_textures(gltf, binary, jobs, encoded)
        output = Path(self.filepath)
        staging = output.with_name(f".{output.name}.tmp")
        try:
            staging.write_bytes(write_glb(gltf, binary))
            os.replace(staging, output)
        except OSError as error:
            staging.unlink(missing_ok=True)
            self.report({"ERROR"}, f"Could not write {output}: {error}")
            return {"CANCELLED"}
        resized = sorted({job.name for job in jobs if job.resized})
        if resized:
            self.report({"WARNING"}, f"Resized {', '.join(resized)} to a multiple of 4 pixels, as KTX2 textures need")
        self.report({"INFO"}, f"Exported Bevy level with {len(jobs)} KTX2 textures ({before // 1024} KB to {sum(len(data) for data in encoded) // 1024} KB): {self.filepath}")
        self._report_warnings()
        return {"FINISHED"}
