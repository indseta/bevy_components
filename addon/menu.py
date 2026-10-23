import bpy

from .operator import BEVY_OT_add_component, BEVY_OT_apply_preset, BEVY_OT_apply_text, BEVY_OT_bake_lighting, BEVY_OT_cancel_bake, BEVY_OT_cancel_export, BEVY_OT_copy_component, BEVY_OT_copy_component_to_selected, BEVY_OT_copy_components, BEVY_OT_copy_to_selected, BEVY_OT_define_fields, BEVY_OT_duplicate_component, BEVY_OT_edit_as_text, BEVY_OT_export_all_scenes, BEVY_OT_export_bsn, BEVY_OT_export_glb, BEVY_OT_move_component, BEVY_OT_paste_components, BEVY_OT_remove_component, BEVY_OT_remove_preset, BEVY_OT_reset_component, BEVY_OT_save_preset, BEVY_OT_select_by_component, BEVY_OT_validate, running_bake, running_export
from .property import COMPONENT_LABELS, COMPONENT_TYPES
from .schema import short_name
from .system import TEXT_COMPONENT, accepts, component_index, game_types, preset_folder, presets, scene_definition


def _draw_add_items(layout, obj, kinds):
    present = {item.component_type for item in obj.bevy_component_data.components} if obj else set()
    for kind in kinds:
        text, icon = COMPONENT_LABELS[kind]
        column = layout.column()
        column.enabled = (kind == "CUSTOM" or kind not in present) and accepts(obj, kind)
        column.operator(BEVY_OT_add_component.bl_idname, text=text, icon=icon).component_type = kind


def _custom_types(obj):
    return {item.custom_type for item in obj.bevy_component_data.components if item.component_type == "CUSTOM"} if obj else set()


def _game_menu_label(types):
    crates = {type_path.split("::", 1)[0] for type_path in types}
    return next(iter(crates)) if len(crates) == 1 else "Game Components"


def _draw_defined_items(layout, obj, scene):
    types = game_types()
    definitions = [definition for definition in scene.bevy_component_definitions.definitions if definition.name.strip() and definition.name not in types] if scene else []
    if not definitions:
        return
    present = _custom_types(obj)
    layout.separator()
    for definition in definitions:
        column = layout.column()
        column.enabled = definition.name not in present
        button = column.operator(BEVY_OT_add_component.bl_idname, text=definition.name, icon=COMPONENT_LABELS["CUSTOM"][1])
        button.component_type = "CUSTOM"
        button.type_path = definition.name


class BEVY_MT_component_add(bpy.types.Menu):
    bl_idname = "BEVY_MT_component_add"
    bl_label = "Add Component"
    bl_options = {"SEARCH_ON_KEY_PRESS"}

    def draw(self, context):
        layout = self.layout
        _draw_add_items(layout, context.object, ("CUSTOM",))
        types = game_types()
        if types:
            layout.menu(BEVY_MT_component_add_game.bl_idname, text=_game_menu_label(types), icon="FILE_SCRIPT")
        _draw_defined_items(layout, context.object, context.scene)
        layout.separator()
        layout.menu(BEVY_MT_component_add_physics.bl_idname)
        layout.menu(BEVY_MT_component_add_rendering.bl_idname)
        layout.menu(BEVY_MT_component_add_lighting.bl_idname)
        layout.separator()
        _draw_add_items(layout, context.object, ("AUDIO_PLAYER", "ANIMATION", "SCENE_REFERENCE", "NAVIGATION"))
        layout.separator()
        layout.menu(BEVY_MT_component_add_presets.bl_idname, icon="PRESET")


class BEVY_MT_component_add_game(bpy.types.Menu):
    bl_idname = "BEVY_MT_component_add_game"
    bl_label = "Game Components"
    bl_options = {"SEARCH_ON_KEY_PRESS"}

    def draw(self, context):
        layout = self.layout
        types = sorted(game_types(), key=lambda type_path: (short_name(type_path).lower(), type_path))
        names = [short_name(type_path) for type_path in types]
        present = _custom_types(context.object)
        for type_path, name in zip(types, names):
            column = layout.column()
            column.enabled = type_path not in present
            button = column.operator(BEVY_OT_add_component.bl_idname, text=name if names.count(name) == 1 else type_path, icon=COMPONENT_LABELS["CUSTOM"][1])
            button.component_type = "CUSTOM"
            button.type_path = type_path


class BEVY_MT_component_add_physics(bpy.types.Menu):
    bl_idname = "BEVY_MT_component_add_physics"
    bl_label = "Physics"
    bl_options = {"SEARCH_ON_KEY_PRESS"}

    def draw(self, context):
        _draw_add_items(self.layout, context.object, ("COLLIDER", "RIGID_BODY", "JOINT"))


