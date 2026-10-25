from types import SimpleNamespace

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ExportHelper

from .export import export_path, scene_issues
from .system import bevy_export, component_of
from .validation import describe, issue_summary

try:
    from io_scene_gltf2 import ExportGLTF2_Base
except ImportError:
    ExportGLTF2_Base = None

SKIPPED_SHOWN = 3


def _skipped_message(skipped):
    shown = "; ".join(skipped[:SKIPPED_SHOWN])
    more = f" and {len(skipped) - SKIPPED_SHOWN} more" if len(skipped) > SKIPPED_SHOWN else ""
    return f"Left out {len(skipped)} Bevy component{'s' if len(skipped) != 1 else ''} that cannot export: {shown}{more}. See Validate All Objects"


def _names(objects):
    shown = ", ".join(obj.name for obj in objects[:SKIPPED_SHOWN])
    return f"{shown} and {len(objects) - SKIPPED_SHOWN} more" if len(objects) > SKIPPED_SHOWN else shown


def _candidates(operator, context):
    collection = bpy.data.collections.get(operator.collection) if operator.collection else None
    if collection is not None:
        objects = collection.all_objects
    elif operator.use_active_collection:
        active = context.view_layer.active_layer_collection.collection
        objects = active.all_objects if operator.use_active_collection_with_nested else active.objects
    else:
        objects = context.view_layer.objects
    return [obj for obj in objects if (not operator.use_selection or obj.select_get()) and (not operator.use_visible or obj.visible_get()) and (not operator.use_renderable or not obj.hide_render)]


def export_messages(operator, context, export):
    messages = []
    if export.skipped:
        messages.append(({"WARNING"}, _skipped_message(export.skipped)))
    if not operator.export_lights:
        lights = [obj for obj in _candidates(operator, context) if obj.type == "LIGHT" and component_of(obj, "LIGHT") is not None]
        if lights:
            messages.append(({"WARNING"}, f"Left out {_names(lights)}, which {'has a Light component' if len(lights) == 1 else 'have Light components'}, because Punctual Lights is off. Tick Include > Punctual Lights to export {'it' if len(lights) == 1 else 'them'}"))
    options = SimpleNamespace(include_animations=operator.export_animations, apply_modifiers=operator.export_apply, selected_only=True)
    issues = scene_issues(options, export.objects, export_path(operator.filepath))
    for issue in issues:
        print("Bevy Components:", describe(issue))
    if issues:
        messages.append(({"WARNING"}, f"Exported with {issue_summary(issues)}: {describe(issues[0])}"))
    return messages


if ExportGLTF2_Base is not None:
    class BEVY_OT_export_gltf(bpy.types.Operator, ExportGLTF2_Base, ExportHelper):
        """Export as glTF 2.0 with the same options as Blender's glTF export, plus the objects' Bevy components"""
        bl_idname = "export_scene.bevy_gltf"
        bl_label = "Export Bevy glTF"

        filename_ext = ""
        filter_glob: StringProperty(default="*.glb", options={"HIDDEN"})
        scene_key = "bevy_gltf_export_settings"

        @classmethod
        def poll(cls, context):
            return "io_scene_gltf2" in context.preferences.addons and context.scene is not None

        def execute(self, context):
            with bevy_export() as export:
                result = ExportGLTF2_Base.execute(self, context)
            if "FINISHED" in result:
                for level, message in export_messages(self, context, export):
                    self.report(level, message)
            return result

    class BEVY_FH_gltf(bpy.types.FileHandler):
        bl_idname = "BEVY_FH_gltf"
        bl_label = "Bevy glTF"
        bl_export_operator = BEVY_OT_export_gltf.bl_idname
        bl_file_extensions = ".glb;.gltf"

        @classmethod
        def poll_drop(cls, context):
            return False

    CLASSES = (BEVY_OT_export_gltf, BEVY_FH_gltf)
else:
    CLASSES = ()
