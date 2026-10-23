from math import radians

import bpy
from bpy.props import BoolProperty, BoolVectorProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, IntVectorProperty, PointerProperty, StringProperty

from .system import component_of, custom_type_changed, definition_renamed, field_changed, light_bias_toggled, light_intensity_toggled, redraw_viewports, sync_changed

COMPONENT_TYPES = [
    ("VISIBILITY_RANGE", "Visibility Range", "Fade the object in and out by camera distance, for levels of detail", "HIDE_OFF", 0),
    ("COLLIDER", "Collider", "Avian collision shape", "MOD_PHYSICS", 1),
    ("RIGID_BODY", "Rigid Body", "Avian rigid body that is static, dynamic or kinematic", "RIGID_BODY", 2),
    ("CUSTOM", "Custom Component", "Any Rust component, filled in from JSON by your game", "FILE_SCRIPT", 4),
    ("JOINT", "Joint", "Avian joint that connects two rigid bodies, or pins one body to a spot in the scene", "CON_PIVOT", 5),
    ("SCENE_REFERENCE", "Scene Reference", "Spawn a scene from another glTF file at this object, like a prefab", "OUTLINER_OB_GROUP_INSTANCE", 10),
    ("ANIMATION", "Animation", "Play an animation clip when the scene loads", "ACTION", 11),
    ("SHADOWS", "Shadows", "Stop the object's meshes from casting or receiving shadows", "SHADING_RENDERED", 15),
    ("LIGHT", "Light", "Bevy settings that glTF leaves out of a light, such as shadows, and area lights as rectangle lights", "LIGHT", 25),
    ("AUDIO_PLAYER", "Audio Player", "Play a sound from your game's assets folder, optionally in 3D at the object's position", "SPEAKER", 16),
    ("FOG_VOLUME", "Fog Volume", "Box of volumetric fog, seen by cameras with VolumetricFog once a light has VolumetricLight", "OUTLINER_OB_VOLUME", 20),
    ("REFLECTION_PROBE", "Reflection Probe", "Box whose meshes reflect a cubemap embedded in the exported scene", "LIGHTPROBE_SPHERE", 21),
    ("IRRADIANCE_VOLUME", "Irradiance Volume", "Box of light samples, from a 3D texture embedded in the exported scene, that light the meshes inside it", "LIGHTPROBE_VOLUME", 22),
    ("LIGHTMAP", "Lightmap", "Light baked into a texture embedded in the exported scene, which lights this static mesh through its second UV map", "SHADING_TEXTURE", 23),
    ("NAVIGATION", "Navigation", "Tag the meshes and colliders on and under the object as ground that agents walk on or as obstacles they go around, for a navmesh crate", "CON_FOLLOWPATH", 30),
]

COMPONENT_LABELS = {identifier: (name, icon) for identifier, name, _description, icon, _number in COMPONENT_TYPES}
LAYER_COUNT = 32
AUDIO_FORMATS = (".ogg", ".oga", ".spx", ".wav", ".mp3", ".flac")
PATH_OPTIONS = {"PATH_SUPPORTS_BLEND_RELATIVE"} if "is_path_supports_blend_relative" in bpy.types.Property.bl_rna.properties else set()
TEXTURE_COMPRESSION = [
    ("DISABLED", "Disabled", "Export ordinary embedded textures"),
    ("ETC1S", "ETC1S", "Compress every texture as ETC1S KTX2, for the smallest files"),
    ("UASTC", "UASTC", "Compress every texture as UASTC KTX2, for the best quality"),
    ("AUTOMATIC", "Automatic", "UASTC for normal maps, data textures such as metallic-roughness and pixel art with Closest sampling, ETC1S for other color textures"),
]

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