class BEVY_MT_component_add_rendering(bpy.types.Menu):
    bl_idname = "BEVY_MT_component_add_rendering"
    bl_label = "Rendering"
    bl_options = {"SEARCH_ON_KEY_PRESS"}

    def draw(self, context):
        _draw_add_items(self.layout, context.object, ("VISIBILITY_RANGE", "SHADOWS"))


class BEVY_MT_component_add_lighting(bpy.types.Menu):
    bl_idname = "BEVY_MT_component_add_lighting"
    bl_label = "Lighting"
    bl_options = {"SEARCH_ON_KEY_PRESS"}

    def draw(self, context):
        _draw_add_items(self.layout, context.object, ("LIGHT", "LIGHTMAP", "REFLECTION_PROBE", "IRRADIANCE_VOLUME", "FOG_VOLUME"))


class BEVY_MT_component_add_presets(bpy.types.Menu):
    bl_idname = "BEVY_MT_component_add_presets"
    bl_label = "Presets"
    bl_options = {"SEARCH_ON_KEY_PRESS"}

    def draw(self, context):
        layout = self.layout
        found = presets()
        for name, path in found:
            layout.operator(BEVY_OT_apply_preset.bl_idname, text=name, icon="PRESET").filepath = str(path)
        if not found:
            row = layout.row()
            row.active = False
            row.label(text="No presets yet", icon="INFO")
        layout.separator()
        layout.operator(BEVY_OT_save_preset.bl_idname, text="Save Components as Preset...", icon="ADD")
        if found:
            layout.menu(BEVY_MT_component_remove_presets.bl_idname, icon="REMOVE")
            layout.operator("wm.path_open", text="Open Presets Folder", icon="FILE_FOLDER").filepath = str(preset_folder())


class BEVY_MT_component_remove_presets(bpy.types.Menu):
    bl_idname = "BEVY_MT_component_remove_presets"
    bl_label = "Remove Preset"

    def draw(self, context):
        for name, path in presets():
            self.layout.operator(BEVY_OT_remove_preset.bl_idname, text=name, icon="X").filepath = str(path)


class BEVY_MT_component_context_menu(bpy.types.Menu):
    bl_idname = "BEVY_MT_component_context_menu"
    bl_label = "Component"

    def draw(self, context):
        layout = self.layout
        obj = context.object
        item = getattr(context, "bevy_component", None)
        if obj is None or item is None:
            return
        index = component_index(obj, item)
        last = len(obj.bevy_component_data.components) - 1
        column = layout.column()
        column.enabled = item.component_type == "CUSTOM"
        column.operator(BEVY_OT_duplicate_component.bl_idname, text="Duplicate", icon="DUPLICATE").index = index
        layout.operator(BEVY_OT_copy_component.bl_idname, text="Copy", icon="COPY_ID").index = index
        layout.operator(BEVY_OT_copy_component_to_selected.bl_idname, text="Copy to Selected", icon="COPYDOWN").index = index
        if item.component_type == "CUSTOM" and item.custom_type not in game_types():
            layout.separator()
            defined = scene_definition(context.scene, item.custom_type) is not None
            layout.operator(BEVY_OT_define_fields.bl_idname, text="Edit Fields" if defined else "Define Fields", icon="PROPERTIES").index = index
        if item.component_type == "CUSTOM":
            layout.operator(BEVY_OT_edit_as_text.bl_idname, text="Edit as Text", icon="TEXT").index = index
        layout.separator()
        layout.operator(BEVY_OT_reset_component.bl_idname, text="Reset to Defaults", icon="LOOP_BACK").index = index
        layout.separator()
        for direction, text, icon, enabled in (("FIRST", "Move to First", "TRIA_UP_BAR", index > 0), ("UP", "Move Up", "TRIA_UP", index > 0), ("DOWN", "Move Down", "TRIA_DOWN", index < last), ("LAST", "Move to Last", "TRIA_DOWN_BAR", index < last)):
            column = layout.column()
            column.enabled = enabled
            button = column.operator(BEVY_OT_move_component.bl_idname, text=text, icon=icon)
            button.index = index
            button.direction = direction
        layout.separator()
        layout.operator(BEVY_OT_remove_component.bl_idname, text="Remove", icon="X").index = index


class BEVY_MT_object_context_menu(bpy.types.Menu):
    bl_idname = "BEVY_MT_object_context_menu"
    bl_label = "Bevy Components"

    def draw(self, context):
        layout = self.layout
        layout.operator(BEVY_OT_copy_to_selected.bl_idname, text="Copy All to Selected", icon="COPYDOWN")
        layout.operator(BEVY_OT_copy_components.bl_idname, text="Copy Components", icon="COPY_ID")
        layout.operator(BEVY_OT_paste_components.bl_idname, text="Paste Components", icon="PASTEDOWN")
        layout.separator()
        layout.operator(BEVY_OT_validate.bl_idname, text="Validate All Objects", icon="CHECKMARK")
        layout.operator(BEVY_OT_bake_lighting.bl_idname, text="Bake Lighting...", icon="RENDER_STILL")
        layout.operator(BEVY_OT_export_glb.bl_idname, text="Export Bevy Scene (.glb)...", icon="EXPORT")
        layout.operator(BEVY_OT_export_bsn.bl_idname, text="Export Bevy Scene (BSN)...", icon="EXPORT")
        draw_export_again(layout, context.scene)
        draw_export_all(layout)


