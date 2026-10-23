use avian3d::prelude::{FixedJoint, JointCollisionDisabled, JointDamping, PrismaticJoint, RevoluteJoint, SphericalJoint};
use bevy::{math::Affine3A, prelude::*};
use crate::component::*;

pub fn world_pose(entity: Entity, parents: &Query<&ChildOf>, transforms: &Query<&Transform>) -> Affine3A {
    return std::iter::once(entity).chain(parents.iter_ancestors(entity)).fold(Affine3A::IDENTITY, |pose, current| transforms.get(current).map_or(Affine3A::IDENTITY, Transform::compute_affine) * pose);
}

pub fn local_frame(joint: Isometry3d, body: Affine3A) -> Isometry3d {
    let (_scale, rotation, translation) = body.to_scale_rotation_translation();
    return Isometry3d::new(translation, rotation).inverse() * joint;
}

pub fn find_body(target: &str, joint: Entity, names: &Query<(Entity, &Name), Without<Mesh3d>>, parents: &Query<&ChildOf>) -> Option<Entity> {
    let ancestors: Vec<Entity> = std::iter::once(joint).chain(parents.iter_ancestors(joint)).collect();
    return names.iter().filter(|(_, name)| name.as_str() == target).map(|(entity, _)| entity).min_by_key(|candidate| {
        let lineage: Vec<Entity> = std::iter::once(*candidate).chain(parents.iter_ancestors(*candidate)).collect();
        return ancestors.iter().position(|ancestor| lineage.contains(ancestor)).unwrap_or(usize::MAX);
    });
}

pub fn insert_joint(target: &mut EntityCommands, spec: &JointSpec, bodies: [Entity; 2], frames: [Isometry3d; 2]) {
    let [body1, body2] = bodies;
    let [frame1, frame2] = frames;
    match spec.kind {
        JointKind::Fixed => {
            target.insert(FixedJoint::new(body1, body2).with_local_frame1(frame1).with_local_frame2(frame2));
        }
        JointKind::Revolute => {
            let mut joint = RevoluteJoint::new(body1, body2).with_local_frame1(frame1).with_local_frame2(frame2).with_hinge_axis(spec.axis);
            if let Some([min, max]) = spec.angle_limits {
                joint = joint.with_angle_limits(min, max);
            }
            target.insert(joint);
        }
        JointKind::Prismatic => {
            let mut joint = PrismaticJoint::new(body1, body2).with_local_frame1(frame1).with_local_frame2(frame2).with_slider_axis(spec.axis);
            if let Some([min, max]) = spec.distance_limits {
                joint = joint.with_limits(min, max);
            }
            target.insert(joint);
        }
        JointKind::Spherical => {
            let mut joint = SphericalJoint::new(body1, body2).with_local_frame1(frame1).with_local_frame2(frame2).with_twist_axis(spec.axis);
            if let Some(swing) = spec.swing_limit {
                joint = joint.with_swing_limits(0.0, swing);
            }
            if let Some([min, max]) = spec.angle_limits {
                joint = joint.with_twist_limits(min, max);
            }
            target.insert(joint);
        }
    }
    if !matches!(spec.kind, JointKind::Fixed) {
        target.insert(JointDamping { linear: spec.linear_damping, angular: spec.angular_damping });
    }
    if !spec.collide {
        target.insert(JointCollisionDisabled);
    }
}
