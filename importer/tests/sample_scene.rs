mod common;

use avian3d::prelude::*;
use bevy::{animation::{RepeatAnimation, graph::AnimationNodeType}, asset::RenderAssetUsages, audio::{PlaybackMode, Volume}, camera::visibility::VisibilityRange, gltf::GltfExtras, light::{CascadeShadowConfig, FogVolume, GeneratedEnvironmentMapLight, IrradianceVolume, LightProbe, NotShadowCaster, NotShadowReceiver, ParallaxCorrection, Skybox, VolumetricLight}, pbr::Lightmap, prelude::*, render::render_resource::{Extent3d, TextureDimension, TextureFormat, TextureViewDimension}};
use bevy_components_importer::{BlenderCustomComponents, BlenderSky, GltfTextures, NavigationObstacle, NavigationWalkable, NoBlenderSky};
use common::*;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{f32::consts::{FRAC_PI_2, FRAC_PI_4}, fs, thread, time::Duration};

#[derive(Deserialize, Debug, PartialEq)]
struct Pickup {
    item: String,
    amount: i32,
    respawn: bool,
    weight: f32,
    spin: Vec3,
    glow: Color,
}

mod stats {
    use bevy::prelude::*;

    #[derive(Component, Reflect, Debug, PartialEq)]
    #[reflect(Component, Default)]
    pub struct Health {
        pub current: f32,
        pub maximum: f32,
    }

    impl Default for Health {
        fn default() -> Self {
            return Health { current: 100.0, maximum: 100.0 };
        }
    }

    #[derive(Component, Reflect, Debug, PartialEq)]
    #[reflect(Component)]
    pub struct Armor(pub i32);

    #[derive(Component, Reflect, Debug, PartialEq)]
    #[reflect(Component)]
    pub struct Loot {
        pub item: String,
        pub tint: Color,
        pub offset: Vec3,
    }

    #[derive(Component, Reflect, Debug, PartialEq)]
    pub struct Unmarked {
        pub value: f32,
    }
}

fn node(world: &mut World, name: &str) -> Entity {
    let mut nodes = world.query_filtered::<(Entity, &Name), Without<Mesh3d>>();
    return nodes.iter(world).find(|(_, node_name)| node_name.as_str() == name).map(|(entity, _)| entity).unwrap_or_else(|| panic!("No node named {name}"));
}

fn meshes(world: &mut World, name: &str) -> Vec<Entity> {
    let node = node(world, name);
    let Some(children) = world.get::<Children>(node) else { return Vec::new(); };
    return children.iter().filter(|child| world.get::<Mesh3d>(*child).is_some()).collect();
}

fn mesh(world: &mut World, name: &str) -> Entity {
    return meshes(world, name).first().copied().unwrap_or_else(|| panic!("{name} has no mesh"));
}

fn node_collider<'a>(world: &'a mut World, name: &str) -> &'a Collider {
    let node = node(world, name);
    return world.get::<Collider>(node).unwrap_or_else(|| panic!("{name} has no collider on its node"));
}

fn mesh_collider<'a>(world: &'a mut World, name: &str) -> &'a Collider {
    let mesh = mesh(world, name);
    return world.get::<Collider>(mesh).unwrap_or_else(|| panic!("{name} has no collider on its mesh"));
}

fn transform(world: &World, entity: Entity) -> Transform {
    return world.get::<Transform>(entity).copied().unwrap_or_else(|| panic!("{entity} has no transform"));
}

fn light_entity(world: &mut World, name: &str) -> Entity {
    let mut nodes = world.query_filtered::<(Entity, &Name), With<GltfExtras>>();
    let node = nodes.iter(world).find(|(_, node_name)| node_name.as_str() == name).map(|(entity, _)| entity).unwrap_or_else(|| panic!("No node named {name}"));
    let world = &*world;
    let children = world.get::<Children>(node).unwrap_or_else(|| panic!("{name} has no children"));
    return children.iter().find(|child| world.get::<PointLight>(*child).is_some() || world.get::<SpotLight>(*child).is_some() || world.get::<DirectionalLight>(*child).is_some()).unwrap_or_else(|| panic!("{name} has no glTF light"));
}

fn component_extras(components: Value) -> GltfExtras {
    return GltfExtras { value: json!({"bevy_components": json!({"version": 1, "components": components}).to_string()}).to_string() };
}

fn joint_entity<T: Component>(world: &mut World, name: &str) -> Entity {
    let node = node(world, name);
    let mut joints = world.query_filtered::<(Entity, &ChildOf), With<T>>();
    return joints.iter(world).find(|(_, parent)| parent.parent() == node).map(|(entity, _)| entity).unwrap_or_else(|| panic!("{name} has no {}", std::any::type_name::<T>()));
}

fn joint<'a, T: Component>(world: &'a mut World, name: &str) -> &'a T {
    let entity = joint_entity::<T>(world, name);
    return world.get::<T>(entity).expect("the joint entity has the joint");
}

fn physics_time(app: &App) -> f32 {
    return app.world().resource::<Time<Physics>>().elapsed_secs();
}

fn nodes(world: &mut World, name: &str) -> Vec<Entity> {
    let mut nodes = world.query_filtered::<(Entity, &Name), Without<Mesh3d>>();
    return nodes.iter(world).filter(|(_, node_name)| node_name.as_str() == name).map(|(entity, _)| entity).collect();
}

fn is_under(world: &World, entity: Entity, ancestor: Entity) -> bool {
    let mut cursor = world.get::<ChildOf>(entity).map(ChildOf::parent);
    while let Some(current) = cursor {
        if current == ancestor {
            return true;
        }
        cursor = world.get::<ChildOf>(current).map(ChildOf::parent);
    }
    return false;
}

fn instance_node(world: &mut World, instance: &str, name: &str) -> Entity {
    let root = node(world, instance);
    return nodes(world, name).into_iter().find(|entity| is_under(world, *entity, root)).unwrap_or_else(|| panic!("{instance} has no {name}"));
}

fn rotation(app: &App, entity: Entity) -> Quat {
    return app.world().get::<Transform>(entity).map(|transform| transform.rotation).expect("animated node has a transform");
}

fn scene_reference(name: &str, path: &str, scene: usize) -> (Name, Transform, GltfExtras) {
    let extras = json!({"bevy_components": json!({"version": 1, "components": [{"type": "scene_reference", "path": path, "scene": scene}]}).to_string()});
    return (Name::new(name.to_string()), Transform::default(), GltfExtras { value: extras.to_string() });
}

fn colliders(world: &mut World, name: &str) -> Vec<Entity> {
    let mut entities = meshes(world, name);
    entities.push(node(world, name));
    return entities.into_iter().filter(|entity| world.get::<Collider>(*entity).is_some()).collect();
}

fn child_with<T: Component>(world: &mut World, name: &str) -> Entity {
    let node = node(world, name);
    let children = world.get::<Children>(node).unwrap_or_else(|| panic!("{name} has no children"));
    return children.iter().find(|child| world.get::<T>(*child).is_some()).unwrap_or_else(|| panic!("{name} has no {} child", std::any::type_name::<T>()));
}

fn scale(world: &World, entity: Entity) -> Option<Vec3> {
    return world.get::<Transform>(entity).map(|transform| transform.scale);
}

#[test]
fn visibility_ranges_are_set_on_meshes() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let expected = [("crate", 20.0..25.0, 80.0..85.0, false), ("crate_copy", 20.0..25.0, 80.0..85.0, false), ("house", 80.0..85.0, 250.0..260.0, true), ("chimney", 80.0..85.0, 250.0..260.0, true), ("tree_lod0", 0.0..0.0, 20.0..25.0, false), ("tree_lod1", 20.0..25.0, 100.0..120.0, false)];
    for (name, start, end, use_aabb) in expected {
        let meshes = meshes(world, name);
        assert!(!meshes.is_empty(), "{name}");
        for mesh in meshes {
            let range = world.get::<VisibilityRange>(mesh).unwrap_or_else(|| panic!("{name} has no visibility range"));
            assert_eq!((range.start_margin.clone(), range.end_margin.clone(), range.use_aabb), (start.clone(), end.clone(), use_aabb), "{name}");
        }
    }
    assert_eq!(meshes(world, "crate").len(), 2);
    for name in ["ground", "ball", "lamp"] {
        let mesh = mesh(world, name);
        assert!(world.get::<VisibilityRange>(mesh).is_none(), "{name}");
    }
}

#[test]
fn colliders_match_exported_shapes() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    assert!(mesh_collider(world, "ground").shape().as_trimesh().is_some());
    assert!(mesh_collider(world, "house").shape().as_trimesh().is_some());
    assert!(mesh_collider(world, "chimney").shape().as_trimesh().is_some());
    assert!(mesh_collider(world, "rock").shape().as_convex_polyhedron().is_some());
    assert_eq!(node_collider(world, "crate").shape().as_cuboid().expect("crate is a cuboid").half_extents, Vec3::splat(1.0));
    assert_eq!(node_collider(world, "crate_copy").shape().as_cuboid().expect("crate_copy is a cuboid").half_extents, Vec3::splat(1.0));
    assert_eq!(node_collider(world, "ball").shape().as_ball().expect("ball is a sphere").radius, 0.5);
    let capsule = node_collider(world, "pillar").shape().as_capsule().expect("pillar is a capsule");
    assert_eq!((capsule.radius, capsule.half_height(), capsule.segment.a.x, capsule.segment.a.z), (0.4, 0.6, 0.0, 0.0));
    assert_eq!(node_collider(world, "trigger_zone").shape().as_cuboid().expect("trigger_zone is a cuboid").half_extents, Vec3::new(0.5, 1.0, 1.5));
    assert_eq!(node_collider(world, "trigger_zone").scale(), Vec3::new(2.0, 1.0, 1.0));
    assert_eq!(node_collider(world, "pickup_zone").shape().as_ball().expect("pickup_zone is a sphere").radius, 1.5);
    assert_eq!(node_collider(world, "cart_shape").shape().as_cuboid().expect("cart_shape is a cuboid").half_extents, Vec3::splat(0.5));
    assert_eq!(node_collider(world, "cart_handle").shape().as_ball().expect("cart_handle is a sphere").radius, 0.25);
    assert_eq!(node_collider(world, "bouncy_ball").shape().as_ball().expect("bouncy_ball is a sphere").radius, 0.3);
    assert_eq!(node_collider(world, "ramp").shape().as_cuboid().expect("ramp is a cuboid").half_extents, Vec3::new(3.0, 0.1, 1.0));
    let signpost = node_collider(world, "signpost").aabb(Vec3::ZERO, Quat::IDENTITY, 0.0);
    assert!(signpost.min.abs_diff_eq(Vec3::new(-0.15, 0.0, -0.15), 1e-5) && signpost.max.abs_diff_eq(Vec3::new(0.15, 1.5, 0.15), 1e-5), "signpost spans {signpost:?}");
    assert!(node_collider(world, "signpost").shape().as_compound().is_some());
    assert_eq!(node_collider(world, "invisible_wall").shape().as_cuboid().expect("invisible_wall is a cuboid").half_extents, Vec3::new(0.1, 1.0, 2.0));
    for name in ["ghost", "ice_block", "rubber_block"] {
        assert!(node_collider(world, name).shape().as_cuboid().is_some(), "{name}");
    }
    for name in ["lamp", "tree_lod0", "tree_lod1", "player_spawn", "enemy_spawn", "cart", "cart_body"] {
        assert!(colliders(world, name).is_empty(), "{name}");
    }
}

