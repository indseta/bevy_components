mod describe;
mod resource;
mod system;

use bevy::prelude::*;
use std::{env, path::PathBuf};

pub use describe::component_schema;
pub use resource::SchemaOutput;

pub const SCHEMA_FILE: &str = "bevy_components_schema.json";

pub struct BlenderSchemaPlugin {
    pub crates: Vec<String>,
    pub path: PathBuf,
}

impl BlenderSchemaPlugin {
    pub fn new(crates: &[&str]) -> Self {
        return BlenderSchemaPlugin { crates: crates.iter().map(|name| name.replace('-', "_")).collect(), path: PathBuf::from(SCHEMA_FILE) };
    }
}

impl Plugin for BlenderSchemaPlugin {
    fn build(&self, app: &mut App) {
        let path = if self.path.is_absolute() { self.path.clone() } else { env::var_os("CARGO_MANIFEST_DIR").map_or_else(|| self.path.clone(), |root| PathBuf::from(root).join(&self.path)) };
        app.insert_resource(SchemaOutput { path, crates: self.crates.clone() });
        app.add_systems(Startup, system::write_schema);
    }
}
