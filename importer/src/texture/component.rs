use bevy::prelude::*;

#[derive(Component, Reflect, Clone, Debug, Default)]
#[reflect(Component, Clone, Default, Debug)]
pub struct GltfTextures(pub Vec<Handle<Image>>);
