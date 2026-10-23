use avian3d::prelude::{Collider, CollisionLayers, Friction, LayerMask, Mass, NoAutoMass, Restitution, RigidBody, Sensor};
use bevy::{audio::{PlaybackMode, SpatialScale, Volume}, camera::visibility::VisibilityRange, gltf::GltfExtras, light::{NotShadowCaster, NotShadowReceiver}, prelude::*};
use serde_json::Value;
use crate::{component::*, data::*};

pub fn read_gltf_components(mut commands: Commands, nodes: Query<(Entity, &GltfExtras, Option<&Name>), Without<DecodedGltfExtras>>, asset_server: Res<AssetServer>, audio_sources: Option<Res<Assets<AudioSource>>>) {
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
        let mut mass = None;
        let mut audio = None;

        for component in exported.components {
            match component {
                ExportedComponent::VisibilityRange { start, end, use_aabb } => {
                    if start[0] <= start[1] && start[1] <= end[0] && end[0] <= end[1] {
                        components.visibility_range = Some(VisibilityRange { start_margin: start[0]..start[1], end_margin: end[0]..end[1], use_aabb });
                    } else {
                        warn!("Invalid visibility range on {:?}", name);
                    }
                }
                ExportedComponent::Collider { shape, size, radius, height, sensor, friction, restitution, memberships, filters } => {
                    if let Some(shape) = ColliderShape::from_str(&shape) {
                        let layers = (memberships.is_some() || filters.is_some()).then(|| CollisionLayers::from_bits(memberships.unwrap_or(LayerMask::DEFAULT.0), filters.unwrap_or(LayerMask::ALL.0)));
                        components.collider = Some(ColliderSpec { shape, size, radius, height, sensor, friction, restitution, layers });
                    } else {
                        warn!("Unsupported collider shape on {:?}", name);
                    }
                }
                ExportedComponent::RigidBody { kind, mass: body_mass } => {
                    rigid_body = match kind.as_str() {
                        "static" => Some(RigidBody::Static),
                        "dynamic" => Some(RigidBody::Dynamic),
                        "kinematic" => Some(RigidBody::Kinematic),
                        _ => {
                            warn!("Unsupported rigid body type on {:?}", name);
                            None
                        }
                    };
                    mass = match body_mass {
                        Some(value) if value <= 0.0 => {
                            warn!("Invalid mass on {:?}", name);
                            None
                        }
                        _ => body_mass,
                    };
                }
                ExportedComponent::Shadows { cast, receive } => components.shadows = Some(ShadowSettings { cast, receive }),
                ExportedComponent::AudioPlayer { path, volume, looping, autoplay, spatial, distance } => {
                    if path.is_empty() {
                        warn!("Audio Player on {:?} has no sound file", name);
                    } else if audio_sources.is_none() {
                        warn!("Audio Player on {:?} needs Bevy's AudioPlugin", name);
                    } else {
                        let mode = if looping { PlaybackMode::Loop } else { PlaybackMode::Once };
                        let spatial_scale = (spatial && distance > 0.0).then(|| SpatialScale::new(1.0 / distance));
                        audio = Some((AudioPlayer::new(asset_server.load(path)), PlaybackSettings { mode, volume: Volume::Linear(volume.max(0.0)), paused: !autoplay, spatial, spatial_scale, ..PlaybackSettings::ONCE }));
                    }
                }
                ExportedComponent::Custom { type_path, data } => custom.0.push(BlenderCustomComponent { type_path, data }),
                ExportedComponent::Unsupported => warn!("Unsupported Bevy component on {:?}", name),
            }
        }

        let has_collider = components.collider.is_some();
        if let Some(spec) = &components.collider && let Some(collider) = primitive_collider(spec) {
            insert_collider(&mut commands.entity(entity), collider, spec);
        }
        commands.entity(entity).insert(components);
        if !custom.0.is_empty() {
            commands.entity(entity).insert(custom);
        }
        if let Some(audio) = audio {
            commands.entity(entity).insert(audio);
        }
        if let Some(body) = rigid_body {
            commands.entity(entity).insert(body);
            if let Some(mass) = mass {
                commands.entity(entity).insert((Mass(mass), NoAutoMass));
            }
        } else if has_collider {
            commands.entity(entity).insert(DefaultStaticBody);
        }
    }
}

pub fn apply_default_bodies(mut commands: Commands, candidates: Query<Entity, With<DefaultStaticBody>>, parents: Query<&ChildOf>, bodies: Query<(), With<RigidBody>>) {
    for entity in &candidates {
        let mut target = commands.entity(entity);
        target.remove::<DefaultStaticBody>();
        if !parents.iter_ancestors(entity).any(|ancestor| bodies.contains(ancestor)) {
            target.insert(RigidBody::Static);
        }
    }
}

pub fn apply_mesh_components(mut commands: Commands, meshes: Query<(Entity, &Mesh3d), Without<ProcessedMesh>>, parents: Query<&ChildOf>, specs: Query<&ImportedComponents>) {
    for (entity, _mesh) in &meshes {
        let mut cursor = Some(entity);
        let mut visibility = None;
        let mut collider = None;
        let mut shadows = None;

        while let Some(current) = cursor {
            if let Ok(spec) = specs.get(current) {
                if visibility.is_none() {
                    visibility = spec.visibility_range.clone();
                }
                if collider.is_none() {
                    collider = spec.collider.clone();
                }
                if shadows.is_none() {
                    shadows = spec.shadows;
                }
                if visibility.is_some() && collider.is_some() && shadows.is_some() {
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
        if let Some(shadows) = shadows {
            if !shadows.cast {
                target.insert(NotShadowCaster);
            }
            if !shadows.receive {
                target.insert(NotShadowReceiver);
            }
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
            insert_collider(&mut target, collider, spec);
        } else {
            warn!("Could not create collider from mesh on entity {:?}", entity);
        }
    }
}

fn insert_collider(target: &mut EntityCommands, collider: Collider, spec: &ColliderSpec) {
    target.insert(collider);
    if spec.sensor {
        target.insert(Sensor);
    }
    if let Some(friction) = spec.friction {
        target.insert(Friction::new(friction));
    }
    if let Some(restitution) = spec.restitution {
        target.insert(Restitution::new(restitution));
    }
    if let Some(layers) = spec.layers {
        target.insert(layers);
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
