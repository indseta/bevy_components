use avian3d::prelude::{AngularDamping, AngularVelocity, CcdFilter, Collider, CollisionEventsEnabled, CollisionLayers, Friction, GravityScale, LayerMask, LinearDamping, LinearVelocity, LockedAxes, Mass, NoAutoMass, Restitution, RigidBody, Sensor, SweptCcd};
use bevy::{asset::AssetPath, audio::{PlaybackMode, SpatialScale, Volume}, camera::visibility::VisibilityRange, ecs::reflect::ReflectCommandExt, gltf::GltfExtras, light::{FogVolume, GeneratedEnvironmentMapLight, IrradianceVolume, LightProbe, NotShadowCaster, NotShadowReceiver, ParallaxCorrection}, math::Affine3A, platform::collections::HashMap, prelude::*};
use serde_json::Value;
use std::iter;
use crate::{component::*, custom, data::*, joint::*, light, lightmap, texture::GltfTextures};

const MAX_CUBEMAP_SIZE: u32 = 8192;
const CUBE_FACES: u32 = 6;

pub fn read_gltf_components(mut commands: Commands, nodes: Query<(Entity, &GltfExtras, Option<&Name>, Option<&GltfTextures>), Without<DecodedGltfExtras>>, asset_server: Res<AssetServer>, audio_sources: Option<Res<Assets<AudioSource>>>, registry: Res<AppTypeRegistry>) {
    let registry = registry.read();
    for (entity, extras, name, textures) in &nodes {
        commands.entity(entity).insert(DecodedGltfExtras);
        let Some(exported) = decode_extras(&extras.value, name) else { continue; };

        let mut components = ImportedComponents::default();
        let mut custom = BlenderCustomComponents::default();
        let mut reflected = Vec::new();
        let mut rigid_body = None;
        let mut audio = None;
        let mut joint = None;
        let mut reference = None;
        let mut animation = None;

        for component in exported.components {
            match component {
                ExportedComponent::VisibilityRange { start, end, use_aabb } => {
                    if start[0] <= start[1] && start[1] <= end[0] && end[0] <= end[1] {
                        components.visibility_range = Some(VisibilityRange { start_margin: start[0]..start[1], end_margin: end[0]..end[1], use_aabb });
                    } else {
                        warn!("Invalid visibility range on {:?}", name);
                    }
                }
                ExportedComponent::Collider { shape, size, radius, height, offset, sensor, events, collision_only, friction, restitution, memberships, filters } => {
                    if let Some(shape) = ColliderShape::from_str(&shape) {
                        let layers = (memberships.is_some() || filters.is_some()).then(|| CollisionLayers::from_bits(memberships.unwrap_or(LayerMask::DEFAULT.0), filters.unwrap_or(LayerMask::ALL.0)));
                        let offset = offset.map_or(Vec3::ZERO, Vec3::from_array);
                        components.collider = Some(ColliderSpec { shape, size, radius, height, offset, sensor, events: events.unwrap_or_default(), collision_only: collision_only.unwrap_or_default(), friction, restitution, layers });
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
                ExportedComponent::Navigation { kind, cost } => {
                    let cost = match cost {
                        Some(value) if value <= 0.0 => {
                            warn!("Invalid navigation cost on {:?}", name);
                            1.0
                        }
                        _ => cost.unwrap_or(1.0),
                    };
                    components.navigation = match kind.as_str() {
                        "walkable" => Some(NavigationRole::Walkable(cost)),
                        "obstacle" => Some(NavigationRole::Obstacle),
                        "ignored" => Some(NavigationRole::Ignored),
                        _ => {
                            warn!("Unsupported navigation type on {:?}", name);
                            continue;
                        }
                    };
                }
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
                ExportedComponent::Light(light) => {
                    if let Some(spec) = light::light_spec(light, name) {
                        commands.entity(entity).insert(light::PendingLight(spec));
                    }
                }
                ExportedComponent::AmbientLight(_) => warn!("Ambient light belongs on the scene, not on {:?}", name),
                ExportedComponent::Custom { type_path, data } => match custom::reflected_component(&registry, &type_path, &data, name) {
                    Some(component) => reflected.push(component),
                    None => custom.0.push(BlenderCustomComponent { type_path, data }),
                },
                ExportedComponent::SceneReference { path, scene } => reference = Some(PendingSceneReference { path, scene }),
                ExportedComponent::Animation { clip, repeat, speed } => animation = Some(PendingAnimation(AnimationSpec { clip, repeat, speed })),
                ExportedComponent::FogVolume { size, color, density, absorption, scattering, anisotropy, light_tint, light_intensity } => {
                    commands.spawn((Name::new("Fog Volume"), FogVolume { fog_color: Color::srgb_from_array(color), density_factor: density, absorption, scattering, scattering_asymmetry: anisotropy, light_tint: Color::srgb_from_array(light_tint), light_intensity, ..default() }, Transform::from_scale(Vec3::from_array(size)), ChildOf(entity)));
                }
                ExportedComponent::ReflectionProbe { size, falloff, intensity, parallax_correction, texture } => {
                    let Some(cubemap) = texture_handle(textures, texture) else {
                        warn!("No cubemap embedded for the reflection probe on {:?}", name);
                        continue;
                    };
                    let mut probe = commands.spawn((Name::new("Reflection Probe"), LightProbe { falloff: Vec3::from_array(falloff) }, PendingReflectionProbe { cubemap, intensity }, Transform::from_scale(Vec3::from_array(size)), ChildOf(entity)));
                    if !parallax_correction {
                        probe.insert(ParallaxCorrection::None);
                    }
                }
                ExportedComponent::IrradianceVolume { size, falloff, intensity, texture } => {
                    let Some(voxels) = texture_handle(textures, texture) else {
                        warn!("No voxel texture embedded for the irradiance volume on {:?}", name);
                        continue;
                    };
                    commands.spawn((Name::new("Irradiance Volume"), LightProbe { falloff: Vec3::from_array(falloff) }, IrradianceVolume { voxels, intensity, affects_lightmapped_meshes: true }, Transform::from_scale(Vec3::from_array(size)), ChildOf(entity)));
                }
                ExportedComponent::Lightmap { bicubic, texture } => {
                    let Some(image) = texture_handle(textures, texture) else {
                        warn!("No lightmap embedded for {:?}", name);
                        continue;
                    };
                    commands.entity(entity).insert(lightmap::PendingLightmap { image, bicubic });
                }
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
        for component in reflected {
            commands.entity(entity).insert_reflect(component);
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
        if let Some(reference) = reference {
            commands.entity(entity).insert(reference);
        }
        if let Some(animation) = animation {
            commands.entity(entity).insert(animation);
        }
    }
}

pub fn apply_reflection_probes(mut commands: Commands, probes: Query<(Entity, &PendingReflectionProbe)>, images: Res<Assets<Image>>) {
    for (entity, pending) in &probes {
        let Some(image) = images.get(&pending.cubemap) else { continue; };
        let size = image.texture_descriptor.size;
        let mut target = commands.entity(entity);
        target.remove::<PendingReflectionProbe>();
        if size.depth_or_array_layers != CUBE_FACES || size.width != size.height || !size.width.is_power_of_two() || size.width > MAX_CUBEMAP_SIZE {
            warn!("Reflection probe cubemap is {}x{}x{}, but Bevy only filters square cubemaps whose size is a power of two", size.width, size.height, size.depth_or_array_layers);
            continue;
        }
        target.insert(GeneratedEnvironmentMapLight { environment_map: pending.cubemap.clone(), intensity: pending.intensity, ..default() });
    }
}

pub fn decode_extras(value: &str, name: Option<&Name>) -> Option<ExportedData> {
    let Ok(outer) = serde_json::from_str::<Value>(value) else {
        warn!("Invalid glTF extras on {:?}", name);
        return None;
    };
    let serialized = outer.get("bevy_components").and_then(Value::as_str)?;
    let Ok(exported) = serde_json::from_str::<ExportedData>(serialized) else {
        warn!("Invalid Bevy component metadata on {:?}", name);
        return None;
    };
    if exported.version != 1 {
        warn!("Unsupported Blender Bevy component version {} on {:?}", exported.version, name);
        return None;
    }
    return Some(exported);
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

pub fn build_joints(mut commands: Commands, joints: Query<(Entity, &PendingJoint, Option<&Name>)>, names: Query<(Entity, &Name), Without<Mesh3d>>, parents: Query<&ChildOf>, transforms: Query<&Transform>, bodies: Query<(), With<RigidBody>>, roots: Query<(), With<WorldAssetRoot>>) {
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
            let root = parents.iter_ancestors(entity).find(|ancestor| parents.get(*ancestor).is_ok_and(|parent| roots.contains(parent.parent()))).or_else(|| parents.iter_ancestors(entity).last());
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

pub fn spawn_scene_references(mut commands: Commands, references: Query<(Entity, &PendingSceneReference, Option<&Name>)>, parents: Query<&ChildOf>, roots: Query<&WorldAssetRoot>, asset_server: Res<AssetServer>) {
    for (entity, reference, name) in &references {
        commands.entity(entity).remove::<PendingSceneReference>();
        let scenes: Vec<AssetPath<'static>> = parents.iter_ancestors(entity).filter_map(|ancestor| roots.get(ancestor).ok()?.0.path().cloned()).collect();
        let base = scenes.first().map(|scene| scene.without_label().clone_owned()).unwrap_or_default();
        let Ok(path) = base.resolve_embed_str(&reference.path) else {
            warn!("Invalid scene reference path {} on {:?}", reference.path, name);
            continue;
        };
        let path = path.with_label(GltfAssetLabel::Scene(reference.scene).to_string());
        if scenes.contains(&path) {
            warn!("Scene reference on {:?} would spawn {} inside itself", name, path);
            continue;
        }
        commands.entity(entity).insert(WorldAssetRoot(asset_server.load(path)));
    }
}

pub fn play_animations(mut commands: Commands, animations: Query<(Entity, &PendingAnimation, Option<&Name>)>, parents: Query<&ChildOf>, scenes: Query<&SceneAnimations>, mut players: Query<(&mut AnimationPlayer, Option<&AnimationGraphHandle>)>, mut graphs: ResMut<Assets<AnimationGraph>>) {
    let mut created = HashMap::new();
    for (entity, pending, name) in &animations {
        commands.entity(entity).remove::<PendingAnimation>();
        let spec = &pending.0;
        let mut player = None;
        let mut clips = None;
        for current in iter::once(entity).chain(parents.iter_ancestors(entity)) {
            if player.is_none() && players.contains(current) {
                player = Some(current);
            }
            if let Ok(scene) = scenes.get(current) {
                clips = Some(scene);
                break;
            }
        }
        let Some(clips) = clips else {
            warn!("Animation on {:?} is not part of a glTF scene", name);
            continue;
        };
        let Some(clip) = clips.0.get(&spec.clip) else {
            warn!("No animation named {} for {:?}", spec.clip, name);
            continue;
        };
        let Some(player) = player else {
            warn!("Animation {} does not animate {:?} or its parents", spec.clip, name);
            continue;
        };
        let Ok((mut animation_player, graph)) = players.get_mut(player) else { continue; };
        let handle = match graph.map(|graph| graph.0.clone()).or_else(|| created.get(&player).cloned()) {
            Some(handle) => handle,
            None => {
                let handle = graphs.add(AnimationGraph::new());
                commands.entity(player).insert(AnimationGraphHandle(handle.clone()));
                created.insert(player, handle.clone());
                handle
            }
        };
        let Some(mut graph) = graphs.get_mut(&handle) else { continue; };
        let root = graph.root;
        let node = graph.add_clip(clip.clone(), 1.0, root);
        let active = animation_player.play(node);
        active.set_speed(spec.speed);
        if spec.repeat {
            active.repeat();
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
        if let Some(spec) = collider {
            if spec.collision_only {
                target.insert(Visibility::Hidden);
            }
            if spec.shape.is_mesh() {
                target.insert(PendingMeshCollider(spec));
            }
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

pub fn apply_navigation(mut commands: Commands, meshes: Query<Entity, Added<Mesh3d>>, nodes: Query<(Entity, &ImportedComponents), Added<ImportedComponents>>, parents: Query<&ChildOf>, specs: Query<&ImportedComponents>) {
    let colliders = nodes.iter().filter(|(_, components)| components.collider.as_ref().is_some_and(|spec| !spec.shape.is_mesh())).map(|(entity, _)| entity);
    for entity in meshes.iter().chain(colliders) {
        match iter::once(entity).chain(parents.iter_ancestors(entity)).find_map(|current| specs.get(current).ok()?.navigation) {
            Some(NavigationRole::Walkable(cost)) => {
                commands.entity(entity).insert(NavigationWalkable { cost });
            }
            Some(NavigationRole::Obstacle) => {
                commands.entity(entity).insert(NavigationObstacle);
            }
            Some(NavigationRole::Ignored) | None => {}
        }
    }
}

fn insert_collider(target: &mut EntityCommands, collider: Collider, spec: &ColliderSpec) {
    if spec.events {
        target.insert(CollisionEventsEnabled);
    }
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

fn texture_handle(textures: Option<&GltfTextures>, index: Option<usize>) -> Option<Handle<Image>> {
    return textures?.0.get(index?).cloned();
}

fn primitive_collider(spec: &ColliderSpec) -> Option<Collider> {
    let collider = match spec.shape {
        ColliderShape::Cuboid => Collider::cuboid(spec.size[0], spec.size[1], spec.size[2]),
        ColliderShape::Sphere => Collider::sphere(spec.radius),
        ColliderShape::Capsule => Collider::capsule(spec.radius, spec.height),
        ColliderShape::Trimesh | ColliderShape::Convex => return None,
    };
    if spec.offset == Vec3::ZERO {
        return Some(collider);
    }
    return Some(Collider::compound(vec![(spec.offset, Quat::IDENTITY, collider)]));
}