#[test]
fn primitive_colliders_are_added_once_per_object() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    for name in ["crate", "crate_copy", "ball", "pillar", "trigger_zone", "pickup_zone", "cart_shape", "cart_handle", "bouncy_ball", "ghost", "signpost", "invisible_wall", "ramp", "ice_block", "rubber_block"] {
        let node = node(world, name);
        assert_eq!(colliders(world, name), vec![node], "{name}");
    }
    for name in ["ground", "rock", "house", "chimney"] {
        let meshes = meshes(world, name);
        assert_eq!(colliders(world, name), meshes, "{name}");
    }
}

#[test]
fn sensors_are_marked() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    for name in ["trigger_zone", "pickup_zone"] {
        let node = node(world, name);
        assert!(world.get::<Sensor>(node).is_some(), "{name}");
    }
    let mut sensors = world.query_filtered::<Entity, With<Sensor>>();
    assert_eq!(sensors.iter(world).count(), 2);
}

#[test]
fn rigid_bodies_own_their_colliders() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let expected = [("ground", RigidBody::Static, "ground"), ("crate", RigidBody::Dynamic, "crate"), ("crate_copy", RigidBody::Dynamic, "crate_copy"), ("ball", RigidBody::Kinematic, "ball"), ("pillar", RigidBody::Static, "pillar"), ("rock", RigidBody::Dynamic, "rock"), ("trigger_zone", RigidBody::Static, "trigger_zone"), ("pickup_zone", RigidBody::Static, "pickup_zone"), ("house", RigidBody::Static, "house"), ("chimney", RigidBody::Static, "house"), ("cart_shape", RigidBody::Dynamic, "cart"), ("cart_handle", RigidBody::Dynamic, "cart"), ("bouncy_ball", RigidBody::Dynamic, "bouncy_ball"), ("ghost", RigidBody::Dynamic, "ghost"), ("signpost", RigidBody::Dynamic, "signpost"), ("invisible_wall", RigidBody::Static, "invisible_wall"), ("ramp", RigidBody::Static, "ramp"), ("ice_block", RigidBody::Dynamic, "ice_block"), ("rubber_block", RigidBody::Dynamic, "rubber_block")];
    for (name, kind, owner) in expected {
        let owner = node(world, owner);
        assert_eq!(world.get::<RigidBody>(owner), Some(&kind), "{name}");
        for collider in colliders(world, name) {
            assert_eq!(world.get::<ColliderOf>(collider).map(|collider_of| collider_of.body), Some(owner), "{name}");
        }
    }
    for name in ["chimney", "lamp", "player_spawn", "enemy_spawn", "tree_lod0", "sun", "cart_shape", "cart_handle", "cart_body"] {
        let node = node(world, name);
        assert!(world.get::<RigidBody>(node).is_none(), "{name}");
    }
}

#[test]
fn empties_keep_positions() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    for (name, translation) in [("player_spawn", Vec3::new(2.0, 0.0, -3.0)), ("enemy_spawn", Vec3::new(-6.0, 0.0, 6.0))] {
        let node = node(world, name);
        assert_eq!(world.get::<Transform>(node).map(|transform| transform.translation), Some(translation), "{name}");
    }
}

#[test]
fn custom_components_keep_type_paths_and_data() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let expected = [("player_spawn", vec![("my_game::PlayerSpawn", json!({}))]), ("enemy_spawn", vec![("my_game::EnemySpawn", json!({})), ("my_game::Wave", json!({"count": 3, "delay": 1.5}))]), ("lamp", vec![("my_game::Glow", json!({"color": [1.0, 0.8, 0.6], "label": "Lamp ✦"})), ("my_game::Flicker", json!(0.25))]), ("pickup_zone", vec![("my_game::Pickup", json!({"item": "coin", "amount": 5, "respawn": true, "weight": 0.1, "spin": [0.0, 1.5, 0.0], "glow": {"Srgba": {"red": 1.0, "green": 0.8, "blue": 0.2, "alpha": 1.0}}}))])];
    for (name, components) in expected {
        let node = node(world, name);
        let custom = world.get::<BlenderCustomComponents>(node).unwrap_or_else(|| panic!("{name} has no custom components"));
        let found: Vec<(&str, &Value)> = custom.0.iter().map(|component| (component.type_path.as_str(), &component.data)).collect();
        let wanted: Vec<(&str, &Value)> = components.iter().map(|(type_path, data)| (*type_path, data)).collect();
        assert_eq!(found, wanted, "{name}");
    }
    let crate_node = node(world, "crate");
    assert!(world.get::<BlenderCustomComponents>(crate_node).is_none());
}

#[test]
fn game_components_fill_in_fields_blender_leaves_out() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let enemy_spawn = node(world, "enemy_spawn");
    assert_eq!(world.get::<Patrol>(enemy_spawn), Some(&Patrol { speed: 2.5, mode: PatrolMode::PingPong, offset: Vec2::new(1.0, -0.5), stops: 3, ..default() }));
    assert_eq!(world.get::<Reward>(enemy_spawn), Some(&Reward(7, 1.5)));
}

#[test]
fn custom_component_fields_deserialize_into_rust_types() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let node = node(world, "pickup_zone");
    let custom = world.get::<BlenderCustomComponents>(node).expect("pickup_zone has custom components");
    let data = custom.0.iter().find(|component| component.type_path == "my_game::Pickup").map(|component| component.data.clone()).expect("pickup_zone has a Pickup");
    let pickup: Pickup = serde_json::from_value(data).expect("Pickup fields match the Rust struct");
    assert_eq!(pickup, Pickup { item: "coin".to_string(), amount: 5, respawn: true, weight: 0.1, spin: Vec3::new(0.0, 1.5, 0.0), glow: Color::srgba(1.0, 0.8, 0.2, 1.0) });
}

#[test]
fn registered_custom_components_are_inserted() {
    let mut app = SceneApp::default().build();
    let hero = json!([{"type": "custom", "type_path": "sample_scene::Health", "data": {"current": 5}}, {"type": "custom", "type_path": "sample_scene::stats::Armor", "data": 3}, {"type": "custom", "type_path": "sample_scene::stats::Loot", "data": {"item": "coin", "tint": {"Srgba": {"red": 1.0, "green": 0.8, "blue": 0.2, "alpha": 1.0}}, "offset": [0.0, 1.5, 0.0]}}, {"type": "custom", "type_path": "my_game::Unknown", "data": {"level": 2}}]);
    let villain = json!([{"type": "custom", "type_path": "sample_scene::stats::Health", "data": {"current": 5, "shield": 2}}, {"type": "custom", "type_path": "sample_scene::stats::Loot", "data": {"item": "coin"}}, {"type": "custom", "type_path": "sample_scene::stats::Unmarked", "data": {"value": 1.0}}, {"type": "custom", "type_path": "other_game::Health", "data": {"current": 1}}]);
    let world = app.world_mut();
    let hero = world.spawn((Name::new("hero"), Transform::default(), component_extras(hero))).id();
    let villain = world.spawn((Name::new("villain"), Transform::default(), component_extras(villain))).id();
    app.update();
    let world = app.world();
    assert_eq!(world.get::<stats::Health>(hero), Some(&stats::Health { current: 5.0, maximum: 100.0 }));
    assert_eq!(world.get::<stats::Armor>(hero), Some(&stats::Armor(3)));
    assert_eq!(world.get::<stats::Loot>(hero), Some(&stats::Loot { item: "coin".to_string(), tint: Color::srgba(1.0, 0.8, 0.2, 1.0), offset: Vec3::new(0.0, 1.5, 0.0) }));
    let kept = |entity: Entity| world.get::<BlenderCustomComponents>(entity).map(|custom| custom.0.iter().map(|component| component.type_path.clone()).collect::<Vec<_>>());
    assert_eq!(kept(hero), Some(vec!["my_game::Unknown".to_string()]));
    assert!(world.get::<stats::Health>(villain).is_none());
    assert!(world.get::<stats::Loot>(villain).is_none());
    assert!(world.get::<stats::Unmarked>(villain).is_none());
    assert_eq!(kept(villain), Some(vec!["sample_scene::stats::Health".to_string(), "sample_scene::stats::Loot".to_string(), "sample_scene::stats::Unmarked".to_string(), "other_game::Health".to_string()]));
}

#[test]
fn components_are_ready_on_the_first_frame() {
    let mut app = SceneApp::default().build();
    let _gltf = load_gltf(&mut app, SCENE).unwrap_or_else(|error| panic!("{SCENE} did not load: {error}"));
    let scene: Handle<WorldAsset> = app.world().resource::<AssetServer>().load(format!("{SCENE}#Scene0"));
    app.world_mut().spawn(WorldAssetRoot(scene));
    app.update();
    let world = app.world_mut();
    assert_eq!(world.resource::<ReadyInstances>().0, 1);
    let crate_node = node(world, "crate");
    assert_eq!(world.get::<RigidBody>(crate_node), Some(&RigidBody::Dynamic));
    assert!(world.get::<Collider>(crate_node).is_some());
    for crate_mesh in meshes(world, "crate") {
        assert!(world.get::<VisibilityRange>(crate_mesh).is_some());
    }
    assert!(mesh_collider(world, "ground").shape().as_trimesh().is_some());
    let water = mesh(world, "water");
    assert!(world.get::<NotShadowCaster>(water).is_some());
    let ground = mesh(world, "ground");
    assert!(world.get::<Lightmap>(ground).is_some());
    let lamp = light_entity(world, "lamp_light");
    assert!(world.get::<PointLight>(lamp).is_some_and(|point| point.shadow_maps_enabled));
    assert_eq!(world.resource::<GlobalAmbientLight>().brightness, 120.0);
}

