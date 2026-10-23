mod common;

use avian3d::prelude::*;
use bevy::{camera::visibility::VisibilityRange, gltf::{Gltf, GltfExtras}, image::CompressedImageFormats, prelude::*, render::render_resource::{AstcBlock, AstcChannel, TextureFormat}};
use bevy_components_importer::BlenderCustomComponents;
use common::*;
use std::{collections::BTreeMap, fs};

const ALPHA_TEXTURES: [&str; 1] = ["crate.crate_metal base_color"];
const NEAREST_TEXTURES: [&str; 1] = ["ball.ball_pixels base_color"];

fn slots(material: &StandardMaterial) -> [(&'static str, Option<Handle<Image>>); 5] {
    return [("base_color", material.base_color_texture.clone()), ("normal", material.normal_map_texture.clone()), ("metallic_roughness", material.metallic_roughness_texture.clone()), ("occlusion", material.occlusion_texture.clone()), ("emissive", material.emissive_texture.clone())];
}

fn materials(world: &mut World) -> BTreeMap<String, Handle<StandardMaterial>> {
    let mut meshes = world.query::<(&Name, &MeshMaterial3d<StandardMaterial>)>();
    return meshes.iter(world).map(|(name, material)| (name.to_string(), material.0.clone())).collect();
}

fn textures(world: &mut World) -> BTreeMap<String, Handle<Image>> {
    let materials = materials(world);
    let assets = world.resource::<Assets<StandardMaterial>>();
    let mut textures = BTreeMap::new();
    for (name, handle) in materials {
        let material = assets.get(&handle).unwrap_or_else(|| panic!("{name} has no material"));
        for (slot, texture) in slots(material) {
            if let Some(texture) = texture {
                textures.insert(format!("{name} {slot}"), texture);
            }
        }
    }
    return textures;
}

fn images(world: &mut World) -> BTreeMap<String, Image> {
    let textures = textures(world);
    let images = world.resource::<Assets<Image>>();
    return textures.into_iter().map(|(key, handle)| {
        let image = images.get(&handle).unwrap_or_else(|| panic!("{key} has no image")).clone();
        return (key, image);
    }).collect();
}

fn load(file: &str, formats: Option<CompressedImageFormats>) -> App {
    let mut app = SceneApp { formats, ..default() }.build();
    app.world_mut().resource_mut::<Time<Physics>>().pause();
    app.world_mut().resource_mut::<Time<Virtual>>().pause();
    if let Err(error) = spawn_scene(&mut app, file) {
        panic!("{file} did not load: {error}");
    }
    return app;
}

fn codec(file: &str, key: &str) -> &'static str {
    if file.contains("etc1s") || (file.contains("automatic") && srgb(key) && !NEAREST_TEXTURES.contains(&key)) {
        return "etc1s";
    }
    return "uastc";
}

fn srgb(key: &str) -> bool {
    return key.ends_with("base_color") || key.ends_with("emissive");
}

fn expected_format(file: &str, key: &str, formats: CompressedImageFormats) -> TextureFormat {
    let srgb = srgb(key);
    let alpha = ALPHA_TEXTURES.contains(&key);
    let etc2 = match (alpha, srgb) {
        (true, true) => TextureFormat::Etc2Rgba8UnormSrgb,
        (true, false) => TextureFormat::Etc2Rgba8Unorm,
        (false, true) => TextureFormat::Etc2Rgb8UnormSrgb,
        (false, false) => TextureFormat::Etc2Rgb8Unorm,
    };
    let astc = TextureFormat::Astc { block: AstcBlock::B4x4, channel: if srgb { AstcChannel::UnormSrgb } else { AstcChannel::Unorm } };
    let bc7 = if srgb { TextureFormat::Bc7RgbaUnormSrgb } else { TextureFormat::Bc7RgbaUnorm };
    let order = if codec(file, key) == "etc1s" { [(CompressedImageFormats::ETC2, etc2), (CompressedImageFormats::BC, bc7), (CompressedImageFormats::ASTC_LDR, astc)] } else { [(CompressedImageFormats::ASTC_LDR, astc), (CompressedImageFormats::BC, bc7), (CompressedImageFormats::ETC2, etc2)] };
    let rgba = if srgb { TextureFormat::Rgba8UnormSrgb } else { TextureFormat::Rgba8Unorm };
    return order.into_iter().find(|(required, _)| formats.contains(*required)).map_or(rgba, |(_, format)| format);
}

fn psnr(expected: &[u8], found: &[u8]) -> f64 {
    let error: f64 = expected.iter().zip(found).map(|(a, b)| (*a as f64 - *b as f64).powi(2)).sum::<f64>() / expected.len() as f64;
    return 10.0 * (255.0 * 255.0 / error.max(1e-9)).log10();
}

