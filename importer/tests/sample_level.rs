mod common;

use avian3d::prelude::*;
use bevy::{audio::{PlaybackMode, Volume}, camera::visibility::VisibilityRange, gltf::GltfExtras, light::{NotShadowCaster, NotShadowReceiver}, prelude::*};
use bevy_components_importer::BlenderCustomComponents;
use common::*;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{thread, time::Duration};

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

fn transform(world: &World, entity: Entity) -> Transform {
    return world.get::<Transform>(entity).copied().unwrap_or_else(|| panic!("{entity} has no transform"));
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
    assert_eq!(count, 43);
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
    assert!(world.get::<GravityScale>(entity).is_none());
    assert!(world.get::<LinearDamping>(entity).is_none());
    assert!(world.get::<AngularDamping>(entity).is_none());
    assert!(world.get::<LockedAxes>(entity).is_none());
    assert!(world.get::<SweptCcd>(entity).is_none());
}

#[test]
fn locked_axes_cancel_initial_velocity() {
    let mut app = LevelApp::default().build();
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
    let mut app = load_level(LEVEL);
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
    let mut app = load_level(LEVEL);
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
    let mut app = load_level(LEVEL);
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
    let mut app = load_level(LEVEL);
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
    let mut app = load_level(LEVEL);
    for _ in 0..20 {
        app.update();
    }
    let world = app.world_mut();
    let (bullet, target) = (node(world, "bullet"), node(world, "bullet_target"));
    let (bullet, target) = (transform(world, bullet).translation, transform(world, target).translation);
    assert!(bullet.x < target.x, "the bullet passed the target to {bullet}");
    assert!(target.x > -5.9, "the bullet did not push the target, which is at {target}");

    let mut app = LevelApp::default().build();
    app.add_observer(|added: On<Add<SweptCcd>>, mut commands: Commands| {
        commands.entity(added.event_target()).remove::<SweptCcd>();
    });
    spawn_level(&mut app, LEVEL).expect("level loads");
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
    let mut app = load_level(LEVEL);
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
    let mut app = load_level(LEVEL);
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
    let mut app = load_level(LEVEL);
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
    let mut app = load_level(LEVEL);
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
    let mut app = load_level(LEVEL);
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
    let mut app = LevelApp::default().build();
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
fn joints_pick_bodies_from_their_own_level() {
    let mut app = LevelApp::default().build();
    let extras = |components: Value| GltfExtras { value: json!({"bevy_components": json!({"version": 1, "components": components}).to_string()}).to_string() };
    let body = json!([{"type": "collider", "shape": "sphere", "size": [1.0, 1.0, 1.0], "radius": 0.5, "height": 1.0, "sensor": false}, {"type": "rigid_body", "kind": "dynamic"}]);
    let hinge = json!([{"type": "joint", "kind": "spherical", "body1": null, "body2": "weight", "axis": [0.0, 1.0, 0.0], "collide": true}]);
    let mut levels = Vec::new();
    for offset in [0.0, 10.0] {
        let root = app.world_mut().spawn((Name::new("level"), Transform::from_xyz(offset, 0.0, 0.0))).id();
        let weight = app.world_mut().spawn((Name::new("weight"), Transform::from_xyz(0.0, -1.0, 0.0), extras(body.clone()), ChildOf(root))).id();
        let pivot = app.world_mut().spawn((Name::new("pivot"), Transform::from_xyz(0.0, 0.5, 0.0), extras(hinge.clone()), ChildOf(root))).id();
        levels.push((root, weight, pivot));
    }
    for _ in 0..3 {
        app.update();
    }
    let world = app.world_mut();
    for (root, weight, pivot) in levels {
        let mut joints = world.query::<(Entity, &SphericalJoint, &ChildOf)>();
        let (joint, anchor, body) = joints.iter(world).find(|(_, _, parent)| parent.parent() == pivot).map(|(entity, joint, _)| (entity, joint.body1, joint.body2)).expect("each pivot has a joint");
        assert_eq!(body, weight);
        assert_eq!(world.get::<ChildOf>(anchor).map(ChildOf::parent), Some(root));
        assert_eq!(world.get::<Transform>(anchor).map(|transform| transform.translation), Some(Vec3::new(0.0, 0.5, 0.0)));
        assert!(world.get::<JointCollisionDisabled>(joint).is_none());
    }
}

#[test]
fn shadow_flags_reach_meshes_on_and_under_the_object() {
    let mut app = load_level(LEVEL);
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
fn audio_players_load_sounds_from_the_assets_folder() {
    let mut app = LevelApp { audio: true, ..default() }.build();
    if let Err(error) = spawn_level(&mut app, LEVEL) {
        panic!("{LEVEL} did not load: {error}");
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
    let mut app = load_level(LEVEL);
    let world = app.world_mut();
    assert!(world.get_resource::<Assets<AudioSource>>().is_none());
    let mut players = world.query::<&AudioPlayer>();
    assert_eq!(players.iter(world).count(), 0);
}