#[test]
fn spot_lights_get_a_radius_only_from_light_settings() {
    let mut app = load_scene("spot_lights.gltf");
    let world = app.world_mut();
    let plain = light_entity(world, "plain_spot");
    assert_eq!(world.get::<SpotLight>(plain).map(|spot| (spot.range, spot.radius)), Some((12.0, 0.0)));
    let set = light_entity(world, "set_spot");
    assert_eq!(world.get::<SpotLight>(set).map(|spot| (spot.range, spot.radius)), Some((12.0, 0.3)));
}

#[test]
fn only_component_data_is_exported() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let mut extras = world.query::<(&Name, &GltfExtras)>();
    let mut count = 0;
    for (name, extra) in extras.iter(world) {
        let value: Value = serde_json::from_str(&extra.value).expect("extras are JSON");
        assert_eq!(value.as_object().map(|object| object.keys().cloned().collect::<Vec<_>>()), Some(vec!["bevy_components".to_string()]), "{name}");
        count += 1;
    }
    assert_eq!(count, 59);
}

#[test]
fn fog_volumes_fill_their_boxes() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let volume = child_with::<FogVolume>(world, "fog_bank");
    let fog = world.get::<FogVolume>(volume).expect("fog_bank has a fog volume");
    assert_eq!((fog.fog_color, fog.density_factor, fog.absorption, fog.scattering, fog.scattering_asymmetry, fog.light_tint, fog.light_intensity), (Color::srgb(0.8, 0.85, 1.0), 0.2, 0.3, 0.3, 0.6, Color::srgb(1.0, 1.0, 1.0), 1.5));
    assert_eq!(scale(world, volume), Some(Vec3::new(6.0, 2.0, 6.0)));
    assert_eq!(world.get::<Name>(volume).map(Name::as_str), Some("Fog Volume"));
}

#[test]
fn reflection_probes_filter_embedded_cubemaps() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let probe = child_with::<LightProbe>(world, "room_probe");
    assert_eq!(world.get::<LightProbe>(probe).map(|probe| probe.falloff), Some(Vec3::splat(0.25)));
    assert_eq!(scale(world, probe), Some(Vec3::new(24.0, 5.0, 24.0)));
    assert!(!matches!(world.get::<ParallaxCorrection>(probe), Some(ParallaxCorrection::None)));
    let light = world.get::<GeneratedEnvironmentMapLight>(probe).expect("room_probe filters its cubemap");
    assert_eq!(light.intensity, 2000.0);
    let image = world.resource::<Assets<Image>>().get(&light.environment_map).expect("the cubemap is loaded");
    assert_eq!((image.texture_descriptor.size, image.texture_descriptor.format), (Extent3d { width: 16, height: 16, depth_or_array_layers: 6 }, TextureFormat::Rgba16Float));
    assert_eq!(image.texture_view_descriptor.as_ref().and_then(|view| view.dimension), Some(TextureViewDimension::Cube));
}

#[test]
fn irradiance_volumes_light_from_embedded_voxels() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let volume = child_with::<IrradianceVolume>(world, "gi_volume");
    assert_eq!(world.get::<LightProbe>(volume).map(|probe| probe.falloff), Some(Vec3::splat(0.1)));
    assert_eq!(scale(world, volume), Some(Vec3::new(24.0, 6.0, 24.0)));
    let irradiance = world.get::<IrradianceVolume>(volume).expect("gi_volume has an irradiance volume");
    assert_eq!((irradiance.intensity, irradiance.affects_lightmapped_meshes), (500.0, true));
    let image = world.resource::<Assets<Image>>().get(&irradiance.voxels).expect("the voxels are loaded");
    assert_eq!((image.texture_descriptor.size, image.texture_descriptor.dimension, image.texture_descriptor.format), (Extent3d { width: 2, height: 4, depth_or_array_layers: 6 }, TextureDimension::D3, TextureFormat::Rgba16Float));
}

#[test]
fn light_probes_need_usable_textures() {
    let mut app = SceneApp::default().build();
    let mut images = app.world_mut().resource_mut::<Assets<Image>>();
    let cubemaps: Vec<Handle<Image>> = [8, 12].into_iter().map(|size| images.add(Image::new_fill(Extent3d { width: size, height: size, depth_or_array_layers: 6 }, TextureDimension::D2, &[0; 8], TextureFormat::Rgba16Float, RenderAssetUsages::default()))).collect();
    let probe = |texture: Value| json!({"type": "reflection_probe", "size": [2.0, 2.0, 2.0], "falloff": [0.0, 0.0, 0.0], "intensity": 100.0, "parallax_correction": false, "texture": texture});
    let components = json!([probe(json!(0)), probe(json!(1)), probe(Value::Null), {"type": "irradiance_volume", "size": [2.0, 2.0, 2.0], "falloff": [0.0, 0.0, 0.0], "intensity": 100.0, "texture": 5}]);
    let extras = json!({"bevy_components": json!({"version": 1, "components": components}).to_string()});
    let entity = app.world_mut().spawn((Name::new("probes"), Transform::default(), GltfExtras { value: extras.to_string() }, GltfTextures(cubemaps.clone()))).id();
    for _ in 0..3 {
        app.update();
    }
    let world = app.world();
    let probes: Vec<Entity> = world.get::<Children>(entity).map(|children| children.iter().filter(|child| world.get::<LightProbe>(*child).is_some()).collect()).unwrap_or_default();
    assert_eq!(probes.len(), 2);
    assert!(probes.iter().all(|probe| matches!(world.get::<ParallaxCorrection>(*probe), Some(ParallaxCorrection::None))));
    assert_eq!(world.get::<GeneratedEnvironmentMapLight>(probes[0]).map(|light| (light.environment_map.id(), light.intensity)), Some((cubemaps[0].id(), 100.0)));
    assert!(world.get::<GeneratedEnvironmentMapLight>(probes[1]).is_none());
}

fn shared_exponent_texel(image: &Image, x: usize, y: usize) -> Vec3 {
    let width = image.texture_descriptor.size.width as usize;
    let data = image.data.as_ref().expect("lightmap pixels");
    let offset = (y * width + x) * 4;
    let packed = u32::from_le_bytes(data[offset..offset + 4].try_into().expect("four bytes"));
    let scale = 2.0_f32.powi((packed >> 27) as i32 - 24);
    return Vec3::new((packed & 511) as f32, (packed >> 9 & 511) as f32, (packed >> 18 & 511) as f32) * scale;
}

fn lightmap_extras(texture: Value) -> GltfExtras {
    return component_extras(json!([{"type": "lightmap", "bicubic": false, "texture": texture}]));
}

#[test]
fn lightmaps_light_meshes_from_embedded_textures() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let ground = mesh(world, "ground");
    let lightmap = world.get::<Lightmap>(ground).expect("ground has a lightmap").clone();
    assert_eq!((lightmap.uv_rect, lightmap.bicubic_sampling), (Rect::new(0.0, 0.0, 1.0, 1.0), true));
    let mesh_handle = world.get::<Mesh3d>(ground).expect("ground has a mesh").0.clone();
    assert!(world.resource::<Assets<Mesh>>().get(&mesh_handle).expect("the mesh is loaded").attribute(Mesh::ATTRIBUTE_UV_1).is_some());
    let image = world.resource::<Assets<Image>>().get(&lightmap.image).expect("the lightmap is loaded");
    assert_eq!((image.texture_descriptor.size, image.texture_descriptor.format), (Extent3d { width: 16, height: 16, depth_or_array_layers: 1 }, TextureFormat::Rgb9e5Ufloat));
    let center = shared_exponent_texel(image, 8, 8);
    let corner = shared_exponent_texel(image, 0, 0);
    assert!(center.x > 800.0 && center.x > center.z, "the center of the ground lightmap is {center}");
    assert!(corner.x < 200.0 && corner.z > corner.x, "the corner of the ground lightmap is {corner}");
    let mut lightmaps = world.query::<&Lightmap>();
    assert_eq!(lightmaps.iter(world).count(), 1);
}

#[test]
fn lightmaps_need_a_mesh_with_two_uv_maps() {
    let mut app = SceneApp::default().build();
    let world = app.world_mut();
    let image = world.resource_mut::<Assets<Image>>().add(Image::default());
    let plain = Mesh::from(Plane3d::default());
    let uvs = plain.attribute(Mesh::ATTRIBUTE_UV_0).expect("planes have UVs").clone();
    let mut meshes = world.resource_mut::<Assets<Mesh>>();
    let plain = meshes.add(plain.clone());
    let unwrapped = meshes.add(Mesh::from(Plane3d::default()).with_inserted_attribute(Mesh::ATTRIBUTE_UV_1, uvs));
    let mut spawn = |name: &str, texture: Value, mesh: &Handle<Mesh>| -> Entity {
        let node = world.spawn((Name::new(name.to_string()), Transform::default(), lightmap_extras(texture), GltfTextures(vec![image.clone()]))).id();
        return world.spawn((Mesh3d(mesh.clone()), Transform::default(), ChildOf(node))).id();
    };
    let lit = spawn("lit", json!(0), &unwrapped);
    let one_uv_map = spawn("one_uv_map", json!(0), &plain);
    let missing = spawn("missing", json!(3), &unwrapped);
    let world = app.world_mut();
    let meshless = world.spawn((Name::new("meshless"), Transform::default(), lightmap_extras(json!(0)), GltfTextures(vec![image.clone()]))).id();
    for _ in 0..3 {
        app.update();
    }
    let world = app.world();
    assert_eq!(world.get::<Lightmap>(lit).map(|lightmap| (lightmap.image.id(), lightmap.bicubic_sampling)), Some((image.id(), false)));
    assert!(world.get::<Lightmap>(one_uv_map).is_none());
    assert!(world.get::<Lightmap>(missing).is_none());
    assert!(world.get::<Lightmap>(meshless).is_none());
}

#[test]
fn dynamic_bodies_rest_on_the_ground() {
    let mut app = load_scene(SCENE);
    for _ in 0..120 {
        app.update();
    }
    let world = app.world_mut();
    assert!(world.resource::<Time<Physics>>().elapsed_secs() > 1.5);
    for (name, start) in [("crate", Vec3::new(3.0, 1.0, 2.0)), ("crate_copy", Vec3::new(6.0, 1.0, 2.0)), ("ball", Vec3::new(-3.0, 0.5, 0.0)), ("cart", Vec3::new(-8.0, 0.5, 2.0)), ("signpost", Vec3::new(-5.0, 0.0, 2.0))] {
        let node = node(world, name);
        let translation = world.get::<Transform>(node).map(|transform| transform.translation).unwrap_or_else(|| panic!("{name} has no transform"));
        assert!(translation.distance(start) < 0.05, "{name} moved from {start} to {translation}");
    }
}