class BEVY_MT_object_menu(bpy.types.Menu):
    bl_idname = "BEVY_MT_object_menu"
    bl_label = "Bevy Components"

    def draw(self, context):
        layout = self.layout
        layout.menu(BEVY_MT_component_add.bl_idname, icon="ADD")
        layout.operator(BEVY_OT_copy_to_selected.bl_idname, text="Copy All to Selected", icon="COPYDOWN")
        layout.operator(BEVY_OT_copy_components.bl_idname, text="Copy Components", icon="COPY_ID")
        layout.operator(BEVY_OT_paste_components.bl_idname, text="Paste Components", icon="PASTEDOWN")
        layout.separator()
        layout.operator(BEVY_OT_validate.bl_idname, text="Validate All Objects", icon="CHECKMARK")
        draw_export_again(layout, context.scene, placeholder=True)
        draw_export_all(layout)


class BEVY_MT_select_by_component(bpy.types.Menu):
    bl_idname = "BEVY_MT_select_by_component"
    bl_label = "Select by Bevy Component"

    def draw(self, context):
        layout = self.layout
        kinds = set()
        type_paths = set()
        for obj in context.view_layer.objects if context.view_layer else ():
            for item in obj.bevy_component_data.components:
                kinds.add(item.component_type)
                if item.component_type == "CUSTOM" and item.custom_type.strip():
                    type_paths.add(item.custom_type)
        found = [kind for kind, _name, _description, _icon, _number in COMPONENT_TYPES if kind in kinds]
        if not found:
            row = layout.row()
            row.active = False
            row.label(text="No objects with Bevy components", icon="INFO")
            return
        layout.operator(BEVY_OT_select_by_component.bl_idname, text="Any Component", icon="PROPERTIES").component_type = "ALL"
        layout.separator()
        for kind in found:
            text, icon = COMPONENT_LABELS[kind]
            layout.operator(BEVY_OT_select_by_component.bl_idname, text=text, icon=icon).component_type = kind
        if type_paths:
            layout.separator()
        for type_path in sorted(type_paths):
            button = layout.operator(BEVY_OT_select_by_component.bl_idname, text=type_path, icon=COMPONENT_LABELS["CUSTOM"][1])
            button.component_type = "CUSTOM"
            button.type_path = type_path


def draw_export_again(layout, scene, placeholder=False):
    shown = False
    for operator in (BEVY_OT_export_glb, BEVY_OT_export_bsn):
        path = operator.remembered(scene)
        if path:
            layout.operator(operator.bl_idname, text=f"Export Again ({bpy.path.basename(path)})", icon="FILE_REFRESH").again = True
            shown = True
    if placeholder and not shown:
        column = layout.column()
        column.enabled = False
        column.operator(BEVY_OT_export_glb.bl_idname, text="Export Again", icon="FILE_REFRESH").again = True


def object_menu(self, context):
    self.layout.separator()
    self.layout.menu(BEVY_MT_object_menu.bl_idname)


def select_menu(self, context):
    self.layout.separator()
    self.layout.menu(BEVY_MT_select_by_component.bl_idname)


def text_header(self, context):
    text = getattr(context.space_data, "text", None)
    if text is not None and TEXT_COMPONENT in text:
        self.layout.operator(BEVY_OT_apply_text.bl_idname, icon="CHECKMARK")


def draw_export_all(layout):
    if len(bpy.data.scenes) > 1:
        layout.operator(BEVY_OT_export_all_scenes.bl_idname, text="Export All Scenes (.glb)", icon="SCENE_DATA")


def export_menu(self, context):
    self.layout.operator(BEVY_OT_export_glb.bl_idname, text="Bevy Scene (.glb)")
    self.layout.operator(BEVY_OT_export_bsn.bl_idname, text="Bevy Scene (BSN)")
    draw_export_again(self.layout, context.scene)


def export_status(self, context):
    task = running_export()
    if task is None:
        return
    row = self.layout.row(align=True)
    row.ui_units_x = 12
    row.progress(factor=task.done / max(task.total, 1), type="BAR", text=f"Compressing textures {task.done}/{task.total}")
    row.operator(BEVY_OT_cancel_export.bl_idname, text="", icon="X", emboss=False)


def bake_status(self, context):
    task = running_bake()
    if task is None:
        return
    row = self.layout.row(align=True)
    row.ui_units_x = 12
    row.progress(factor=(task.done + task.fraction) / max(task.total, 1), type="BAR", text=f"Baking lighting {task.done}/{task.total}")
    row.operator(BEVY_OT_cancel_bake.bl_idname, text="", icon="X", emboss=False)
