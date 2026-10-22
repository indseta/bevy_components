use serde::Deserialize;
use serde_json::Value;

#[derive(Deserialize)]
pub struct ExportedData {
    pub version: u32,
    pub components: Vec<ExportedComponent>,
}

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ExportedComponent {
    VisibilityRange {
        start: [f32; 2],
        end: [f32; 2],
        use_aabb: bool,
    },
    Collider {
        shape: String,
        size: [f32; 3],
        radius: f32,
        height: f32,
        sensor: bool,
    },
    RigidBody {
        kind: String,
    },
    Custom {
        type_path: String,
        data: Value,
    },
    #[serde(other)]
    Unsupported,
}
