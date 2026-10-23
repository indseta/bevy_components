from pathlib import Path

import bpy

from .play import DEFAULT_COMMAND, VIEWER_COMMAND, PlayError, check_game_folder, check_viewer_folder


def addon_preferences(context):
    addon = context.preferences.addons.get(__package__) if getattr(context, "preferences", None) else None
    return addon.preferences if addon is not None else None


def folder_setting(path):
    return Path(bpy.path.abspath(path.strip())) if path.strip() else None


def blend_game_folder(context):
    scenes = [context.scene] if getattr(context, "scene", None) is not None else []
    scenes += [scene for scene in bpy.data.scenes if scene not in scenes]
    return next((folder_setting(scene.bevy_game.folder) for scene in scenes if hasattr(scene, "bevy_game") and scene.bevy_game.folder.strip()), None)


def default_game_folder(context):
    preferences = addon_preferences(context)
    return folder_setting(preferences.game_folder) if preferences is not None else None


def game_folder(context):
    folder = blend_game_folder(context)
    return folder if folder is not None else default_game_folder(context)


def game_assets(context):
    folder = game_folder(context)
    return folder / "assets" if folder is not None else None


def viewer_folder(context):
    preferences = addon_preferences(context)
    return folder_setting(preferences.viewer_folder) if preferences is not None else None


def play_target(context):
    folder = game_folder(context)
    if folder is not None:
        preferences = addon_preferences(context)
        command = preferences.run_command.strip() if preferences is not None else ""
        return check_game_folder(folder), command or DEFAULT_COMMAND
    viewer = viewer_folder(context)
    if viewer is not None:
        return check_viewer_folder(viewer), VIEWER_COMMAND
    raise PlayError("Set the game project folder, or the importer folder for the viewer, in the add-on preferences")
