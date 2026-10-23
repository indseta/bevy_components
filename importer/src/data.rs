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
        friction: Option<f32>,
        restitution: Option<f32>,
        memberships: Option<u32>,
        filters: Option<u32>,
    },
    RigidBody {
        kind: String,
        mass: Option<f32>,
        gravity_scale: Option<f32>,
        linear_damping: Option<f32>,
        angular_damping: Option<f32>,
        lock_translation: Option<[bool; 3]>,
        lock_rotation: Option<[bool; 3]>,
        ccd: Option<String>,
        linear_velocity: Option<[f32; 3]>,
        angular_velocity: Option<[f32; 3]>,
    },
    Joint {
        kind: String,
        body1: Option<String>,
        body2: Option<String>,
        axis: Option<[f32; 3]>,
        angle_limits: Option<[f32; 2]>,
        distance_limits: Option<[f32; 2]>,
        swing_limit: Option<f32>,
        linear_damping: Option<f32>,
        angular_damping: Option<f32>,
        collide: bool,
    },
    Shadows {
        cast: bool,
        receive: bool,
    },
    AudioPlayer {
        path: String,
        volume: f32,
        #[serde(rename = "loop")]
        looping: bool,
        autoplay: bool,
        spatial: bool,
        distance: f32,
    },
    Custom {
        type_path: String,
        data: Value,
    },
    SceneReference {
        path: String,
        scene: usize,
    },
    Animation {
        clip: String,
        repeat: bool,
        speed: f32,
    },
    #[serde(other)]
    Unsupported,
}
