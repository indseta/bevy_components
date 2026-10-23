use bevy::{gltf::GltfSceneExtras, light::{CascadeShadowConfig, CascadeShadowConfigBuilder, VolumetricLight}, pbr::MAX_CASCADES_PER_LIGHT, prelude::*};
use crate::{data::*, system::decode_extras};
use super::component::*;

pub fn light_spec(light: ExportedLight, name: Option<&Name>) -> Option<LightSpec> {
    let Some(kind) = LightKind::from_str(&light.kind) else {
        warn!("Unsupported light type on {:?}", name);
        return None;
    };
    let cascades = light.cascades.as_ref().and_then(|exported| {
        let built = cascades(exported);
        if built.is_none() {
            warn!("Invalid shadow cascades on {:?}", name);
        }
        return built;
    });
    let [red, green, blue] = light.color.unwrap_or([1.0, 1.0, 1.0]);
    return Some(LightSpec { kind, intensity: light.intensity, radius: light.radius, range: light.range, color: Color::linear_rgb(red, green, blue), size: light.size.map_or(Vec2::ONE, Vec2::from), shadows: light.shadows, contact_shadows: light.contact_shadows, volumetric: light.volumetric, baked: light.baked, depth_bias: light.depth_bias, normal_bias: light.normal_bias, near_clip: light.near_clip, cascades });
}

fn cascades(exported: &ExportedCascades) -> Option<CascadeShadowConfig> {
    let valid = (1..=MAX_CASCADES_PER_LIGHT).contains(&exported.count) && exported.minimum_distance >= 0.0 && exported.maximum_distance > exported.minimum_distance && (exported.count == 1 || exported.minimum_distance < exported.first_cascade_far_bound) && (0.0..1.0).contains(&exported.overlap_proportion);
    if !valid {
        return None;
    }
    return Some(CascadeShadowConfigBuilder { num_cascades: exported.count, minimum_distance: exported.minimum_distance, maximum_distance: exported.maximum_distance, first_cascade_far_bound: exported.first_cascade_far_bound, overlap_proportion: exported.overlap_proportion }.build());
}

pub fn apply_lights(mut commands: Commands, nodes: Query<(Entity, &PendingLight, Option<&Children>, Option<&Name>)>, mut point_lights: Query<&mut PointLight>, mut spot_lights: Query<&mut SpotLight>, mut directional_lights: Query<&mut DirectionalLight>) {
    for (entity, pending, children, name) in &nodes {
        let spec = &pending.0;
        commands.entity(entity).remove::<PendingLight>();
        if spec.kind == LightKind::Area {
            commands.entity(entity).insert(rect_light(spec));
            continue;
        }
        let Some(light) = children.into_iter().flatten().copied().find(|child| point_lights.contains(*child) || spot_lights.contains(*child) || directional_lights.contains(*child)) else {
            warn!("No glTF light found for the light settings on {:?}", name);
            continue;
        };
        if let Ok(mut point) = point_lights.get_mut(light) {
            point.intensity = spec.intensity.unwrap_or(point.intensity);
            point.radius = spec.radius.unwrap_or(point.radius);
            point.shadow_maps_enabled = spec.shadows;
            point.contact_shadows_enabled = spec.contact_shadows;
            point.affects_lightmapped_mesh_diffuse = !spec.baked;
            point.shadow_depth_bias = spec.depth_bias.unwrap_or(point.shadow_depth_bias);
            point.shadow_normal_bias = spec.normal_bias.unwrap_or(point.shadow_normal_bias);
            point.shadow_map_near_z = spec.near_clip.unwrap_or(point.shadow_map_near_z);
        }
        if let Ok(mut spot) = spot_lights.get_mut(light) {
            spot.intensity = spec.intensity.unwrap_or(spot.intensity);
            spot.radius = spec.radius.unwrap_or(spot.radius);
            spot.shadow_maps_enabled = spec.shadows;
            spot.contact_shadows_enabled = spec.contact_shadows;
            spot.affects_lightmapped_mesh_diffuse = !spec.baked;
            spot.shadow_depth_bias = spec.depth_bias.unwrap_or(spot.shadow_depth_bias);
            spot.shadow_normal_bias = spec.normal_bias.unwrap_or(spot.shadow_normal_bias);
            spot.shadow_map_near_z = spec.near_clip.unwrap_or(spot.shadow_map_near_z);
        }
        if let Ok(mut directional) = directional_lights.get_mut(light) {
            directional.illuminance = spec.intensity.unwrap_or(directional.illuminance);
            directional.shadow_maps_enabled = spec.shadows;
            directional.contact_shadows_enabled = spec.contact_shadows;
            directional.affects_lightmapped_mesh_diffuse = !spec.baked;
            directional.shadow_depth_bias = spec.depth_bias.unwrap_or(directional.shadow_depth_bias);
            directional.shadow_normal_bias = spec.normal_bias.unwrap_or(directional.shadow_normal_bias);
            if let Some(cascades) = &spec.cascades {
                commands.entity(light).insert(cascades.clone());
            }
        }
        if spec.volumetric {
            commands.entity(light).insert(VolumetricLight);
        }
    }
}

fn rect_light(spec: &LightSpec) -> RectLight {
    let defaults = RectLight::default();
    return RectLight { color: spec.color, intensity: spec.intensity.unwrap_or(defaults.intensity), range: spec.range.unwrap_or(defaults.range), width: spec.size.x, height: spec.size.y };
}

pub fn apply_ambient_light(mut commands: Commands, scenes: Query<(Entity, &GltfSceneExtras, Option<&Name>), Without<DecodedGltfSceneExtras>>) {
    for (entity, extras, name) in &scenes {
        commands.entity(entity).insert(DecodedGltfSceneExtras);
        let Some(exported) = decode_extras(&extras.value, name) else { continue; };
        for component in exported.components {
            if let ExportedComponent::AmbientLight(ambient) = component {
                let [red, green, blue] = ambient.color;
                commands.insert_resource(GlobalAmbientLight { color: Color::linear_rgb(red, green, blue), brightness: ambient.brightness, affects_lightmapped_meshes: !ambient.baked });
            }
        }
    }
}
