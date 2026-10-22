import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty

from .system import custom_type_changed, definition_renamed, field_changed, redraw_viewports, sync_changed

COMPONENT_TYPES = [
    ("VISIBILITY_RANGE", "Visibility Range", "Fade the object in and out by camera distance, for levels of detail", "HIDE_OFF", 0),
    ("COLLIDER", "Collider", "Avian collision shape", "MOD_PHYSICS", 1),
    ("RIGID_BODY", "Rigid Body", "Avian rigid body that is static, dynamic or kinematic", "RIGID_BODY", 2),
    ("CUSTOM", "Custom Component", "Any Rust component, filled in from JSON by your game", "FILE_SCRIPT", 4),
]

COMPONENT_LABELS = {identifier: (name, icon) for identifier, name, _description, icon, _number in COMPONENT_TYPES}

FIELD_TYPES = [
    ("FLOAT", "Float", "Decimal number, read as f32"),
    ("INT", "Integer", "Whole number, read as i32 or another integer type"),
    ("BOOL", "Boolean", "On or off, read as bool"),
    ("STRING", "String", "Text, read as String"),
    ("VECTOR", "Vector", "Three numbers on Bevy's axes (Y up), read as Vec3"),
    ("COLOR", "Color", "sRGB color with alpha, read as Bevy's Color"),
]

FIELD_LABELS = {identifier: name for identifier, name, _description in FIELD_TYPES}


