mod common;

use avian3d::prelude::*;
use bevy::{camera::visibility::VisibilityRange, gltf::GltfExtras, prelude::*};
use bevy_components_importer::BlenderCustomComponents;
use common::*;
use serde::Deserialize;
use serde_json::{Value, json};

#[derive(Deserialize, Debug, PartialEq)]
struct Pickup {
    item: String,
    amount: i32,
    respawn: bool,
    weight: f32,
    spin: Vec3,
    glow: Color,
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

fn colliders(world: &mut World, name: &str) -> Vec<Entity> {
    let mut entities = meshes(world, name);
    entities.push(node(world, name));
    return entities.into_iter().filter(|entity| world.get::<Collider>(*entity).is_some()).collect();
}

#[test]
fn visibility_ranges_are_set_on_meshes() {
    let mut app = load_level(LEVEL);
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
    let mut app = load_level(LEVEL);
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
    for name in ["ghost", "ice_block", "rubber_block"] {
        assert!(node_collider(world, name).shape().as_cuboid().is_some(), "{name}");
    }
    for name in ["lamp", "tree_lod0", "tree_lod1", "player_spawn", "enemy_spawn", "cart", "cart_body"] {
        assert!(colliders(world, name).is_empty(), "{name}");
    }
}

#[test]
fn primitive_colliders_are_added_once_per_object() {
    let mut app = load_level(LEVEL);
    let world = app.world_mut();
    for name in ["crate", "crate_copy", "ball", "pillar", "trigger_zone", "pickup_zone", "cart_shape", "cart_handle", "bouncy_ball", "ghost", "ramp", "ice_block", "rubber_block"] {
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
    let mut app = load_level(LEVEL);
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
    let mut app = load_level(LEVEL);
    let world = app.world_mut();
    let expected = [("ground", RigidBody::Static, "ground"), ("crate", RigidBody::Dynamic, "crate"), ("crate_copy", RigidBody::Dynamic, "crate_copy"), ("ball", RigidBody::Kinematic, "ball"), ("pillar", RigidBody::Static, "pillar"), ("rock", RigidBody::Dynamic, "rock"), ("trigger_zone", RigidBody::Static, "trigger_zone"), ("pickup_zone", RigidBody::Static, "pickup_zone"), ("house", RigidBody::Static, "house"), ("chimney", RigidBody::Static, "house"), ("cart_shape", RigidBody::Dynamic, "cart"), ("cart_handle", RigidBody::Dynamic, "cart"), ("bouncy_ball", RigidBody::Dynamic, "bouncy_ball"), ("ghost", RigidBody::Dynamic, "ghost"), ("ramp", RigidBody::Static, "ramp"), ("ice_block", RigidBody::Dynamic, "ice_block"), ("rubber_block", RigidBody::Dynamic, "rubber_block")];
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
    let mut app = load_level(LEVEL);
    let world = app.world_mut();
    for (name, translation) in [("player_spawn", Vec3::new(2.0, 0.0, -3.0)), ("enemy_spawn", Vec3::new(-6.0, 0.0, 6.0))] {
        let node = node(world, name);
        assert_eq!(world.get::<Transform>(node).map(|transform| transform.translation), Some(translation), "{name}");
    }
}

#[test]
fn custom_components_keep_type_paths_and_data() {
    let mut app = load_level(LEVEL);
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
fn custom_component_fields_deserialize_into_rust_types() {
    let mut app = load_level(LEVEL);
    let world = app.world_mut();
    let node = node(world, "pickup_zone");
    let custom = world.get::<BlenderCustomComponents>(node).expect("pickup_zone has custom components");
    let data = custom.0.iter().find(|component| component.type_path == "my_game::Pickup").map(|component| component.data.clone()).expect("pickup_zone has a Pickup");
    let pickup: Pickup = serde_json::from_value(data).expect("Pickup fields match the Rust struct");
    assert_eq!(pickup, Pickup { item: "coin".to_string(), amount: 5, respawn: true, weight: 0.1, spin: Vec3::new(0.0, 1.5, 0.0), glow: Color::srgba(1.0, 0.8, 0.2, 1.0) });
}

#[test]
fn only_component_data_is_exported() {
    let mut app = load_level(LEVEL);
    let world = app.world_mut();
    let mut extras = world.query::<(&Name, &GltfExtras)>();
    let mut count = 0;
    for (name, extra) in extras.iter(world) {
        let value: Value = serde_json::from_str(&extra.value).expect("extras are JSON");
        assert_eq!(value.as_object().map(|object| object.keys().cloned().collect::<Vec<_>>()), Some(vec!["bevy_components".to_string()]), "{name}");
        count += 1;
    }
    assert_eq!(count, 22);
}

#[test]
fn dynamic_bodies_rest_on_the_ground() {
    let mut app = load_level(LEVEL);
    for _ in 0..120 {
        app.update();
    }
    let world = app.world_mut();
    assert!(world.resource::<Time<Physics>>().elapsed_secs() > 1.5);
    for (name, start) in [("crate", Vec3::new(3.0, 1.0, 2.0)), ("crate_copy", Vec3::new(6.0, 1.0, 2.0)), ("ball", Vec3::new(-3.0, 0.5, 0.0)), ("cart", Vec3::new(-8.0, 0.5, 2.0))] {
        let node = node(world, name);
        let translation = world.get::<Transform>(node).map(|transform| transform.translation).unwrap_or_else(|| panic!("{name} has no transform"));
        assert!(translation.distance(start) < 0.05, "{name} moved from {start} to {translation}");
    }
}

#[test]
fn colliders_keep_surface_and_layer_settings() {
    let mut app = load_level(LEVEL);
    let world = app.world_mut();
    let expected = [("ground", 0.5, 0.0, CollisionLayers::DEFAULT), ("crate", 0.8, 0.1, CollisionLayers::DEFAULT), ("crate_copy", 0.8, 0.1, CollisionLayers::DEFAULT), ("rock", 0.5, 0.0, CollisionLayers::DEFAULT), ("house", 0.5, 0.0, CollisionLayers::DEFAULT), ("chimney", 0.5, 0.0, CollisionLayers::DEFAULT), ("trigger_zone", 0.5, 0.0, CollisionLayers::from_bits(0b100, 0b010)), ("cart_shape", 0.5, 0.0, CollisionLayers::DEFAULT), ("bouncy_ball", 0.5, 1.0, CollisionLayers::DEFAULT), ("ghost", 0.5, 0.0, CollisionLayers::from_bits(0b10, 0b10)), ("ice_block", 0.0, 0.0, CollisionLayers::DEFAULT), ("rubber_block", 1.0, 0.0, CollisionLayers::DEFAULT)];
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

#[test]
fn masses_set_the_total_body_mass() {
    let mut app = load_level(LEVEL);
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
    let mut app = load_level(LEVEL);
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
    let mut app = load_level(LEVEL);
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
    let mut app = load_level(LEVEL);
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
    let mut app = LevelApp::default().build();
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
}