#[test]
fn colliders_keep_surface_and_layer_settings() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let expected = [("ground", 0.5, 0.0, CollisionLayers::DEFAULT), ("crate", 0.8, 0.1, CollisionLayers::DEFAULT), ("crate_copy", 0.8, 0.1, CollisionLayers::DEFAULT), ("rock", 0.5, 0.0, CollisionLayers::DEFAULT), ("house", 0.5, 0.0, CollisionLayers::DEFAULT), ("chimney", 0.5, 0.0, CollisionLayers::DEFAULT), ("trigger_zone", 0.5, 0.0, CollisionLayers::from_bits(0b100, 0b010)), ("cart_shape", 0.5, 0.0, CollisionLayers::DEFAULT), ("bouncy_ball", 0.5, 1.0, CollisionLayers::DEFAULT), ("ghost", 0.5, 0.0, CollisionLayers::from_bits(0b10, 0b10)), ("signpost", 0.5, 0.0, CollisionLayers::DEFAULT), ("invisible_wall", 0.5, 0.0, CollisionLayers::DEFAULT), ("ice_block", 0.0, 0.0, CollisionLayers::DEFAULT), ("rubber_block", 1.0, 0.0, CollisionLayers::DEFAULT)];
    for (name, friction, restitution, layers) in expected {
        let entities = colliders(world, name);
        assert!(!entities.is_empty(), "{name}");
        for collider in entities {
            assert_eq!(world.get::<Friction>(collider), Some(&Friction::new(friction)), "{name}");
            assert_eq!(world.get::<Restitution>(collider), Some(&Restitution::new(restitution)), "{name}");
            assert_eq!(world.get::<CollisionLayers>(collider), Some(&layers), "{name}");
        }
    }
}

#[derive(Resource, Default)]
struct CollisionStarts {
    read: Vec<(Entity, Entity)>,
    observed: Vec<(Entity, Entity)>,
}

fn read_collision_starts(mut messages: MessageReader<CollisionStart>, mut starts: ResMut<CollisionStarts>) {
    starts.read.extend(messages.read().map(|start| (start.collider1, start.collider2)));
}

fn spawn_components(world: &mut World, name: &str, translation: Vec3, components: Value) -> Entity {
    return world.spawn((Name::new(name.to_string()), Transform::from_translation(translation), component_extras(components))).id();
}

fn spawn_mesh(world: &mut World, mesh: &Handle<Mesh>, parent: Entity) -> Entity {
    return world.spawn((Mesh3d(mesh.clone()), Transform::default(), ChildOf(parent))).id();
}

fn box_collider(shape: &str, sensor: bool, events: Option<bool>, collision_only: bool) -> Value {
    return json!({"type": "collider", "shape": shape, "size": [2.0, 2.0, 2.0], "radius": 0.25, "height": 1.0, "sensor": sensor, "events": events, "collision_only": collision_only});
}

#[test]
fn collision_events_are_enabled_where_exported() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    for name in ["trigger_zone", "pickup_zone", "bouncy_ball"] {
        let node = node(world, name);
        assert!(world.get::<CollisionEventsEnabled>(node).is_some(), "{name}");
    }
    let mut enabled = world.query_filtered::<Entity, With<CollisionEventsEnabled>>();
    assert_eq!(enabled.iter(world).count(), 3);
}

#[test]
fn collision_events_reach_readers_and_observers() {
    let mut app = SceneApp::default().build();
    app.init_resource::<CollisionStarts>();
    app.add_systems(Update, read_collision_starts);
    app.add_observer(|start: On<CollisionStart>, mut starts: ResMut<CollisionStarts>| starts.observed.push((start.collider1, start.collider2)));
    let world = app.world_mut();
    let cube = world.resource_mut::<Assets<Mesh>>().add(Mesh::from(Cuboid::new(2.0, 2.0, 2.0)));
    let listening = spawn_components(world, "listening", Vec3::ZERO, json!([box_collider("cuboid", true, Some(true), false)]));
    let silent = spawn_components(world, "silent", Vec3::new(10.0, 0.0, 0.0), json!([box_collider("cuboid", true, Some(false), false)]));
    let older = spawn_components(world, "older", Vec3::new(20.0, 0.0, 0.0), json!([box_collider("cuboid", true, None, false)]));
    let shaped = spawn_components(world, "shaped", Vec3::new(30.0, 0.0, 0.0), json!([box_collider("trimesh", true, Some(true), false)]));
    let shaped_mesh = spawn_mesh(world, &cube, shaped);
    let balls = [0.0, 10.0, 20.0, 30.0].map(|x| spawn_components(world, "ball", Vec3::new(x, 2.0, 0.0), json!([box_collider("sphere", false, None, false), {"type": "rigid_body", "kind": "dynamic"}])));
    for _ in 0..60 {
        app.update();
    }
    let world = app.world();
    assert_eq!([listening, silent, older, shaped, shaped_mesh].map(|entity| world.get::<CollisionEventsEnabled>(entity).is_some()), [true, false, false, false, true]);
    assert!(balls.iter().all(|ball| world.get::<Transform>(*ball).is_some_and(|transform| transform.translation.y < -1.0)), "the balls did not fall through the sensors");
    let starts = world.resource::<CollisionStarts>();
    let mut read: Vec<(Entity, Entity)> = starts.read.iter().map(|&(first, second)| if balls.contains(&first) { (second, first) } else { (first, second) }).collect();
    read.sort();
    read.dedup();
    let mut observed = starts.observed.clone();
    observed.sort();
    observed.dedup();
    let mut expected = vec![(listening, balls[0]), (shaped_mesh, balls[3])];
    expected.sort();
    assert_eq!((read, observed), (expected.clone(), expected));
}

#[test]
fn collision_only_hides_meshes_but_keeps_colliders() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let wall = node(world, "invisible_wall");
    let meshes = meshes(world, "invisible_wall");
    assert!(!meshes.is_empty());
    assert!(meshes.iter().all(|mesh| world.get::<Visibility>(*mesh) == Some(&Visibility::Hidden)));
    assert_ne!(world.get::<Visibility>(wall), Some(&Visibility::Hidden));
    assert!(world.get::<Collider>(wall).is_some());
    let mut hidden = world.query_filtered::<&Visibility, With<Mesh3d>>();
    assert_eq!(hidden.iter(world).filter(|visibility| **visibility == Visibility::Hidden).count(), meshes.len());

    let mut app = SceneApp::default().build();
    let world = app.world_mut();
    let cube = world.resource_mut::<Assets<Mesh>>().add(Mesh::from(Cuboid::new(2.0, 2.0, 2.0)));
    let hull = spawn_components(world, "hull", Vec3::ZERO, json!([box_collider("convex", false, None, true)]));
    let hull_mesh = spawn_mesh(world, &cube, hull);
    let plain_part = world.spawn((Transform::default(), ChildOf(hull))).id();
    let plain_mesh = spawn_mesh(world, &cube, plain_part);
    let solid_part = spawn_components(world, "solid_part", Vec3::ZERO, json!([box_collider("trimesh", false, None, false)]));
    world.entity_mut(solid_part).insert(ChildOf(hull));
    let solid_mesh = spawn_mesh(world, &cube, solid_part);
    for _ in 0..3 {
        app.update();
    }
    let world = app.world();
    assert_eq!([hull_mesh, plain_mesh, solid_mesh].map(|mesh| world.get::<Visibility>(mesh) == Some(&Visibility::Hidden)), [true, true, false]);
    assert!([hull_mesh, plain_mesh, solid_mesh].iter().all(|mesh| world.get::<Collider>(*mesh).is_some()));
    assert_ne!(world.get::<Visibility>(hull), Some(&Visibility::Hidden));
}

#[test]
fn masses_set_the_total_body_mass() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    for (name, mass) in [("rock", 25.0), ("cart", 12.0)] {
        let node = node(world, name);
        assert_eq!(world.get::<Mass>(node), Some(&Mass(mass)), "{name}");
        assert!(world.get::<NoAutoMass>(node).is_some(), "{name}");
        assert_eq!(world.get::<ComputedMass>(node).map(|computed| computed.value()), Some(mass), "{name}");
    }
    for (name, mass) in [("crate", 8.0), ("ice_block", 0.125)] {
        let node = node(world, name);
        assert!(world.get::<Mass>(node).is_none(), "{name}");
        let computed = world.get::<ComputedMass>(node).map(|computed| computed.value()).unwrap_or_else(|| panic!("{name} has no computed mass"));
        assert!((computed - mass).abs() < 1e-4, "{name} weighs {computed}");
    }
}

#[test]
fn restitution_makes_bodies_bounce() {
    let mut app = load_scene(SCENE);
    let ball = node(app.world_mut(), "bouncy_ball");
    let mut fell = false;
    let mut bounced = false;
    let mut peak = 0.0_f32;
    for _ in 0..120 {
        app.update();
        let world = app.world();
        let velocity = world.get::<LinearVelocity>(ball).map(|velocity| velocity.y).expect("bouncy_ball has a velocity");
        let height = world.get::<Transform>(ball).map(|transform| transform.translation.y).expect("bouncy_ball has a transform");
        fell |= velocity < -1.0;
        bounced |= fell && velocity > 0.0;
        if bounced {
            peak = peak.max(height);
        }
    }
    assert!(bounced, "bouncy_ball never bounced");
    assert!(peak > 0.8, "bouncy_ball only bounced up to {peak}");
}

#[test]
fn collision_layers_let_bodies_pass_through() {
    let mut app = load_scene(SCENE);
    for _ in 0..60 {
        app.update();
    }
    let world = app.world_mut();
    let ghost = node(world, "ghost");
    let height = world.get::<Transform>(ghost).map(|transform| transform.translation.y).expect("ghost has a transform");
    assert!(height < -2.0, "ghost stopped at {height}");
}

#[test]
fn friction_decides_whether_bodies_slide() {
    let mut app = load_scene(SCENE);
    for _ in 0..60 {
        app.update();
    }
    let world = app.world_mut();
    for (name, start, sliding) in [("ice_block", Vec3::new(-1.124038, 3.053109, -7.4), true), ("rubber_block", Vec3::new(-1.124038, 3.053109, -8.6), false)] {
        let node = node(world, name);
        let distance = world.get::<Transform>(node).map(|transform| transform.translation.distance(start)).unwrap_or_else(|| panic!("{name} has no transform"));
        assert_eq!(distance > 1.0, sliding, "{name} moved {distance}");
        assert!(sliding || distance < 0.05, "{name} moved {distance}");
    }
}

