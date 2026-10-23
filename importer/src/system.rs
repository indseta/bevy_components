use avian3d::prelude::{AngularDamping, AngularVelocity, CcdFilter, Collider, CollisionLayers, Friction, GravityScale, LayerMask, LinearDamping, LinearVelocity, LockedAxes, Mass, NoAutoMass, Restitution, RigidBody, Sensor, SweptCcd};
use bevy::{audio::{PlaybackMode, SpatialScale, Volume}, camera::visibility::VisibilityRange, gltf::GltfExtras, light::{NotShadowCaster, NotShadowReceiver}, math::Affine3A, prelude::*};
use serde_json::Value;
use crate::{component::*, data::*, joint::*};

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
        let mut audio = None;
        let mut joint = None;

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
                ExportedComponent::RigidBody { kind, mass, gravity_scale, linear_damping, angular_damping, lock_translation, lock_rotation, ccd, linear_velocity, angular_velocity } => {
                    let body = match kind.as_str() {
                        "static" => RigidBody::Static,
                        "dynamic" => RigidBody::Dynamic,
                        "kinematic" => RigidBody::Kinematic,
                        _ => {
                            warn!("Unsupported rigid body type on {:?}", name);
                            continue;
                        }
                    };
                    let mass = match mass {
                        Some(value) if value <= 0.0 => {
                            warn!("Invalid mass on {:?}", name);
                            None
                        }
                        _ => mass,
                    };
                    let ccd = match ccd.as_deref() {
                        None | Some("default") => None,
                        Some("all") => Some(SweptCcd::new().with_filter(CcdFilter::ALL)),
                        Some("off") => Some(SweptCcd::new().with_filter(CcdFilter::NONE)),
                        Some(_) => {
                            warn!("Unsupported continuous collision setting on {:?}", name);
                            None
                        }
                    };
                    let locked_axes = (lock_translation.is_some() || lock_rotation.is_some()).then(|| locked_axes(lock_translation.unwrap_or_default(), lock_rotation.unwrap_or_default()));
                    let linear_velocity = linear_velocity.map(|velocity| unlocked(velocity, lock_translation));
                    let angular_velocity = angular_velocity.map(|velocity| unlocked(velocity, lock_rotation));
                    rigid_body = Some(RigidBodySpec { body, mass, gravity_scale, linear_damping, angular_damping, locked_axes, ccd, linear_velocity, angular_velocity });
                }
                ExportedComponent::Joint { kind, body1, body2, axis, angle_limits, distance_limits, swing_limit, linear_damping, angular_damping, collide } => {
                    let Some(kind) = JointKind::from_str(&kind) else {
                        warn!("Unsupported joint type on {:?}", name);
                        continue;
                    };
                    if body1.is_none() && body2.is_none() {
                        warn!("Joint on {:?} connects no bodies", name);
                        continue;
                    }
                    let axis = axis.map(Vec3::from).and_then(Vec3::try_normalize).unwrap_or(Vec3::Y);
                    joint = Some(JointSpec { kind, body1, body2, axis, angle_limits, distance_limits, swing_limit, linear_damping: linear_damping.unwrap_or_default(), angular_damping: angular_damping.unwrap_or_default(), collide });
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
        if let Some(spec) = rigid_body {
            insert_rigid_body(&mut commands.entity(entity), &spec);
        } else if has_collider {
            commands.entity(entity).insert(DefaultStaticBody);
        }
        if let Some(spec) = joint {
            commands.entity(entity).insert(PendingJoint(spec));
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

pub fn build_joints(mut commands: Commands, joints: Query<(Entity, &PendingJoint, Option<&Name>)>, names: Query<(Entity, &Name), Without<Mesh3d>>, parents: Query<&ChildOf>, transforms: Query<&Transform>, bodies: Query<(), With<RigidBody>>) {
    for (entity, pending, name) in &joints {
        commands.entity(entity).remove::<PendingJoint>();
        let spec = &pending.0;
        let label = name.map_or("joint".to_string(), |name| name.as_str().to_string());
        let pose = world_pose(entity, &parents, &transforms);
        let (_scale, rotation, translation) = pose.to_scale_rotation_translation();
        let joint_pose = Isometry3d::new(translation, rotation);
        let mut ends = Vec::new();
        for target in [&spec.body1, &spec.body2] {
            let Some(target) = target else {
                ends.push(None);
                continue;
            };
            let Some(body) = find_body(target, entity, &names, &parents) else {
                warn!("Joint on {:?} found no object named {}", name, target);
                break;
            };
            if !bodies.contains(body) {
                warn!("Joint on {:?} connects {}, which has no rigid body", name, target);
            }
            ends.push(Some(body));
        }
        if ends.len() < 2 {
            continue;
        }
        let mut connected = [Entity::PLACEHOLDER; 2];
        let mut frames = [Isometry3d::IDENTITY; 2];
        for (index, end) in ends.into_iter().enumerate() {
            if let Some(body) = end {
                connected[index] = body;
                frames[index] = local_frame(joint_pose, world_pose(body, &parents, &transforms));
                continue;
            }
            let root = parents.iter_ancestors(entity).last();
            let anchor = Affine3A::from_rotation_translation(rotation, translation);
            let local = root.map_or(anchor, |root| world_pose(root, &parents, &transforms).inverse() * anchor);
            let mut spawned = commands.spawn((Name::new(format!("{label} anchor")), RigidBody::Static, Transform::from_matrix(Mat4::from(local))));
            if let Some(root) = root {
                spawned.insert(ChildOf(root));
            }
            connected[index] = spawned.id();
        }
        let mut joint = commands.spawn((Name::new(format!("{label} joint")), ChildOf(entity)));
        insert_joint(&mut joint, spec, connected, frames);
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

fn insert_rigid_body(target: &mut EntityCommands, spec: &RigidBodySpec) {
    target.insert(spec.body);
    if let Some(mass) = spec.mass {
        target.insert((Mass(mass), NoAutoMass));
    }
    if let Some(scale) = spec.gravity_scale {
        target.insert(GravityScale(scale));
    }
    if let Some(damping) = spec.linear_damping {
        target.insert(LinearDamping(damping));
    }
    if let Some(damping) = spec.angular_damping {
        target.insert(AngularDamping(damping));
    }
    if let Some(axes) = spec.locked_axes {
        target.insert(axes);
    }
    if let Some(ccd) = spec.ccd {
        target.insert(ccd);
    }
    if let Some(velocity) = spec.linear_velocity {
        target.insert(LinearVelocity(velocity));
    }
    if let Some(velocity) = spec.angular_velocity {
        target.insert(AngularVelocity(velocity));
    }
}

fn locked_axes(translation: [bool; 3], rotation: [bool; 3]) -> LockedAxes {
    return LockedAxes::from_bits(translation.into_iter().chain(rotation).fold(0, |bits, locked| (bits << 1) | u8::from(locked)));
}

fn unlocked(vector: [f32; 3], locks: Option<[bool; 3]>) -> Vec3 {
    let locks = locks.unwrap_or_default();
    return Vec3::from_array(std::array::from_fn(|axis| if locks[axis] { 0.0 } else { vector[axis] }));
}

fn primitive_collider(spec: &ColliderSpec) -> Option<Collider> {
    return match spec.shape {
        ColliderShape::Cuboid => Some(Collider::cuboid(spec.size[0], spec.size[1], spec.size[2])),
        ColliderShape::Sphere => Some(Collider::sphere(spec.radius)),
        ColliderShape::Capsule => Some(Collider::capsule(spec.radius, spec.height)),
        ColliderShape::Trimesh | ColliderShape::Convex => None,
    };
}
