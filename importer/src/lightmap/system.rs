use bevy::{pbr::Lightmap, prelude::*};
use std::iter;
use crate::name::object_name;
use super::component::PendingLightmap;

pub fn apply_lightmaps(mut commands: Commands, nodes: Query<(Entity, &PendingLightmap, Option<&Children>, Option<&Name>)>, meshes: Query<&Mesh3d>, mesh_assets: Res<Assets<Mesh>>) {
    for (entity, pending, children, name) in &nodes {
        let targets: Vec<(Entity, &Mesh3d)> = iter::once(entity).chain(children.into_iter().flatten().copied()).filter_map(|target| Some((target, meshes.get(target).ok()?))).collect();
        if targets.iter().any(|(_target, mesh)| mesh_assets.get(&mesh.0).is_none()) {
            continue;
        }
        commands.entity(entity).remove::<PendingLightmap>();
        if targets.is_empty() {
            warn!("{}: Lightmap has no mesh to light", object_name(name));
            continue;
        }
        for (target, mesh) in targets {
            if mesh_assets.get(&mesh.0).is_some_and(|mesh| mesh.attribute(Mesh::ATTRIBUTE_UV_1).is_none()) {
                warn!("{}: Lightmap needs a second UV map on its mesh", object_name(name));
                continue;
            }
            commands.entity(target).insert(Lightmap { image: pending.image.clone(), uv_rect: Rect::new(0.0, 0.0, 1.0, 1.0), bicubic_sampling: pending.bicubic });
        }
    }
}
