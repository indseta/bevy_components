import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper

from .metadata import validate_items
from .property import COMPONENT_LABELS, COMPONENT_TYPES
from .system import components_for, copy_component, redraw_viewports, sync_object


def _editable(context):
    return context.object is not None and context.object.library is None


def _components(context, index):
    if not _editable(context) or not 0 <= index < len(context.object.bevy_component_data.components):
        return None
    return context.object.bevy_component_data.components


class BEVY_OT_add_component(bpy.types.Operator):
    bl_idname = "bevy_components.add"
    bl_label = "Add Component"
    bl_description = "Add a Bevy component to the active object"
    bl_options = {"REGISTER", "UNDO"}

    component_type: EnumProperty(name="Component", items=COMPONENT_TYPES)

    @classmethod
    def poll(cls, context):
        return _editable(context)

    def execute(self, context):
        obj = context.object
        items = obj.bevy_component_data.components
        if self.component_type != "CUSTOM" and any(existing.component_type == self.component_type for existing in items):
            self.report({"WARNING"}, f"{COMPONENT_LABELS[self.component_type][0]} is already on {obj.name}")
            return {"CANCELLED"}
        item = items.add()
        item.component_type = self.component_type
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
            copy_component(source, destination.add() if target is None else target)
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
        for field in item.bl_rna.properties:
            if field.identifier not in {"rna_type", "name", "component_type", "enabled", "show_expanded"} and not field.is_readonly:
                item.property_unset(field.identifier)
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
                copy_component(item, destination.add())
            sync_object(obj)
            count += 1
        redraw_viewports()
        self.report({"INFO"}, f"Copied components to {count} objects")
        return {"FINISHED"}


class BEVY_OT_validate(bpy.types.Operator):
    bl_idname = "bevy_components.validate"
    bl_label = "Validate Components"
    bl_description = "Check the components of every object for problems that would block export"

    def execute(self, context):
        problems = []
        for obj in bpy.data.objects:
            problems.extend(validate_items(components_for(obj), obj.name))
        if problems:
            for problem in problems[:8]:
                print("Bevy Components:", problem)
            self.report({"ERROR"}, f"{len(problems)} issue(s); see Blender console: {problems[0]}")
            return {"CANCELLED"}
        self.report({"INFO"}, "All Bevy components are valid")
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

    def execute(self, context):
        if not hasattr(bpy.ops.export_scene, "gltf"):
            self.report({"ERROR"}, "Blender glTF exporter is unavailable")
            return {"CANCELLED"}
        objects = context.selected_objects if self.selected_only else bpy.data.objects
        problems = []
        for obj in objects:
            problems.extend(validate_items(components_for(obj), obj.name))
        if problems:
            self.report({"ERROR"}, f"Cannot export: {problems[0]}")
            return {"CANCELLED"}
        for obj in objects:
            sync_object(obj)
        try:
            result = bpy.ops.export_scene.gltf(filepath=self.filepath, export_format="GLB", export_extras=True, use_selection=self.selected_only, export_lights=self.include_lights, export_cameras=self.include_cameras, export_animations=self.include_animations, check_existing=False)
        except Exception as error:
            self.report({"ERROR"}, f"GLB export failed: {error}")
            return {"CANCELLED"}
        if "FINISHED" in result:
            self.report({"INFO"}, f"Exported Bevy level: {self.filepath}")
        return result
