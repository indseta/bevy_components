use bevy::{gltf::{GltfExtras, GltfSceneExtras}, prelude::*, world_serialization::{WorldInstance, WorldInstanceReady, WorldInstanceSpawner}};
use serde_json::Value;
use crate::{component::*, data::ExportedScene, light::PendingLight, lightmap::PendingLightmap, name::object_name};
use super::{component::*, event::*};

const IMPORTER_VERSION: &str = env!("CARGO_PKG_VERSION");

pub fn mark_spawned_scenes(ready: On<WorldInstanceReady>, mut commands: Commands) {
    if ready.entity == Entity::PLACEHOLDER {
        return;
    }
    commands.entity(ready.entity).try_insert(PendingBlenderScene);
}

pub fn announce_ready_scenes(mut commands: Commands, scenes: Query<Entity, With<PendingBlenderScene>>, children: Query<&Children>, unfinished: Query<(), Or<(With<PendingMeshCollider>, With<PendingLightmap>, With<PendingReflectionProbe>, With<PendingJoint>, With<PendingLight>, With<PendingSceneReference>, With<PendingAnimation>, With<DefaultStaticBody>, (With<GltfExtras>, Without<DecodedGltfExtras>), (With<Mesh3d>, Without<ProcessedMesh>))>>, nested: Query<(&WorldAssetRoot, Option<&WorldInstance>, Has<PendingBlenderScene>)>, spawner: Res<WorldInstanceSpawner>, asset_server: Res<AssetServer>) {
    for entity in &scenes {
        let waiting = |descendant: Entity| nested.get(descendant).is_ok_and(|(root, instance, pending)| !asset_server.load_state(&root.0).is_failed() && (pending || !instance.is_some_and(|instance| spawner.instance_is_ready(**instance))));
        if children.iter_descendants(entity).any(|descendant| unfinished.contains(descendant) || waiting(descendant)) {
            continue;
        }
        commands.entity(entity).remove::<PendingBlenderScene>();
        commands.trigger(BlenderSceneReady { entity });
    }
}

pub fn check_addon_version(scenes: Query<(Entity, &GltfSceneExtras, Option<&Name>), Added<GltfSceneExtras>>, parents: Query<&ChildOf>, roots: Query<&WorldAssetRoot>, mut warned: Local<bool>) {
    if *warned {
        return;
    }
    for (entity, extras, name) in &scenes {
        let Some(version) = addon_version(&extras.value) else { continue; };
        if !is_newer(&version, IMPORTER_VERSION) {
            continue;
        }
        let scene = parents.iter_ancestors(entity).find_map(|ancestor| roots.get(ancestor).ok()?.0.path().map(ToString::to_string)).unwrap_or_else(|| object_name(name).to_string());
        warn!("{}: Exported by Bevy Components {}, which is newer than this bevy_components_importer {}, so update the importer to load all of its components", scene, version, IMPORTER_VERSION);
        *warned = true;
        return;
    }
}

fn addon_version(value: &str) -> Option<String> {
    let outer = serde_json::from_str::<Value>(value).ok()?;
    let serialized = outer.get("bevy_components").and_then(Value::as_str)?;
    return serde_json::from_str::<ExportedScene>(serialized).ok()?.addon;
}

fn is_newer(version: &str, current: &str) -> bool {
    return version_numbers(version) > version_numbers(current);
}

fn version_numbers(version: &str) -> Vec<u64> {
    return version.split(['-', '+']).next().unwrap_or_default().split('.').map(|part| part.trim().parse().unwrap_or(0)).collect();
}