fn name_path(world: &World, entity: Entity) -> String {
    let mut names = Vec::new();
    let mut cursor = Some(entity);
    while let Some(current) = cursor {
        if let Some(name) = world.get::<Name>(current) {
            names.push(name.to_string());
        }
        cursor = world.get::<ChildOf>(current).map(ChildOf::parent);
    }
    names.reverse();
    return names.join("/");
}

fn component_snapshot(world: &mut World) -> BTreeMap<String, String> {
    let mut named = world.query_filtered::<Entity, With<Name>>();
    let named: Vec<Entity> = named.iter(world).collect();
    let entities: Vec<(Entity, String)> = named.into_iter().map(|entity| (entity, name_path(world, entity))).collect();
    let mut snapshot = BTreeMap::new();
    for (entity, name) in entities {
        let parent = world.get::<ChildOf>(entity).and_then(|child_of| world.get::<Name>(child_of.parent())).map(|name| name.to_string());
        let transform = world.get::<Transform>(entity).copied();
        let range = world.get::<VisibilityRange>(entity).map(|range| (range.start_margin.clone(), range.end_margin.clone(), range.use_aabb));
        let collider = world.get::<Collider>(entity).map(|collider| format!("{:?} {:?} {:?}", collider.shape().shape_type(), collider.shape().compute_local_aabb(), collider.scale()));
        let body = world.get::<RigidBody>(entity).copied();
        let sensor = world.get::<Sensor>(entity).is_some();
        let custom = world.get::<BlenderCustomComponents>(entity).map(|custom| custom.0.iter().map(|component| format!("{} {}", component.type_path, component.data)).collect::<Vec<_>>());
        let extras = world.get::<GltfExtras>(entity).map(|extras| extras.value.clone());
        let mesh = world.get::<Mesh3d>(entity).is_some();
        snapshot.insert(name, format!("{parent:?} {transform:?} {range:?} {collider:?} {body:?} {sensor} {custom:?} {extras:?} {mesh}"));
    }
    return snapshot;
}

fn material_snapshot(world: &mut World) -> BTreeMap<String, String> {
    let materials = materials(world);
    let assets = world.resource::<Assets<StandardMaterial>>();
    let mut snapshot = BTreeMap::new();
    for (name, handle) in materials {
        let mut material = assets.get(&handle).unwrap_or_else(|| panic!("{name} has no material")).clone();
        let used: Vec<&str> = slots(&material).into_iter().filter(|(_, texture)| texture.is_some()).map(|(slot, _)| slot).collect();
        if used.is_empty() {
            continue;
        }
        material.base_color_texture = None;
        material.normal_map_texture = None;
        material.metallic_roughness_texture = None;
        material.occlusion_texture = None;
        material.emissive_texture = None;
        snapshot.insert(name, format!("{used:?} {material:?}"));
    }
    return snapshot;
}

#[test]
fn compressed_scenes_load_from_the_ordinary_scene_path() {
    for file in COMPRESSED_SCENES {
        let mut app = load(file, None);
        let images = images(app.world_mut());
        assert_eq!(images.len(), 14, "{file}");
        for (key, image) in &images {
            assert!(image.texture_descriptor.mip_level_count > 1, "{file} {key} has no mipmaps");
            assert_eq!(image.texture_descriptor.format, expected_format(file, key, CompressedImageFormats::NONE), "{file} {key}");
        }
        assert_eq!(images["pillar.pillar_gradient base_color"].size(), UVec2::new(32, 20));
    }
}

#[test]
fn typed_gltf_handles_load_compressed_scenes() {
    for file in COMPRESSED_SCENES {
        let mut app = SceneApp::default().build();
        let handle = load_gltf(&mut app, file).unwrap_or_else(|error| panic!("{file} did not load: {error}"));
        let gltf = app.world().resource::<Assets<Gltf>>().get(&handle).unwrap_or_else(|| panic!("{file} has no Gltf asset"));
        assert_eq!(gltf.materials.len(), 7, "{file}");
        assert_eq!(gltf.named_materials.len(), 7, "{file}");
    }
}

#[test]
fn components_match_the_uncompressed_scene() {
    let expected = component_snapshot(load(SCENE, None).world_mut());
    assert!(expected.len() > 20);
    for file in COMPRESSED_SCENES {
        let found = component_snapshot(load(file, None).world_mut());
        assert_eq!(found, expected, "{file}");
    }
}

#[test]
fn materials_match_the_uncompressed_scene() {
    let expected = material_snapshot(load(SCENE, None).world_mut());
    assert_eq!(expected.len(), 8);
    assert!(expected["crate.crate_metal"].contains("Blend"));
    assert!(expected["ground.ground_wood"].contains("uv_transform"));
    for file in COMPRESSED_SCENES {
        let found = material_snapshot(load(file, None).world_mut());
        assert_eq!(found, expected, "{file}");
    }
}

