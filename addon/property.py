from math import radians

import bpy
from bpy.props import BoolProperty, BoolVectorProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty, StringProperty

from .system import component_of, custom_type_changed, definition_renamed, field_changed, redraw_viewports, sync_changed

COMPONENT_TYPES = [
    ("VISIBILITY_RANGE", "Visibility Range", "Fade the object in and out by camera distance, for levels of detail", "HIDE_OFF", 0),
    ("COLLIDER", "Collider", "Avian collision shape", "MOD_PHYSICS", 1),
    ("RIGID_BODY", "Rigid Body", "Avian rigid body that is static, dynamic or kinematic", "RIGID_BODY", 2),
    ("CUSTOM", "Custom Component", "Any Rust component, filled in from JSON by your game", "FILE_SCRIPT", 4),
    ("JOINT", "Joint", "Avian joint that connects two rigid bodies, or pins one body to a spot in the level", "CON_PIVOT", 5),
    ("SHADOWS", "Shadows", "Stop the object's meshes from casting or receiving shadows", "SHADING_RENDERED", 15),
    ("AUDIO_PLAYER", "Audio Player", "Play a sound from your game's assets folder, optionally in 3D at the object's position", "SPEAKER", 16),
]

COMPONENT_LABELS = {identifier: (name, icon) for identifier, name, _description, icon, _number in COMPONENT_TYPES}
LAYER_COUNT = 32
AUDIO_FORMATS = (".ogg", ".oga", ".spx", ".wav", ".mp3", ".flac")

FIELD_TYPES = [
    ("FLOAT", "Float", "Decimal number, read as f32"),
    ("INT", "Integer", "Whole number, read as i32 or another integer type"),
    ("BOOL", "Boolean", "On or off, read as bool"),
    ("STRING", "String", "Text, read as String"),
    ("VECTOR", "Vector", "Three numbers on Bevy's axes (Y up), read as Vec3"),
    ("COLOR", "Color", "sRGB color with alpha, read as Bevy's Color"),
]

FIELD_LABELS = {identifier: name for identifier, name, _description in FIELD_TYPES}

JOINT_TYPES = [
    ("FIXED", "Fixed", "Holds the bodies together so they move as one, Avian FixedJoint", "LOCKED", 0),
    ("REVOLUTE", "Hinge", "Lets the bodies turn around the axis, like a door, wheel or lever, Avian RevoluteJoint", "CON_ROTLIMIT", 1),
    ("PRISMATIC", "Slider", "Lets the bodies slide along the axis, like a drawer or elevator, Avian PrismaticJoint", "CON_LOCLIMIT", 2),
    ("SPHERICAL", "Ball", "Lets the bodies turn freely around the joint, like a chain link or shoulder, Avian SphericalJoint", "SPHERE", 3),
]

JOINT_LABELS = {identifier: name for identifier, name, _description, _icon, _number in JOINT_TYPES}

AXES = [
    ("X", "X", "Bevy's X axis"),
    ("Y", "Y (Up)", "Bevy's Y axis, which points up"),
    ("Z", "Z", "Bevy's Z axis"),
]


