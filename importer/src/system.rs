use avian3d::prelude::{Collider, RigidBody, Sensor};
use bevy::{camera::visibility::VisibilityRange, gltf::GltfExtras, prelude::*};
use serde_json::Value;
use crate::{component::*, data::*};

pub fn read_gltf_components(mut commands: Commands, nodes: Query<(Entity, &GltfExtras, Option<&Name>), Without<DecodedGltfExtras>>) {
    for (entity, extras, name) in &nodes {
        commands.entity(entity).insert(DecodedGltfExtras);
        let Ok(outer) = serde_json::from_str::<Value>(&extras.value) else {
            warn!("Invalid glTF extras on {:?}", name);
            continue;
        };
        let Some(serialized) = outer.get("bevy_components").and_then(Value::as_str) else { continue; };
        let Ok(exported) = serde_json::from_str::<ExportedData>(serialized) else {
            warn!("Invalid Bevy component metadata on {:?}", name);
            continue;
        };
        if exported.version != 1 {
            warn!("Unsupported Blender Bevy component version {} on {:?}", exported.version, name);
            continue;
        }

        let mut components = ImportedComponents::default();
        let mut custom = BlenderCustomComponents::default();
        let mut rigid_body = None;
        let mut spawn_tag = None;

        for component in exported.components {
            match component {
                ExportedComponent::VisibilityRange { start, end, use_aabb } => {
                    if start[0] <= start[1] && start[1] <= end[0] && end[0] <= end[1] {
                        components.visibility_range = Some(VisibilityRange { start_margin: start[0]..start[1], end_margin: end[0]..end[1], use_aabb });
                    } else {
                        warn!("Invalid visibility range on {:?}", name);
                    }
                }
                ExportedComponent::Collider { shape, size, radius, height, sensor } => {
                    if let Some(shape) = ColliderShape::from_str(&shape) {
                        components.collider = Some(ColliderSpec { shape, size, radius, height, sensor });
                    } else {
                        warn!("Unsupported collider shape on {:?}", name);
                    }
                }
                ExportedComponent::RigidBody { kind } => {
                    rigid_body = match kind.as_str() {
                        "static" => Some(RigidBody::Static),
                        "dynamic" => Some(RigidBody::Dynamic),
                        "kinematic" => Some(RigidBody::Kinematic),
                        _ => {
                            warn!("Unsupported rigid body type on {:?}", name);
                            None
                        }
                    };
                }
                ExportedComponent::SpawnPoint { tag } => spawn_tag = Some(tag),
                ExportedComponent::Custom { type_path, data } => custom.0.push(BlenderCustomComponent { type_path, data }),
            }
        }

        let has_collider = components.collider.is_some();
        if let Some(spec) = &components.collider && let Some(collider) = primitive_collider(spec) {
            commands.entity(entity).insert(collider);
            if spec.sensor {
                commands.entity(entity).insert(Sensor);
            }
        }
        commands.entity(entity).insert(components);
        if let Some(tag) = spawn_tag {
            commands.entity(entity).insert(BlenderSpawnPoint(tag));
        }
        if !custom.0.is_empty() {
            commands.entity(entity).insert(custom);
        }
        if let Some(body) = rigid_body {
            commands.entity(entity).insert(body);
        } else if has_collider {
            commands.entity(entity).insert(RigidBody::Static);
        }
    }
}

pub fn apply_mesh_components(mut commands: Commands, meshes: Query<(Entity, &Mesh3d), Without<ProcessedMesh>>, parents: Query<&ChildOf>, specs: Query<&ImportedComponents>) {
    for (entity, _mesh) in &meshes {
        let mut cursor = Some(entity);
        let mut visibility = None;
        let mut collider = None;

        while let Some(current) = cursor {
            if let Ok(spec) = specs.get(current) {
                if visibility.is_none() {
                    visibility = spec.visibility_range.clone();
                }
                if collider.is_none() {
                    collider = spec.collider.clone();
                }
                if visibility.is_some() && collider.is_some() {
                    break;
                }
            }
            cursor = parents.get(current).ok().map(ChildOf::parent);
        }

        let mut target = commands.entity(entity);
        target.insert(ProcessedMesh);
        if let Some(range) = visibility {
            target.insert(range);
        }
        if let Some(spec) = collider && spec.shape.is_mesh() {
            target.insert(PendingMeshCollider(spec));
        }
    }
}

pub fn build_colliders(mut commands: Commands, candidates: Query<(Entity, &Mesh3d, &PendingMeshCollider)>, mesh_assets: Res<Assets<Mesh>>) {
    for (entity, mesh3d, pending) in &candidates {
        let spec = &pending.0;
        let Some(mesh) = mesh_assets.get(&mesh3d.0) else { continue; };
        let collider = match spec.shape {
            ColliderShape::Convex => Collider::convex_hull_from_mesh(mesh),
            _ => Collider::trimesh_from_mesh(mesh),
        };

        let mut target = commands.entity(entity);
        target.remove::<PendingMeshCollider>();
        if let Some(collider) = collider {
            target.insert(collider);
            if spec.sensor {
                target.insert(Sensor);
            }
        } else {
            warn!("Could not create collider from mesh on entity {:?}", entity);
        }
    }
}

fn primitive_collider(spec: &ColliderSpec) -> Option<Collider> {
    return match spec.shape {
        ColliderShape::Cuboid => Some(Collider::cuboid(spec.size[0], spec.size[1], spec.size[2])),
        ColliderShape::Sphere => Some(Collider::sphere(spec.radius)),
        ColliderShape::Capsule => Some(Collider::capsule(spec.radius, spec.height)),
        ColliderShape::Trimesh | ColliderShape::Convex => None,
    };
}
