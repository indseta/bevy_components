import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty

from .system import redraw_viewports, sync_changed

COMPONENT_TYPES = [
    ("VISIBILITY_RANGE", "Visibility Range", "Fade the object in and out by camera distance, for levels of detail", "HIDE_OFF", 0),
    ("COLLIDER", "Collider", "Avian collision shape", "MOD_PHYSICS", 1),
    ("RIGID_BODY", "Rigid Body", "Avian rigid body that is static, dynamic or kinematic", "RIGID_BODY", 2),
    ("SPAWN_POINT", "Spawn Point", "Tagged marker your game can spawn things at", "EMPTY_AXIS", 3),
    ("CUSTOM", "Custom Component", "Any Rust component, filled in from JSON by your game", "FILE_SCRIPT", 4),
]

COMPONENT_LABELS = {identifier: (name, icon) for identifier, name, _description, icon, _number in COMPONENT_TYPES}


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
    spawn_tag: StringProperty(name="Tag", description="Name your game uses to find this spawn point", default="default", update=sync_changed)
    custom_type: StringProperty(name="Type Path", description="Rust type path of the component, such as my_game::Health", default="my_game::MyComponent", update=sync_changed)
    custom_json: StringProperty(name="Data", description="Component fields as JSON, read by your game code", default="{}", update=sync_changed)


class BEVY_PG_object_data(bpy.types.PropertyGroup):
    components: CollectionProperty(type=BEVY_PG_component)


class BEVY_PG_viewport_settings(bpy.types.PropertyGroup):
    enabled: BoolProperty(name="Bevy Components", description="Draw Bevy component previews in the 3D Viewport, never exported", default=True, update=redraw_viewports)
    scope: EnumProperty(name="Draw On", items=[
        ("SELECTED", "Selected", "Draw previews for selected objects only"),
        ("ALL", "All", "Draw previews for every visible object with Bevy components"),
    ], default="SELECTED", update=redraw_viewports)
    colliders: BoolProperty(name="Colliders", description="Draw collider shapes", default=True, update=redraw_viewports)
    visibility_ranges: BoolProperty(name="Visibility Ranges", description="Draw fade distances as spheres", default=True, update=redraw_viewports)
    spawn_points: BoolProperty(name="Spawn Points", description="Draw spawn point markers", default=True, update=redraw_viewports)
    labels: BoolProperty(name="Labels", description="Write component details next to each object", default=True, update=redraw_viewports)
    xray: BoolProperty(name="In Front", description="Draw previews on top of other geometry", default=False, update=redraw_viewports)
    edit_handles: BoolProperty(name="Resize Handles", description="Drag arrow gizmos on the active object to resize box, sphere and capsule colliders", default=True, update=redraw_viewports)
    max_mesh_edges: IntProperty(name="Max Mesh Edges", description="Draw triangle mesh colliders with more edges than this as bounding boxes", default=2000, min=64, max=20000, update=redraw_viewports)
