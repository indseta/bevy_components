bl_info = {
    "name": "Bevy Components",
    "author": "Ask Indset",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),
    "location": "Object Properties > Bevy Components; 3D View > Sidebar > Bevy",
    "description": "Bevy component inspector, 3D collider/LOD overlays, viewport handles, and GLB exporter",
    "category": "Import-Export",
}

import bpy
from bpy.app.handlers import persistent
from bpy.props import (
    BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
    FloatVectorProperty, IntProperty, PointerProperty, StringProperty,
)
from bpy_extras.io_utils import ExportHelper

from .metadata import EXTRAS_KEY, serialize_items, validate_items
from .viewport import (
    BEVY_GGT_collider_handles, BEVY_PG_viewport_settings,
    BEVY_PT_viewport_previews, draw_viewport_controls,
    redraw_viewports, register_draw_handlers, unregister_draw_handlers,
)


COMPONENT_TYPES = [
    ("VISIBILITY_RANGE", "Visibility Range", "Dithered visibility distance range", "HIDE_OFF", 0),
    ("COLLIDER", "Collider", "Physics collider, mapped to Avian 3D", "MESH_ICOSPHERE", 1),
    ("RIGID_BODY", "Rigid Body", "Static, dynamic, or kinematic physics body", "PHYSICS", 2),
    ("SPAWN_POINT", "Spawn Point", "Game-defined spawn marker", "EMPTY_AXIS", 3),
    ("CUSTOM", "Custom Component", "Custom JSON data for a Rust type", "FILE_SCRIPT", 4),
]


def sync_object(obj):
    if not obj or not isinstance(obj, bpy.types.Object) or obj.library:
        return
    data = getattr(obj, "bevy_component_data", None)
    if not data:
        return
    if len(data.components):
        try:
            obj[EXTRAS_KEY] = serialize_items(data.components)
        except ValueError:
            # Preserve the previous valid export metadata until corrected.
            obj.pop(EXTRAS_KEY, None)
    else:
        obj.pop(EXTRAS_KEY, None)


def sync_changed(self, context):
    obj = getattr(self, "id_data", None)
    if isinstance(obj, bpy.types.Object):
        sync_object(obj)
        redraw_viewports()


class BEVY_PG_component(bpy.types.PropertyGroup):
    component_type: EnumProperty(name="Component", items=COMPONENT_TYPES)
    expanded: BoolProperty(name="Expanded", default=True)

    fade_in_start: FloatProperty(name="Fade-in Start", description="Fully invisible below this distance", default=0.0, min=0.0, update=sync_changed)
    fade_in_end: FloatProperty(name="Fade-in End", description="Fully visible at this distance", default=0.0, min=0.0, update=sync_changed)
    fade_out_start: FloatProperty(name="Fade-out Start", description="Starts fading out beyond this distance", default=20.0, min=0.0, update=sync_changed)
    fade_out_end: FloatProperty(name="Fade-out End", description="Fully invisible at this distance", default=25.0, min=0.0, update=sync_changed)
    use_aabb: BoolProperty(name="Use AABB Center", default=False, description="Use mesh AABB center instead of origin for range distance; usually leave off for aligned LOD meshes", update=sync_changed)

    collider_shape: EnumProperty(name="Shape", items=[
        ("TRIMESH", "Triangle Mesh", "Exact mesh surface; static environments", "MESH_DATA", 0),
        ("CONVEX", "Convex Hull", "Convex hull from mesh; good for dynamic objects", "MESH_ICOSPHERE", 1),
        ("CUBOID", "Cuboid", "Box with explicit dimensions in Bevy local XYZ", "MESH_CUBE", 2),
        ("SPHERE", "Sphere", "Sphere with radius in meters", "MESH_UVSPHERE", 3),
        ("CAPSULE", "Capsule", "Y-aligned capsule, height excludes caps", "MESH_UVSPHERE", 4),
    ], default="TRIMESH", update=sync_changed)
    collider_size: FloatVectorProperty(name="Size (Bevy XYZ)", size=3, subtype="XYZ", default=(1.0, 1.0, 1.0), min=0.001, unit="LENGTH", update=sync_changed)
    collider_radius: FloatProperty(name="Radius", default=0.5, min=0.001, unit="LENGTH", update=sync_changed)
    collider_height: FloatProperty(name="Cylinder Height", default=1.0, min=0.0, unit="LENGTH", update=sync_changed)
    collider_sensor: BoolProperty(name="Sensor", default=False, description="Trigger volume with no collision forces", update=sync_changed)

    rigid_body_kind: EnumProperty(name="Type", items=[
        ("STATIC", "Static", "Immovable world object"),
        ("DYNAMIC", "Dynamic", "Affected by physics and gravity"),
        ("KINEMATIC", "Kinematic", "Controlled by game logic"),
    ], default="STATIC", update=sync_changed)
    spawn_tag: StringProperty(name="Tag", description="Identifier for your game systems", default="default", update=sync_changed)
    custom_type: StringProperty(name="Type Path", description="Rust path/name for custom component", default="my_game::MyComponent", update=sync_changed)
    custom_json: StringProperty(name="JSON Data", description="JSON object/primitive; read by your game code", default="{}", update=sync_changed)


