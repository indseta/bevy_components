extern crate self as my_game;

mod common;
#[path = "bsn/sample_scene.rs"]
mod sample_scene;
#[path = "bsn/static_scene.rs"]
mod static_scene;

use avian3d::prelude::*;
use bevy::{animation::{AnimatedBy, AnimationTargetId, graph::AnimationNodeType}, asset::UntypedAssetId, audio::PlaybackSettings, camera::visibility::VisibilityRange, gltf::Gltf, light::{CascadeShadowConfig, FogVolume, GeneratedEnvironmentMapLight, IrradianceVolume, LightProbe, NotShadowCaster, NotShadowReceiver, ParallaxCorrection, VolumetricLight}, pbr::Lightmap, prelude::*, render::render_resource::Face, world_serialization::WorldAssetRoot};
use bevy_components_importer::{BlenderCustomComponents, NavigationObstacle, NavigationWalkable};
use common::*;
use serde_json::{Value, json};
use std::{collections::{BTreeMap, HashSet}, fmt::Debug, fs, thread, time::Duration};

const ROOT: &str = "sample_scene";
const BSN_SCENE: &str = "bsn/sample_scene.glb";
const STATIC_SCENE: &str = "bsn_static/static_scene.glb";
const STATIC_ROCKS: usize = 260;
const DECIMALS: usize = 4;

#[derive(Component, Reflect, Clone, Default)]
#[reflect(Component, Default)]
#[type_path = "my_game"]
pub struct Pickup {
    pub item: String,
    pub amount: i32,
    pub respawn: bool,
    pub weight: f32,
    pub spin: Vec3,
    pub glow: Color,
}

#[derive(Component, Reflect, Clone, Default)]
#[reflect(Component, Default)]
#[type_path = "my_game"]
pub struct Wave {
    pub count: i32,
    pub delay: f32,
}

#[derive(Component, Reflect, Clone, Default)]
#[reflect(Component, Default)]
#[type_path = "my_game"]
pub struct PlayerSpawn;

#[derive(Component, Reflect, Clone, Default)]
#[reflect(Component, Default)]
#[type_path = "my_game"]
pub struct EnemySpawn;

#[derive(Component, Reflect, Clone, Default)]
#[reflect(Component, Default)]
#[type_path = "my_game"]
pub struct Glow {
    pub color: Vec3,
    pub label: String,
}

#[derive(Component, Reflect, Clone, Default)]
#[reflect(Component, Default)]
#[type_path = "my_game"]
pub struct Flicker(pub f32);

struct Tree {
    names: Vec<String>,
    children: Vec<Vec<usize>>,
    roots: Vec<usize>,
}

fn gltf_tree(file: &str) -> Tree {
    let data = fs::read(format!("{ASSETS}/{file}")).unwrap_or_else(|error| panic!("{file} could not be read: {error}"));
    let length = u32::from_le_bytes(data[12..16].try_into().unwrap()) as usize;
    let gltf: Value = serde_json::from_slice(&data[20..20 + length]).expect("the GLB has a JSON chunk");
    let nodes = gltf["nodes"].as_array().expect("the GLB has nodes");
    let names = nodes.iter().enumerate().map(|(index, node)| node["name"].as_str().map_or(format!("GltfNode{index}"), str::to_string)).collect();
    let children = nodes.iter().map(|node| node["children"].as_array().map_or(Vec::new(), |children| children.iter().filter_map(Value::as_u64).map(|child| child as usize).collect())).collect();
    let roots = gltf["scenes"][0]["nodes"].as_array().expect("the GLB has a scene").iter().filter_map(Value::as_u64).map(|root| root as usize).collect();
    return Tree { names, children, roots };
}

fn bsn_app(paused: bool) -> App {
    let mut app = SceneApp { plugin: false, audio: true, ..default() }.build();
    if paused {
        app.world_mut().resource_mut::<Time<Physics>>().pause();
    }
    app.world_mut().commands().queue_spawn_scene(sample_scene::setup());
    app.world_mut().flush();
    for _ in 0..1000 {
        app.update();
        if bsn_ready(app.world_mut()) {
            for _ in 0..10 {
                app.update();
            }
            return app;
        }
        thread::sleep(Duration::from_millis(10));
    }
    panic!("the BSN scene did not spawn");
}

