import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper

from .metadata import validate_items
from .property import COMPONENT_TYPES
from .system import redraw_viewports, sync_object


class BEVY_OT_add_component(bpy.types.Operator):
    bl_idname = "bevy_components.add"
    bl_label = "Add Bevy Component"
    bl_description = "Search for a component preset and attach it to the active object"
    bl_options = {"REGISTER", "UNDO"}

    component_type: EnumProperty(name="Component", items=COMPONENT_TYPES)

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.library is None

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        obj = context.object
        items = obj.bevy_component_data.components
        if self.component_type != "CUSTOM" and any(existing.component_type == self.component_type for existing in items):
            self.report({"WARNING"}, "This component is already present on the object")
            return {"CANCELLED"}
        item = items.add()
        item.component_type = self.component_type
        item.expanded = True
        sync_object(obj)
        redraw_viewports()
        return {"FINISHED"}


class BEVY_OT_remove_component(bpy.types.Operator):
    bl_idname = "bevy_components.remove"
    bl_label = "Remove Bevy Component"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty()

    def execute(self, context):
        if context.object is None:
            return {"CANCELLED"}
        items = context.object.bevy_component_data.components
        if not 0 <= self.index < len(items):
            return {"CANCELLED"}
        items.remove(self.index)
        sync_object(context.object)
        redraw_viewports()
        return {"FINISHED"}


class BEVY_OT_lod_preset(bpy.types.Operator):
    bl_idname = "bevy_components.lod_preset"
    bl_label = "Apply LOD Preset"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty()
    preset: EnumProperty(items=[
        ("NEAR", "Near (LOD0)", "0 to 25 m"),
        ("MID", "Mid (LOD1)", "20 to 85 m"),
        ("FAR", "Far (LOD2)", "80 to 260 m"),
    ])

    def execute(self, context):
        if context.object is None:
            return {"CANCELLED"}
        items = context.object.bevy_component_data.components
        if not 0 <= self.index < len(items) or items[self.index].component_type != "VISIBILITY_RANGE":
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
    bl_description = "Replace Bevy components on all other selected objects with the active object's components"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        source = context.object
        if source is None:
            return {"CANCELLED"}
        count = 0
        for obj in context.selected_objects:
            if obj == source or obj.library:
                continue
            destination = obj.bevy_component_data.components
            destination.clear()
            for old in source.bevy_component_data.components:
                new = destination.add()
                for field in old.bl_rna.properties:
                    if field.identifier in {"rna_type", "id_data"} or field.is_readonly:
                        continue
                    value = getattr(old, field.identifier)
                    try:
                        setattr(new, field.identifier, tuple(value) if field.type == "FLOAT" and field.is_array else value)
                    except (TypeError, AttributeError):
                        continue
            sync_object(obj)
            count += 1
        redraw_viewports()
        self.report({"INFO"}, f"Copied components to {count} objects")
        return {"FINISHED"}


class BEVY_OT_validate(bpy.types.Operator):
    bl_idname = "bevy_components.validate"
    bl_label = "Validate Bevy Components"

    def execute(self, context):
        problems = []
        for obj in bpy.data.objects:
            problems.extend(validate_items(obj.bevy_component_data.components, obj.name))
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
    bl_description = "Export entire Blender scene, materials and per-object Bevy component metadata to one GLB"
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
            problems.extend(validate_items(obj.bevy_component_data.components, obj.name))
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