#[test]
fn textures_transcode_to_supported_gpu_formats() {
    let format_sets = [CompressedImageFormats::BC, CompressedImageFormats::ETC2, CompressedImageFormats::ASTC_LDR, CompressedImageFormats::ETC2 | CompressedImageFormats::ASTC_LDR, CompressedImageFormats::BC | CompressedImageFormats::ETC2 | CompressedImageFormats::ASTC_LDR];
    for file in COMPRESSED_SCENES {
        for formats in format_sets {
            let mut app = load(file, Some(formats));
            let images = images(app.world_mut());
            assert_eq!(images.len(), 14, "{file}");
            for (key, image) in &images {
                assert_eq!(image.texture_descriptor.format, expected_format(file, key, formats), "{file} {key} with {formats:?}");
                assert!(image.texture_descriptor.mip_level_count > 1, "{file} {key} has no mipmaps");
                assert_eq!(image.data.as_ref().map(Vec::len), Some(expected_size(image)), "{file} {key} with {formats:?}");
            }
        }
    }
}

fn expected_size(image: &Image) -> usize {
    let (block, bytes) = match image.texture_descriptor.format {
        TextureFormat::Rgba8Unorm | TextureFormat::Rgba8UnormSrgb => (1, 4),
        TextureFormat::Etc2Rgb8Unorm | TextureFormat::Etc2Rgb8UnormSrgb => (4, 8),
        _ => (4, 16),
    };
    let size = image.size();
    return (0..image.texture_descriptor.mip_level_count).map(|level| {
        let width = (size.x >> level).max(1).div_ceil(block) as usize;
        let height = (size.y >> level).max(1).div_ceil(block) as usize;
        return width * height * bytes;
    }).sum();
}

#[test]
fn decoded_textures_match_the_source_images() {
    let expected = images(load(SCENE, None).world_mut());
    for file in COMPRESSED_SCENES {
        let found = images(load(file, None).world_mut());
        for (key, image) in &found {
            let source = &expected[key];
            if source.size() != image.size() {
                continue;
            }
            let length = source.data.as_ref().map_or(0, Vec::len);
            let decoded = &image.data.as_ref().expect("decoded texture data")[..length];
            let quality = psnr(source.data.as_ref().expect("source texture data"), decoded);
            let minimum = if codec(file, key) == "uastc" { 40.0 } else if NEAREST_TEXTURES.contains(&key.as_str()) { 10.0 } else { 22.0 };
            assert!(quality > minimum, "{file} {key} decoded at {quality:.1} dB");
        }
    }
}

#[test]
fn shared_textures_and_materials_keep_shared_handles() {
    for file in std::iter::once(SCENE).chain(COMPRESSED_SCENES) {
        let mut app = load(file, None);
        let materials = materials(app.world_mut());
        assert_eq!(materials["crate.crate_wood"], materials["crate_copy.crate_wood"], "{file}");
        let textures = textures(app.world_mut());
        assert_eq!(textures["crate.crate_wood metallic_roughness"], textures["crate.crate_wood occlusion"], "{file}");
        assert_eq!(textures["crate.crate_wood base_color"], textures["crate_copy.crate_wood base_color"], "{file}");
        assert_ne!(textures["crate.crate_wood metallic_roughness"], textures["rock.rock_orm base_color"], "{file}");
    }
}

#[test]
fn compressed_scenes_need_the_plugin() {
    for file in COMPRESSED_SCENES {
        let mut app = SceneApp { plugin: false, ..default() }.build();
        let error = spawn_scene(&mut app, file).expect_err("compressed scenes fail without the plugin");
        assert!(error.contains("KHR_texture_basisu"), "{file}: {error}");
    }
    let mut app = SceneApp { plugin: false, ..default() }.build();
    assert!(spawn_scene(&mut app, SCENE).is_ok());
}

#[test]
fn broken_textures_report_an_error() {
    let directory = std::env::temp_dir().join(format!("bevy_components_broken_{}", std::process::id()));
    fs::create_dir_all(&directory).expect("temporary directory");
    let mut bytes = fs::read(format!("{ASSETS}/sample_scene_uastc.glb")).expect("fixture");
    let identifier = [0xAB, b'K', b'T', b'X', b' ', b'2', b'0', 0xBB];
    let start = bytes.windows(identifier.len()).position(|window| window == identifier).expect("embedded KTX2 texture");
    bytes[start + 80..start + 200].fill(0xFF);
    fs::write(directory.join("broken.glb"), &bytes).expect("broken scene");
    let mut app = SceneApp { assets: directory.to_string_lossy().to_string(), ..default() }.build();
    let error = spawn_scene(&mut app, "broken.glb").expect_err("broken textures fail to load");
    fs::remove_dir_all(&directory).ok();
    assert!(error.contains("Basis Universal") || error.contains("KTX2"), "{error}");
}