fn bsn_ready(world: &mut World) -> bool {
    let spawned = world.query::<&Name>().iter(world).any(|name| name.as_str() == ROOT);
    let constructors = world.query_filtered::<(), With<ColliderConstructor>>().iter(world).count();
    let references = world.query::<&WorldAssetRoot>().iter(world).count();
    let mut handles: Vec<UntypedAssetId> = world.query::<&Mesh3d>().iter(world).map(|mesh| mesh.id().untyped()).collect();
    handles.extend(world.query::<&Lightmap>().iter(world).map(|lightmap| lightmap.image.id().untyped()));
    handles.extend(world.query::<&GeneratedEnvironmentMapLight>().iter(world).map(|light| light.environment_map.id().untyped()));
    handles.extend(world.query::<&IrradianceVolume>().iter(world).map(|volume| volume.voxels.id().untyped()));
    let asset_server = world.resource::<AssetServer>();
    let loaded = handles.iter().all(|handle| asset_server.is_loaded_with_dependencies(*handle));
    return spawned && constructors == 0 && loaded && world.resource::<ReadyInstances>().0 >= references;
}

fn static_app() -> App {
    let mut app = SceneApp { plugin: false, ..default() }.build();
    app.world_mut().commands().queue_spawn_scene(static_scene::setup());
    app.world_mut().flush();
    for _ in 0..1000 {
        app.update();
        let world = app.world_mut();
        let mut handles: Vec<UntypedAssetId> = world.query::<&Mesh3d>().iter(world).map(|mesh| mesh.id().untyped()).collect();
        handles.extend(world.query::<&MeshMaterial3d<StandardMaterial>>().iter(world).map(|material| material.id().untyped()));
        let asset_server = world.resource::<AssetServer>();
        if handles.len() == 2 * (STATIC_ROCKS + 2) && handles.iter().all(|handle| asset_server.is_loaded_with_dependencies(*handle)) {
            return app;
        }
        thread::sleep(Duration::from_millis(10));
    }
    panic!("the static BSN scene did not spawn");
}

fn cull_mode(app: &mut App, target: &str) -> Option<Face> {
    let entity = named(app.world_mut(), target);
    let material = app.world().get::<MeshMaterial3d<StandardMaterial>>(entity).unwrap_or_else(|| panic!("{target} has a material"));
    return app.world().resource::<Assets<StandardMaterial>>().get(material.id()).expect("the material is loaded").cull_mode;
}

fn glb_app() -> App {
    let mut app = SceneApp { audio: true, ..default() }.build();
    app.world_mut().resource_mut::<Time<Physics>>().pause();
    if let Err(error) = spawn_scene(&mut app, SCENE) {
        panic!("{SCENE} did not load: {error}");
    }
    return app;
}

fn rounded(text: &str) -> String {
    let characters: Vec<char> = text.chars().collect();
    let mut output = String::new();
    let mut index = 0;
    while index < characters.len() {
        let character = characters[index];
        let previous = index.checked_sub(1).map(|before| characters[before]);
        let starts = character.is_ascii_digit() || (character == '-' && characters.get(index + 1).is_some_and(char::is_ascii_digit));
        if !starts || previous.is_some_and(|before| before.is_alphanumeric() || before == '_') {
            output.push(character);
            index += 1;
            continue;
        }
        let start = index;
        index += 1;
        while index < characters.len() && (characters[index].is_ascii_digit() || characters[index] == '.' || characters[index] == 'e' || (characters[index] == '-' && characters[index - 1] == 'e')) {
            index += 1;
        }
        let number: String = characters[start..index].iter().collect();
        match number.parse::<f64>() {
            Ok(value) if number.contains(['.', 'e']) => {
                let value = if value.abs() < 0.5 * 10f64.powi(-(DECIMALS as i32)) { 0.0 } else { value };
                output.push_str(&format!("{value:.DECIMALS$}"));
            }
            _ => output.push_str(&number),
        }
    }
    return output;
}

fn debug<T: Debug>(value: &T) -> String {
    return rounded(&format!("{value:?}"));
}

fn label(path: Option<String>) -> String {
    let path = path.unwrap_or_default();
    return path.rsplit_once('#').map_or(path.clone(), |(_, label)| label.to_string());
}

fn image(world: &World, handle: &Handle<Image>) -> String {
    let Some(image) = world.resource::<Assets<Image>>().get(handle) else { return "missing image".to_string(); };
    return format!("{:?} {:?} {:?}", image.texture_descriptor.size, image.texture_descriptor.format, image.texture_view_descriptor.as_ref().and_then(|view| view.dimension));
}

fn name(world: &World, entity: Entity) -> String {
    return world.get::<Name>(entity).map_or(format!("{entity}"), |name| name.as_str().to_string());
}

