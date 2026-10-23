mod component;
mod data;
mod extension;
mod joint;
mod system;
mod texture;

use bevy::{gltf::extensions::GltfExtensionHandlers, prelude::*};

pub use component::{BlenderCustomComponent, BlenderCustomComponents};
pub use texture::GltfTextures;

pub struct BlenderBevyComponentsPlugin;

impl Plugin for BlenderBevyComponentsPlugin {
    fn build(&self, app: &mut App) {
        app.add_plugins(texture::TexturePlugin);
        app.register_type::<component::SceneAnimations>();
        app.add_systems(Update, (system::read_gltf_components, system::apply_default_bodies, system::build_joints, system::spawn_scene_references, system::play_animations, system::apply_mesh_components, system::build_colliders).chain());
        app.add_systems(Update, system::apply_reflection_probes.after(system::read_gltf_components));
    }

    fn finish(&self, app: &mut App) {
        let Some(mut handlers) = app.world().get_resource::<GltfExtensionHandlers>().and_then(|handlers| handlers.0.try_write()) else {
            warn!("GltfPlugin was not found, Animation components will not play");
            return;
        };
        handlers.push(Box::new(extension::AnimationExtension::default()));
    }
}
