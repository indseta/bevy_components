use bevy::prelude::*;
use std::env;

pub const VIEW_VARIABLE: &str = "BEVY_COMPONENTS_VIEW";

pub fn blender_view() -> Option<Transform> {
    return parse_view(&env::var(VIEW_VARIABLE).ok()?);
}

pub fn parse_view(value: &str) -> Option<Transform> {
    let numbers: Vec<f32> = value.split(',').map(|part| part.trim().parse().ok()).collect::<Option<_>>()?;
    let [x, y, z, rotation_x, rotation_y, rotation_z, rotation_w] = numbers.as_slice() else { return None; };
    let translation = Vec3::new(*x, *y, *z);
    let rotation = Quat::from_xyzw(*rotation_x, *rotation_y, *rotation_z, *rotation_w);
    if !translation.is_finite() || !rotation.is_finite() || rotation.length_squared() < 1e-6 {
        return None;
    }
    return Some(Transform::from_translation(translation).with_rotation(rotation.normalize()));
}