def _is_body(_self, obj):
    return component_of(obj, "RIGID_BODY") is not None or component_of(obj, "COLLIDER") is not None


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
    collider_friction: FloatProperty(name="Friction", description="How strongly the collider resists sliding, from 0 (ice) to 1 (rubber), averaged with the surface it touches", default=0.5, min=0.0, soft_max=1.0, update=sync_changed)
    collider_restitution: FloatProperty(name="Restitution", description="How much speed the collider keeps when it bounces, from 0 (no bounce) to 1 (full bounce), averaged with the surface it touches", default=0.0, min=0.0, soft_max=1.0, update=sync_changed)
    collider_memberships: BoolVectorProperty(name="Belongs To", description="Collision layers the collider is on", size=LAYER_COUNT, default=(True,) + (False,) * (LAYER_COUNT - 1), update=sync_changed)
    collider_filters: BoolVectorProperty(name="Collides With", description="Collision layers the collider touches. Two colliders touch only when each is on a layer the other collides with", size=LAYER_COUNT, default=(True,) * LAYER_COUNT, update=sync_changed)
    show_layers: BoolProperty(name="Collision Layers", description="Show the collider's collision layers", default=False)

    rigid_body_kind: EnumProperty(name="Type", items=[
        ("STATIC", "Static", "Never moves"),
        ("DYNAMIC", "Dynamic", "Moved by forces and gravity"),
        ("KINEMATIC", "Kinematic", "Moved by game code and pushes dynamic bodies"),
    ], default="STATIC", update=sync_changed)
    rigid_body_use_mass: BoolProperty(name="Set Mass", description="Use a fixed total mass instead of one computed from the colliders' volume at 1 kg per cubic meter", default=False, update=sync_changed)
    rigid_body_mass: FloatProperty(name="Mass", description="Total mass of the body, including colliders on child objects", default=1.0, min=0.001, precision=3, unit="MASS", update=sync_changed)
    shadows_cast: BoolProperty(name="Cast", description="Cast shadows onto other objects. Off adds Bevy's NotShadowCaster to the meshes on and under the object", default=False, update=sync_changed)
    shadows_receive: BoolProperty(name="Receive", description="Show shadows cast by other objects. Off adds Bevy's NotShadowReceiver to the meshes on and under the object", default=True, update=sync_changed)

    audio_path: StringProperty(name="Sound", description="Path of the sound inside your game's assets folder, such as sounds/fire.ogg. Bevy plays .ogg files by default and .wav, .mp3 and .flac with its matching cargo features", default="", update=sync_changed)
    audio_volume: FloatProperty(name="Volume", description="How loud the sound plays, where 1 is its original volume", default=1.0, min=0.0, soft_max=1.0, subtype="FACTOR", update=sync_changed)
    audio_loop: BoolProperty(name="Loop", description="Repeat the sound forever instead of playing it once", default=False, update=sync_changed)
    audio_autoplay: BoolProperty(name="Autoplay", description="Start playing when the level loads. Off starts the sound paused, for your game to play through its AudioSink", default=True, update=sync_changed)
    audio_spatial: BoolProperty(name="Spatial", description="Pan and fade the sound by where it is relative to the game's SpatialListener, usually on the camera or player", default=True, update=sync_changed)
    audio_distance: FloatProperty(name="Distance", description="Distance within which the sound plays at full volume. Farther away it gets quieter: a quarter as loud at twice the distance and 1% as loud at ten times", default=5.0, min=0.01, unit="LENGTH", update=sync_changed)

    rigid_body_gravity_scale: FloatProperty(name="Gravity Scale", description="Multiplies gravity for this body. 0 makes it float and negative values make it rise", default=1.0, soft_min=-2.0, soft_max=2.0, update=sync_changed)
    rigid_body_linear_damping: FloatProperty(name="Linear Damping", description="Slows the body's movement over time, like air resistance", default=0.0, min=0.0, soft_max=10.0, update=sync_changed)
    rigid_body_angular_damping: FloatProperty(name="Angular Damping", description="Slows the body's spin over time", default=0.0, min=0.0, soft_max=10.0, update=sync_changed)
    rigid_body_lock_translation: BoolVectorProperty(name="Lock Position", description="World axes the body cannot move along, on Bevy's axes (Y up)", size=3, default=(False, False, False), update=sync_changed)
    rigid_body_lock_rotation: BoolVectorProperty(name="Lock Rotation", description="World axes the body cannot turn around, on Bevy's axes (Y up)", size=3, default=(False, False, False), update=sync_changed)
    rigid_body_ccd: EnumProperty(name="Continuous Collision", description="Sweeps fast bodies along their path so they do not pass through thin colliders", items=[
        ("DEFAULT", "Static and Kinematic", "Sweep fast movement against static and kinematic bodies, so the body does not pass through walls. This is Avian's default"),
        ("ALL", "All Bodies", "Also sweep against dynamic bodies and colliders without a body, for small fast objects such as bullets"),
        ("OFF", "Off", "Never sweep, which is cheaper but lets fast bodies pass through thin colliders"),
    ], default="DEFAULT", update=sync_changed)
    rigid_body_linear_velocity: FloatVectorProperty(name="Velocity", description="Velocity the body starts with, along Bevy's world axes (Y up). Kinematic bodies keep it until game code changes it", size=3, subtype="XYZ", unit="VELOCITY", update=sync_changed)
    rigid_body_angular_velocity: FloatVectorProperty(name="Angular Velocity", description="Spin per second the body starts with, around Bevy's world axes (Y up). Kinematic bodies keep it until game code changes it", size=3, subtype="XYZ", unit="ROTATION", update=sync_changed)
    show_velocity: BoolProperty(name="Initial Velocity", description="Show the velocity the body starts with", default=False)
    show_dynamics: BoolProperty(name="Dynamics", description="Show damping, locked axes and continuous collision", default=False)

    joint_kind: EnumProperty(name="Type", items=JOINT_TYPES, default="REVOLUTE", update=sync_changed)
    joint_body1: PointerProperty(type=bpy.types.Object, name="Body 1", description="First body the joint connects, an object with a Rigid Body or Collider. Leave empty to pin Body 2 to this spot in the level", poll=_is_body, update=sync_changed)
    joint_body2: PointerProperty(type=bpy.types.Object, name="Body 2", description="Second body the joint connects, an object with a Rigid Body or Collider. Leave empty to pin Body 1 to this spot in the level", poll=_is_body, update=sync_changed)
    joint_axis: EnumProperty(name="Axis", description="Axis of this object that the bodies turn around, slide along or twist around, on Bevy's axes (Y up)", items=AXES, default="Y", update=sync_changed)
    joint_use_limits: BoolProperty(name="Limits", description="Limit how far the bodies turn, slide or twist away from where they are in Blender", default=False, update=sync_changed)
    joint_angle_min: FloatProperty(name="Min", description="Furthest Body 2 turns backwards around the axis, relative to Body 1", default=radians(-90), soft_min=radians(-180), soft_max=radians(180), subtype="ANGLE", update=sync_changed)
    joint_angle_max: FloatProperty(name="Max", description="Furthest Body 2 turns forwards around the axis, relative to Body 1", default=radians(90), soft_min=radians(-180), soft_max=radians(180), subtype="ANGLE", update=sync_changed)
    joint_distance_min: FloatProperty(name="Min", description="Furthest Body 2 slides backwards along the axis, relative to Body 1", default=-1.0, unit="LENGTH", update=sync_changed)
    joint_distance_max: FloatProperty(name="Max", description="Furthest Body 2 slides forwards along the axis, relative to Body 1", default=1.0, unit="LENGTH", update=sync_changed)
    joint_use_swing: BoolProperty(name="Swing Limit", description="Keep the bodies' axes within a cone of each other", default=False, update=sync_changed)
    joint_swing: FloatProperty(name="Swing Limit", description="Largest angle between the bodies' axes, the half angle of the cone", default=radians(45), min=0.0, max=radians(180), subtype="ANGLE", update=sync_changed)
    joint_linear_damping: FloatProperty(name="Linear Damping", description="Slows how fast the bodies move relative to each other", default=0.0, min=0.0, soft_max=10.0, update=sync_changed)
    joint_angular_damping: FloatProperty(name="Angular Damping", description="Slows how fast the bodies turn relative to each other, so a door or pendulum settles", default=0.0, min=0.0, soft_max=10.0, update=sync_changed)
    joint_collide: BoolProperty(name="Collide Bodies", description="Let the two connected bodies collide with each other", default=False, update=sync_changed)
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
    joints: BoolProperty(name="Joints", description="Draw joint axes and limits, and lines to the bodies they connect. Joints of selected bodies are drawn too", default=True, update=redraw_viewports)
    velocities: BoolProperty(name="Velocities", description="Draw the velocity and spin rigid bodies start with as arrows", default=True, update=redraw_viewports)
    visibility_ranges: BoolProperty(name="Visibility Ranges", description="Draw fade distances as spheres", default=True, update=redraw_viewports)
    audio_ranges: BoolProperty(name="Audio Ranges", description="Draw where spatial sounds play at full volume and where they fade to 1%", default=True, update=redraw_viewports)
    labels: BoolProperty(name="Labels", description="Write component details next to each object", default=True, update=redraw_viewports)
    xray: BoolProperty(name="In Front", description="Draw previews on top of other geometry", default=False, update=redraw_viewports)
    edit_handles: BoolProperty(name="Resize Handles", description="Drag arrow gizmos on the selected active object to resize box, sphere and capsule colliders and spatial audio ranges", default=True, update=redraw_viewports)
    max_mesh_edges: IntProperty(name="Max Mesh Edges", description="Draw triangle mesh colliders with more edges than this as bounding boxes", default=2000, min=64, max=20000, update=redraw_viewports)