class BEVY_PG_object_data(bpy.types.PropertyGroup):
    components: CollectionProperty(type=BEVY_PG_component)


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
        if self.component_type != "CUSTOM" and any(i.component_type == self.component_type for i in items):
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
        start_0, start_1, end_0, end_1 = {
            "NEAR": (0.0, 0.0, 20.0, 25.0),
            "MID": (20.0, 25.0, 80.0, 85.0),
            "FAR": (80.0, 85.0, 250.0, 260.0),
        }[self.preset]
        item.fade_in_start = start_0
        item.fade_in_end = start_1
        item.fade_out_start = end_0
        item.fade_out_end = end_1
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
            dest = obj.bevy_component_data.components
            dest.clear()
            for old in source.bevy_component_data.components:
                new = dest.add()
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
            for error in problems[:8]:
                print("Bevy Components:", error)
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
            result = bpy.ops.export_scene.gltf(
                filepath=self.filepath,
                export_format="GLB",
                export_extras=True,
                use_selection=self.selected_only,
                export_lights=self.include_lights,
                export_cameras=self.include_cameras,
                export_animations=self.include_animations,
                check_existing=False,
            )
        except Exception as exc:
            self.report({"ERROR"}, f"GLB export failed: {exc}")
            return {"CANCELLED"}
        if "FINISHED" in result:
            self.report({"INFO"}, f"Exported Bevy level: {self.filepath}")
        return result


