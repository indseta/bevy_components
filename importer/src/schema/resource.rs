use bevy::prelude::*;
use std::path::PathBuf;

#[derive(Resource, Clone, Debug)]
pub struct SchemaOutput {
    pub path: PathBuf,
    pub crates: Vec<String>,
}
