mod component;
mod extension;
mod system;

use bevy::{app::SceneSpawnerSystems, gltf::extensions::GltfExtensionHandlers, prelude::*};

pub use component::PendingLight;
pub use system::light_spec;

pub struct LightingPlugin;

impl Plugin for LightingPlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(SpawnScene, system::apply_lights.after(crate::system::read_gltf_components));
        app.add_systems(SpawnScene, system::apply_ambient_light.after(SceneSpawnerSystems::WorldInstanceSpawn));
    }

    fn finish(&self, app: &mut App) {
        let Some(mut handlers) = app.world().get_resource::<GltfExtensionHandlers>().and_then(|handlers| handlers.0.try_write()) else { return; };
        handlers.push(Box::new(extension::SpotLightRadius));
    }
}