#[test]
fn older_exports_keep_avian_defaults() {
    let mut app = SceneApp::default().build();
    let extras = json!({"bevy_components": json!({"version": 1, "components": [{"type": "collider", "shape": "cuboid", "size": [1.0, 1.0, 1.0], "radius": 0.5, "height": 1.0, "sensor": false}, {"type": "rigid_body", "kind": "dynamic"}]}).to_string()});
    let entity = app.world_mut().spawn((Name::new("old_crate"), Transform::default(), GltfExtras { value: extras.to_string() })).id();
    for _ in 0..3 {
        app.update();
    }
    let world = app.world();
    assert!(world.get::<Collider>(entity).is_some());
    assert_eq!(world.get::<RigidBody>(entity), Some(&RigidBody::Dynamic));
    assert_eq!(world.get::<CollisionLayers>(entity), Some(&CollisionLayers::DEFAULT));
    assert!(world.get::<Friction>(entity).is_none());
    assert!(world.get::<Restitution>(entity).is_none());
    assert!(world.get::<Mass>(entity).is_none());
    assert!(world.get::<NoAutoMass>(entity).is_none());
    assert!(world.get::<GravityScale>(entity).is_none());
    assert!(world.get::<LinearDamping>(entity).is_none());
    assert!(world.get::<AngularDamping>(entity).is_none());
    assert!(world.get::<LockedAxes>(entity).is_none());
    assert!(world.get::<SweptCcd>(entity).is_none());
}

#[test]
fn locked_axes_cancel_initial_velocity() {
    let mut app = SceneApp::default().build();
    let extras = json!({"bevy_components": json!({"version": 1, "components": [{"type": "rigid_body", "kind": "dynamic", "gravity_scale": 0.0, "lock_translation": [true, false, false], "lock_rotation": [false, true, false], "linear_velocity": [1.0, 2.0, 3.0], "angular_velocity": [4.0, 5.0, 6.0]}]}).to_string()});
    let entity = app.world_mut().spawn((Name::new("locked"), Transform::default(), GltfExtras { value: extras.to_string() })).id();
    app.update();
    let world = app.world();
    assert_eq!(world.get::<LinearVelocity>(entity), Some(&LinearVelocity(Vec3::new(0.0, 2.0, 3.0))));
    assert_eq!(world.get::<AngularVelocity>(entity), Some(&AngularVelocity(Vec3::new(4.0, 0.0, 6.0))));
    assert_eq!(world.get::<LockedAxes>(entity).map(LockedAxes::to_bits), Some(0b100_010));
}

#[test]
fn rigid_bodies_keep_their_tuning() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let balloon = node(world, "balloon");
    assert_eq!(world.get::<GravityScale>(balloon), Some(&GravityScale(-0.5)));
    assert_eq!(world.get::<LinearDamping>(balloon), Some(&LinearDamping(0.5)));
    assert_eq!(world.get::<AngularDamping>(balloon), Some(&AngularDamping(0.2)));
    let puck = node(world, "puck");
    assert_eq!(world.get::<LockedAxes>(puck).map(LockedAxes::to_bits), Some(0b010_111));
    let bullet = node(world, "bullet");
    assert_eq!(world.get::<SweptCcd>(bullet).map(|ccd| ccd.filter), Some(CcdFilter::ALL));
    assert_eq!(world.get::<GravityScale>(bullet), Some(&GravityScale(0.0)));
    let crate_node = node(world, "crate");
    assert_eq!(world.get::<GravityScale>(crate_node), Some(&GravityScale(1.0)));
    assert_eq!(world.get::<LockedAxes>(crate_node).map(LockedAxes::to_bits), Some(0));
    assert!(world.get::<SweptCcd>(crate_node).is_none());
    for name in ["ground", "ramp", "spinner", "ball", "drawer_cabinet"] {
        let node = node(world, name);
        assert!(world.get::<GravityScale>(node).is_none(), "{name}");
        assert!(world.get::<LinearDamping>(node).is_none(), "{name}");
        assert!(world.get::<LockedAxes>(node).is_none(), "{name}");
    }
}

#[test]
fn negative_gravity_and_damping_make_bodies_rise_slowly() {
    let mut app = load_scene(SCENE);
    let balloon = node(app.world_mut(), "balloon");
    let start = transform(app.world(), balloon).translation;
    for _ in 0..300 {
        app.update();
    }
    let world = app.world();
    let height = transform(world, balloon).translation.y;
    let velocity = world.get::<LinearVelocity>(balloon).map(|velocity| velocity.y).expect("balloon has a velocity");
    assert!(height > start.y + 5.0, "balloon only rose from {} to {height}", start.y);
    assert!(velocity > 0.0 && velocity < 9.81, "balloon rises at {velocity} m/s, faster than damping allows");
}

#[test]
fn kinematic_bodies_keep_their_initial_spin() {
    let mut app = load_scene(SCENE);
    let spinner = node(app.world_mut(), "spinner");
    let before = transform(app.world(), spinner);
    let start = physics_time(&app);
    for _ in 0..60 {
        app.update();
    }
    let after = transform(app.world(), spinner);
    let elapsed = physics_time(&app) - start;
    let (axis, angle) = (after.rotation * before.rotation.inverse()).to_axis_angle();
    assert!(elapsed > 0.9, "only {elapsed} s of physics ran");
    assert!(axis.dot(Vec3::Y) > 0.999, "spinner turned around {axis}");
    assert!((angle - std::f32::consts::FRAC_PI_2 * elapsed).abs() < 0.02, "spinner turned {angle} rad in {elapsed} s");
    assert!(after.translation.distance(before.translation) < 1e-4);
}

#[test]
fn locked_axes_keep_bodies_from_turning_or_lifting() {
    let mut app = load_scene(SCENE);
    for _ in 0..60 {
        app.update();
    }
    let world = app.world_mut();
    let puck = node(world, "puck");
    let pose = transform(world, puck);
    assert!(pose.rotation.angle_between(Quat::IDENTITY) < 1e-3, "puck turned to {}", pose.rotation);
    assert!((pose.translation.y - 0.05).abs() < 1e-4, "puck moved to height {}", pose.translation.y);
    assert!(pose.translation.x > -7.9, "puck did not slide, it is at {}", pose.translation);
    assert!((pose.translation.z - 5.0).abs() < 1e-3, "puck slid sideways to {}", pose.translation);
}

#[test]
fn continuous_collision_stops_fast_bodies() {
    let mut app = load_scene(SCENE);
    for _ in 0..20 {
        app.update();
    }
    let world = app.world_mut();
    let (bullet, target) = (node(world, "bullet"), node(world, "bullet_target"));
    let (bullet, target) = (transform(world, bullet).translation, transform(world, target).translation);
    assert!(bullet.x < target.x, "the bullet passed the target to {bullet}");
    assert!(target.x > -5.9, "the bullet did not push the target, which is at {target}");

    let mut app = SceneApp::default().build();
    app.add_observer(|added: On<Add<SweptCcd>>, mut commands: Commands| {
        commands.entity(added.event_target()).remove::<SweptCcd>();
    });
    spawn_scene(&mut app, SCENE).expect("scene loads");
    for _ in 0..20 {
        app.update();
    }
    let world = app.world_mut();
    let (bullet, target) = (node(world, "bullet"), node(world, "bullet_target"));
    let (bullet, target) = (transform(world, bullet).translation, transform(world, target).translation);
    assert!(bullet.x > target.x + 1.0, "without sweeps against dynamic bodies the bullet should fly through the target, but it is at {bullet}");
    assert_eq!(target.x, -6.0);
}

#[test]
fn joints_connect_the_named_bodies() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let (door_frame, door) = (node(world, "door_frame"), node(world, "door"));
    let hinge = joint::<RevoluteJoint>(world, "door_hinge").clone();
    assert_eq!((hinge.body1, hinge.body2, hinge.hinge_axis), (door_frame, door, Vec3::Y));
    assert_eq!(hinge.angle_limit, Some(AngleLimit::new(0.0, std::f32::consts::FRAC_PI_2)));
    let hinge = joint_entity::<RevoluteJoint>(world, "door_hinge");
    assert!(world.get::<JointCollisionDisabled>(hinge).is_some());
    assert_eq!(world.get::<JointDamping>(hinge), Some(&JointDamping { linear: 0.0, angular: 0.0 }));
    assert_eq!(world.get::<Name>(hinge).map(Name::as_str), Some("door_hinge joint"));

    let (cabinet, drawer) = (node(world, "drawer_cabinet"), node(world, "drawer"));
    let slider = joint::<PrismaticJoint>(world, "drawer").clone();
    assert_eq!((slider.body1, slider.body2, slider.slider_axis), (cabinet, drawer, Vec3::X));
    assert_eq!(slider.limits, Some(DistanceLimit::new(0.0, 0.4)));

    let (barrel, lid) = (node(world, "barrel"), node(world, "barrel_lid"));
    let fixed = joint::<FixedJoint>(world, "barrel_lid").clone();
    assert_eq!((fixed.body1, fixed.body2), (barrel, lid));
    let fixed = joint_entity::<FixedJoint>(world, "barrel_lid");
    assert!(world.get::<JointDamping>(fixed).is_none());

    let (first, second) = (node(world, "chain_link_1"), node(world, "chain_link_2"));
    let middle = joint::<SphericalJoint>(world, "chain_middle").clone();
    assert_eq!((middle.body1, middle.body2, middle.twist_axis), (first, second, Vec3::Y));
    assert_eq!((middle.swing_limit, middle.twist_limit), (Some(AngleLimit::new(0.0, std::f32::consts::FRAC_PI_4)), None));
    let top = joint::<SphericalJoint>(world, "chain_top").clone();
    assert_eq!(top.body2, first);
    assert_eq!(world.get::<Name>(top.body1).map(Name::as_str), Some("chain_top anchor"));
    assert_eq!(world.get::<RigidBody>(top.body1), Some(&RigidBody::Static));
    assert!((world.get::<GlobalTransform>(top.body1).expect("the anchor has a transform").translation() - Vec3::new(-6.0, 4.0, -2.0)).length() < 1e-4);

    let mut joints = world.query::<AnyOf<(&FixedJoint, &RevoluteJoint, &PrismaticJoint, &SphericalJoint)>>();
    assert_eq!(joints.iter(world).count(), 5);
}