fn joint<T: Component + Clone + Debug>(world: &World, entity: Entity, bodies: fn(&mut T) -> [&mut Entity; 2], found: &mut Vec<String>) {
    let Some(joint) = world.get::<T>(entity) else { return; };
    let mut joint = joint.clone();
    let names: Vec<String> = bodies(&mut joint).into_iter().map(|body| {
        let named = name(world, *body);
        *body = Entity::PLACEHOLDER;
        return named;
    }).collect();
    found.push(format!("{} {names:?}", debug(&joint)));
}

fn custom(type_path: &str, data: Value) -> String {
    return rounded(&format!("{type_path} {data}"));
}

fn srgba(color: Color) -> Value {
    let color = color.to_srgba();
    return json!({"Srgba": {"red": color.red, "green": color.green, "blue": color.blue, "alpha": color.alpha}});
}

fn describe(world: &World, entity: Entity) -> Vec<String> {
    let target = world.entity(entity);
    let mut found = Vec::new();
    macro_rules! present {
        ($($component:ty),*) => {
            $(if let Some(component) = target.get::<$component>() {
                found.push(debug(component));
            })*
        };
    }
    macro_rules! changed {
        ($($component:ty),*) => {
            $(if let Some(component) = target.get::<$component>() && debug(component) != debug(&<$component>::default()) {
                found.push(debug(component));
            })*
        };
    }
    present!(NavigationWalkable, NavigationObstacle, NotShadowCaster, NotShadowReceiver, Sensor, RigidBody, Mass, NoAutoMass, SweptCcd, PointLight, SpotLight, DirectionalLight, RectLight, CascadeShadowConfig, VolumetricLight, PlaybackSettings, FogVolume, LightProbe, JointDamping, JointCollisionDisabled, AnimationTargetId);
    changed!(Friction, Restitution, CollisionLayers, LockedAxes, GravityScale, LinearDamping, AngularDamping, LinearVelocity, AngularVelocity);
    if let Some(range) = target.get::<VisibilityRange>() {
        found.push(format!("VisibilityRange {} {} {}", debug(&range.start_margin), debug(&range.end_margin), range.use_aabb));
    }
    if let Some(correction) = target.get::<ParallaxCorrection>() {
        found.push(format!("ParallaxCorrection {}", matches!(correction, ParallaxCorrection::None)));
    }
    if let Some(mesh) = target.get::<Mesh3d>() {
        found.push(format!("Mesh3d {}", label(mesh.0.path().map(ToString::to_string))));
    }
    if let Some(material) = target.get::<MeshMaterial3d<StandardMaterial>>() {
        found.push(format!("MeshMaterial3d {}", label(material.0.path().map(ToString::to_string))));
    }
    if let Some(collider) = target.get::<Collider>() {
        found.push(format!("Collider {:?} {}", collider.shape().shape_type(), debug(&collider.aabb(Vec3::ZERO, Quat::IDENTITY, 0.0))));
    }
    if let Some(lightmap) = target.get::<Lightmap>() {
        found.push(format!("Lightmap {} {} {}", image(world, &lightmap.image), debug(&lightmap.uv_rect), lightmap.bicubic_sampling));
    }
    if let Some(light) = target.get::<GeneratedEnvironmentMapLight>() {
        found.push(format!("GeneratedEnvironmentMapLight {} {} {} {}", image(world, &light.environment_map), rounded(&light.intensity.to_string()), debug(&light.rotation), light.affects_lightmapped_mesh_diffuse));
    }
    if let Some(volume) = target.get::<IrradianceVolume>() {
        found.push(format!("IrradianceVolume {} {} {}", image(world, &volume.voxels), rounded(&volume.intensity.to_string()), volume.affects_lightmapped_meshes));
    }
    if let Some(audio) = target.get::<AudioPlayer>() {
        found.push(format!("AudioPlayer {:?}", audio.0.path().map(ToString::to_string)));
    }
    if let Some(root) = target.get::<WorldAssetRoot>() {
        found.push(format!("WorldAssetRoot {:?}", root.0.path().map(ToString::to_string)));
    }
    if let Some(animated) = target.get::<AnimatedBy>() {
        found.push(format!("AnimatedBy {}", name(world, animated.0)));
    }
    if let Some(player) = target.get::<AnimationPlayer>() {
        let mut playing: Vec<String> = player.playing_animations().map(|(node, active)| format!("{node:?} {:?} {}", active.repeat_mode(), rounded(&active.speed().to_string()))).collect();
        playing.sort();
        found.push(format!("AnimationPlayer {playing:?}"));
    }
    if let Some(graph) = target.get::<AnimationGraphHandle>() {
        let graph = world.resource::<Assets<AnimationGraph>>().get(&graph.0).expect("the animation graph is loaded");
        let clips: Vec<String> = graph.nodes().filter_map(|index| match &graph.get(index)?.node_type {
            AnimationNodeType::Clip(clip) => Some(label(clip.path().map(ToString::to_string))),
            _ => None,
        }).collect();
        found.push(format!("AnimationGraph {clips:?}"));
    }
    joint::<FixedJoint>(world, entity, |joint| [&mut joint.body1, &mut joint.body2], &mut found);
    joint::<RevoluteJoint>(world, entity, |joint| [&mut joint.body1, &mut joint.body2], &mut found);
    joint::<PrismaticJoint>(world, entity, |joint| [&mut joint.body1, &mut joint.body2], &mut found);
    joint::<SphericalJoint>(world, entity, |joint| [&mut joint.body1, &mut joint.body2], &mut found);
    if let Some(customs) = target.get::<BlenderCustomComponents>() {
        found.extend(customs.0.iter().map(|component| custom(&component.type_path, component.data.clone())));
    }
    if let Some(pickup) = target.get::<Pickup>() {
        found.push(custom("my_game::Pickup", json!({"item": pickup.item, "amount": pickup.amount, "respawn": pickup.respawn, "weight": pickup.weight, "spin": pickup.spin.to_array(), "glow": srgba(pickup.glow)})));
    }
    if let Some(wave) = target.get::<Wave>() {
        found.push(custom("my_game::Wave", json!({"count": wave.count, "delay": wave.delay})));
    }
    if target.contains::<PlayerSpawn>() {
        found.push(custom("my_game::PlayerSpawn", json!({})));
    }
    if target.contains::<EnemySpawn>() {
        found.push(custom("my_game::EnemySpawn", json!({})));
    }
    if let Some(glow) = target.get::<Glow>() {
        found.push(custom("my_game::Glow", json!({"color": glow.color.to_array(), "label": glow.label})));
    }
    if let Some(flicker) = target.get::<Flicker>() {
        found.push(custom("my_game::Flicker", json!(flicker.0)));
    }
    return found;
}

