use bevy::prelude::*;

#[derive(EntityEvent, Clone, Copy, Debug)]
pub struct BlenderSceneReady {
    pub entity: Entity,
}
