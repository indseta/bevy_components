import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty

from .system import redraw_viewports, sync_changed

COMPONENT_TYPES = [
    ("VISIBILITY_RANGE", "Visibility Range", "Dithered visibility distance range", "HIDE_OFF", 0),
    ("COLLIDER", "Collider", "Physics collider, mapped to Avian 3D", "MESH_ICOSPHERE", 1),
    ("RIGID_BODY", "Rigid Body", "Static, dynamic, or kinematic physics body", "PHYSICS", 2),
    ("SPAWN_POINT", "Spawn Point", "Game-defined spawn marker", "EMPTY_AXIS", 3),
    ("CUSTOM", "Custom Component", "Custom JSON data for a Rust type", "FILE_SCRIPT", 4),
]


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


class BEVY_PG_viewport_settings(bpy.types.PropertyGroup):
    enabled: BoolProperty(name="Show Bevy Previews", description="Draw Bevy component overlays in the 3D Viewport; never exported", default=True, update=redraw_viewports)
    scope: EnumProperty(name="Draw On", items=[
        ("SELECTED", "Selected", "Draw only selected objects"),
        ("ALL", "All Visible", "Draw every visible object with Bevy components"),
    ], default="SELECTED", update=redraw_viewports)
    colliders: BoolProperty(name="Colliders", default=True, update=redraw_viewports)
    visibility_ranges: BoolProperty(name="Visibility Ranges", default=True, update=redraw_viewports)
    spawn_points: BoolProperty(name="Spawn Points", default=True, update=redraw_viewports)
    labels: BoolProperty(name="Labels", default=True, update=redraw_viewports)
    xray: BoolProperty(name="See Through Meshes", default=False, update=redraw_viewports)
    edit_handles: BoolProperty(name="Edit Collider in Viewport", description="Drag the colored gizmo arrows to change primitive collider dimensions", default=True, update=redraw_viewports)
    max_mesh_edges: IntProperty(name="Max Mesh Edges", description="Limits the wireframe preview cost per triangle-mesh collider", default=2000, min=64, max=20000, update=redraw_viewports)
