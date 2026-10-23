use bevy::{asset::LoadContext, gltf::{extensions::{ErasedGltfExtensionHandler, GltfExtensionHandler}, gltf::{Node, Texture}}, prelude::*};
use super::component::GltfTextures;

const TEXTURE_KEY: &str = "\\\"texture\\\":";

#[derive(Clone, Default)]
pub struct TextureHandles {
    textures: Vec<Handle<Image>>,
}

impl GltfExtensionHandler for TextureHandles {
    fn dyn_clone(&self) -> Box<dyn ErasedGltfExtensionHandler> {
        return Box::new(self.clone());
    }

    fn on_texture(&mut self, _gltf_texture: &Texture, texture: Handle<Image>) {
        self.textures.push(texture);
    }

    fn on_gltf_node(&mut self, _load_context: &mut LoadContext<'_>, gltf_node: &Node, entity: &mut EntityWorldMut) {
        if gltf_node.extras().as_ref().is_some_and(|extras| extras.get().contains(TEXTURE_KEY)) {
            entity.insert(GltfTextures(self.textures.clone()));
        }
    }
}