def draw_component_cards(layout, obj):
    items = obj.bevy_component_data.components
    row = layout.row(align=True)
    row.label(text=f"{len(items)} component(s)")
    row.operator("bevy_components.add", text="Add Component", icon="ADD")
    if not items:
        layout.label(text="Use Add Component to begin", icon="INFO")
    for idx, item in enumerate(items):
        title, icon = {
            "VISIBILITY_RANGE": ("Visibility Range", "HIDE_OFF"),
            "COLLIDER": ("Collider", "MESH_ICOSPHERE"),
            "RIGID_BODY": ("Rigid Body", "PHYSICS"),
            "SPAWN_POINT": ("Spawn Point", "EMPTY_AXIS"),
            "CUSTOM": (item.custom_type or "Custom Component", "FILE_SCRIPT"),
        }[item.component_type]
        card = layout.box()
        header = card.row(align=True)
        header.prop(item, "expanded", icon="TRIA_DOWN" if item.expanded else "TRIA_RIGHT", text="", emboss=False)
        header.label(text=title, icon=icon)
        op = header.operator("bevy_components.remove", icon="X", text="", emboss=False)
        op.index = idx
        if not item.expanded:
            continue
        column = card.column(align=True)
        if item.component_type == "VISIBILITY_RANGE":
            column.label(text="LOD presets (matched crossfades)")
            preset_row = column.row(align=True)
            for preset, name in (("NEAR", "LOD0"), ("MID", "LOD1"), ("FAR", "LOD2")):
                op = preset_row.operator("bevy_components.lod_preset", text=name)
                op.index = idx
                op.preset = preset
            column.separator(factor=0.5)
            column.label(text="Fade In (meters)")
            row = column.row(align=True)
            row.prop(item, "fade_in_start", text="Start")
            row.prop(item, "fade_in_end", text="End")
            column.label(text="Fade Out (meters)")
            row = column.row(align=True)
            row.prop(item, "fade_out_start", text="Start")
            row.prop(item, "fade_out_end", text="End")
            column.prop(item, "use_aabb")
            if validate_items([item], obj.name):
                column.label(text="Distances must be ordered", icon="ERROR")
        elif item.component_type == "COLLIDER":
            column.prop(item, "collider_shape")
            if item.collider_shape == "CUBOID":
                column.prop(item, "collider_size")
                column.label(text="Bevy local axes: X, Y (up), Z", icon="INFO")
            elif item.collider_shape == "SPHERE":
                column.prop(item, "collider_radius")
            elif item.collider_shape == "CAPSULE":
                column.prop(item, "collider_radius")
                column.prop(item, "collider_height")
            else:
                column.label(text="Derived from imported mesh geometry", icon="INFO")
            column.prop(item, "collider_sensor")
            if item.collider_shape == "TRIMESH":
                column.label(text="Use only for static bodies", icon="INFO")
        elif item.component_type == "RIGID_BODY":
            column.prop(item, "rigid_body_kind")
        elif item.component_type == "SPAWN_POINT":
            column.prop(item, "spawn_tag")
        elif item.component_type == "CUSTOM":
            column.prop(item, "custom_type")
            column.prop(item, "custom_json")
            column.label(text="Custom data requires your game-side handler", icon="INFO")
    if items:
        layout.separator()
        row = layout.row(align=True)
        row.operator("bevy_components.copy_to_selected", text="Copy to Selected", icon="DUPLICATE")
        row.operator("bevy_components.validate", text="Validate", icon="CHECKMARK")
    layout.separator()
    if hasattr(bpy.context, "scene") and bpy.context.scene:
        preview = layout.box()
        preview.label(text="3D Viewport Preview", icon="SHADING_WIRE")
        preview.prop(bpy.context.scene.bevy_component_previews, "enabled")
        preview.label(text="More controls: 3D View > N > Bevy")
    layout.operator("export_scene.bevy_components_glb", text="Export Level (.glb)", icon="EXPORT")


class BEVY_PT_object_properties(bpy.types.Panel):
    bl_label = "Bevy Components"
    bl_idname = "BEVY_PT_object_properties"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def draw(self, context):
        draw_component_cards(self.layout, context.object)


class BEVY_PT_view_sidebar(bpy.types.Panel):
    bl_label = "Bevy Components"
    bl_idname = "BEVY_PT_view_sidebar"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bevy"

    def draw(self, context):
        obj = context.object
        if obj is None:
            self.layout.label(text="Select an object", icon="INFO")
            return
        draw_component_cards(self.layout, obj)


def export_menu(self, context):
    self.layout.operator(BEVY_OT_export_glb.bl_idname, text="Bevy Level (.glb)")


@persistent
def save_sync(_scene):
    for obj in bpy.data.objects:
        sync_object(obj)


CLASSES = (
    BEVY_PG_component, BEVY_PG_object_data, BEVY_OT_add_component,
    BEVY_OT_remove_component, BEVY_OT_lod_preset,
    BEVY_OT_copy_to_selected, BEVY_OT_validate, BEVY_OT_export_glb,
    BEVY_PT_object_properties, BEVY_PT_view_sidebar,
    BEVY_PG_viewport_settings, BEVY_PT_viewport_previews,
    BEVY_GGT_collider_handles,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.bevy_component_data = PointerProperty(type=BEVY_PG_object_data)
    bpy.types.Scene.bevy_component_previews = PointerProperty(type=BEVY_PG_viewport_settings)
    bpy.types.TOPBAR_MT_file_export.append(export_menu)
    register_draw_handlers()
    if save_sync not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(save_sync)


def unregister():
    unregister_draw_handlers()
    if save_sync in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(save_sync)
    bpy.types.TOPBAR_MT_file_export.remove(export_menu)
    del bpy.types.Scene.bevy_component_previews
    del bpy.types.Object.bevy_component_data
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