BAKE_SIZES = (64, 128, 256, 512, 1024)
LIGHTMAP_SIZES = (64, 128, 256, 512, 1024, 2048)
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
    audio_autoplay: BoolProperty(name="Autoplay", description="Start playing when the scene loads. Off starts the sound paused, for your game to play through its AudioSink", default=True, update=sync_changed)
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
    joint_body1: PointerProperty(type=bpy.types.Object, name="Body 1", description="First body the joint connects, an object with a Rigid Body or Collider. Leave empty to pin Body 2 to this spot in the scene", poll=_is_body, update=sync_changed)
    joint_body2: PointerProperty(type=bpy.types.Object, name="Body 2", description="Second body the joint connects, an object with a Rigid Body or Collider. Leave empty to pin Body 1 to this spot in the scene", poll=_is_body, update=sync_changed)
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

    volume_size: FloatVectorProperty(name="Size", description="Box dimensions along Bevy's local X, Y (up) and Z axes", size=3, subtype="XYZ", default=(10.0, 5.0, 10.0), min=0.001, unit="LENGTH", update=sync_changed)
    volume_falloff: FloatProperty(name="Falloff", description="Share of the box, from its walls inward, over which the probe's light fades out, so that neighbouring probes blend", default=0.0, min=0.0, max=1.0, subtype="FACTOR", update=sync_changed)
    fog_color: FloatVectorProperty(name="Color", description="Color of the fog where light reaches it", size=3, subtype="COLOR_GAMMA", default=(1.0, 1.0, 1.0), min=0.0, max=1.0, update=sync_changed)
    fog_density: FloatProperty(name="Density", description="How thick the fog is", default=0.1, min=0.0, soft_max=1.0, update=sync_changed)
    fog_absorption: FloatProperty(name="Absorption", description="How much light the fog swallows, which darkens it", default=0.3, min=0.0, soft_max=1.0, update=sync_changed)
    fog_scattering: FloatProperty(name="Scattering", description="How much light the fog scatters, which brightens it where light reaches it", default=0.3, min=0.0, soft_max=1.0, update=sync_changed)
    fog_anisotropy: FloatProperty(name="Anisotropy", description="Direction light scatters in: positive values scatter it forward, so light shafts show when the camera faces the light", default=0.5, min=-0.99, max=0.99, update=sync_changed)
    fog_light_tint: FloatVectorProperty(name="Light Tint", description="Tints the light inside the fog, an artistic control that is not physically based", size=3, subtype="COLOR_GAMMA", default=(1.0, 1.0, 1.0), min=0.0, max=1.0, update=sync_changed)
    fog_light_intensity: FloatProperty(name="Light Intensity", description="Scales the light inside the fog, an artistic control that is not physically based", default=1.0, min=0.0, soft_max=10.0, update=sync_changed)
    probe_intensity: FloatProperty(name="Intensity", description="Brightness in candela per square meter that a texture value of 1 gives. The default, 683, converts Blender's light units the way the glTF export converts lights, so baked lighting matches the exported lamps", default=683.0, min=0.0, soft_max=100000.0, update=sync_changed)
    probe_parallax: BoolProperty(name="Parallax Correction", description="Reflect the surroundings as if they lie on the box walls, which suits rooms. Turn off for open areas whose surroundings are far away", default=True, update=sync_changed)
    probe_file: StringProperty(name="File", description="KTX2 file that the export embeds in the scene: a cubemap for a Reflection Probe, a 3D texture for an Irradiance Volume, a 2D texture for a Lightmap", subtype="FILE_PATH", options=PATH_OPTIONS, update=sync_changed)
    bake_resolution: EnumProperty(name="Bake Size", description="Size of each cubemap face that Bake renders", items=[(str(size), f"{size} px", f"{size} × {size} pixels per cubemap face, which adds {size * size * 48 / 2 ** 20:.2g} MB to the exported scene") for size in BAKE_SIZES], default="256")
    bake_voxels: IntVectorProperty(name="Voxels", description="Light samples that Bake places along the box's X, Y (up) and Z axes", size=3, default=(8, 4, 8), min=1, max=64)
    lightmap_resolution: EnumProperty(name="Bake Size", description="Size of the lightmap that Bake renders. Unwrap the lightmap UVs again after changing it, so their islands stay a few pixels apart", items=[(str(size), f"{size} px", f"{size} × {size} pixels, which adds {size * size * 4 / 2 ** 20:.2g} MB to the exported scene") for size in LIGHTMAP_SIZES], default="512")
    lightmap_bicubic: BoolProperty(name="Bicubic Sampling", description="Smooth the lightmap's pixels with bicubic filtering, which costs a little more on the GPU and can leak light across nearby UV islands", default=False, update=sync_changed)

    light_use_intensity: BoolProperty(name="Set Intensity", description="Use this brightness in Bevy instead of the one converted from the light's power at 683 lumens per watt", default=False, update=light_intensity_toggled)
    light_intensity: FloatProperty(name="Intensity", description="Brightness in Bevy, in lumens for point, spot and area lights and in lux for sun lights", default=1000.0, min=0.0, soft_max=1000000.0, precision=1, update=sync_changed)
    light_baked: BoolProperty(name="Baked", description="Bake Lighting bakes this light's direct light into lightmaps, so on meshes with a lightmap Bevy only adds its reflections", default=False, update=sync_changed)
    light_volumetric: BoolProperty(name="Volumetric", description="Light up fog volumes with light shafts. Needs Shadows, and VolumetricFog on the game's camera", default=False, update=sync_changed)
    light_contact_shadows: BoolProperty(name="Contact Shadows", description="Add screen-space shadows where objects touch. Needs ContactShadows and a depth prepass on the game's camera", default=False, update=sync_changed)
    light_use_bias: BoolProperty(name="Custom Bias", description="Tune the shadow map instead of using Bevy's defaults for this kind of light", default=False, update=light_bias_toggled)
    light_depth_bias: FloatProperty(name="Depth Bias", description="Pushes shadows away from surfaces to stop shadow acne, too much detaches them from objects", default=0.02, min=0.0, soft_max=1.0, precision=3, update=sync_changed)
    light_normal_bias: FloatProperty(name="Normal Bias", description="Offsets shadow lookups along the surface normal to stop shadow acne on slopes", default=1.8, min=0.0, soft_max=5.0, precision=2, update=sync_changed)
    light_near_clip: FloatProperty(name="Near Clip", description="Objects closer to the light than this cast no shadow", default=0.1, min=0.001, precision=3, unit="LENGTH", update=sync_changed)
    light_use_cascades: BoolProperty(name="Custom Cascades", description="Choose how the sun's shadow map is split by distance from the camera instead of Bevy's 4 cascades up to 150 m", default=False, update=sync_changed)
    light_cascade_count: IntProperty(name="Cascades", description="Number of shadow maps, more keeps shadows sharp further away and costs more", default=4, min=1, max=4, update=sync_changed)
    light_cascade_near: FloatProperty(name="Near", description="Distance from the camera where shadows start", default=0.1, min=0.0, precision=3, unit="LENGTH", update=sync_changed)
    light_cascade_first: FloatProperty(name="First Cascade", description="Distance from the camera that the first and sharpest cascade covers", default=10.0, min=0.001, unit="LENGTH", update=sync_changed)
    light_cascade_far: FloatProperty(name="Max Distance", description="Distance from the camera where shadows end", default=150.0, min=0.001, unit="LENGTH", update=sync_changed)
    light_cascade_overlap: FloatProperty(name="Overlap", description="How far neighbouring cascades overlap, which hides the seam between them", default=0.2, min=0.0, max=0.95, subtype="FACTOR", update=sync_changed)
    show_shadows: BoolProperty(name="Shadows", description="Show the light's shadow settings", default=False)
    custom_type: StringProperty(name="Type Path", description="Rust type path of the component, such as my_game::Health. Pick a type defined in Properties > Scene to edit its fields instead of JSON", default="my_game::MyComponent", update=custom_type_changed)
    custom_json: StringProperty(name="Data", description="Component fields as JSON, read by your game code", default="{}", update=sync_changed)
    use_fields: BoolProperty(name="Use Fields", description="Edit the data as the fields defined in Properties > Scene instead of JSON")
    fields: CollectionProperty(type=BEVY_PG_field)
    scene_file: StringProperty(name="File", description="glTF file whose scene spawns at this object. It is stored relative to the exported scene, so keep both in your game's assets folder", subtype="FILE_PATH", options=PATH_OPTIONS, update=sync_changed)
    scene_index: IntProperty(name="Scene", description="Which scene of the file to spawn, counting from 0 like Bevy's Scene0 label", default=0, min=0, update=sync_changed)
    animation_clip: StringProperty(name="Clip", description="Action to play, exported as the glTF animation of the same name", update=sync_changed)
    animation_loop: BoolProperty(name="Loop", description="Start over at the end instead of stopping on the last frame", default=True, update=sync_changed)
    animation_speed: FloatProperty(name="Speed", description="Playback speed, where 1 matches the timing in Blender", default=1.0, min=0.0, soft_max=4.0, update=sync_changed)
    navigation_kind: EnumProperty(name="Type", items=[
        ("WALKABLE", "Walkable", "Ground that agents walk on, such as floors, ramps and stairs. Its meshes and colliders get NavigationWalkable"),
        ("OBSTACLE", "Obstacle", "Something agents go around, such as walls, crates and trees. Its meshes and colliders get NavigationObstacle"),
        ("IGNORED", "Ignored", "Leave the meshes and colliders out of navigation, even when a parent has Navigation, such as small props on walkable ground"),
    ], default="WALKABLE", update=sync_changed)
    navigation_cost: FloatProperty(name="Cost", description="How much agents avoid this ground when they find a path: each meter here counts as Cost meters, so 1 is plain ground, 3 suits mud and 0.5 a road", default=1.0, min=0.01, soft_max=10.0, update=sync_changed)


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