fn walk(world: &World, entity: Entity, node: usize, path: &str, tree: &Tree, nodes: &mut BTreeMap<String, Vec<String>>) {
    let path = format!("{path}/{}", tree.names[node]);
    let transform = world.get::<Transform>(entity).expect("nodes have a transform");
    let mut found = vec![if world.get::<AnimatedBy>(entity).is_some() { format!("Transform {} {}", debug(&transform.translation), debug(&transform.scale)) } else { format!("Transform {}", debug(transform)) }];
    found.extend(describe(world, entity));
    let children: Vec<Entity> = world.get::<Children>(entity).map_or(Vec::new(), |children| children.iter().collect());
    let mut matched = HashSet::new();
    for child in &tree.children[node] {
        let Some(child_entity) = children.iter().copied().find(|candidate| !matched.contains(candidate) && world.get::<Name>(*candidate).is_some_and(|name| name.as_str() == tree.names[*child])) else {
            found.push(format!("missing child {}", tree.names[*child]));
            continue;
        };
        matched.insert(child_entity);
        walk(world, child_entity, *child, &path, tree, nodes);
    }
    for child in children.into_iter().filter(|child| !matched.contains(child)) {
        if let Some(transform) = world.get::<Transform>(child) && *transform != Transform::IDENTITY {
            found.push(format!("child Transform {}", debug(transform)));
        }
        found.extend(describe(world, child));
    }
    found.sort();
    found.dedup_by(|later, earlier| later == earlier && later.starts_with("Navigation"));
    nodes.insert(path, found);
}

fn scene_nodes(world: &mut World, scene_root: Entity) -> BTreeMap<String, Vec<String>> {
    let tree = gltf_tree(BSN_SCENE);
    let mut nodes = BTreeMap::new();
    let world = &*world;
    let children: Vec<Entity> = world.get::<Children>(scene_root).map_or(Vec::new(), |children| children.iter().collect());
    for root in &tree.roots {
        let entity = children.iter().copied().find(|child| world.get::<Name>(*child).is_some_and(|name| name.as_str() == tree.names[*root])).unwrap_or_else(|| panic!("no root node named {}", tree.names[*root]));
        walk(world, entity, *root, "", &tree, &mut nodes);
    }
    return nodes;
}

