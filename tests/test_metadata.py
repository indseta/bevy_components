import importlib.util
import json
import pathlib
import types
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "addon" / "metadata.py"
spec = importlib.util.spec_from_file_location("bevy_metadata", MODULE)
metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata)


def item(**kwargs):
    return types.SimpleNamespace(**kwargs)


def body(**kwargs):
    values = {"component_type": "RIGID_BODY", "rigid_body_kind": "STATIC", "rigid_body_use_mass": False, "rigid_body_mass": 1.0, "rigid_body_gravity_scale": 1.0, "rigid_body_linear_damping": 0.0, "rigid_body_angular_damping": 0.0, "rigid_body_lock_translation": (False, False, False), "rigid_body_lock_rotation": (False, False, False), "rigid_body_ccd": "DEFAULT", "rigid_body_linear_velocity": (0.0, 0.0, 0.0), "rigid_body_angular_velocity": (0.0, 0.0, 0.0)}
    return item(**{**values, **kwargs})


def collider(**kwargs):
    values = {"component_type": "COLLIDER", "collider_shape": "CUBOID", "collider_size": (1, 1, 1), "collider_radius": 0.5, "collider_height": 1.0, "collider_offset": (0.0, 0.0, 0.0), "collider_sensor": False, "collider_events": False, "collider_collision_only": False, "collider_friction": 0.5, "collider_restitution": 0.0, "collider_memberships": [True] + [False] * 31, "collider_filters": [True] * 32}
    return item(**{**values, **kwargs})


def joint(**kwargs):
    values = {"component_type": "JOINT", "joint_kind": "REVOLUTE", "joint_body1": None, "joint_body2": None, "joint_axis": "Y", "joint_use_limits": False, "joint_angle_min": -1.0, "joint_angle_max": 1.0, "joint_distance_min": -2.0, "joint_distance_max": 2.0, "joint_use_swing": False, "joint_swing": 0.5, "joint_linear_damping": 0.0, "joint_angular_damping": 0.0, "joint_collide": False}
    return item(**{**values, **kwargs})


def field(name, field_type, value, variants="", rust_type=""):
    values = {"float_value": 0.0, "int_value": 0, "bool_value": False, "string_value": "", "vector2_value": (0.0, 0.0), "vector_value": (0.0, 0.0, 0.0), "color_value": (1.0, 1.0, 1.0, 1.0)}
    values[metadata.FIELD_VALUES[field_type]] = value
    return item(name=name, field_type=field_type, variants=variants, rust_type=rust_type, **values)