class BEVY_PG_ambient_light(bpy.types.PropertyGroup):
    enabled: BoolProperty(name="Bevy Ambient Light", description="Export the scene's ambient light, which the importer sets as Bevy's GlobalAmbientLight", default=False)
    use_world_color: BoolProperty(name="From World", description="Use the World's background color and strength, converted at 683 lumens per watt like lights", default=True)
    color: FloatVectorProperty(name="Color", description="Color of the ambient light", size=3, subtype="COLOR", default=(1.0, 1.0, 1.0), min=0.0, max=1.0)
    brightness: FloatProperty(name="Brightness", description="Ambient brightness in candela per square meter, Bevy's default is 80", default=80.0, min=0.0, soft_max=2000.0, precision=1)
    baked: BoolProperty(name="Baked", description="The ambient light is already baked into lightmaps, so it skips meshes with a lightmap", default=False)


class BEVY_PG_bake_settings(bpy.types.PropertyGroup):
    samples: IntProperty(name="Samples", description="Cycles samples per pixel. More samples give smoother light and take longer", default=128, min=1, soft_max=4096)
    folder: StringProperty(name="Folder", description="Folder for the baked .ktx2 files, where // is the folder of the .blend file", subtype="DIR_PATH", default="//baked_lighting/", options=PATH_OPTIONS)
    lamp_direct: BoolProperty(name="Direct Lamp Light", description="Also bake the light that lamps shine straight onto irradiance volumes. Leave it off when the scene exports its lamps, since Bevy already lights meshes with them", default=False)


