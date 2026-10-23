mod common;

use avian3d::prelude::*;
use bevy::{asset::RenderAssetUsages, camera::{RenderTarget, visibility::VisibilityRange}, image::CompressedImageFormats, light::{FogVolume, LightProbe, VolumetricFog, VolumetricLight}, prelude::*, render::{render_resource::{PollType, TextureFormat}, renderer::{RenderAdapterInfo, RenderDevice}, view::screenshot::{Screenshot, ScreenshotCaptured}}};
use common::*;
use std::sync::{Arc, Mutex};

const WIDTH: u32 = 384;
const HEIGHT: u32 = 256;

struct Render {
    pixels: Vec<u8>,
    device: CompressedImageFormats,
    adapter: String,
    formats: Vec<TextureFormat>,
}

fn render(file: &str, formats: Option<CompressedImageFormats>) -> Render {
    return render_with(file, formats, "", |_world, _camera| {});
}

fn render_with(file: &str, formats: Option<CompressedImageFormats>, variant: &str, change: impl FnOnce(&mut World, Entity)) -> Render {
    let mut app = LevelApp { gpu: true, formats, ..default() }.build();
    app.world_mut().resource_mut::<Time<Physics>>().pause();
    app.world_mut().resource_mut::<Time<Virtual>>().pause();
    if let Err(error) = spawn_level(&mut app, file) {
        panic!("{file} did not load: {error}");
    }
    let world = app.world_mut();
    let mut ranges = world.query_filtered::<Entity, With<VisibilityRange>>();
    for entity in ranges.iter(world).collect::<Vec<_>>() {
        world.entity_mut(entity).remove::<VisibilityRange>();
    }
    let mut target = Image::new_target_texture(WIDTH, HEIGHT, TextureFormat::Rgba8UnormSrgb, None);
    target.asset_usage = RenderAssetUsages::RENDER_WORLD;
    let target = world.resource_mut::<Assets<Image>>().add(target);
    let camera = world.spawn((Camera3d::default(), RenderTarget::Image(target.clone().into()), Transform::from_xyz(1.0, 7.0, 11.0).looking_at(Vec3::new(1.0, 0.5, -1.0), Vec3::Y))).id();
    change(world, camera);
    for _ in 0..10 {
        update(&mut app);
    }
    let captured = Arc::new(Mutex::new(None));
    let sink = captured.clone();
    app.world_mut().spawn(Screenshot::image(target)).observe(move |event: On<ScreenshotCaptured>| {
        *sink.lock().expect("screenshot lock") = Some(event.image.clone());
    });
    for _ in 0..20 {
        update(&mut app);
        if captured.lock().expect("screenshot lock").is_some() {
            break;
        }
    }
    let image = captured.lock().expect("screenshot lock").take().unwrap_or_else(|| panic!("{file} was not captured"));
    let image = image.convert(TextureFormat::Rgba8UnormSrgb).expect("screenshot converts to RGBA");
    if let Ok(directory) = std::env::var("BEVY_COMPONENTS_RENDER_OUTPUT") {
        let name = format!("{}_{}{variant}.png", file.trim_end_matches(".glb"), formats.map_or("default".to_string(), |formats| format!("{:?}", formats.iter_names().map(|(name, _)| name.to_lowercase()).collect::<Vec<_>>().join("_"))).replace('"', ""));
        std::fs::create_dir_all(&directory).expect("render output directory");
        image.clone().try_into_dynamic().expect("screenshot image").save(std::path::Path::new(&directory).join(name)).expect("saved render");
    }
    let world = app.world_mut();
    let mut materials = world.query::<&MeshMaterial3d<StandardMaterial>>();
    let handles: Vec<Handle<StandardMaterial>> = materials.iter(world).map(|material| material.0.clone()).collect();
    let mut formats = Vec::new();
    for handle in handles {
        let material = world.resource::<Assets<StandardMaterial>>().get(&handle).expect("material").clone();
        if let Some(texture) = material.base_color_texture.as_ref().and_then(|texture| world.resource::<Assets<Image>>().get(texture)) && !formats.contains(&texture.texture_descriptor.format) {
            formats.push(texture.texture_descriptor.format);
        }
    }
    return Render {
        pixels: image.data.expect("screenshot pixels"),
        device: world.resource::<DeviceFormats>().0,
        adapter: format!("{} ({:?})", world.resource::<RenderAdapterInfo>().name, world.resource::<RenderAdapterInfo>().backend),
        formats,
    };
}

