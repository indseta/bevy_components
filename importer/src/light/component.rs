use bevy::{light::CascadeShadowConfig, prelude::*};

#[derive(Clone, Debug)]
pub struct LightSpec {
    pub kind: LightKind,
    pub intensity: Option<f32>,
    pub radius: Option<f32>,
    pub range: Option<f32>,
    pub color: Color,
    pub size: Vec2,
    pub shadows: bool,
    pub contact_shadows: bool,
    pub volumetric: bool,
    pub baked: bool,
    pub depth_bias: Option<f32>,
    pub normal_bias: Option<f32>,
    pub near_clip: Option<f32>,
    pub cascades: Option<CascadeShadowConfig>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum LightKind {
    Point,
    Spot,
    Directional,
    Area,
}

impl LightKind {
    pub fn from_str(value: &str) -> Option<Self> {
        return match value {
            "point" => Some(Self::Point),
            "spot" => Some(Self::Spot),
            "directional" => Some(Self::Directional),
            "area" => Some(Self::Area),
            _ => None,
        };
    }
}

#[derive(Component)]
pub struct PendingLight(pub LightSpec);

#[derive(Component)]
pub struct DecodedGltfSceneExtras;

#[derive(Resource, Clone, Debug, PartialEq)]
pub struct BlenderSky {
    pub image: Handle<Image>,
    pub brightness: f32,
    pub environment_light: Option<f32>,
}

#[derive(Component, Clone, Copy, Debug, Default)]
pub struct NoBlenderSky;

#[derive(Component)]
pub struct SkyCamera(pub BlenderSky);

#[derive(Resource)]
pub struct SkySource(pub Entity);
