import os
import tempfile
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper

from .compression import check_encoded, embed_textures, plan_textures, read_glb, write_glb
from .encoder import HINT, EncoderError, check_encoder, encode
from .preferences import draw_encoder_status, encoder_path, texture_cache
from .property import COMPONENT_LABELS, COMPONENT_TYPES
from .system import copy_component, image_to_png, redraw_viewports, sync_object
from .validation import check_objects, count, describe, draw_issues, issue_summary

TEXTURE_COMPRESSION = [
    ("DISABLED", "Disabled", "Export ordinary embedded textures"),
    ("ETC1S", "ETC1S", "Compress every texture as ETC1S KTX2, for the smallest files"),
    ("UASTC", "UASTC", "Compress every texture as UASTC KTX2, for the best quality"),
    ("AUTOMATIC", "Automatic", "UASTC for normal maps, data textures such as metallic-roughness and pixel art with Closest sampling, ETC1S for other color textures"),
]


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
        checks = getattr(self, "_checks", None)
        if checks is None or checks[0] != self.selected_only:
            checks = (self.selected_only, check_objects(context.selected_objects if self.selected_only else bpy.data.objects))
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

    def execute(self, context):
        if not hasattr(bpy.ops.export_scene, "gltf"):
            self.report({"ERROR"}, "Blender glTF exporter is unavailable")
            return {"CANCELLED"}
        objects = context.selected_objects if self.selected_only else bpy.data.objects
        issues = check_objects(objects)
        errors = [issue for issue in issues if issue.level == "ERROR"]
        if errors:
            self.report({"ERROR"}, f"Cannot export: {describe(errors[0])}")
            return {"CANCELLED"}
        encoder = None
        if self.texture_compression != "DISABLED":
            try:
                encoder, _version = check_encoder(encoder_path(context))
            except EncoderError as error:
                self.report({"ERROR"}, f"{error}. {HINT}")
                return {"CANCELLED"}
        for obj in objects:
            sync_object(obj)
        with tempfile.TemporaryDirectory(prefix="bevy_components_") as directory:
            path = Path(directory) / "level.glb" if encoder else Path(self.filepath)
            try:
                result = bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", export_extras=True, use_selection=self.selected_only, export_lights=self.include_lights, export_cameras=self.include_cameras, export_animations=self.include_animations, check_existing=False)
            except Exception as error:
                self.report({"ERROR"}, f"GLB export failed: {error}")
                return {"CANCELLED"}
            if "FINISHED" not in result:
                return result
            if encoder:
                try:
                    message = self._compress_textures(context, path, encoder, directory)
                except (EncoderError, ValueError) as error:
                    self.report({"ERROR"}, f"Texture compression failed: {error}")
                    return {"CANCELLED"}
                self.report({"INFO"}, f"Exported Bevy level with {message}: {self.filepath}")
                self._report_warnings(issues)
                return result
        self.report({"INFO"}, f"Exported Bevy level: {self.filepath}")
        self._report_warnings(issues)
        return result

    def _report_warnings(self, issues):
        for issue in issues:
            print("Bevy Components:", describe(issue))
        if issues:
            self.report({"WARNING"}, f"Exported with {count(len(issues), 'warning')}, see Validate All Objects: {describe(issues[0])}")

    def _compress_textures(self, context, path, encoder, directory):
        gltf, binary = read_glb(path.read_bytes())
        jobs = plan_textures(gltf, binary, self.texture_compression, convert=image_to_png)
        settings = {
            "etc1s_quality": self.etc1s_quality,
            "etc1s_effort": self.etc1s_effort,
            "uastc_quality": self.uastc_quality,
            "uastc_zstd": self.uastc_zstd,
        }
        window_manager = context.window_manager
        window_manager.progress_begin(0, max(len(jobs), 1))
        try:
            encoded = encode(encoder, jobs, settings, directory, progress=window_manager.progress_update, cache=texture_cache(), check=check_encoded)
        finally:
            window_manager.progress_end()
        for job, data in zip(jobs, encoded):
            problem = check_encoded(job, data)
            if problem:
                raise ValueError(problem)
        before = sum(len(data) for data in {job.image: job.data for job in jobs}.values())
        gltf, binary = embed_textures(gltf, binary, jobs, encoded)
        output = Path(self.filepath)
        staging = output.with_name(f".{output.name}.tmp")
        staging.write_bytes(write_glb(gltf, binary))
        os.replace(staging, output)
        resized = sorted({job.name for job in jobs if job.resized})
        if resized:
            self.report({"WARNING"}, f"Resized {', '.join(resized)} to a multiple of 4 pixels, as KTX2 textures need")
        return f"{len(jobs)} KTX2 textures ({before // 1024} KB to {sum(len(data) for data in encoded) // 1024} KB)"
