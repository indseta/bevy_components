mod component;
mod system;

use bevy::prelude::*;

pub use component::PendingLight;
pub use system::light_spec;

pub struct LightingPlugin;

impl Plugin for LightingPlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(Update, system::apply_lights.after(crate::system::read_gltf_components));
        app.add_systems(Update, system::apply_ambient_light);
    }
}
