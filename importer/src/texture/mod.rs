mod component;
mod extension;
mod glb;
mod loader;
mod transcode;

use bevy::{gltf::{DefaultGltfImageSampler, GltfLoader, GltfPlugin, extensions::GltfExtensionHandlers}, image::{CompressedImageFormatSupport, CompressedImageFormats}, prelude::*};
use extension::TextureHandles;
use loader::CompressedGltfLoader;

pub use component::GltfTextures;

pub struct TexturePlugin;

impl Plugin for TexturePlugin {
    fn build(&self, app: &mut App) {
        app.register_type::<GltfTextures>();
    }

    fn cleanup(&self, app: &mut App) {
        let Some(gltf) = gltf_loader(app) else {
            warn!("GltfPlugin was not found, compressed KTX2 textures and light probe textures in GLB files will not load");
            return;
        };
        gltf.extensions.write_blocking().push(Box::new(TextureHandles::default()));
        app.register_asset_loader(CompressedGltfLoader { gltf });
    }
}

fn gltf_loader(app: &App) -> Option<GltfLoader> {
    let plugin = app.get_added_plugins::<GltfPlugin>().into_iter().next()?;
    let world = app.world();
    return Some(GltfLoader {
        supported_compressed_formats: world.get_resource::<CompressedImageFormatSupport>().map_or(CompressedImageFormats::NONE, |support| support.0),
        custom_vertex_attributes: plugin.custom_vertex_attributes.clone(),
        default_sampler: world.get_resource::<DefaultGltfImageSampler>()?.get_internal(),
        default_convert_coordinates: plugin.convert_coordinates,
        extensions: world.get_resource::<GltfExtensionHandlers>()?.0.clone(),
        default_skinned_mesh_bounds_policy: plugin.skinned_mesh_bounds_policy,
        default_mesh_compression: plugin.mesh_compression.clone(),
    });
}
