use bevy::prelude::*;
use std::{fs, io, path::Path};
use super::{describe::component_schema, resource::SchemaOutput};

pub fn write_schema(output: Res<SchemaOutput>, registry: Res<AppTypeRegistry>) {
    let schema = component_schema(&registry.read(), &output.crates);
    let count = schema["components"].as_array().map_or(0, Vec::len);
    let text = serde_json::to_string_pretty(&schema).expect("a JSON value always serializes") + "\n";
    match write_if_changed(&output.path, &text) {
        Ok(true) => info!("Wrote {} game components for Blender to {}", count, output.path.display()),
        Ok(false) => {}
        Err(error) => warn!("Could not write the Blender component schema to {}: {}", output.path.display(), error),
    }
}

fn write_if_changed(path: &Path, text: &str) -> io::Result<bool> {
    if fs::read_to_string(path).is_ok_and(|existing| existing == text) {
        return Ok(false);
    }
    if let Some(folder) = path.parent().filter(|folder| !folder.as_os_str().is_empty()) {
        fs::create_dir_all(folder)?;
    }
    let staging = path.with_file_name(format!(".{}.tmp", path.file_name().and_then(|name| name.to_str()).unwrap_or("schema")));
    fs::write(&staging, text)?;
    if let Err(error) = fs::rename(&staging, path) {
        let _ = fs::remove_file(&staging);
        return Err(error);
    }
    return Ok(true);
}
