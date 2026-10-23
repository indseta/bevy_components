use avian3d::prelude::*;
use bevy::{animation::{AnimatedBy, AnimationTargetId}, audio::{PlaybackMode, SpatialScale, Volume}, camera::visibility::VisibilityRange, ecs::template::{EntityTemplate, Template}, gltf::Gltf, light::{CascadeShadowConfigBuilder, FogVolume, GeneratedEnvironmentMapLight, IrradianceVolume, LightProbe, NotShadowCaster, NotShadowReceiver, VolumetricLight}, pbr::Lightmap, prelude::*, scene::{EmptySceneEffect, ResolveContext, ResolveSceneError, ResolvedScene, SceneDependencies}, world_serialization::WorldAssetRoot};

pub fn setup() -> impl Scene {
    return bsn! {
        #sample_scene
        Transform
        Visibility
        @ambient_light(GlobalAmbientLight { color: Color::linear_rgb(0.9, 0.95, 1.0), brightness: 120.0, affects_lightmapped_meshes: true })
        @preload("bsn/sample_scene.glb")
        Children [
            #ground
            Transform
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh0/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#Material0/std")
            ColliderConstructor::TrimeshFromMesh
            Lightmap { image: "bsn/ground_lightmap.ktx2", uv_rect: Rect::new(0.0, 0.0, 1.0, 1.0), bicubic_sampling: true }
            RigidBody::Static
            --
            Name("crate")
            Transform { translation: Vec3::new(3.0, 1.0, 2.0), rotation: Quat::from_xyzw(0.0, 0.25881907, 0.0, 0.96592593) }
            Visibility
            Collider::cuboid(2.0, 2.0, 2.0)
            Friction::new(0.8)
            Restitution::new(0.1)
            RigidBody::Dynamic
            Children [
                Transform
                Mesh3d("bsn/sample_scene.glb#Mesh1/Primitive0")
                MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#Material1/std")
                VisibilityRange { start_margin: {20.0..25.0}, end_margin: {80.0..85.0} }
                --
                Transform
                Mesh3d("bsn/sample_scene.glb#Mesh1/Primitive1")
                MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#Material2/std")
                VisibilityRange { start_margin: {20.0..25.0}, end_margin: {80.0..85.0} }
            ]
            --
            #crate_copy
            Transform { translation: Vec3::new(6.0, 1.0, 2.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh2/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#Material1/std")
            VisibilityRange { start_margin: {20.0..25.0}, end_margin: {80.0..85.0} }
            Collider::cuboid(2.0, 2.0, 2.0)
            Friction::new(0.8)
            Restitution::new(0.1)
            RigidBody::Dynamic
            --
            #ball
            Transform { translation: Vec3::new(-3.0, 0.5, 0.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh3/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#Material3/std")
            Collider::sphere(0.5)
            RigidBody::Kinematic
            --
            #pillar
            Transform { translation: Vec3::new(0.0, 1.0, -4.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh4/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#Material4/std")
            Collider::capsule(0.4, 1.2)
            RigidBody::Static
            --
            #rock
            Transform { translation: Vec3::new(-4.0, 0.8, -4.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh5/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#Material5/std")
            ColliderConstructor::ConvexHullFromMesh
            RigidBody::Dynamic
            Mass(25.0)
            NoAutoMass
            --
            #trigger_zone
            Transform { translation: Vec3::new(0.0, 1.0, 6.0), scale: Vec3::new(2.0, 1.0, 1.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh6/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(1.0, 2.0, 3.0)
            Sensor
            CollisionLayers::from_bits(4, 2)
            RigidBody::Static
            --
            #pickup_zone
            Transform { translation: Vec3::new(4.0, 1.0, 4.0) }
            Visibility
            Collider::sphere(1.5)
            Sensor
            RigidBody::Static
            my_game::Pickup { item: "coin", amount: 5, respawn: true, weight: 0.1, spin: Vec3::new(0.0, 1.5, 0.0), glow: Color::srgba(1.0, 0.8, 0.2, 1.0) }
            --
            #player_spawn
            Transform { translation: Vec3::new(2.0, 0.0, -3.0) }
            Visibility
            my_game::PlayerSpawn
            --
            #enemy_spawn
            Transform { translation: Vec3::new(-6.0, 0.0, 6.0) }
            Visibility
            my_game::EnemySpawn
            my_game::Wave { count: 3, delay: 1.5 }
            --
            #lamp
            Transform { translation: Vec3::new(4.0, 0.25, -4.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh7/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#Material6/std")
            my_game::Glow { color: Vec3::new(1.0, 0.8, 0.6), label: "Lamp ✦" }
            my_game::Flicker(0.25)
            --
            #house
            Transform { translation: Vec3::new(10.0, 2.0, -10.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh9/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            VisibilityRange { start_margin: {80.0..85.0}, end_margin: {250.0..260.0}, use_aabb: true }
            ColliderConstructor::TrimeshFromMesh
            RigidBody::Static
            Children [
                #chimney
                Transform { translation: Vec3::new(1.0, 2.25, -1.0) }
                Visibility
                Mesh3d("bsn/sample_scene.glb#Mesh8/Primitive0")
                MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
                VisibilityRange { start_margin: {80.0..85.0}, end_margin: {250.0..260.0}, use_aabb: true }
                ColliderConstructor::TrimeshFromMesh
            ]
            --
            #tree_lod0
            Transform { translation: Vec3::new(-8.0, 1.5, -8.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh10/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            VisibilityRange { start_margin: {0.0..0.0}, end_margin: {20.0..25.0} }
            --
            #tree_lod1
            Transform { translation: Vec3::new(-8.0, 1.5, -8.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh11/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            VisibilityRange { start_margin: {20.0..25.0}, end_margin: {100.0..120.0} }
            --
            #cart
            Transform { translation: Vec3::new(-8.0, 0.5, 2.0) }
            Visibility
            RigidBody::Dynamic
            Mass(12.0)
            NoAutoMass
            Children [
                #cart_body
                Transform
                Visibility
                Mesh3d("bsn/sample_scene.glb#Mesh12/Primitive0")
                MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
                --
                #cart_handle
                Transform { translation: Vec3::new(-0.75, 0.25, 0.0) }
                Visibility
                Collider::sphere(0.25)
                --
                #cart_shape
                Transform
                Visibility
                Collider::cuboid(1.0, 1.0, 1.0)
            ]
            --
            #bouncy_ball
            Transform { translation: Vec3::new(8.0, 4.0, 8.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh13/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::sphere(0.3)
            Restitution::new(1.0)
            RigidBody::Dynamic
            --
            #ghost
            Transform { translation: Vec3::new(8.0, 0.5, 0.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh14/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(1.0, 1.0, 1.0)
            CollisionLayers::from_bits(2, 2)
            RigidBody::Dynamic
            --
            #ramp
            Transform { translation: Vec3::new(0.0, 2.0, -8.0), rotation: Quat::from_xyzw(0.0, 0.0, -0.25881907, 0.96592593) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh15/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(6.0, 0.2, 2.0)
            RigidBody::Static
            --
            #ice_block
            Transform { translation: Vec3::new(-1.1240381, 3.053109, -7.4), rotation: Quat::from_xyzw(0.0, 0.0, -0.25881907, 0.96592593) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh16/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(0.5, 0.5, 0.5)
            Friction::new(0.0)
            RigidBody::Dynamic
            --
            #rubber_block
            Transform { translation: Vec3::new(-1.1240381, 3.053109, -8.6), rotation: Quat::from_xyzw(0.0, 0.0, -0.25881907, 0.96592593) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh17/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(0.5, 0.5, 0.5)
            Friction::new(1.0)
            RigidBody::Dynamic
            --
            #water
            Transform { translation: Vec3::new(-8.0, 0.05, 8.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh18/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            NotShadowCaster
            NotShadowReceiver
            --
            #bushes
            Transform { translation: Vec3::new(6.0, 0.0, -8.0) }
            Visibility
            Children [
                #bush_a
                Transform { translation: Vec3::new(-0.5999999, 0.4, 0.0) }
                Visibility
                Mesh3d("bsn/sample_scene.glb#Mesh19/Primitive0")
                MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
                NotShadowCaster
                --
                #bush_b
                Transform { translation: Vec3::new(0.5999999, 0.6, -0.3000002) }
                Visibility
                Mesh3d("bsn/sample_scene.glb#Mesh20/Primitive0")
                MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            ]
            --
            #campfire
            Transform { translation: Vec3::new(-2.0, 0.0, 4.0) }
            Visibility
            AudioPlayer("sounds/campfire.ogg")
            PlaybackSettings { mode: PlaybackMode::Loop, volume: Volume::Linear(0.8), spatial: true, spatial_scale: {Some(SpatialScale::new(0.25))} }
            --
            #jingle
            Transform { translation: Vec3::new(0.0, 3.0, 0.0) }
            Visibility
            AudioPlayer("sounds/chime.ogg")
            PlaybackSettings { volume: Volume::Linear(0.5), paused: true }
            --
            #door_frame
            Transform { translation: Vec3::new(-2.05, 1.1, 9.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh21/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(0.1, 2.2, 0.2)
            RigidBody::Static
            --
            #door
            Transform { translation: Vec3::new(-1.5, 1.1, 9.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh22/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(1.0, 2.0, 0.1)
            RigidBody::Dynamic
            AngularVelocity(Vec3::new(0.0, 6.0, 0.0))
            --
            #door_hinge
            Transform { translation: Vec3::new(-2.0, 1.1, 9.0) }
            Visibility
            Children [
                Name("door_hinge joint")
                Transform
                @joint(#door_frame, #door, |body1, body2| RevoluteJoint::new(body1, body2).with_local_frame1(Isometry3d::new(Vec3::new(0.049999952, 0.0, 0.0), Quat::from_xyzw(0.0, 0.0, 0.0, 1.0))).with_local_frame2(Isometry3d::new(Vec3::new(-0.5, 0.0, 0.0), Quat::from_xyzw(0.0, 0.0, 0.0, 1.0))).with_hinge_axis(Vec3::new(0.0, 1.0, 0.0)).with_angle_limits(0.0, 1.5707964))
                JointDamping { linear: 0.0, angular: 0.0 }
                template(|_context| Ok(JointCollisionDisabled))
            ]
            --
            #chain_link_1
            Transform { translation: Vec3::new(-6.0, 3.7, -2.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh23/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(0.15, 0.6, 0.15)
            RigidBody::Dynamic
            --
            #chain_link_2
            Transform { translation: Vec3::new(-6.0, 3.1, -2.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh24/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(0.15, 0.6, 0.15)
            RigidBody::Dynamic
            LinearVelocity(Vec3::new(3.0, 0.0, 0.0))
            --
            #chain_top
            Transform { translation: Vec3::new(-6.0, 4.0, -2.0) }
            Visibility
            Children [
                Name("chain_top joint")
                Transform
                @joint(#chain_top_anchor, #chain_link_1, |body1, body2| SphericalJoint::new(body1, body2).with_local_frame2(Isometry3d::new(Vec3::new(0.0, 0.29999995, 0.0), Quat::from_xyzw(0.0, 0.0, 0.0, 1.0))).with_twist_axis(Vec3::new(0.0, 1.0, 0.0)))
                JointDamping { linear: 0.0, angular: 0.0 }
                template(|_context| Ok(JointCollisionDisabled))
            ]
            --
            #chain_middle
            Transform { translation: Vec3::new(-6.0, 3.4, -2.0) }
            Visibility
            Children [
                Name("chain_middle joint")
                Transform
                @joint(#chain_link_1, #chain_link_2, |body1, body2| SphericalJoint::new(body1, body2).with_local_frame1(Isometry3d::new(Vec3::new(0.0, -0.29999995, 0.0), Quat::from_xyzw(0.0, 0.0, 0.0, 1.0))).with_local_frame2(Isometry3d::new(Vec3::new(0.0, 0.3000002, 0.0), Quat::from_xyzw(0.0, 0.0, 0.0, 1.0))).with_twist_axis(Vec3::new(0.0, 1.0, 0.0)).with_swing_limits(0.0, 0.7853982))
                JointDamping { linear: 0.0, angular: 0.0 }
                template(|_context| Ok(JointCollisionDisabled))
            ]
            --
            #drawer_cabinet
            Transform { translation: Vec3::new(2.0, 0.5, 9.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh25/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(1.0, 1.0, 1.0)
            RigidBody::Static
            --
            #drawer
            Transform { translation: Vec3::new(2.0, 0.5, 9.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh26/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(0.8, 0.3, 0.8)
            RigidBody::Dynamic
            LinearVelocity(Vec3::new(2.0, 0.0, 0.0))
            Children [
                Name("drawer joint")
                Transform
                @joint(#drawer_cabinet, #drawer, |body1, body2| PrismaticJoint::new(body1, body2).with_slider_axis(Vec3::new(1.0, 0.0, 0.0)).with_limits(0.0, 0.4))
                JointDamping { linear: 0.0, angular: 0.0 }
                template(|_context| Ok(JointCollisionDisabled))
            ]
            --
            #barrel
            Transform { translation: Vec3::new(6.0, 1.5, -2.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh27/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(0.8, 1.0, 0.8)
            RigidBody::Dynamic
            --
            #barrel_lid
            Transform { translation: Vec3::new(6.0, 2.1, -2.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh28/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(0.9, 0.1, 0.9)
            RigidBody::Dynamic
            Children [
                Name("barrel_lid joint")
                Transform
                @joint(#barrel, #barrel_lid, |body1, body2| FixedJoint::new(body1, body2).with_local_frame1(Isometry3d::new(Vec3::new(0.0, 0.5999999, 0.0), Quat::from_xyzw(0.0, 0.0, 0.0, 1.0))))
                template(|_context| Ok(JointCollisionDisabled))
            ]
            --
            #balloon
            Transform { translation: Vec3::new(-2.0, 1.0, -5.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh29/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::sphere(0.3)
            RigidBody::Dynamic
            GravityScale(-0.5)
            LinearDamping(0.5)
            AngularDamping(0.2)
            --
            #spinner
            Transform { translation: Vec3::new(8.0, 1.0, -4.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh30/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(1.5, 0.2, 0.2)
            RigidBody::Kinematic
            AngularVelocity(Vec3::new(0.0, 1.5707964, 0.0))
            --
            #puck
            Transform { translation: Vec3::new(-8.0, 0.05, 5.0) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh31/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(0.5, 0.1, 0.5)
            RigidBody::Dynamic
            LockedAxes::from_bits(0b010111)
            LinearVelocity(Vec3::new(2.0, 0.0, 0.0))
            --
            #bullet
            Transform { translation: Vec3::new(-9.5, 1.0, -9.5) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh32/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::sphere(0.05)
            RigidBody::Dynamic
            GravityScale(0.0)
            SweptCcd::new().with_filter(CcdFilter::ALL)
            LinearVelocity(Vec3::new(80.0, 0.0, 0.0))
            --
            #bullet_target
            Transform { translation: Vec3::new(-6.0, 1.0, -9.5) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh33/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            Collider::cuboid(0.02, 1.0, 1.0)
            RigidBody::Dynamic
            GravityScale(0.0)
            --
            #gate
            Transform { translation: Vec3::new(3.5, 1.0, 9.5) }
            Visibility
            Mesh3d("bsn/sample_scene.glb#Mesh34/Primitive0")
            MeshMaterial3d::<StandardMaterial>("bsn/sample_scene.glb#DefaultMaterial/std")
            @animation(&[("bsn/sample_scene.glb#Animation0", 1.0, false)])
            ~AnimationTargetId::from_names([Name::new("gate")].iter())
            @animated_by(#gate)
            --
            #windmill_a
            @object_windmill()
            Transform { translation: Vec3::new(-7.0, 0.0, 9.5) }
            --
            #windmill_b
            @object_windmill()
            Transform { translation: Vec3::new(6.0, 0.0, 9.5), rotation: Quat::from_xyzw(0.0, 0.38268346, 0.0, 0.92387956), scale: Vec3::new(0.74999994, 0.75, 0.74999994) }
            --
            #fog_bank
            Transform { translation: Vec3::new(-6.0, 1.0, -6.0) }
            Visibility
            Children [
                Name("Fog Volume")
                Transform { scale: Vec3::new(6.0, 2.0, 6.0) }
                template(|_context| Ok(FogVolume { fog_color: Color::srgb(0.8, 0.85, 1.0), density_factor: 0.2, absorption: 0.3, scattering: 0.3, scattering_asymmetry: 0.6, light_tint: Color::srgb(1.0, 1.0, 1.0), light_intensity: 1.5, ..default() }))
            ]
            --
            #room_probe
            Transform { translation: Vec3::new(0.0, 2.5, 0.0) }
            Visibility
            Children [
                Name("Reflection Probe")
                Transform { scale: Vec3::new(24.0, 5.0, 24.0) }
                LightProbe { falloff: Vec3::new(0.25, 0.25, 0.25) }
                GeneratedEnvironmentMapLight { environment_map: "bsn/probe_cubemap.ktx2", intensity: 2000.0, affects_lightmapped_mesh_diffuse: true }
            ]
            --
            #gi_volume
            Transform { translation: Vec3::new(0.0, 3.0, 0.0) }
            Visibility
            Children [
                Name("Irradiance Volume")
                Transform { scale: Vec3::new(24.0, 6.0, 24.0) }
                LightProbe { falloff: Vec3::new(0.1, 0.1, 0.1) }
                IrradianceVolume { voxels: "bsn/irradiance_volume.ktx2", intensity: 500.0, affects_lightmapped_meshes: true }
            ]
            --
            #sun
            Transform { translation: Vec3::new(0.0, 10.0, 0.0), rotation: Quat::from_xyzw(-0.7071068, 0.0, 0.0, 0.7071068) }
            Visibility
            DirectionalLight { color: Color::srgb(1.0, 1.0, 1.0), illuminance: 683.0, shadow_maps_enabled: true }
            ~{CascadeShadowConfigBuilder { num_cascades: 3, minimum_distance: 0.1, maximum_distance: 80.0, first_cascade_far_bound: 8.0, overlap_proportion: 0.2 }.build()}
            VolumetricLight
            --
            #lamp_light
            Transform { translation: Vec3::new(4.0, 1.0, -4.0), rotation: Quat::from_xyzw(-0.7071068, 0.0, 0.0, 0.7071068) }
            Visibility
            PointLight { color: Color::srgb(1.0, 1.0, 1.0), intensity: 136600.0, range: 15.0, radius: 0.1, shadow_maps_enabled: true, affects_lightmapped_mesh_diffuse: false, shadow_depth_bias: 0.1, shadow_normal_bias: 0.5, shadow_map_near_z: 0.05 }
            --
            #spot_light
            Transform { translation: Vec3::new(-4.0, 4.0, 4.0), rotation: Quat::from_xyzw(-0.5, 0.0, 0.0, 0.8660254) }
            Visibility
            SpotLight { color: Color::srgb(1.0, 1.0, 1.0), intensity: 2000.0, range: 20.0, radius: 0.0, inner_angle: 0.33379424, outer_angle: 0.3926991, contact_shadows_enabled: true }
            --
            #window_light
            Transform { translation: Vec3::new(0.0, 2.0, -9.0), rotation: Quat::from_xyzw(1.0, 0.0, 0.0, 4.741422e-9) }
            Visibility
            RectLight { color: Color::linear_rgb(1.0, 1.0, 1.0), intensity: 34150.0, width: 2.0, height: 1.0 }
            --
            #chain_top_anchor
            Name("chain_top anchor")
            Transform { translation: Vec3::new(-6.0, 4.0, -2.0) }
            RigidBody::Static
        ]
    };
}

pub fn object_windmill() -> impl Scene {
    return bsn! {
        Visibility
        WorldAssetRoot("props/windmill.glb#Scene0")
    };
}

fn preload(path: &'static str) -> impl Scene {
    return Preload(path);
}

struct Preload(&'static str);

impl Scene for Preload {
    fn resolve(self, _context: &mut ResolveContext, _scene: &mut ResolvedScene) -> Result<(), ResolveSceneError> {
        return Ok(());
    }

    fn register_dependencies(&self, dependencies: &mut SceneDependencies) {
        dependencies.register::<Gltf>(self.0.into());
    }
}

fn joint<J: Component + Clone>(body1: EntityTemplate, body2: EntityTemplate, build: fn(Entity, Entity) -> J) -> impl Scene {
    return bsn! {
        template(move |context| Ok(build(body1.build_template(context)?, body2.build_template(context)?)))
    };
}

fn animation(clips: &'static [(&'static str, f32, bool)]) -> impl Scene {
    return bsn! {
        template(move |context| {
            let asset_server = context.resource::<AssetServer>().clone();
            let graph = AnimationGraph::from_clips(clips.iter().map(|(path, _speed, _repeat)| asset_server.load(*path))).0;
            return Ok(AnimationGraphHandle(context.resource_mut::<Assets<AnimationGraph>>().add(graph)));
        })
        template(move |_context| {
            let mut player = AnimationPlayer::default();
            for (index, (_path, speed, repeat)) in clips.iter().enumerate() {
                let active = player.play(AnimationNodeIndex::new(index + 1));
                active.set_speed(*speed);
                if *repeat {
                    active.repeat();
                }
            }
            return Ok(player);
        })
    };
}

fn animated_by(player: EntityTemplate) -> impl Scene {
    return bsn! {
        template(move |context| Ok(AnimatedBy(player.build_template(context)?)))
    };
}

fn ambient_light(light: GlobalAmbientLight) -> impl Scene {
    return bsn! {
        template(move |context| {
            *context.resource_mut::<GlobalAmbientLight>() = light.clone();
            return Ok(EmptySceneEffect);
        })
    };
}