class ExportOptions:
    selected_only: BoolProperty(name="Selected Objects Only", default=False)
    include_lights: BoolProperty(name="Include Lights", default=True)
    include_cameras: BoolProperty(name="Include Cameras", default=False)
    include_animations: BoolProperty(name="Include Animations", default=False)
    texture_compression: EnumProperty(name="Texture Compression", description="Convert textures to KTX2 with KTX-Software and embed them in the GLB", items=TEXTURE_COMPRESSION, default="DISABLED")
    etc1s_quality: IntProperty(name="ETC1S Quality", description="Higher keeps more detail in ETC1S textures and makes them larger", default=128, min=1, max=255)
    etc1s_effort: IntProperty(name="ETC1S Effort", description="Higher encodes ETC1S textures more slowly with slightly better quality", default=2, min=0, max=6)
    uastc_quality: IntProperty(name="UASTC Quality", description="Higher encodes UASTC textures more slowly with better quality", default=2, min=0, max=4)
    uastc_zstd: IntProperty(name="UASTC Supercompression", description="Zstandard level that shrinks UASTC textures in the file, 0 turns it off", default=18, min=0, max=22)


EXPORT_OPTIONS = tuple(ExportOptions.__annotations__)


class BEVY_PG_glb_export(bpy.types.PropertyGroup, ExportOptions):
    filepath: StringProperty(name="GLB File", description="GLB file that the last export wrote, which Export Again writes again", subtype="FILE_PATH", options=PATH_OPTIONS)


