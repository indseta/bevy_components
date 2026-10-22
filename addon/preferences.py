import bpy
from bpy.props import StringProperty

from .encoder import EncoderError, check_encoder


def encoder_path(context):
    addon = context.preferences.addons.get(__package__)
    if addon is None or not addon.preferences.ktx_path:
        return ""
    return bpy.path.abspath(addon.preferences.ktx_path)


def draw_encoder_status(layout, context):
    try:
        path, version = check_encoder(encoder_path(context))
    except EncoderError as error:
        column = layout.column(align=True)
        column.alert = True
        column.label(text=str(error), icon="ERROR")
        column.label(text="Install KTX-Software 4.4 or newer, or set the ktx path in the add-on preferences")
        return
    layout.label(text=f"KTX-Software {'.'.join(map(str, version))}: {path}", icon="CHECKMARK")


class BEVY_AP_preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    ktx_path: StringProperty(name="KTX-Software", description="The ktx executable from KTX-Software, used to compress textures on export. Leave empty to find it on the PATH", subtype="FILE_PATH")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "ktx_path")
        draw_encoder_status(layout, context)
