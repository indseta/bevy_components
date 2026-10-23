use bevy::{asset::LoadContext, gltf::{extensions::{ErasedGltfExtensionHandler, GltfExtensionHandler}, gltf::Node}, prelude::*};

#[derive(Clone, Default)]
pub struct SpotLightRadius;

impl GltfExtensionHandler for SpotLightRadius {
    fn dyn_clone(&self) -> Box<dyn ErasedGltfExtensionHandler> {
        return Box::new(self.clone());
    }

    fn on_spawn_light_spot(&mut self, _load_context: &mut LoadContext<'_>, _gltf_node: &Node, entity: &mut EntityWorldMut) {
        if let Some(mut spot) = entity.get_mut::<SpotLight>() {
            spot.radius = 0.0;
        }
    }
}