class TestMetadata(unittest.TestCase):
    def test_visibility(self):
        component = item(component_type="VISIBILITY_RANGE", fade_in_start=0, fade_in_end=0, fade_out_start=20, fade_out_end=25, use_aabb=False)
        result = json.loads(metadata.serialize_items([component]))
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["components"][0], {"type": "visibility_range", "start": [0, 0], "end": [20, 25], "use_aabb": False})
        self.assertEqual(metadata.validate_items([component]), [])

    def test_invalid_visibility(self):
        component = item(component_type="VISIBILITY_RANGE", fade_in_start=5, fade_in_end=20, fade_out_start=10, fade_out_end=25)
        self.assertTrue(metadata.validate_items([component]))

    def test_collider(self):
        component = collider(collider_shape="CONVEX", collider_size=(1, 2, 3), collider_offset=(1.0, 2.0, 3.0), collider_sensor=True, collider_events=True, collider_collision_only=True, collider_friction=0.25, collider_restitution=0.75, collider_memberships=[index in {0, 3} for index in range(32)], collider_filters=[index != 1 for index in range(32)])
        result = json.loads(metadata.serialize_items([component]))
        self.assertEqual(result["components"][0], {"type": "collider", "shape": "convex", "size": [1, 2, 3], "radius": 0.5, "height": 1.0, "offset": None, "sensor": True, "events": True, "collision_only": True, "friction": 0.25, "restitution": 0.75, "memberships": 0b1001, "filters": 0xFFFFFFFD})

    def test_primitive_collider_offset(self):
        for shape in ("CUBOID", "SPHERE", "CAPSULE"):
            component = collider(collider_shape=shape, collider_offset=(0.1, -0.25, 3.0))
            result = json.loads(metadata.serialize_items([component]))["components"][0]
            self.assertEqual((result["offset"], result["events"], result["collision_only"]), ([0.1, -0.25, 3.0], False, False), shape)

    def test_collider_layer_extremes(self):
        component = collider(collider_memberships=[False] * 32, collider_filters=[True] * 32)
        result = json.loads(metadata.serialize_items([component]))["components"][0]
        self.assertEqual((result["memberships"], result["filters"]), (0, 2**32 - 1))

    def test_rigid_body_mass(self):
        component = body(rigid_body_kind="DYNAMIC", rigid_body_mass=12.5)
        self.assertIsNone(json.loads(metadata.serialize_items([component]))["components"][0]["mass"])
        component.rigid_body_use_mass = True
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0]["mass"], 12.5)
        for kind in ("STATIC", "KINEMATIC"):
            component.rigid_body_kind = kind
            self.assertIsNone(json.loads(metadata.serialize_items([component]))["components"][0]["mass"], kind)

    def test_shadows(self):
        component = item(component_type="SHADOWS", shadows_cast=False, shadows_receive=True)
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0], {"type": "shadows", "cast": False, "receive": True})
        self.assertEqual(metadata.component_errors(component), [])

    def test_navigation(self):
        component = item(component_type="NAVIGATION", navigation_kind="WALKABLE", navigation_cost=2.5)
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0], {"type": "navigation", "kind": "walkable", "cost": 2.5})
        for kind in ("OBSTACLE", "IGNORED"):
            component.navigation_kind = kind
            self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0], {"type": "navigation", "kind": kind.lower(), "cost": None})
        self.assertEqual(metadata.component_errors(component), [])

    def test_audio_player(self):
        component = item(component_type="AUDIO_PLAYER", audio_path=" sounds/fire.ogg ", audio_volume=0.699999988079071, audio_loop=True, audio_autoplay=False, audio_spatial=True, audio_distance=2.5)
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0], {"type": "audio_player", "path": "sounds/fire.ogg", "volume": 0.7, "loop": True, "autoplay": False, "spatial": True, "distance": 2.5})
        component.audio_path = ""
        self.assertEqual(metadata.component_errors(component), [])

    def test_rigid_body_tuning(self):
        component = body(rigid_body_kind="DYNAMIC", rigid_body_gravity_scale=-0.5, rigid_body_linear_damping=0.25, rigid_body_angular_damping=2.0, rigid_body_lock_translation=(False, True, False), rigid_body_lock_rotation=(True, False, True), rigid_body_ccd="ALL", rigid_body_linear_velocity=(1.0, 2.0, 3.0), rigid_body_angular_velocity=(0.0, 1.5, 0.0))
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0], {"type": "rigid_body", "kind": "dynamic", "mass": None, "gravity_scale": -0.5, "linear_damping": 0.25, "angular_damping": 2.0, "lock_translation": [False, True, False], "lock_rotation": [True, False, True], "ccd": "all", "linear_velocity": [1.0, 2.0, 3.0], "angular_velocity": [0.0, 1.5, 0.0]})
        component.rigid_body_kind = "KINEMATIC"
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0], {"type": "rigid_body", "kind": "kinematic", "mass": None, "gravity_scale": None, "linear_damping": None, "angular_damping": None, "lock_translation": None, "lock_rotation": None, "ccd": None, "linear_velocity": [1.0, 2.0, 3.0], "angular_velocity": [0.0, 1.5, 0.0]})
        component.rigid_body_kind = "STATIC"
        exported = json.loads(metadata.serialize_items([component]))["components"][0]
        self.assertEqual({key: value for key, value in exported.items() if value is not None}, {"type": "rigid_body", "kind": "static"})

    def test_locked_axes_cancel_initial_velocity(self):
        component = body(rigid_body_kind="DYNAMIC", rigid_body_lock_translation=(False, True, False), rigid_body_lock_rotation=(True, True, True), rigid_body_linear_velocity=(1.0, 2.0, 3.0), rigid_body_angular_velocity=(4.0, 5.0, 6.0))
        self.assertEqual(metadata.initial_velocities(component), ([1.0, 0.0, 3.0], [0.0, 0.0, 0.0]))
        component.rigid_body_kind = "KINEMATIC"
        self.assertEqual(metadata.initial_velocities(component), ([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]))

    def test_joint(self):
        frame = item(name="frame")
        door = item(name="door")
        component = joint(joint_body1=frame, joint_body2=door, joint_use_limits=True, joint_angle_min=0.0, joint_angle_max=1.5, joint_angular_damping=0.5)
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0], {"type": "joint", "kind": "revolute", "body1": "frame", "body2": "door", "axis": [0.0, 1.0, 0.0], "angle_limits": [0.0, 1.5], "distance_limits": None, "swing_limit": None, "linear_damping": 0.0, "angular_damping": 0.5, "collide": False})
        self.assertEqual(metadata.validate_items([component]), [])

    def test_joint_types_export_their_own_settings(self):
        component = joint(joint_body2=item(name="link"), joint_axis="X", joint_use_limits=True, joint_use_swing=True, joint_collide=True)
        expected = {
            "FIXED": {"axis": None, "angle_limits": None, "distance_limits": None, "swing_limit": None, "linear_damping": None, "angular_damping": None},
            "REVOLUTE": {"axis": [1.0, 0.0, 0.0], "angle_limits": [-1.0, 1.0], "distance_limits": None, "swing_limit": None, "linear_damping": 0.0, "angular_damping": 0.0},
            "PRISMATIC": {"axis": [1.0, 0.0, 0.0], "angle_limits": None, "distance_limits": [-2.0, 2.0], "swing_limit": None, "linear_damping": 0.0, "angular_damping": 0.0},
            "SPHERICAL": {"axis": [1.0, 0.0, 0.0], "angle_limits": [-1.0, 1.0], "distance_limits": None, "swing_limit": 0.5, "linear_damping": 0.0, "angular_damping": 0.0},
        }
        for kind, settings in expected.items():
            component.joint_kind = kind
            self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0], {"type": "joint", "kind": kind.lower(), "body1": None, "body2": "link", **settings, "collide": True}, kind)

    def test_inverted_joint_limits(self):
        component = joint(joint_use_limits=True, joint_angle_min=1.0, joint_angle_max=-1.0)
        self.assertEqual(metadata.validate_items([component], "hinge"), ["hinge: Joint limit Min is above Max"])
        component.joint_use_limits = False
        self.assertEqual(metadata.validate_items([component]), [])
        component.joint_use_limits = True
        component.joint_kind = "PRISMATIC"
        self.assertEqual(metadata.validate_items([component]), [])
        component.joint_distance_min = 3.0
        self.assertTrue(metadata.validate_items([component]))
        component.joint_kind = "FIXED"
        self.assertEqual(metadata.validate_items([component]), [])

    def test_fog_volume(self):
        component = item(component_type="FOG_VOLUME", volume_size=(6, 2, 4), fog_color=(1.0, 0.5, 0.25), fog_density=0.20000000298023224, fog_absorption=0.5, fog_scattering=0.75, fog_anisotropy=-0.5, fog_light_tint=(0.5, 1.0, 0.8999999761581421), fog_light_intensity=2.0)
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0], {"type": "fog_volume", "size": [6, 2, 4], "color": [1.0, 0.5, 0.25], "density": 0.2, "absorption": 0.5, "scattering": 0.75, "anisotropy": -0.5, "light_tint": [0.5, 1.0, 0.9], "light_intensity": 2.0})
        self.assertEqual(metadata.validate_items([component]), [])

    def test_light_probes(self):
        reflection = item(component_type="REFLECTION_PROBE", volume_size=(8, 4, 8), volume_falloff=0.25, probe_intensity=2000.0, probe_parallax=False, probe_file="//room.ktx2")
        irradiance = item(component_type="IRRADIANCE_VOLUME", volume_size=(20, 6, 20), volume_falloff=0.0, probe_intensity=500.0, probe_parallax=True, probe_file="")
        reflection_data, irradiance_data = json.loads(metadata.serialize_items([reflection, irradiance]))["components"]
        self.assertEqual(reflection_data, {"type": "reflection_probe", "size": [8, 4, 8], "falloff": [0.25, 0.25, 0.25], "intensity": 2000.0, "parallax_correction": False, "file": "//room.ktx2"})
        self.assertEqual(irradiance_data, {"type": "irradiance_volume", "size": [20, 6, 20], "falloff": [0.0, 0.0, 0.0], "intensity": 500.0, "file": None})
        self.assertEqual(metadata.validate_items([reflection, irradiance]), [])

    def light_item(self, kind, **values):
        light = item(type=kind, energy=10.0, shadow_soft_size=0.25, use_custom_distance=False, cutoff_distance=40.0, use_shadow=True, color=(1.0, 0.5, 0.25), shape="RECTANGLE", size=2.0, size_y=0.5, **values)
        owner = item(type="LIGHT", data=light, matrix_world=item(to_scale=lambda: (2.0, 1.0, 1.0)))
        settings = {"light_use_intensity": False, "light_intensity": 1000.0, "light_baked": False, "light_volumetric": False, "light_contact_shadows": False, "light_use_bias": False, "light_depth_bias": 0.02, "light_normal_bias": 1.8, "light_near_clip": 0.1, "light_use_cascades": False, "light_cascade_count": 4, "light_cascade_near": 0.1, "light_cascade_first": 10.0, "light_cascade_far": 150.0, "light_cascade_overlap": 0.2}
        return item(component_type="LIGHT", id_data=owner, **settings), light

    def test_point_light(self):
        component, light = self.light_item("POINT")
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0], {"type": "light", "kind": "point", "intensity": None, "radius": 0.25, "range": None, "color": None, "size": None, "shadows": True, "contact_shadows": False, "volumetric": False, "baked": False, "depth_bias": None, "normal_bias": None, "near_clip": None, "cascades": None})
        component.light_use_bias = True
        component.light_use_intensity = True
        light.use_shadow = False
        result = json.loads(metadata.serialize_items([component]))["components"][0]
        self.assertEqual((result["intensity"], result["shadows"], result["depth_bias"], result["normal_bias"], result["near_clip"]), (1000.0, False, 0.02, 1.8, 0.1))
        self.assertEqual(metadata.light_intensity(light), 6830.0)
        self.assertEqual(metadata.component_errors(component), [])

    def test_sun_light_cascades(self):
        component, light = self.light_item("SUN")
        component.light_use_cascades = True
        component.light_use_bias = True
        result = json.loads(metadata.serialize_items([component]))["components"][0]
        self.assertEqual((result["kind"], result["radius"], result["near_clip"]), ("directional", None, None))
        self.assertEqual(result["cascades"], {"count": 4, "minimum_distance": 0.1, "first_cascade_far_bound": 10.0, "maximum_distance": 150.0, "overlap_proportion": 0.2})
        self.assertEqual(metadata.light_unit(light), "lx")
        self.assertEqual(metadata.component_errors(component), [])
        component.light_cascade_first = 0.05
        self.assertEqual(metadata.component_errors(component), ["Shadow cascades must satisfy near < first cascade < max distance"])
        component.light_cascade_count = 1
        self.assertEqual(metadata.component_errors(component), [])
        component.light_cascade_far = 0.1
        self.assertEqual(metadata.component_errors(component), ["Shadow cascades must satisfy near < first cascade < max distance"])
        component.light_use_cascades = False
        self.assertEqual(metadata.component_errors(component), [])

    def test_area_light(self):
        component, light = self.light_item("AREA", exposure=1.0)
        component.light_volumetric = True
        component.light_use_bias = True
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0], {"type": "light", "kind": "area", "intensity": 13660.0, "radius": None, "range": None, "color": [1.0, 0.5, 0.25], "size": [2.0, 0.5], "shadows": False, "contact_shadows": False, "volumetric": False, "baked": False, "depth_bias": None, "normal_bias": None, "near_clip": None, "cascades": None})
        light.use_custom_distance = True
        light.shape = "SQUARE"
        light.normalize = False
        result = json.loads(metadata.serialize_items([component]))["components"][0]
        self.assertEqual((result["range"], result["size"], result["intensity"]), (40.0, [2.0, 2.0], 109280.0))
        light.use_temperature = True
        light.temperature_color = (1.0, 0.5, 0.5)
        self.assertEqual(metadata.light_color(light), [1.0, 0.25, 0.125])

    def test_lights_are_skipped_on_other_objects(self):
        component, light = self.light_item("POINT")
        component.id_data = item(type="MESH", data=None)
        self.assertEqual(json.loads(metadata.serialize_items([component])), {"version": 1, "components": []})
        light.type = "UNKNOWN"
        component.id_data = item(type="LIGHT", data=light)
        self.assertIsNone(metadata.light_of(component.id_data))

    def test_light_amounts(self):
        self.assertEqual([metadata.light_amount(value, "lm") for value in (136600, 683.0, 99.5, 12.5, 0.25)], ["136,600 lm", "683 lm", "99.5 lm", "12.5 lm", "0.25 lm"])

    def test_ambient_light(self):
        self.assertEqual(json.loads(metadata.serialize_scene([metadata.ambient_light_component((0.9, 0.95, 1.0, 1.0), 120, False)])), {"version": 1, "components": [{"type": "ambient_light", "color": [0.9, 0.95, 1.0], "brightness": 120.0, "baked": False}]})

    def test_sky(self):
        sky = item(brightness=1000.0, environment_light=True, environment_intensity=0.1, sky_file="//baked_lighting/world_sky.ktx2")
        self.assertEqual(metadata.sky_component(sky), {"type": "sky", "brightness": 1000.0, "environment_light": 0.1, "file": "//baked_lighting/world_sky.ktx2"})
        sky.environment_light = False
        sky.sky_file = ""
        self.assertEqual(metadata.sky_component(sky), {"type": "sky", "brightness": 1000.0, "environment_light": None, "file": None})

    def test_custom(self):
        component = item(component_type="CUSTOM", custom_type="game::Marker", custom_json='{"value":42}', use_fields=False, fields=[])
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0]["data"]["value"], 42)
        component.custom_json = "oops"
        self.assertTrue(metadata.validate_items([component]))
        with self.assertRaises(ValueError):
            metadata.serialize_items([component])

    def test_scene_reference(self):
        component = item(component_type="SCENE_REFERENCE", scene_file="props\\windmill.glb", scene_index=2)
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0], {"type": "scene_reference", "path": "props/windmill.glb", "scene": 2})
        located = json.loads(metadata.serialize_items([component], lambda path: f"located/{path}"))["components"][0]
        self.assertEqual(located["path"], "located/props\\windmill.glb")
        self.assertEqual(metadata.validate_items([component]), [])
        component.scene_file = " "
        self.assertEqual(metadata.validate_items([component], "mill"), ["mill: Scene Reference needs a glTF file"])

    def test_relative_path(self):
        self.assertEqual(metadata.relative_path("/game/assets/props/windmill.glb", "/game/assets/scenes"), "../props/windmill.glb")
        self.assertEqual(metadata.relative_path("/game/assets/scenes/house.glb", "/game/assets/scenes"), "house.glb")

    def test_animation(self):
        component = item(component_type="ANIMATION", animation_clip="door_open", animation_loop=False, animation_speed=0.30000001192092896)
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0], {"type": "animation", "clip": "door_open", "repeat": False, "speed": 0.3})
        self.assertEqual(metadata.validate_items([component]), [])

    def test_component_errors_leave_out_the_object_name(self):
        component = item(component_type="CUSTOM", custom_type=" ", custom_json="oops", use_fields=False)
        self.assertEqual(metadata.component_errors(component), ["Custom Component needs a Rust type path", "invalid JSON in Custom Component"])
        self.assertEqual(metadata.validate_items([component], "lamp"), ["lamp: Custom Component needs a Rust type path", "lamp: invalid JSON in Custom Component"])

    def test_matching_levels_of_detail_crossfade(self):
        self.assertEqual(metadata.visibility_range_problems([("far", (80, 85, 250, 260)), ("near", (0, 0, 20, 25)), ("mid", (20, 25, 80, 85))]), [])

    def test_gaps_between_levels_of_detail(self):
        self.assertEqual(metadata.visibility_range_problems([("near", (0, 0, 20, 25)), ("far", (30, 35, 80, 85))]), [("far", "Gap after near: nothing shows from 25 to 30 m")])

    def test_overlapping_levels_of_detail(self):
        self.assertEqual(metadata.visibility_range_problems([("near", (0, 0, 20, 25)), ("far", (0, 0, 100, 120))]), [("far", "Shows together with near from 0 to 20 m")])

    def test_mismatched_fade_margins(self):
        self.assertEqual(metadata.visibility_range_problems([("near", (0, 0, 20, 25)), ("far", (22.5, 24, 80, 85))]), [("far", "Fades in over 22.5–24 m but near fades out over 20–25 m, so they do not crossfade")])

    def test_parts_of_one_level_of_detail_share_its_range(self):
        entries = [("trunk", (0, 0, 20, 25)), ("leaves", (0, 0, 20, 25)), ("far_trunk", (30, 35, 80, 85)), ("far_leaves", (30, 35, 80, 85))]
        self.assertEqual(metadata.visibility_range_problems(entries), [("far_trunk", "Gap after trunk: nothing shows from 25 to 30 m"), ("far_leaves", "Gap after trunk: nothing shows from 25 to 30 m")])

    def test_custom_fields(self):
        fields = [field("count", "INT", 3), field("delay", "FLOAT", 0.10000000149011612), field("label", "STRING", "Wave ✦"), field("boss", "BOOL", True), field("offset", "VECTOR", (0.0, 1.5, -2.0)), field("tint", "COLOR", (1.0, 0.800000011920929, 0.20000000298023224, 1.0))]
        component = item(component_type="CUSTOM", custom_type="game::Wave", custom_json="{broken", use_fields=True, fields=fields)
        self.assertEqual(metadata.validate_items([component]), [])
        data = json.loads(metadata.serialize_items([component]))["components"][0]
        self.assertEqual(data, {"type": "custom", "type_path": "game::Wave", "data": {"count": 3, "delay": 0.1, "label": "Wave ✦", "boss": True, "offset": [0.0, 1.5, -2.0], "tint": {"Srgba": {"red": 1.0, "green": 0.8, "blue": 0.2, "alpha": 1.0}}}})
        self.assertIsInstance(data["data"]["count"], int)

    def test_custom_fields_need_unique_names(self):
        for names in (["speed", "speed"], ["speed", " "]):
            component = item(component_type="CUSTOM", custom_type="game::Mover", use_fields=True, fields=[field(name, "FLOAT", 1.0) for name in names])
            self.assertEqual(metadata.validate_items([component], "car"), ["car: game::Mover needs a unique name for every field"])
        self.assertEqual(metadata.invalid_names(["a", "b", "a", ""]), {"a", ""})

    def test_enum_and_vector2_fields(self):
        fields = [field("mode", "ENUM", "PingPong", "Loop, PingPong", "my_game::PatrolMode"), field("offset", "VECTOR2", (1.0, 0.10000000149011612)), field("stops", "INT", 3, rust_type="u8")]
        component = item(component_type="CUSTOM", custom_type="my_game::Patrol", custom_json="{}", use_fields=True, fields=fields)
        self.assertEqual(metadata.validate_items([component]), [])
        self.assertEqual(json.loads(metadata.serialize_items([component]))["components"][0], {"type": "custom", "type_path": "my_game::Patrol", "data": {"mode": "PingPong", "offset": [1.0, 0.1], "stops": 3}, "enums": {"mode": "my_game::PatrolMode"}})
        component.fields[0].rust_type = " "
        self.assertNotIn("enums", json.loads(metadata.serialize_items([component]))["components"][0])

    def test_tuple_struct_fields(self):
        single = item(component_type="CUSTOM", custom_type="my_game::Armor", custom_json="{}", use_fields=True, fields=[field("0", "INT", 3)])
        pair = item(component_type="CUSTOM", custom_type="my_game::Reward", custom_json="{}", use_fields=True, fields=[field("0", "INT", 7), field("1", "FLOAT", 1.5)])
        shuffled = item(component_type="CUSTOM", custom_type="my_game::Odd", custom_json="{}", use_fields=True, fields=[field("1", "INT", 7), field("0", "FLOAT", 1.5)])
        self.assertEqual([component["data"] for component in json.loads(metadata.serialize_items([single, pair, shuffled]))["components"]], [3, [7, 1.5], {"1": 7, "0": 1.5}])
        self.assertEqual(metadata.json_fields([7, 1.5]), {"0": 7, "1": 1.5})
        self.assertEqual(metadata.json_fields(0.25), {"0": 0.25})
        self.assertEqual(metadata.json_fields({"a": 1}), {"a": 1})
        self.assertEqual(metadata.json_fields(None), {})

    def test_field_values_must_fit_their_rust_types(self):
        fields = [field("stops", "INT", 256, rust_type="u8"), field("lives", "INT", -1, rust_type="u32"), field("score", "INT", -5, rust_type="i32"), field("mode", "ENUM", "Hover", "Loop, PingPong"), field("team", "ENUM", "", " , ")]
        component = item(component_type="CUSTOM", custom_type="my_game::Patrol", use_fields=True, fields=fields)
        self.assertEqual(metadata.component_errors(component), ["stops must be from 0 to 255 to fit u8", "lives must be from 0 to 2147483647 to fit u32", "mode needs one of its variants", "team needs a list of variants"])
        self.assertEqual(metadata.variant_names(" Loop, PingPong,,Loop "), ["Loop", "PingPong"])

    def test_float32_values_are_short(self):
        for value, expected in ((0.10000000149011612, 0.1), (1.0, 1.0), (16777217.0, 16777216.0), (3.4028234663852886e38, 3.4028235e38), (1e-45, 1e-45)):
            self.assertEqual(metadata._float32(value), expected)

    def test_convert_value(self):
        cases = [
            ("FLOAT", 3, 3.0),
            ("FLOAT", "3", None),
            ("FLOAT", True, None),
            ("INT", 2.6, 3),
            ("INT", 2 ** 31, None),
            ("INT", False, None),
            ("BOOL", True, True),
            ("BOOL", 1, None),
            ("STRING", "coin", "coin"),
            ("STRING", 5, None),
            ("VECTOR", [1, 2.5, 3], (1.0, 2.5, 3.0)),
            ("VECTOR", [1, 2], None),
            ("VECTOR2", [1, 2], (1.0, 2.0)),
            ("VECTOR2", [1, 2, 3], None),
            ("ENUM", "Loop", "Loop"),
            ("ENUM", 1, None),
            ("VECTOR", [1, "2", 3], None),
            ("COLOR", [1, 0.5, 0], (1.0, 0.5, 0.0, 1.0)),
            ("COLOR", [1, 0.5, 0, 0.25], (1.0, 0.5, 0.0, 0.25)),
            ("COLOR", {"Srgba": {"red": 1, "green": 0.5, "blue": 0, "alpha": 0.25}}, (1.0, 0.5, 0.0, 0.25)),
            ("COLOR", {"Srgba": {"red": 1, "green": 0.5, "blue": 0}}, (1.0, 0.5, 0.0, 1.0)),
            ("COLOR", {"Srgba": {"red": 1, "green": 0.5}}, None),
            ("COLOR", {"LinearRgba": {"red": 1, "green": 0.5, "blue": 0, "alpha": 1}}, None),
            ("FLOAT", float("inf"), None),
        ]
        for kind, value, expected in cases:
            self.assertEqual(metadata.convert_value(kind, value), expected, (kind, value))

    def test_infer_fields(self):
        data = {"count": 3, "delay": 1.5, "boss": False, "label": "x", "offset": [0, 1, 0], "tint": [1, 1, 1, 1], "glow": {"Srgba": {"red": 1, "green": 1, "blue": 1, "alpha": 1}}}
        self.assertEqual(metadata.infer_fields(data), [("count", "INT", 3), ("delay", "FLOAT", 1.5), ("boss", "BOOL", False), ("label", "STRING", "x"), ("offset", "VECTOR", (0.0, 1.0, 0.0)), ("tint", "COLOR", (1.0, 1.0, 1.0, 1.0)), ("glow", "COLOR", (1.0, 1.0, 1.0, 1.0))])
        self.assertEqual(metadata.infer_fields({"aim": [0, 1]}), [("aim", "VECTOR2", (0.0, 1.0))])
        with self.assertRaisesRegex(ValueError, "No field type fits target, path"):
            metadata.infer_fields({"count": 3, "target": None, "path": [[0, 0]]})
        with self.assertRaisesRegex(ValueError, "Only a JSON object"):
            metadata.infer_fields(0.25)

    def test_empty(self):
        self.assertEqual(json.loads(metadata.serialize_items([])), {"version": 1, "components": []})


if __name__ == "__main__":
    unittest.main()
