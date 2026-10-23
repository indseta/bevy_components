use avian3d::prelude::*;
use bevy::{asset::LoadState, camera::primitives::Aabb, camera_controller::free_camera::{FreeCamera, FreeCameraPlugin, FreeCameraState}, gltf::Gltf, prelude::*};
use bevy_components_importer::{BlenderBevyComponentsPlugin, BlenderSceneReady, blender_view};
use std::{env, path::{Path, PathBuf}, process};

const HELP: &str = "WASD to fly, Q and E to go down and up, Shift to go faster\nHold the right mouse button or press M to look around\nP pauses physics, F1 hides or shows colliders and joints";

#[derive(Resource)]
struct ViewedScene {
    path: String,
    gltf: Handle<Gltf>,
    spawned: bool,
    framed: bool,
}

#[derive(Resource)]
struct FrameScene(Entity);

#[derive(Component)]
struct ViewerCamera;

fn main() {
    let Some(argument) = env::args().nth(1) else {
        eprintln!("Usage: cargo run --example viewer -- <scene.glb>");
        process::exit(2);
    };
    let Ok(file) = Path::new(&argument).canonicalize() else {
        eprintln!("No scene file at {argument}");
        process::exit(2);
    };
    let root = asset_root(&file);
    let path = file.strip_prefix(&root).unwrap_or(&file).to_string_lossy().replace('\\', "/");
    let mut app = App::new();
    app.add_plugins(DefaultPlugins.set(AssetPlugin { file_path: root.to_string_lossy().to_string(), watch_for_changes_override: Some(true), ..default() }).set(WindowPlugin { primary_window: Some(Window { title: format!("Bevy Components viewer: {path}"), ..default() }), ..default() }));
    app.add_plugins((PhysicsPlugins::default(), PhysicsDebugPlugin, FreeCameraPlugin, BlenderBevyComponentsPlugin));
    app.insert_resource(ViewedScene { path, gltf: Handle::default(), spawned: false, framed: blender_view().is_some() });
    app.add_systems(Startup, setup);
    app.add_systems(Update, (spawn_scene, frame_scene, toggle_physics));
    app.add_observer(scene_ready);
    app.run();
}

fn asset_root(file: &Path) -> PathBuf {
    let folders: Vec<&Path> = file.ancestors().skip(1).filter(|folder| folder.file_name().is_some_and(|name| name.eq_ignore_ascii_case("assets"))).collect();
    let root = folders.iter().find(|folder| folder.parent().is_some_and(|parent| parent.join("Cargo.toml").is_file())).or(folders.first());
    return root.map_or_else(|| file.parent().unwrap_or(Path::new(".")).to_path_buf(), |folder| folder.to_path_buf());
}

fn setup(mut commands: Commands, asset_server: Res<AssetServer>, mut viewed: ResMut<ViewedScene>) {
    viewed.gltf = asset_server.load(viewed.path.clone());
    let start = blender_view().unwrap_or_else(|| Transform::from_xyz(8.0, 6.0, 8.0).looking_at(Vec3::ZERO, Vec3::Y));
    commands.spawn((Name::new("Viewer Camera"), ViewerCamera, Camera3d::default(), FreeCamera::default(), start));
    commands.spawn((Text::new(HELP), TextFont { font_size: FontSize::Px(14.0), ..default() }, Node { position_type: PositionType::Absolute, left: px(12), bottom: px(12), ..default() }));
}

fn spawn_scene(mut commands: Commands, mut viewed: ResMut<ViewedScene>, gltfs: Res<Assets<Gltf>>, asset_server: Res<AssetServer>, mut exit: MessageWriter<AppExit>) {
    if viewed.spawned {
        return;
    }
    if let LoadState::Failed(error) = asset_server.load_state(&viewed.gltf) {
        error!("Could not load {}: {}", viewed.path, error);
        exit.write(AppExit::error());
        viewed.spawned = true;
        return;
    }
    let Some(gltf) = gltfs.get(&viewed.gltf) else { return; };
    let Some(scene) = gltf.default_scene.clone().or_else(|| gltf.scenes.first().cloned()) else {
        error!("{} has no scene", viewed.path);
        exit.write(AppExit::error());
        viewed.spawned = true;
        return;
    };
    commands.spawn((Name::new(viewed.path.clone()), WorldAssetRoot(scene)));
    viewed.spawned = true;
}

fn scene_ready(ready: On<BlenderSceneReady>, mut commands: Commands, mut viewed: ResMut<ViewedScene>, mut cameras: Query<&mut Camera, Without<ViewerCamera>>, lights: Query<(), Or<(With<PointLight>, With<SpotLight>, With<DirectionalLight>, With<RectLight>)>>) {
    for mut camera in &mut cameras {
        camera.is_active = false;
    }
    if lights.is_empty() {
        commands.spawn((Name::new("Viewer Light"), DirectionalLight { shadow_maps_enabled: true, ..default() }, Transform::from_xyz(4.0, 10.0, 6.0).looking_at(Vec3::ZERO, Vec3::Y)));
    }
    if !viewed.framed {
        viewed.framed = true;
        commands.insert_resource(FrameScene(ready.entity));
    }
}

fn frame_scene(mut commands: Commands, frame: Option<Res<FrameScene>>, children: Query<&Children>, bounds: Query<(&GlobalTransform, &Aabb)>, scene_cameras: Query<&GlobalTransform, (With<Camera3d>, Without<ViewerCamera>)>, viewer: Single<(&mut Transform, &mut FreeCameraState), With<ViewerCamera>>) {
    let Some(frame) = frame else { return; };
    commands.remove_resource::<FrameScene>();
    let descendants: Vec<Entity> = children.iter_descendants(frame.0).collect();
    if let Some(camera) = descendants.iter().find_map(|entity| scene_cameras.get(*entity).ok()) {
        place(viewer, camera.compute_transform());
        return;
    }
    let corners: Vec<(Vec3, Vec3)> = descendants.iter().filter_map(|entity| bounds.get(*entity).ok()).map(|(transform, aabb)| {
        let center = transform.transform_point(Vec3::from(aabb.center));
        let extent = transform.affine().matrix3.abs() * Vec3A::from(aabb.half_extents);
        return (center - Vec3::from(extent), center + Vec3::from(extent));
    }).collect();
    let Some(minimum) = corners.iter().map(|corner| corner.0).reduce(Vec3::min) else { return; };
    let maximum = corners.iter().map(|corner| corner.1).fold(minimum, Vec3::max);
    let center = (minimum + maximum) / 2.0;
    let radius = ((maximum - minimum).length() / 2.0).max(1.0);
    place(viewer, Transform::from_translation(center + Vec3::new(1.0, 0.7, 1.0).normalize() * radius * 1.6).looking_at(center, Vec3::Y));
}

fn place(viewer: Single<(&mut Transform, &mut FreeCameraState), With<ViewerCamera>>, target: Transform) {
    let (mut transform, mut state) = viewer.into_inner();
    let (yaw, pitch, _roll) = target.rotation.to_euler(EulerRot::YXZ);
    *transform = target;
    state.yaw = yaw;
    state.pitch = pitch;
}

fn toggle_physics(keys: Res<ButtonInput<KeyCode>>, mut time: ResMut<Time<Physics>>, mut gizmos: ResMut<GizmoConfigStore>) {
    if keys.just_pressed(KeyCode::KeyP) {
        if time.is_paused() {
            time.unpause();
        } else {
            time.pause();
        }
    }
    if keys.just_pressed(KeyCode::F1) {
        let (config, _) = gizmos.config_mut::<PhysicsGizmos>();
        config.enabled = !config.enabled;
    }
}