#[test]
fn hinges_turn_until_their_limit() {
    let mut app = load_scene(SCENE);
    let door = node(app.world_mut(), "door");
    let frame = node(app.world_mut(), "door_frame");
    let mut widest = 0.0_f32;
    for _ in 0..120 {
        app.update();
        let pose = transform(app.world(), door);
        let facing = pose.rotation * Vec3::X;
        let angle = (-facing.z).atan2(facing.x).to_degrees();
        assert!((-3.0..93.0).contains(&angle), "the door swung to {angle} degrees, past its 0 to 90 degree limits");
        assert!(facing.y.abs() < 0.01, "the door tipped off its hinge axis to {facing}");
        widest = widest.max(angle);
        let hinge = pose.transform_point(Vec3::new(-0.5, 0.0, 0.0));
        assert!(hinge.distance(Vec3::new(-2.0, 1.1, 9.0)) < 0.02, "the door came off its hinge to {hinge}");
    }
    assert!(widest > 85.0, "the door only opened to {widest} degrees");
    assert_eq!(transform(app.world(), frame).translation, Vec3::new(-2.05, 1.1, 9.0));
}

#[test]
fn ball_joints_hold_chains_together() {
    let mut app = load_scene(SCENE);
    let first = node(app.world_mut(), "chain_link_1");
    let second = node(app.world_mut(), "chain_link_2");
    let start = transform(app.world(), second).translation;
    let mut swing = 0.0_f32;
    for _ in 0..120 {
        app.update();
        let (upper, lower) = (transform(app.world(), first), transform(app.world(), second));
        assert!(upper.transform_point(Vec3::new(0.0, 0.3, 0.0)).distance(Vec3::new(-6.0, 4.0, -2.0)) < 0.03, "the chain came off its anchor");
        assert!(upper.transform_point(Vec3::new(0.0, -0.3, 0.0)).distance(lower.transform_point(Vec3::new(0.0, 0.3, 0.0))) < 0.03, "the links came apart");
        assert!((upper.rotation * Vec3::Y).angle_between(lower.rotation * Vec3::Y) < 48.0_f32.to_radians(), "the links bent past their swing limit");
        swing = swing.max((lower.translation.x - start.x).abs());
    }
    assert!(swing > 0.2, "the chain only swung {swing} m");
}

#[test]
fn sliders_stop_at_their_limit() {
    let mut app = load_scene(SCENE);
    for _ in 0..60 {
        app.update();
    }
    let world = app.world_mut();
    let drawer = node(world, "drawer");
    let pose = transform(world, drawer);
    assert!(pose.translation.distance(Vec3::new(2.4, 0.5, 9.0)) < 0.02, "the drawer is at {}", pose.translation);
    assert!(pose.rotation.angle_between(Quat::IDENTITY) < 1e-3, "the drawer turned to {}", pose.rotation);
}

#[test]
fn fixed_joints_move_bodies_as_one() {
    let mut app = load_scene(SCENE);
    for _ in 0..120 {
        app.update();
    }
    let world = app.world_mut();
    let (barrel, lid) = (node(world, "barrel"), node(world, "barrel_lid"));
    let (barrel, lid) = (transform(world, barrel), transform(world, lid));
    assert!((barrel.translation.y - 0.5).abs() < 0.02, "the barrel did not land, it is at {}", barrel.translation);
    assert!((lid.translation - barrel.translation).distance(barrel.rotation * Vec3::new(0.0, 0.6, 0.0)) < 0.01, "the lid moved to {} on a barrel at {}", lid.translation, barrel.translation);
    assert!(lid.rotation.angle_between(barrel.rotation) < 1e-2);
}

#[test]
fn joints_to_missing_bodies_are_skipped() {
    let mut app = SceneApp::default().build();
    let extras = json!({"bevy_components": json!({"version": 1, "components": [{"type": "joint", "kind": "revolute", "body1": "nowhere", "body2": null, "axis": [0.0, 1.0, 0.0], "collide": false}]}).to_string()});
    app.world_mut().spawn((Name::new("lost_hinge"), Transform::default(), GltfExtras { value: extras.to_string() }));
    for _ in 0..3 {
        app.update();
    }
    let world = app.world_mut();
    let mut joints = world.query::<&RevoluteJoint>();
    assert_eq!(joints.iter(world).count(), 0);
    let mut anchors = world.query::<&Name>();
    assert!(anchors.iter(world).all(|name| name.as_str() != "lost_hinge anchor"));
}

#[test]
fn joints_pick_bodies_from_their_own_scene() {
    let mut app = SceneApp::default().build();
    let extras = |components: Value| GltfExtras { value: json!({"bevy_components": json!({"version": 1, "components": components}).to_string()}).to_string() };
    let body = json!([{"type": "collider", "shape": "sphere", "size": [1.0, 1.0, 1.0], "radius": 0.5, "height": 1.0, "sensor": false}, {"type": "rigid_body", "kind": "dynamic"}]);
    let hinge = json!([{"type": "joint", "kind": "spherical", "body1": null, "body2": "weight", "axis": [0.0, 1.0, 0.0], "collide": true}]);
    let mut scenes = Vec::new();
    for offset in [0.0, 10.0] {
        let root = app.world_mut().spawn((Name::new("scene"), Transform::from_xyz(offset, 0.0, 0.0))).id();
        let weight = app.world_mut().spawn((Name::new("weight"), Transform::from_xyz(0.0, -1.0, 0.0), extras(body.clone()), ChildOf(root))).id();
        let pivot = app.world_mut().spawn((Name::new("pivot"), Transform::from_xyz(0.0, 0.5, 0.0), extras(hinge.clone()), ChildOf(root))).id();
        scenes.push((root, weight, pivot));
    }
    for _ in 0..3 {
        app.update();
    }
    let world = app.world_mut();
    for (root, weight, pivot) in scenes {
        let mut joints = world.query::<(Entity, &SphericalJoint, &ChildOf)>();
        let (joint, anchor, body) = joints.iter(world).find(|(_, _, parent)| parent.parent() == pivot).map(|(entity, joint, _)| (entity, joint.body1, joint.body2)).expect("each pivot has a joint");
        assert_eq!(body, weight);
        assert_eq!(world.get::<ChildOf>(anchor).map(ChildOf::parent), Some(root));
        assert_eq!(world.get::<Transform>(anchor).map(|transform| transform.translation), Some(Vec3::new(0.0, 0.5, 0.0)));
        assert!(world.get::<JointCollisionDisabled>(joint).is_none());
    }
}

fn with_friction(glb: &[u8], name: &str, friction: f32) -> Vec<u8> {
    let length = u32::from_le_bytes(glb[12..16].try_into().expect("the GLB has a JSON chunk")) as usize;
    let mut gltf: Value = serde_json::from_slice(&glb[20..20 + length]).expect("the GLB holds JSON");
    let node = gltf["nodes"].as_array_mut().expect("the scene has nodes").iter_mut().find(|node| node["name"] == name).unwrap_or_else(|| panic!("No node named {name}"));
    let mut exported: Value = serde_json::from_str(node["extras"]["bevy_components"].as_str().expect("the node has components")).expect("components are JSON");
    exported["components"][0]["friction"] = json!(friction);
    node["extras"]["bevy_components"] = json!(exported.to_string());
    let mut chunk = serde_json::to_vec(&gltf).expect("the glTF serializes");
    chunk.resize(chunk.len().div_ceil(4) * 4, b' ');
    let binary = &glb[20 + length..];
    let mut output = glb[..8].to_vec();
    output.extend_from_slice(&((20 + chunk.len() + binary.len()) as u32).to_le_bytes());
    output.extend_from_slice(&(chunk.len() as u32).to_le_bytes());
    output.extend_from_slice(b"JSON");
    output.extend_from_slice(&chunk);
    output.extend_from_slice(binary);
    return output;
}

fn scene_counts(world: &mut World) -> Vec<(&'static str, usize)> {
    let mut names = world.query::<&Name>();
    let anchors = names.iter(world).filter(|name| name.as_str().ends_with(" anchor")).count();
    let mut joints = world.query::<AnyOf<(&FixedJoint, &RevoluteJoint, &PrismaticJoint, &SphericalJoint)>>();
    let joints = joints.iter(world).count();
    let mut colliders = world.query::<&Collider>();
    let colliders = colliders.iter(world).count();
    let mut bodies = world.query::<&RigidBody>();
    let bodies = bodies.iter(world).count();
    let mut extras = world.query::<&GltfExtras>();
    let extras = extras.iter(world).count();
    return vec![("anchors", anchors), ("joints", joints), ("colliders", colliders), ("rigid bodies", bodies), ("nodes with extras", extras), ("crates", nodes(world, "crate").len()), ("windmill towers", nodes(world, "windmill_tower").len())];
}

#[test]
fn reloaded_scenes_rebuild_their_components_once() {
    let directory = std::env::temp_dir().join(format!("bevy_components_reload_{}", std::process::id()));
    fs::create_dir_all(directory.join("props")).expect("temporary directory");
    fs::copy(format!("{ASSETS}/{SCENE}"), directory.join(SCENE)).expect("scene copy");
    fs::copy(format!("{ASSETS}/props/windmill.glb"), directory.join("props/windmill.glb")).expect("prop copy");
    let mut app = SceneApp { assets: directory.to_string_lossy().to_string(), watch: true, ..default() }.build();
    spawn_scene(&mut app, SCENE).expect("the copied scene loads");
    let before = scene_counts(app.world_mut());
    assert_eq!(before[0], ("anchors", 1));
    let ready = app.world().resource::<ReadyInstances>().0;
    let glb = fs::read(directory.join(SCENE)).expect("scene copy");
    fs::write(directory.join(SCENE), with_friction(&glb, "crate", 0.3)).expect("changed scene");
    app.world().resource::<AssetServer>().reload(SCENE);
    let mut reloaded = false;
    for _ in 0..1000 {
        app.update();
        let friction = colliders(app.world_mut(), "crate").first().and_then(|collider| app.world().get::<Friction>(*collider).copied());
        if friction == Some(Friction::new(0.3)) && app.world().resource::<ReadyInstances>().0 >= ready + 3 {
            reloaded = true;
            break;
        }
        thread::sleep(Duration::from_millis(10));
    }
    for _ in 0..10 {
        app.update();
    }
    fs::remove_dir_all(&directory).ok();
    assert!(reloaded, "the scene was not respawned with the changed friction");
    assert_eq!(scene_counts(app.world_mut()), before);
    let world = app.world_mut();
    let top = joint::<SphericalJoint>(world, "chain_top").clone();
    assert_eq!(top.body2, node(world, "chain_link_1"));
    assert!((world.get::<GlobalTransform>(top.body1).expect("the anchor has a transform").translation() - Vec3::new(-6.0, 4.0, -2.0)).length() < 1e-4);
}