class BEVY_PG_bsn_export(bpy.types.PropertyGroup, ExportOptions):
    rust_file: StringProperty(name="Rust File", description="Rust file that the last BSN export wrote, which Export Again writes again", subtype="FILE_PATH", options=PATH_OPTIONS)
    assets_folder: StringProperty(name="Assets Folder", description="Assets folder that the last BSN export wrote, empty for the default next to Cargo.toml", subtype="DIR_PATH", options=PATH_OPTIONS)
    prefab_functions: BoolProperty(name="Prefab Functions", description="Whether the last BSN export wrote shared objects as object_ functions", default=True)
    written_files: StringProperty(name="Written Files", description="Assets folder and files that the last BSN export wrote there, so the next export can remove the ones it no longer needs", options={"HIDDEN"})


class BEVY_PG_viewport_settings(bpy.types.PropertyGroup):
    enabled: BoolProperty(name="Bevy Components", description="Draw Bevy component previews in the 3D Viewport while the Components panel in Properties is expanded, never exported", default=True, update=redraw_viewports)
    scope: EnumProperty(name="Draw On", items=[
        ("SELECTED", "Selected", "Draw previews for selected objects only"),
        ("ALL", "All", "Draw previews for every visible object with Bevy components"),
    ], default="SELECTED", update=redraw_viewports)
    colliders: BoolProperty(name="Colliders", description="Draw collider shapes", default=True, update=redraw_viewports)
    joints: BoolProperty(name="Joints", description="Draw joint axes and limits, and lines to the bodies they connect. Joints of selected bodies are drawn too", default=True, update=redraw_viewports)
    velocities: BoolProperty(name="Velocities", description="Draw the velocity and spin rigid bodies start with as arrows", default=True, update=redraw_viewports)
    visibility_ranges: BoolProperty(name="Visibility Ranges", description="Draw fade distances as spheres", default=True, update=redraw_viewports)
    audio_ranges: BoolProperty(name="Audio Ranges", description="Draw where spatial sounds play at full volume and where they fade to 1%", default=True, update=redraw_viewports)
    scene_references: BoolProperty(name="Scene References", description="Draw the bounds of referenced scenes", default=True, update=redraw_viewports)
    volumes: BoolProperty(name="Fog and Probes", description="Draw fog volume and light probe boxes", default=True, update=redraw_viewports)
    lights: BoolProperty(name="Light Ranges", description="Draw how far each light reaches in Bevy, where it stops lighting anything", default=True, update=redraw_viewports)
    navigation: BoolProperty(name="Navigation", description="Draw the faces of walkable ground that slope less than 45°, and the bounds of obstacles", default=True, update=redraw_viewports)
    labels: BoolProperty(name="Labels", description="Write component details next to each object", default=True, update=redraw_viewports)
    xray: BoolProperty(name="In Front", description="Draw previews on top of other geometry", default=False, update=redraw_viewports)
    edit_handles: BoolProperty(name="Resize Handles", description="Drag arrow gizmos on the selected active object to resize box, sphere and capsule colliders, spatial audio ranges, fog volumes and light probes", default=True, update=redraw_viewports)
    max_mesh_edges: IntProperty(name="Max Mesh Edges", description="Draw triangle mesh colliders with more edges than this as bounding boxes", default=2000, min=64, max=20000, update=redraw_viewports)
