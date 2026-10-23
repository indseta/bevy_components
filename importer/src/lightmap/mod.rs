mod component;
mod system;

use bevy::prelude::*;

pub use component::PendingLightmap;

pub struct LightmapPlugin;

impl Plugin for LightmapPlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(Update, system::apply_lightmaps.after(crate::system::read_gltf_components));
    }
}