#[test]
fn shadow_flags_reach_meshes_on_and_under_the_object() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    for (name, cast, receive) in [("water", false, false), ("bush_a", false, true), ("bush_b", true, true), ("ground", true, true), ("crate", true, true)] {
        let meshes = meshes(world, name);
        assert!(!meshes.is_empty(), "{name}");
        for mesh in meshes {
            assert_eq!(world.get::<NotShadowCaster>(mesh).is_none(), cast, "{name}");
            assert_eq!(world.get::<NotShadowReceiver>(mesh).is_none(), receive, "{name}");
        }
    }
    let mut casters = world.query_filtered::<Entity, With<NotShadowCaster>>();
    assert_eq!(casters.iter(world).count(), 2);
    let mut receivers = world.query_filtered::<Entity, With<NotShadowReceiver>>();
    assert_eq!(receivers.iter(world).count(), 1);
}

#[test]
fn navigation_tags_reach_meshes_and_colliders_on_and_under_the_object() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    for (name, cost) in [("ground", 1.0), ("water", 3.0)] {
        let mesh = mesh(world, name);
        assert_eq!(world.get::<NavigationWalkable>(mesh).map(|walkable| walkable.cost), Some(cost), "{name}");
        assert!(world.get::<NavigationObstacle>(mesh).is_none(), "{name}");
    }
    for name in ["crate", "crate_copy", "house", "chimney", "bush_a", "cart_body"] {
        let meshes = meshes(world, name);
        assert!(!meshes.is_empty(), "{name}");
        for mesh in meshes {
            assert!(world.get::<NavigationObstacle>(mesh).is_some(), "{name}");
        }
    }
    for name in ["crate", "crate_copy", "cart_shape", "cart_handle"] {
        let node = node(world, name);
        assert!(world.get::<Collider>(node).is_some() && world.get::<NavigationObstacle>(node).is_some(), "{name}");
    }
    for name in ["ground", "house", "cart", "bushes"] {
        let node = node(world, name);
        assert!(world.get::<NavigationObstacle>(node).is_none() && world.get::<NavigationWalkable>(node).is_none(), "{name}");
    }
    for name in ["bush_b", "ball", "lamp"] {
        let mesh = mesh(world, name);
        assert!(world.get::<NavigationObstacle>(mesh).is_none() && world.get::<NavigationWalkable>(mesh).is_none(), "{name}");
    }
    let mut walkable = world.query_filtered::<Entity, With<NavigationWalkable>>();
    assert_eq!(walkable.iter(world).count(), 2);
    let mut obstacles = world.query_filtered::<Entity, With<NavigationObstacle>>();
    assert_eq!(obstacles.iter(world).count(), 11);
}

#[test]
fn navigation_tags_meshes_added_later_and_survives_bad_data() {
    let mut app = SceneApp::default().build();
    let cuboid = json!({"type": "collider", "shape": "cuboid", "size": [1.0, 1.0, 1.0], "radius": 0.5, "height": 1.0, "sensor": false});
    let world = app.world_mut();
    let floor = world.spawn((Name::new("floor"), Transform::default(), component_extras(json!([{"type": "navigation", "kind": "walkable", "cost": -2.0}, cuboid.clone()])))).id();
    let path = world.spawn((Name::new("path"), Transform::default(), component_extras(json!([{"type": "navigation", "kind": "walkable"}, cuboid.clone()])))).id();
    let pond = world.spawn((Name::new("pond"), Transform::default(), component_extras(json!([{"type": "navigation", "kind": "swimmable", "cost": null}, cuboid])))).id();
    for _ in 0..3 {
        app.update();
    }
    let world = app.world_mut();
    assert_eq!(world.get::<NavigationWalkable>(floor).map(|walkable| walkable.cost), Some(1.0));
    assert_eq!(world.get::<NavigationWalkable>(path).map(|walkable| walkable.cost), Some(1.0));
    assert!(world.get::<NavigationWalkable>(pond).is_none() && world.get::<NavigationObstacle>(pond).is_none());
    let rug = world.spawn((Mesh3d::default(), ChildOf(floor))).id();
    app.update();
    assert_eq!(app.world().get::<NavigationWalkable>(rug).map(|walkable| walkable.cost), Some(1.0));
}

#[test]
fn audio_players_load_sounds_from_the_assets_folder() {
    let mut app = SceneApp { audio: true, ..default() }.build();
    if let Err(error) = spawn_scene(&mut app, SCENE) {
        panic!("{SCENE} did not load: {error}");
    }
    let expected = [("campfire", "sounds/campfire.ogg", true, 0.8, false, true, Some(Vec3::splat(0.25))), ("jingle", "sounds/chime.ogg", false, 0.5, true, false, None)];
    for (name, path, looping, volume, paused, spatial, scale) in expected {
        let node = node(app.world_mut(), name);
        let world = app.world();
        let handle = world.get::<AudioPlayer>(node).map(|player| player.0.clone()).unwrap_or_else(|| panic!("{name} has no audio player"));
        assert_eq!(handle.path().map(ToString::to_string), Some(path.to_string()), "{name}");
        let settings = world.get::<PlaybackSettings>(node).unwrap_or_else(|| panic!("{name} has no playback settings"));
        assert!(matches!((looping, settings.mode), (true, PlaybackMode::Loop) | (false, PlaybackMode::Once)), "{name}");
        assert_eq!(settings.volume, Volume::Linear(volume), "{name}");
        assert_eq!((settings.paused, settings.spatial, settings.spatial_scale.map(|spatial_scale| spatial_scale.0)), (paused, spatial, scale), "{name}");
        let asset_server = world.resource::<AssetServer>().clone();
        for _ in 0..500 {
            if asset_server.is_loaded(&handle) {
                break;
            }
            app.update();
            thread::sleep(Duration::from_millis(5));
        }
        let source = app.world().resource::<Assets<AudioSource>>().get(&handle).unwrap_or_else(|| panic!("{path} did not load"));
        assert!(source.decoder().count() > 1000, "{path}");
    }
    let world = app.world_mut();
    let mut players = world.query::<&AudioPlayer>();
    assert_eq!(players.iter(world).count(), 2);
}

#[test]
fn audio_players_are_skipped_without_the_audio_plugin() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    assert!(world.get_resource::<Assets<AudioSource>>().is_none());
    let mut players = world.query::<&AudioPlayer>();
    assert_eq!(players.iter(world).count(), 0);
}

#[test]
fn scene_references_spawn_their_scenes() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    for (name, translation) in [("windmill_a", Vec3::new(-7.0, 1.5, 9.5)), ("windmill_b", Vec3::new(6.0, 1.125, 9.5))] {
        let root = node(world, name);
        let path = world.get::<WorldAssetRoot>(root).and_then(|root| root.0.path()).map(|path| path.to_string());
        assert_eq!(path.as_deref(), Some("props/windmill.glb#Scene0"), "{name}");
        let tower = instance_node(world, name, "windmill_tower");
        let found = world.get::<GlobalTransform>(tower).map(|transform| transform.translation()).expect("tower has a global transform");
        assert!(found.distance(translation) < 1e-4, "{name} tower is at {found}");
        assert!(world.get::<Collider>(tower).and_then(|collider| collider.shape().as_capsule()).is_some(), "{name}");
        assert_eq!(world.get::<RigidBody>(tower), Some(&RigidBody::Static), "{name}");
        instance_node(world, name, "windmill_blades");
    }
    assert_eq!(nodes(world, "windmill_tower").len(), 2);
}

#[test]
fn scene_references_resolve_from_their_scene() {
    let mut app = SceneApp::default().build();
    let scene: Handle<WorldAsset> = app.world().resource::<AssetServer>().load("props/scene.glb#Scene0");
    let root = app.world_mut().spawn(WorldAssetRoot(scene)).id();
    let beside = app.world_mut().spawn((scene_reference("beside", "windmill.glb", 1), ChildOf(root))).id();
    let above = app.world_mut().spawn((scene_reference("above", "../windmill.glb", 0), ChildOf(root))).id();
    let itself = app.world_mut().spawn((scene_reference("itself", "scene.glb", 0), ChildOf(root))).id();
    let other_scene = app.world_mut().spawn((scene_reference("other_scene", "scene.glb", 2), ChildOf(root))).id();
    let outside = app.world_mut().spawn(scene_reference("outside", "props/windmill.glb", 0)).id();
    for _ in 0..3 {
        app.update();
    }
    let world = app.world();
    let path = |entity: Entity| world.get::<WorldAssetRoot>(entity).and_then(|root| root.0.path()).map(|path| path.to_string());
    assert_eq!(path(beside).as_deref(), Some("props/windmill.glb#Scene1"));
    assert_eq!(path(above).as_deref(), Some("windmill.glb#Scene0"));
    assert_eq!(path(itself), None);
    assert_eq!(path(other_scene).as_deref(), Some("props/scene.glb#Scene2"));
    assert_eq!(path(outside).as_deref(), Some("props/windmill.glb#Scene0"));
}

#[test]
fn animations_start_when_the_scene_loads() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let mut expected = vec![(node(world, "gate"), "sample_scene.glb#Animation0", RepeatAnimation::Never, 1.0)];
    for name in ["windmill_a", "windmill_b"] {
        expected.push((instance_node(world, name, "windmill_tower"), "props/windmill.glb#Animation0", RepeatAnimation::Forever, 0.5));
    }
    for (player, clip, repeat, speed) in expected {
        let handle = world.get::<AnimationGraphHandle>(player).expect("animated node has a graph");
        let graph = world.resource::<Assets<AnimationGraph>>().get(&handle.0).expect("graph is loaded");
        let clips: Vec<String> = graph.nodes().filter_map(|index| match &graph.get(index)?.node_type {
            AnimationNodeType::Clip(clip) => clip.path().map(|path| path.to_string()),
            _ => None,
        }).collect();
        assert_eq!(clips, vec![clip.to_string()]);
        let animation_player = world.get::<AnimationPlayer>(player).expect("animated node has a player");
        let playing: Vec<(RepeatAnimation, f32)> = animation_player.playing_animations().map(|(_, active)| (active.repeat_mode(), active.speed())).collect();
        assert_eq!(playing, vec![(repeat, speed)], "{clip}");
    }
    let mut graphs = world.query::<&AnimationGraphHandle>();
    assert_eq!(graphs.iter(world).count(), 3);
}

