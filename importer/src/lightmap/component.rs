use bevy::prelude::*;

#[derive(Component)]
pub struct PendingLightmap {
    pub image: Handle<Image>,
    pub bicubic: bool,
}
