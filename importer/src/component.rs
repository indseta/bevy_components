use avian3d::prelude::{CollisionLayers, LockedAxes, RigidBody, SweptCcd};
use bevy::{camera::visibility::VisibilityRange, platform::collections::HashMap, prelude::*};
use serde_json::Value;

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
    pub offset: Vec3,
    pub sensor: bool,
    pub events: bool,
    pub collision_only: bool,
    pub own_mesh: bool,
    pub friction: Option<f32>,
    pub restitution: Option<f32>,
    pub layers: Option<CollisionLayers>,
}

#[derive(Clone, Copy, Debug)]
pub enum ColliderShape {
    Trimesh,
    Convex,
    Cuboid,
    Sphere,
    Capsule,
    Cylinder,
    Cone,
}

impl ColliderShape {
    pub fn from_str(value: &str) -> Option<Self> {
        return match value {
            "trimesh" => Some(Self::Trimesh),
            "convex" => Some(Self::Convex),
            "cuboid" => Some(Self::Cuboid),
            "sphere" => Some(Self::Sphere),
            "capsule" => Some(Self::Capsule),
            "cylinder" => Some(Self::Cylinder),
            "cone" => Some(Self::Cone),
            _ => None,
        };
    }

    pub fn is_mesh(&self) -> bool {
        return matches!(self, Self::Trimesh | Self::Convex);
    }
}

#[derive(Clone, Copy, Debug)]
pub struct ShadowSettings {
    pub cast: bool,
    pub receive: bool,
    pub own_mesh: bool,
}

#[derive(Clone, Debug)]
pub struct RigidBodySpec {
    pub body: RigidBody,
    pub mass: Option<f32>,
    pub gravity_scale: Option<f32>,
    pub linear_damping: Option<f32>,
    pub angular_damping: Option<f32>,
    pub locked_axes: Option<LockedAxes>,
    pub ccd: Option<SweptCcd>,
    pub linear_velocity: Option<Vec3>,
    pub angular_velocity: Option<Vec3>,
}

#[derive(Clone, Debug)]
pub struct JointSpec {
    pub kind: JointKind,
    pub body1: Option<String>,
    pub body2: Option<String>,
    pub axis: Vec3,
    pub angle_limits: Option<[f32; 2]>,
    pub distance_limits: Option<[f32; 2]>,
    pub swing_limit: Option<f32>,
    pub linear_damping: f32,
    pub angular_damping: f32,
    pub collide: bool,
}

#[derive(Clone, Copy, Debug)]
pub enum JointKind {
    Fixed,
    Revolute,
    Prismatic,
    Spherical,
}

impl JointKind {
    pub fn from_str(value: &str) -> Option<Self> {
        return match value {
            "fixed" => Some(Self::Fixed),
            "revolute" => Some(Self::Revolute),
            "prismatic" => Some(Self::Prismatic),
            "spherical" => Some(Self::Spherical),
            _ => None,
        };
    }
}

#[derive(Clone, Copy, Debug)]
pub enum NavigationRole {
    Walkable(f32),
    Obstacle,
    Ignored,
}

#[derive(Component, Clone, Copy, Debug, Reflect)]
#[reflect(Component, Clone, Default)]
pub struct NavigationWalkable {
    pub cost: f32,
}

impl Default for NavigationWalkable {
    fn default() -> Self {
        return Self { cost: 1.0 };
    }
}

#[derive(Component, Clone, Copy, Debug, Default, Reflect)]
#[reflect(Component, Clone, Default)]
pub struct NavigationObstacle;

#[derive(Component, Default)]
pub struct ImportedComponents {
    pub visibility_range: Option<VisibilityRange>,
    pub collider: Option<ColliderSpec>,
    pub shadows: Option<ShadowSettings>,
    pub navigation: Option<NavigationRole>,
}

#[derive(Component)]
pub struct DecodedGltfExtras;

#[derive(Component)]
pub struct DefaultStaticBody;

#[derive(Component)]
pub struct DecodedScenePhysics;

#[derive(Resource)]
pub struct GravitySource {
    pub scene: Entity,
    pub previous: Vec3,
}

#[derive(Component)]
pub struct ProcessedMesh;

#[derive(Component)]
pub struct PendingMeshCollider(pub ColliderSpec);

#[derive(Component)]
pub struct PendingJoint(pub JointSpec);

#[derive(Component, Clone, Debug, Default, Reflect)]
#[reflect(Component, Clone, Default)]
pub struct SceneAnimations(pub HashMap<String, Handle<AnimationClip>>);

#[derive(Clone, Debug)]
pub struct AnimationSpec {
    pub clip: String,
    pub repeat: bool,
    pub speed: f32,
}

#[derive(Component)]
pub struct PendingAnimation(pub AnimationSpec);

#[derive(Component)]
pub struct PendingSceneReference {
    pub path: String,
    pub scene: usize,
}

#[derive(Component)]
pub struct PendingReflectionProbe {
    pub cubemap: Handle<Image>,
    pub intensity: f32,
}
