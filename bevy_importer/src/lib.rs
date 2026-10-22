mod component;
mod data;
mod system;

use bevy::prelude::*;

pub use component::{BlenderCustomComponent, BlenderCustomComponents, BlenderSpawnPoint};

pub struct BlenderBevyComponentsPlugin;

impl Plugin for BlenderBevyComponentsPlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(Update, (system::read_gltf_components, system::apply_mesh_components, system::build_colliders).chain());
    }
}
