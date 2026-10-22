use bevy::{camera::visibility::VisibilityRange, prelude::*};
use serde_json::Value;

#[derive(Component, Clone, Debug)]
pub struct BlenderSpawnPoint(pub String);

#[derive(Clone, Debug)]
pub struct BlenderCustomComponent {
    pub type_path: String,
    pub data: Value,
}

#[derive(Component, Debug, Default)]
pub struct BlenderCustomComponents(pub Vec<BlenderCustomComponent>);

#[derive(Clone, Debug)]
pub struct ColliderSpec {
    pub shape: ColliderShape,
    pub size: [f32; 3],
    pub radius: f32,
    pub height: f32,
    pub sensor: bool,
}

#[derive(Clone, Copy, Debug)]
pub enum ColliderShape {
    Trimesh,
    Convex,
    Cuboid,
    Sphere,
    Capsule,
}

impl ColliderShape {
    pub fn from_str(value: &str) -> Option<Self> {
        return match value {
            "trimesh" => Some(Self::Trimesh),
            "convex" => Some(Self::Convex),
            "cuboid" => Some(Self::Cuboid),
            "sphere" => Some(Self::Sphere),
            "capsule" => Some(Self::Capsule),
            _ => None,
        };
    }

    pub fn is_mesh(&self) -> bool {
        return matches!(self, Self::Trimesh | Self::Convex);
    }
}

#[derive(Component, Default)]
pub struct ImportedComponents {
    pub visibility_range: Option<VisibilityRange>,
    pub collider: Option<ColliderSpec>,
}

#[derive(Component)]
pub struct DecodedGltfExtras;

#[derive(Component)]
pub struct ProcessedMesh;

#[derive(Component)]
pub struct PendingMeshCollider(pub ColliderSpec);
