import bpy
from bpy.props import StringProperty

from .encoder import EncoderError, check_encoder
from .play import DEFAULT_COMMAND, PlayError, check_game_folder, check_viewer_folder
from .project import addon_preferences, folder_setting
from .schema import SCHEMA_FILE
from .system import game_schema, schema_setting_changed
from .validation import draw_message


def encoder_path(context):
    preferences = addon_preferences(context)
    if preferences is None or not preferences.ktx_path:
        return ""
    return bpy.path.abspath(preferences.ktx_path)


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
        row.label(text=f"No {SCHEMA_FILE} in the game project or the folders above the .blend file", icon="INFO")
    else:
        row.label(text=f"{len(schema['types'])} game components from {schema['path']}", icon="CHECKMARK")
    row.operator("bevy_components.reload_schema", text="", icon="FILE_REFRESH")


def _draw_folder_check(layout, path, check):
    if not path.strip():
        return
    try:
        check(folder_setting(path))
    except PlayError as error:
        row = layout.row()
        row.alert = True
        row.label(text=str(error), icon="ERROR")


class BEVY_AP_preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    ktx_path: StringProperty(name="KTX-Software", description="The ktx executable from KTX-Software, used to compress textures on export. Leave empty to find it on the PATH", subtype="FILE_PATH")
    schema_path: StringProperty(name="Game Components", description=f"The {SCHEMA_FILE} that BlenderSchemaPlugin writes in your game. Leave empty to find it in the game project folder or the folders above the .blend file", subtype="FILE_PATH", update=schema_setting_changed)
    game_folder: StringProperty(name="Game Project", description="The folder with your game's Cargo.toml. Play runs the run command there, and exports and file pickers start in its assets folder. A .blend file can set its own in the Bevy sidebar", subtype="DIR_PATH")
    run_command: StringProperty(name="Run Command", description="The command Play runs in the game project folder. {scene} becomes the path of the exported GLB file", default=DEFAULT_COMMAND)
    viewer_folder: StringProperty(name="Importer", description="The bevy_components_importer folder. With no game project, Play opens the exported scene in its viewer example", subtype="DIR_PATH")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "ktx_path")
        draw_encoder_status(layout, context)
        layout.separator()
        layout.prop(self, "schema_path")
        draw_schema_status(layout)
        header, body = layout.panel("BEVY_preferences_play")
        header.label(text="Play")
        if body:
            body.prop(self, "game_folder")
            _draw_folder_check(body, self.game_folder, check_game_folder)
            body.prop(self, "run_command")
            body.prop(self, "viewer_folder")
            _draw_folder_check(body, self.viewer_folder, check_viewer_folder)
