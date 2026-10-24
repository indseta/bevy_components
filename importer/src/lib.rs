mod component;
mod custom;
mod data;
mod extension;
mod joint;
mod light;
mod lightmap;
mod name;
mod scene;
mod schema;
mod system;
mod texture;
mod view;

use bevy::{app::SceneSpawnerSystems, gltf::extensions::GltfExtensionHandlers, prelude::*};

pub use component::{BlenderCustomComponent, BlenderCustomComponents, NavigationObstacle, NavigationWalkable};
pub use light::{BlenderSky, NoBlenderSky};
pub use scene::BlenderSceneReady;
pub use schema::{BlenderSchemaPlugin, SCHEMA_FILE, SchemaOutput, component_schema};
pub use texture::GltfTextures;
pub use view::{VIEW_VARIABLE, blender_view, parse_view};

pub struct BlenderBevyComponentsPlugin;

impl Plugin for BlenderBevyComponentsPlugin {
    fn build(&self, app: &mut App) {
        app.add_plugins((texture::TexturePlugin, light::LightingPlugin, lightmap::LightmapPlugin, scene::ScenePlugin));
        app.register_type::<component::SceneAnimations>();
        app.register_type::<component::NavigationWalkable>();
        app.register_type::<component::NavigationObstacle>();
        app.add_systems(SpawnScene, (system::read_gltf_components, system::apply_default_bodies, system::build_joints, system::spawn_scene_references, system::play_animations, system::apply_mesh_components, system::build_colliders, system::apply_navigation).chain().after(SceneSpawnerSystems::WorldInstanceSpawn));
        app.add_systems(SpawnScene, system::apply_reflection_probes.after(system::read_gltf_components));
        app.add_systems(SpawnScene, (system::clear_scene_physics, system::apply_scene_physics).chain().after(SceneSpawnerSystems::WorldInstanceSpawn));
    }

    fn finish(&self, app: &mut App) {
        let Some(mut handlers) = app.world().get_resource::<GltfExtensionHandlers>().and_then(|handlers| handlers.0.try_write()) else {
            warn!("GltfPlugin was not found, Animation components will not play");
            return;
        };
        handlers.push(Box::new(extension::AnimationExtension::default()));
    }
}
