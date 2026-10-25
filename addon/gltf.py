import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ExportHelper

from .system import bevy_export

try:
    from io_scene_gltf2 import ExportGLTF2_Base
except ImportError:
    ExportGLTF2_Base = None

SKIPPED_SHOWN = 3


def _skipped_message(skipped):
    shown = "; ".join(skipped[:SKIPPED_SHOWN])
    more = f" and {len(skipped) - SKIPPED_SHOWN} more" if len(skipped) > SKIPPED_SHOWN else ""
    return f"Left out {len(skipped)} Bevy component{'s' if len(skipped) != 1 else ''} that cannot export: {shown}{more}. See Validate All Objects"


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
            with bevy_export() as skipped:
                result = ExportGLTF2_Base.execute(self, context)
            if skipped and "FINISHED" in result:
                self.report({"WARNING"}, _skipped_message(skipped))
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