class BEVY_PG_field(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", description="Field name, as written in the Rust struct", update=field_changed)
    identifier: StringProperty(name="Identifier", description="Links the field to its definition when it is renamed")
    field_type: EnumProperty(name="Type", description="Kind of value the field holds", items=FIELD_TYPES, default="FLOAT", update=field_changed)
    float_value: FloatProperty(name="Value", update=sync_changed)
    int_value: IntProperty(name="Value", update=sync_changed)
    bool_value: BoolProperty(name="Value", update=sync_changed)
    string_value: StringProperty(name="Value", update=sync_changed)
    vector_value: FloatVectorProperty(name="Value", size=3, subtype="XYZ", update=sync_changed)
    color_value: FloatVectorProperty(name="Value", size=4, subtype="COLOR_GAMMA", default=(1.0, 1.0, 1.0, 1.0), min=0.0, max=1.0, update=sync_changed)


class BEVY_PG_component(bpy.types.PropertyGroup):
    component_type: EnumProperty(name="Component", items=COMPONENT_TYPES)
    enabled: BoolProperty(name="Enabled", description="Export this component and draw its viewport preview", default=True, update=sync_changed)
    show_expanded: BoolProperty(name="Expanded", description="Show the component's settings", default=True)

    fade_in_start: FloatProperty(name="Fade In Start", description="Fully invisible closer than this distance", default=0.0, min=0.0, unit="LENGTH", update=sync_changed)
    fade_in_end: FloatProperty(name="Fade In End", description="Fully visible from this distance", default=0.0, min=0.0, unit="LENGTH", update=sync_changed)
    fade_out_start: FloatProperty(name="Fade Out Start", description="Starts fading out beyond this distance", default=20.0, min=0.0, unit="LENGTH", update=sync_changed)
    fade_out_end: FloatProperty(name="Fade Out End", description="Fully invisible beyond this distance", default=25.0, min=0.0, unit="LENGTH", update=sync_changed)
    use_aabb: BoolProperty(name="Use AABB Center", description="Measure distance from the mesh bounds center instead of the origin, usually off for aligned LOD meshes", default=False, update=sync_changed)

    collider_shape: EnumProperty(name="Shape", items=[
        ("TRIMESH", "Triangle Mesh", "Exact mesh surface, best for static environments", "MESH_DATA", 0),
        ("CONVEX", "Convex Hull", "Convex hull of the mesh, good for dynamic objects", "MESH_ICOSPHERE", 1),
        ("CUBOID", "Cuboid", "Box with explicit dimensions on Bevy's local axes", "MESH_CUBE", 2),
        ("SPHERE", "Sphere", "Sphere with a radius", "MESH_UVSPHERE", 3),
        ("CAPSULE", "Capsule", "Capsule along Bevy's local Y axis", "MESH_CAPSULE", 4),
    ], default="TRIMESH", update=sync_changed)
    collider_size: FloatVectorProperty(name="Size", description="Box dimensions along Bevy's local X, Y (up) and Z axes", size=3, subtype="XYZ", default=(1.0, 1.0, 1.0), min=0.001, unit="LENGTH", update=sync_changed)
    collider_radius: FloatProperty(name="Radius", description="Radius of the sphere or capsule", default=0.5, min=0.001, unit="LENGTH", update=sync_changed)
    collider_height: FloatProperty(name="Height", description="Length of the capsule's cylinder, without the caps", default=1.0, min=0.0, unit="LENGTH", update=sync_changed)
    collider_sensor: BoolProperty(name="Sensor", description="Detect overlaps without producing collision forces", default=False, update=sync_changed)

    rigid_body_kind: EnumProperty(name="Type", items=[
        ("STATIC", "Static", "Never moves"),
        ("DYNAMIC", "Dynamic", "Moved by forces and gravity"),
        ("KINEMATIC", "Kinematic", "Moved by game code and pushes dynamic bodies"),
    ], default="STATIC", update=sync_changed)
    custom_type: StringProperty(name="Type Path", description="Rust type path of the component, such as my_game::Health. Pick a type defined in Properties > Scene to edit its fields instead of JSON", default="my_game::MyComponent", update=custom_type_changed)
    custom_json: StringProperty(name="Data", description="Component fields as JSON, read by your game code", default="{}", update=sync_changed)
    use_fields: BoolProperty(name="Use Fields", description="Edit the data as the fields defined in Properties > Scene instead of JSON")
    fields: CollectionProperty(type=BEVY_PG_field)


class BEVY_PG_object_data(bpy.types.PropertyGroup):
    components: CollectionProperty(type=BEVY_PG_component)


class BEVY_PG_definition(bpy.types.PropertyGroup):
    name: StringProperty(name="Type Path", description="Rust type path of the component, such as my_game::Health", update=definition_renamed)
    linked_name: StringProperty(name="Linked Type Path", description="Type path that components on objects use, followed when the definition is renamed")
    fields: CollectionProperty(type=BEVY_PG_field)
    active_field: IntProperty(name="Active Field")


class BEVY_PG_definitions(bpy.types.PropertyGroup):
    definitions: CollectionProperty(type=BEVY_PG_definition)
    active_index: IntProperty(name="Active Definition")


class BEVY_PG_viewport_settings(bpy.types.PropertyGroup):
    enabled: BoolProperty(name="Bevy Components", description="Draw Bevy component previews in the 3D Viewport while the Bevy Components panel in Properties is expanded, never exported", default=True, update=redraw_viewports)
    scope: EnumProperty(name="Draw On", items=[
        ("SELECTED", "Selected", "Draw previews for selected objects only"),
        ("ALL", "All", "Draw previews for every visible object with Bevy components"),
    ], default="SELECTED", update=redraw_viewports)
    colliders: BoolProperty(name="Colliders", description="Draw collider shapes", default=True, update=redraw_viewports)
    visibility_ranges: BoolProperty(name="Visibility Ranges", description="Draw fade distances as spheres", default=True, update=redraw_viewports)
    labels: BoolProperty(name="Labels", description="Write component details next to each object", default=True, update=redraw_viewports)
    xray: BoolProperty(name="In Front", description="Draw previews on top of other geometry", default=False, update=redraw_viewports)
    edit_handles: BoolProperty(name="Resize Handles", description="Drag arrow gizmos on the selected active object to resize box, sphere and capsule colliders", default=True, update=redraw_viewports)
    max_mesh_edges: IntProperty(name="Max Mesh Edges", description="Draw triangle mesh colliders with more edges than this as bounding boxes", default=2000, min=64, max=20000, update=redraw_viewports)