fn despawn<T: Component>(world: &mut World) {
    let mut entities = world.query_filtered::<Entity, With<T>>();
    for entity in entities.iter(world).collect::<Vec<_>>() {
        world.despawn(entity);
    }
}

fn volumetric(world: &mut World, camera: Entity) {
    world.entity_mut(camera).insert(VolumetricFog::default());
    let mut lights = world.query_filtered::<Entity, With<DirectionalLight>>();
    for light in lights.iter(world).collect::<Vec<_>>() {
        world.entity_mut(light).insert(VolumetricLight);
    }
}

fn update(app: &mut App) {
    app.update();
    app.world().resource::<RenderDevice>().wgpu_device().poll(PollType::Wait { submission_index: None, timeout: None }).expect("device poll");
}

fn difference(expected: &[u8], found: &[u8]) -> (f64, f64) {
    let mut differences: Vec<u8> = expected.chunks(4).zip(found.chunks(4)).map(|(a, b)| (0..3).map(|channel| a[channel].abs_diff(b[channel])).max().unwrap_or(0)).collect();
    let mean = differences.iter().map(|value| *value as f64).sum::<f64>() / differences.len() as f64;
    differences.sort_unstable();
    return (mean, differences[differences.len() * 99 / 100] as f64);
}

fn colors(pixels: &[u8]) -> usize {
    let mut colors: Vec<&[u8]> = pixels.chunks(4).collect();
    colors.sort_unstable();
    colors.dedup();
    return colors.len();
}

#[test]
#[ignore = "needs a GPU, run with cargo test -- --ignored"]
fn compressed_levels_render_like_the_uncompressed_level() {
    let reference = render(LEVEL, None);
    println!("Adapter {} supports {:?}", reference.adapter, reference.device);
    assert!(colors(&reference.pixels) > 500, "the reference render shows no textures");
    let candidates = [CompressedImageFormats::NONE, CompressedImageFormats::BC, CompressedImageFormats::ETC2, CompressedImageFormats::ASTC_LDR];
    let mut rendered = 0;
    for formats in candidates.into_iter().filter(|formats| reference.device.contains(*formats)) {
        for file in COMPRESSED_LEVELS {
            let found = render(file, Some(formats));
            let (mean, percentile) = difference(&reference.pixels, &found.pixels);
            println!("{file} with {formats:?} as {:?}: mean difference {mean:.2}, 99th percentile {percentile}", found.formats);
            assert!(found.formats.iter().all(|format| formats.supports(*format) && format.is_compressed() != formats.is_empty()), "{file} with {formats:?} used {:?}", found.formats);
            assert!(mean < 3.0 && percentile < 48.0, "{file} with {formats:?} differs from the uncompressed level: mean {mean:.2}, 99th percentile {percentile}");
            rendered += 1;
        }
    }
    assert!(rendered >= 6, "the GPU supports no compressed texture formats: {:?}", reference.device);
}

#[test]
#[ignore = "needs a GPU, run with cargo test -- --ignored"]
fn light_probes_and_fog_volumes_change_the_render() {
    let reference = render(LEVEL, None);
    let without_probes = render_with(LEVEL, None, "_without_probes", |world, _camera| despawn::<LightProbe>(world));
    let without_fog = render_with(LEVEL, None, "_without_fog", |world, camera| {
        volumetric(world, camera);
        despawn::<FogVolume>(world);
    });
    let foggy = render_with(LEVEL, None, "_foggy", volumetric);
    let (probes, _) = difference(&reference.pixels, &without_probes.pixels);
    let (fog, _) = difference(&without_fog.pixels, &foggy.pixels);
    println!("Light probes change the render by {probes:.2} on average, the fog volume by {fog:.2}");
    assert!(probes > 5.0, "the light probes barely light the level: {probes:.2}");
    assert!(fog > 1.0, "the fog volume is not visible: {fog:.2}");
}