fn anchors(world: &mut World) -> BTreeMap<String, Vec<String>> {
    let mut found = BTreeMap::new();
    let mut entities = world.query::<(Entity, &Name)>();
    for (entity, name) in entities.iter(world) {
        if name.as_str().ends_with(" anchor") {
            let mut description = describe(world, entity);
            description.push(format!("Transform {}", debug(world.get::<Transform>(entity).expect("anchors have a transform"))));
            found.insert(name.as_str().to_string(), description);
        }
    }
    return found;
}

fn named(world: &mut World, target: &str) -> Entity {
    let mut entities = world.query::<(Entity, &Name)>();
    return entities.iter(world).find(|(_, name)| name.as_str() == target).map(|(entity, _)| entity).unwrap_or_else(|| panic!("no entity named {target}"));
}

fn glb_scene_root(world: &mut World) -> Entity {
    let mut roots = world.query_filtered::<(Entity, &Children), (With<WorldAssetRoot>, Without<ChildOf>)>();
    let (_, children) = roots.iter(world).next().expect("the GLB scene is spawned");
    return children.iter().next().expect("the GLB scene has a root");
}

#[test]
fn bsn_scene_matches_the_glb_scene_with_the_importer() {
    let mut glb = glb_app();
    let mut bsn = bsn_app(true);
    let glb_root = glb_scene_root(glb.world_mut());
    let bsn_root = named(bsn.world_mut(), ROOT);
    let expected = scene_nodes(glb.world_mut(), glb_root);
    let actual = scene_nodes(bsn.world_mut(), bsn_root);
    assert_eq!(actual.keys().collect::<Vec<_>>(), expected.keys().collect::<Vec<_>>());
    let differences: Vec<String> = expected.iter().filter(|(path, components)| &actual[*path] != *components).map(|(path, components)| format!("{path}\n  BSN: {:?}\n  GLB: {components:?}", actual[path])).collect();
    assert!(differences.is_empty(), "{}", differences.join("\n"));
    assert_eq!(anchors(bsn.world_mut()), anchors(glb.world_mut()));
    assert_eq!(debug(bsn.world().resource::<GlobalAmbientLight>()), debug(glb.world().resource::<GlobalAmbientLight>()));
}

#[test]
fn bsn_scene_shares_prefabs() {
    let source = include_str!("bsn/sample_scene.rs");
    assert!(source.contains("pub fn setup() -> impl Scene"));
    assert_eq!(source.matches("@object_windmill()").count(), 2);
    assert!(source.contains("pub fn object_windmill() -> impl Scene"));
}

#[test]
fn bsn_scene_simulates() {
    let mut app = bsn_app(false);
    let ball = named(app.world_mut(), "bouncy_ball");
    let bullet = named(app.world_mut(), "bullet");
    let start = (app.world().get::<Transform>(ball).unwrap().translation, app.world().get::<Transform>(bullet).unwrap().translation);
    for _ in 0..30 {
        app.update();
    }
    let ball_now = app.world().get::<Transform>(ball).unwrap().translation;
    let bullet_now = app.world().get::<Transform>(bullet).unwrap().translation;
    assert!(ball_now.y < start.0.y - 0.1, "the ball fell from {} to {}", start.0, ball_now);
    assert!(bullet_now.x > start.1.x + 1.0, "the bullet flew from {} to {}", start.1, bullet_now);
    let mut joints = app.world_mut().query_filtered::<&Name, Or<(With<FixedJoint>, With<RevoluteJoint>, With<PrismaticJoint>, With<SphericalJoint>)>>();
    let mut names: Vec<String> = joints.iter(app.world()).map(|name| name.as_str().to_string()).collect();
    names.sort();
    assert_eq!(names, ["barrel_lid joint", "chain_middle joint", "chain_top joint", "door_hinge joint", "drawer joint"]);
}

#[test]
fn static_bsn_scene_loads_without_the_gltf_node_tree() {
    let mut app = static_app();
    let handle = app.world().resource::<AssetServer>().load::<Gltf>(STATIC_SCENE);
    for _ in 0..1000 {
        if app.world().resource::<AssetServer>().is_loaded(&handle) {
            break;
        }
        app.update();
        thread::sleep(Duration::from_millis(10));
    }
    let gltf = app.world().resource::<Assets<Gltf>>().get(&handle).expect("the GLB is loaded");
    assert_eq!((gltf.nodes.len(), gltf.scenes.len()), (1, 1));
    let rocks = named(app.world_mut(), "rocks");
    assert_eq!(app.world().get::<Children>(rocks).map_or(0, |children| children.len()), STATIC_ROCKS);
    assert_eq!(cull_mode(&mut app, "statue"), Some(Face::Back));
    assert_eq!(cull_mode(&mut app, "statue_mirrored"), Some(Face::Front));
}
