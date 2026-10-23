mod common;

use bevy::prelude::*;
use bevy_components_importer::{BlenderSchemaPlugin, SCHEMA_FILE, component_schema};
use serde_json::{Value, json};
use std::{env, fs};

const SCHEMA: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/assets/", "bevy_components_schema.json");

#[derive(Component, Reflect, Default)]
#[reflect(Component, Default)]
#[type_path = "other_game"]
struct Elsewhere {
    value: f32,
}

#[derive(Component, Reflect)]
#[reflect(Component)]
#[type_path = "other_game"]
struct Marker;

#[derive(Component, Reflect)]
#[reflect(Component)]
#[type_path = "other_game"]
struct Hidden {
    shown: i16,
    #[reflect(skip_serializing)]
    cache: Vec<f32>,
    tint: Color,
}

fn game_schema(crates: &[&str]) -> Value {
    let app = App::new();
    let registry = app.world().resource::<AppTypeRegistry>().read();
    return component_schema(&registry, &crates.iter().map(|name| name.to_string()).collect::<Vec<_>>());
}

fn written(crates: &[&str]) -> String {
    let folder = env::temp_dir().join(format!("bevy_components_schema_{}", std::process::id()));
    let path = folder.join("nested").join(SCHEMA_FILE);
    let mut app = App::new();
    app.add_plugins(BlenderSchemaPlugin { path: path.clone(), ..BlenderSchemaPlugin::new(crates) });
    app.update();
    let text = fs::read_to_string(&path).unwrap_or_else(|error| panic!("the plugin did not write {}: {error}", path.display()));
    let _ = fs::remove_dir_all(folder);
    return text;
}

#[test]
fn schema_lists_game_components_with_typed_fields() {
    let schema = game_schema(&["my_game"]);
    let components = schema["components"].as_array().expect("the schema lists components");
    assert_eq!(components.iter().map(|component| component["type_path"].as_str().unwrap_or_default()).collect::<Vec<_>>(), ["my_game::Patrol", "my_game::Reward"]);
    assert_eq!(components[0], json!({"type_path": "my_game::Patrol", "kind": "struct", "has_default": true, "fields": [
        {"name": "speed", "type": "float", "rust_type": "f32", "default": 2.0},
        {"name": "mode", "type": "enum", "rust_type": "my_game::PatrolMode", "variants": ["Loop", "PingPong"], "default": "Loop"},
        {"name": "offset", "type": "vector2", "rust_type": "glam::Vec2", "default": [0.0, 0.0]},
        {"name": "stops", "type": "int", "rust_type": "u8", "default": 1},
        {"name": "timer", "type": "other", "rust_type": "bevy_time::timer::Timer"}
    ]}));
    assert_eq!(components[1], json!({"type_path": "my_game::Reward", "kind": "tuple_struct", "has_default": true, "fields": [
        {"name": "0", "type": "int", "rust_type": "u32", "default": 0},
        {"name": "1", "type": "float", "rust_type": "f32", "default": 0.0}
    ]}));
}

#[test]
fn schema_reads_types_without_default_and_skips_hidden_fields() {
    let schema = game_schema(&["other_game"]);
    assert_eq!(schema["components"], json!([
        {"type_path": "other_game::Elsewhere", "kind": "struct", "has_default": true, "fields": [{"name": "value", "type": "float", "rust_type": "f32", "default": 0.0}]},
        {"type_path": "other_game::Hidden", "kind": "struct", "has_default": false, "fields": [{"name": "shown", "type": "int", "rust_type": "i16", "default": 0}, {"name": "tint", "type": "color", "rust_type": "bevy_color::color::Color", "default": {"Srgba": {"red": 1.0, "green": 1.0, "blue": 1.0, "alpha": 1.0}}}]},
        {"type_path": "other_game::Marker", "kind": "struct", "has_default": false, "fields": []}
    ]));
    assert_eq!(game_schema(&["missing_game"])["components"], json!([]));
}

#[test]
fn plugin_writes_the_schema_fixture() {
    let text = written(&["my_game"]);
    if env::var_os("BEVY_COMPONENTS_WRITE_SCHEMA").is_some() {
        fs::write(SCHEMA, &text).expect("the schema fixture is writable");
    }
    let fixture = fs::read_to_string(SCHEMA).unwrap_or_default();
    assert!(fixture == text, "{SCHEMA} is out of date, run BEVY_COMPONENTS_WRITE_SCHEMA=1 cargo test --test schema to write it");
}
