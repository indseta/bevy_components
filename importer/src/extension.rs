use bevy::{asset::LoadContext, gltf::{extensions::{ErasedGltfExtensionHandler, GltfExtensionHandler}, gltf}, platform::collections::{HashMap, HashSet}, prelude::*};
use crate::component::SceneAnimations;

#[derive(Clone, Default)]
pub struct AnimationExtension {
    clips: HashMap<String, Handle<AnimationClip>>,
}

impl GltfExtensionHandler for AnimationExtension {
    fn dyn_clone(&self) -> Box<dyn ErasedGltfExtensionHandler> {
        return Box::new(self.clone());
    }

    fn on_animations_collected(&mut self, _load_context: &mut LoadContext<'_>, _animations: &[Handle<AnimationClip>], named_animations: &HashMap<Box<str>, Handle<AnimationClip>>, _animation_roots: &HashSet<usize>) {
        self.clips = named_animations.iter().map(|(name, clip)| (name.to_string(), clip.clone())).collect();
    }

    fn on_scene_completed(&mut self, _load_context: &mut LoadContext<'_>, _scene: &gltf::Scene, world_root_id: Entity, scene_world: &mut World) {
        scene_world.entity_mut(world_root_id).insert(SceneAnimations(self.clips.clone()));
    }
}
