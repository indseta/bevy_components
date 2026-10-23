import bpy
from bpy.props import StringProperty

from .encoder import EncoderError, check_encoder
from .schema import SCHEMA_FILE
from .system import game_schema, schema_setting_changed
from .validation import draw_message


def encoder_path(context):
    addon = context.preferences.addons.get(__package__)
    if addon is None or not addon.preferences.ktx_path:
        return ""
    return bpy.path.abspath(addon.preferences.ktx_path)


def texture_cache():
    try:
        return bpy.utils.extension_path_user(__package__, path="texture_cache", create=True)
    except (OSError, ValueError):
        return None


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


def draw_schema_status(layout):
    schema = game_schema()
    row = layout.row()
    if schema["error"]:
        column = row.column()
        column.alert = True
        draw_message(column, schema["error"], width=bpy.context.region.width if bpy.context.region else 300)
    elif schema["path"] is None:
        row.active = False
        row.label(text=f"No {SCHEMA_FILE} in the folders above the .blend file", icon="INFO")
    else:
        row.label(text=f"{len(schema['types'])} game components from {schema['path']}", icon="CHECKMARK")
    row.operator("bevy_components.reload_schema", text="", icon="FILE_REFRESH")


class BEVY_AP_preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    ktx_path: StringProperty(name="KTX-Software", description="The ktx executable from KTX-Software, used to compress textures on export. Leave empty to find it on the PATH", subtype="FILE_PATH")
    schema_path: StringProperty(name="Game Components", description=f"The {SCHEMA_FILE} that BlenderSchemaPlugin writes in your game. Leave empty to find it in the folders above the .blend file", subtype="FILE_PATH", update=schema_setting_changed)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "ktx_path")
        draw_encoder_status(layout, context)
        layout.separator()
        layout.prop(self, "schema_path")
        draw_schema_status(layout)
