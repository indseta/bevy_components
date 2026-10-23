mod component;
mod event;
mod system;

use bevy::{app::SceneSpawnerSystems, prelude::*};

pub use event::BlenderSceneReady;

pub struct ScenePlugin;

impl Plugin for ScenePlugin {
    fn build(&self, app: &mut App) {
        app.add_observer(system::mark_spawned_scenes);
        app.add_systems(SpawnScene, system::check_addon_version.after(SceneSpawnerSystems::WorldInstanceSpawn));
        app.add_systems(SpawnScene, system::announce_ready_scenes.after(crate::system::apply_navigation).after(crate::system::apply_reflection_probes).after(crate::light::apply_lights).after(crate::light::apply_scene_lighting).after(crate::light::apply_sky).after(crate::lightmap::apply_lightmaps));
    }
}