#[test]
fn animations_move_their_targets() {
    let mut app = load_scene(SCENE);
    let gate = node(app.world_mut(), "gate");
    let blades: Vec<Entity> = ["windmill_a", "windmill_b"].iter().map(|name| instance_node(app.world_mut(), name, "windmill_blades")).collect();
    for _ in 0..120 {
        app.update();
    }
    assert!(rotation(&app, gate).angle_between(Quat::from_rotation_y(FRAC_PI_2)) < 1e-3, "gate stopped at {:?}", rotation(&app, gate).to_euler(EulerRot::YXZ));
    assert!(app.world().get::<AnimationPlayer>(gate).is_some_and(AnimationPlayer::all_finished));
    for wait in [0, 180] {
        for _ in 0..wait {
            app.update();
        }
        let before: Vec<Quat> = blades.iter().map(|entity| rotation(&app, *entity)).collect();
        for _ in 0..30 {
            app.update();
        }
        for (entity, start) in blades.iter().zip(before) {
            let turned = rotation(&app, *entity) * start.inverse();
            assert!(turned.angle_between(Quat::from_rotation_z(-FRAC_PI_4)) < 1e-3, "blades turned {:?} in half a second", turned.to_axis_angle());
        }
    }
}

#[test]
fn lights_get_the_settings_gltf_leaves_out() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let lamp = light_entity(world, "lamp_light");
    let point = world.get::<PointLight>(lamp).expect("lamp_light is a point light");
    assert!((point.intensity - 136_600.0).abs() < 1.0, "{}", point.intensity);
    assert_eq!((point.range, point.radius), (15.0, 0.1));
    assert_eq!((point.shadow_maps_enabled, point.contact_shadows_enabled, point.affects_lightmapped_mesh_diffuse), (true, false, false));
    assert_eq!((point.shadow_depth_bias, point.shadow_normal_bias, point.shadow_map_near_z), (0.1, 0.5, 0.05));
    assert!(world.get::<VolumetricLight>(lamp).is_none());

    let spot_light = light_entity(world, "spot_light");
    let spot = world.get::<SpotLight>(spot_light).expect("spot_light is a spot light");
    let defaults = SpotLight::default();
    assert_eq!((spot.intensity, spot.radius, spot.range), (2000.0, 0.0, 20.0));
    assert_eq!((spot.shadow_maps_enabled, spot.contact_shadows_enabled, spot.affects_lightmapped_mesh_diffuse), (false, true, true));
    assert_eq!((spot.shadow_depth_bias, spot.shadow_normal_bias, spot.shadow_map_near_z), (defaults.shadow_depth_bias, defaults.shadow_normal_bias, defaults.shadow_map_near_z));

    let sun_light = light_entity(world, "sun");
    let sun = world.get::<DirectionalLight>(sun_light).expect("sun is a directional light");
    let defaults = DirectionalLight::default();
    assert_eq!((sun.illuminance, sun.shadow_maps_enabled, sun.contact_shadows_enabled), (683.0, true, false));
    assert_eq!((sun.shadow_depth_bias, sun.shadow_normal_bias), (defaults.shadow_depth_bias, defaults.shadow_normal_bias));
    let cascades = world.get::<CascadeShadowConfig>(sun_light).expect("sun has shadow cascades");
    assert_eq!((cascades.bounds.len(), cascades.minimum_distance, cascades.overlap_proportion), (3, 0.1, 0.2));
    assert!((cascades.bounds[0] - 8.0).abs() < 1e-4 && (cascades.bounds[2] - 80.0).abs() < 1e-3, "{:?}", cascades.bounds);
    assert!(world.get::<VolumetricLight>(sun_light).is_some());
}

#[test]
fn area_lights_become_rect_lights() {
    let mut app = load_scene(SCENE);
    let world = app.world_mut();
    let mut lights = world.query::<(&Name, &RectLight, &GlobalTransform)>();
    let found: Vec<(String, RectLight, Vec3)> = lights.iter(world).map(|(name, light, transform)| (name.to_string(), *light, Vec3::from(transform.forward()))).collect();
    assert_eq!(found.len(), 1);
    let (name, light, forward) = &found[0];
    assert_eq!(name, "window_light");
    assert_eq!((light.width, light.height, light.range, light.color), (2.0, 1.0, 20.0, Color::linear_rgb(1.0, 1.0, 1.0)));
    assert!((light.intensity - 34_150.0).abs() < 1.0, "{}", light.intensity);
    assert!(forward.dot(Vec3::Z) > 0.999, "window_light faces {forward}");
}

#[test]
fn ambient_light_comes_from_the_scene() {
    let app = load_scene(SCENE);
    let ambient = app.world().resource::<GlobalAmbientLight>();
    assert_eq!((ambient.color, ambient.brightness, ambient.affects_lightmapped_meshes), (Color::linear_rgb(0.9, 0.95, 1.0), 120.0, true));
}

#[test]
fn cameras_show_the_scene_sky() {
    let mut app = SceneApp::default().build();
    let early = app.world_mut().spawn(Camera3d::default()).id();
    let opted_out = app.world_mut().spawn((Camera3d::default(), NoBlenderSky)).id();
    if let Err(error) = spawn_scene(&mut app, SCENE) {
        panic!("{SCENE} did not load: {error}");
    }
    let late = app.world_mut().spawn(Camera3d::default()).id();
    app.update();
    let world = app.world_mut();
    let sky = world.resource::<BlenderSky>().clone();
    assert_eq!((sky.brightness, sky.environment_light), (1000.0, Some(300.0)));
    let image = world.resource::<Assets<Image>>().get(&sky.image).expect("the sky cubemap is loaded");
    assert_eq!(image.texture_descriptor.size, Extent3d { width: 16, height: 16, depth_or_array_layers: 6 });
    assert_eq!(image.texture_view_descriptor.as_ref().and_then(|view| view.dimension), Some(TextureViewDimension::Cube));
    for camera in [early, late] {
        let skybox = world.get::<Skybox>(camera).expect("the camera shows the sky");
        assert_eq!((skybox.image.as_ref().map(Handle::id), skybox.brightness, skybox.rotation), (Some(sky.image.id()), 1000.0, Quat::IDENTITY));
        let light = world.get::<GeneratedEnvironmentMapLight>(camera).expect("the sky lights the scene");
        assert_eq!((light.environment_map.id(), light.intensity, light.affects_lightmapped_mesh_diffuse), (sky.image.id(), 300.0, true));
    }
    assert!(world.get::<Skybox>(opted_out).is_none());
    assert!(world.get::<GeneratedEnvironmentMapLight>(opted_out).is_none());
}

#[test]
fn the_sky_follows_changes_and_needs_a_usable_cubemap() {
    let mut app = SceneApp::default().build();
    let world = app.world_mut();
    let mut images = world.resource_mut::<Assets<Image>>();
    let mut image = |width: u32, height: u32, layers: u32| images.add(Image::new_fill(Extent3d { width, height, depth_or_array_layers: layers }, TextureDimension::D2, &[0; 8], TextureFormat::Rgba16Float, RenderAssetUsages::default()));
    let (cubemap, uneven, flat) = (image(8, 8, 6), image(12, 12, 6), image(8, 8, 1));
    let camera = world.spawn(Camera3d::default()).id();
    let show = |app: &mut App, image: &Handle<Image>, environment_light: Option<f32>| -> (Option<(AssetId<Image>, f32)>, Option<f32>) {
        app.world_mut().insert_resource(BlenderSky { image: image.clone(), brightness: 500.0, environment_light });
        for _ in 0..2 {
            app.update();
        }
        let world = app.world();
        return (world.get::<Skybox>(camera).map(|skybox| (skybox.image.as_ref().expect("the skybox has an image").id(), skybox.brightness)), world.get::<GeneratedEnvironmentMapLight>(camera).map(|light| light.intensity));
    };
    assert_eq!(show(&mut app, &cubemap, Some(200.0)), (Some((cubemap.id(), 500.0)), Some(200.0)));
    app.world_mut().entity_mut(camera).insert(EnvironmentMapLight::default());
    assert_eq!(show(&mut app, &uneven, Some(200.0)), (Some((uneven.id(), 500.0)), None));
    assert!(app.world().get::<EnvironmentMapLight>(camera).is_none());
    assert_eq!(show(&mut app, &cubemap, None), (Some((cubemap.id(), 500.0)), None));
    assert_eq!(show(&mut app, &cubemap, Some(100.0)), (Some((cubemap.id(), 500.0)), Some(100.0)));
    assert_eq!(show(&mut app, &flat, Some(100.0)), (None, None));
}

#[test]
fn invalid_light_settings_are_skipped() {
    let mut app = SceneApp::default().build();
    let light = json!({"type": "light", "kind": "directional", "shadows": true, "contact_shadows": false, "volumetric": false, "baked": true, "cascades": {"count": 3, "minimum_distance": 10.0, "first_cascade_far_bound": 5.0, "maximum_distance": 100.0, "overlap_proportion": 0.2}});
    let world = app.world_mut();
    let sun = world.spawn((Name::new("bad_cascades"), Transform::default(), component_extras(json!([light])))).with_child(DirectionalLight::default()).id();
    let candle = world.spawn((Name::new("candle"), Transform::default(), component_extras(json!([{"type": "light", "kind": "candle", "shadows": true, "contact_shadows": false, "volumetric": false, "baked": false}])))).with_child(PointLight::default()).id();
    let lonely = world.spawn((Name::new("lonely"), Transform::default(), component_extras(json!([{"type": "light", "kind": "point", "shadows": true, "contact_shadows": false, "volumetric": true, "baked": false}, {"type": "ambient_light", "color": [1.0, 0.0, 0.0], "brightness": 5.0, "baked": false}])))).id();
    for _ in 0..3 {
        app.update();
    }
    let world = app.world_mut();
    let sun_light = world.get::<Children>(sun).expect("the sun keeps its light")[0];
    let directional = world.get::<DirectionalLight>(sun_light).expect("the sun light is directional");
    assert_eq!((directional.shadow_maps_enabled, directional.affects_lightmapped_mesh_diffuse), (true, false));
    assert_eq!(world.get::<CascadeShadowConfig>(sun_light).map(|cascades| cascades.bounds.clone()), Some(CascadeShadowConfig::default().bounds));
    let candle_light = world.get::<Children>(candle).expect("the candle keeps its light")[0];
    assert_eq!(world.get::<PointLight>(candle_light).map(|point| point.shadow_maps_enabled), Some(PointLight::default().shadow_maps_enabled));
    assert!(world.get::<VolumetricLight>(lonely).is_none());
    assert_ne!(world.resource::<GlobalAmbientLight>().color, Color::linear_rgb(1.0, 0.0, 0.0));
}
