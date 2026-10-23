#![allow(dead_code)]

use avian3d::prelude::*;
use bevy::{app::PluginsState, asset::{AssetPlugin, LoadState, UntypedAssetId}, audio::{AudioPlugin, Volume}, gilrs::GilrsPlugin, gltf::{Gltf, GltfExtras}, image::{CompressedImageFormatSupport, CompressedImageFormats}, log::LogPlugin, prelude::*, render::{RenderPlugin, pipelined_rendering::PipelinedRenderingPlugin, settings::WgpuSettings}, time::TimeUpdateStrategy, window::ExitCondition, winit::WinitPlugin, world_serialization::WorldInstanceReady};
use bevy_components_importer::BlenderBevyComponentsPlugin;
use std::{thread, time::Duration};

pub const ASSETS: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/assets");
pub const LEVEL: &str = "sample_level.glb";
pub const COMPRESSED_LEVELS: [&str; 3] = ["sample_level_etc1s.glb", "sample_level_uastc.glb", "sample_level_automatic.glb"];

#[derive(Resource, Clone, Copy)]
pub struct DeviceFormats(pub CompressedImageFormats);

#[derive(Resource, Default)]
pub struct ReadyInstances(pub usize);

pub struct LevelApp {
    pub assets: String,
    pub gpu: bool,
    pub plugin: bool,
    pub audio: bool,
    pub formats: Option<CompressedImageFormats>,
}

impl Default for LevelApp {
    fn default() -> Self {
        return LevelApp {
            assets: ASSETS.to_string(),
            gpu: false,
            plugin: true,
            audio: false,
            formats: None,
        };
    }
}

impl LevelApp {
    pub fn build(&self) -> App {
        let mut app = App::new();
        let render = if self.gpu { RenderPlugin { synchronous_pipeline_compilation: true, ..default() } } else { RenderPlugin { render_creation: WgpuSettings { backends: None, ..default() }.into(), ..default() } };
        let plugins = DefaultPlugins.set(AssetPlugin { file_path: self.assets.clone(), ..default() }).set(render).set(WindowPlugin { primary_window: None, exit_condition: ExitCondition::DontExit, close_when_requested: false, ..default() }).disable::<WinitPlugin>().disable::<GilrsPlugin>().disable::<LogPlugin>().disable::<PipelinedRenderingPlugin>();
        app.add_plugins(if self.audio { plugins.set(AudioPlugin { global_volume: GlobalVolume::new(Volume::SILENT), ..default() }) } else { plugins.disable::<AudioPlugin>() });
        app.add_plugins(PhysicsPlugins::default());
        if self.plugin {
            app.add_plugins(BlenderBevyComponentsPlugin);
        }
        app.insert_resource(TimeUpdateStrategy::ManualDuration(Duration::from_secs_f64(1.0 / 60.0)));
        app.init_resource::<ReadyInstances>();
        app.add_observer(|_ready: On<WorldInstanceReady>, mut instances: ResMut<ReadyInstances>| instances.0 += 1);
        while app.plugins_state() == PluginsState::Adding {
            thread::sleep(Duration::from_millis(1));
        }
        app.finish();
        let device = app.world().get_resource::<CompressedImageFormatSupport>().map_or(CompressedImageFormats::NONE, |support| support.0);
        app.insert_resource(DeviceFormats(device));
        if let Some(formats) = self.formats {
            app.insert_resource(CompressedImageFormatSupport(formats));
        }
        app.cleanup();
        return app;
    }
}

pub fn spawn_level(app: &mut App, file: &str) -> Result<(), String> {
    let scene: Handle<WorldAsset> = app.world().resource::<AssetServer>().load(format!("{file}#Scene0"));
    app.world_mut().spawn(WorldAssetRoot(scene.clone()));
    return wait_for(app, scene.id().untyped(), file, true);
}

pub fn load_gltf(app: &mut App, file: &str) -> Result<Handle<Gltf>, String> {
    let gltf: Handle<Gltf> = app.world().resource::<AssetServer>().load(file.to_string());
    wait_for(app, gltf.id().untyped(), file, false)?;
    return Ok(gltf);
}

fn wait_for(app: &mut App, id: UntypedAssetId, file: &str, spawned: bool) -> Result<(), String> {
    let asset_server = app.world().resource::<AssetServer>().clone();
    for _ in 0..1000 {
        app.update();
        if let LoadState::Failed(error) = asset_server.load_state(id) {
            return Err(error.to_string());
        }
        let mut extras = app.world_mut().query::<&GltfExtras>();
        if asset_server.is_loaded_with_dependencies(id) && (!spawned || extras.iter(app.world()).count() > 0) {
            wait_for_references(app)?;
            for _ in 0..10 {
                app.update();
            }
            return Ok(());
        }
        thread::sleep(Duration::from_millis(10));
    }
    return Err(format!("{file} did not load"));
}

fn wait_for_references(app: &mut App) -> Result<(), String> {
    let mut settled = 0;
    for _ in 0..1000 {
        app.update();
        let mut roots = app.world_mut().query::<&WorldAssetRoot>();
        let pending = roots.iter(app.world()).count();
        settled = if app.world().resource::<ReadyInstances>().0 >= pending { settled + 1 } else { 0 };
        if settled == 2 {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(10));
    }
    return Err("Scene references did not load".to_string());
}

pub fn load_level(file: &str) -> App {
    let mut app = LevelApp::default().build();
    if let Err(error) = spawn_level(&mut app, file) {
        panic!("{file} did not load: {error}");
    }
    return app;
}
