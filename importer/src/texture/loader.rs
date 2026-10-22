use bevy::{asset::{AssetLoader, LoadContext, io::Reader}, gltf::{Gltf, GltfLoader, GltfLoaderSettings}, prelude::*};
use super::glb::transcode_glb;

#[derive(TypePath)]
pub struct CompressedGltfLoader {
    pub gltf: GltfLoader,
}

impl AssetLoader for CompressedGltfLoader {
    type Asset = Gltf;
    type Settings = GltfLoaderSettings;
    type Error = BevyError;

    async fn load(&self, reader: &mut dyn Reader, settings: &GltfLoaderSettings, load_context: &mut LoadContext<'_>) -> Result<Gltf, BevyError> {
        let mut bytes = Vec::new();
        reader.read_to_end(&mut bytes).await?;
        if let Some(transcoded) = transcode_glb(&bytes, self.gltf.supported_compressed_formats)? {
            bytes = transcoded;
        }
        return Ok(GltfLoader::load_gltf(&self.gltf, &bytes, load_context, settings).await?);
    }

    fn extensions(&self) -> &[&str] {
        return &["glb"];
    }
}
