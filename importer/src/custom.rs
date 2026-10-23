use bevy::{prelude::*, reflect::{TypeRegistration, TypeRegistry, serde::TypedReflectDeserializer}};
use serde::de::DeserializeSeed;
use serde_json::Value;

pub fn reflected_component(registry: &TypeRegistry, type_path: &str, data: &Value, name: Option<&Name>) -> Option<Box<dyn PartialReflect>> {
    let registration = registration(registry, type_path)?;
    if registration.data::<ReflectComponent>().is_none() {
        warn!("{} on {:?} is registered for reflection but not as a component, add #[reflect(Component)] to insert it", type_path, name);
        return None;
    }
    let value = match TypedReflectDeserializer::new(registration, registry).deserialize(data) {
        Ok(value) => value,
        Err(error) => {
            warn!("Custom component {} on {:?} does not match the Rust type, so it stays in BlenderCustomComponents: {}", type_path, name, error);
            return None;
        }
    };
    if let Some(component) = registration.data::<ReflectFromReflect>().and_then(|from_reflect| from_reflect.from_reflect(value.as_ref())) {
        return Some(component.into_partial_reflect());
    }
    let Some(mut component) = registration.data::<ReflectDefault>().map(ReflectDefault::default) else {
        warn!("Custom component {} on {:?} leaves out fields, add #[reflect(Default)] to fill them in", type_path, name);
        return None;
    };
    if let Err(error) = component.try_apply(value.as_ref()) {
        warn!("Custom component {} on {:?} does not match the Rust type, so it stays in BlenderCustomComponents: {}", type_path, name, error);
        return None;
    }
    return Some(component.into_partial_reflect());
}

fn registration<'a>(registry: &'a TypeRegistry, type_path: &str) -> Option<&'a TypeRegistration> {
    if let Some(registration) = registry.get_with_type_path(type_path) {
        return Some(registration);
    }
    let (crate_name, _) = type_path.split_once("::")?;
    let short_path = type_path.rsplit("::").next()?;
    let in_crate = |registration: &&TypeRegistration| registration.type_info().type_path_table().crate_name() == Some(crate_name);
    if !registry.is_ambiguous(short_path) {
        return registry.get_with_short_type_path(short_path).filter(in_crate);
    }
    let mut found = registry.iter().filter(|registration| registration.type_info().type_path_table().short_path() == short_path).filter(in_crate);
    let registration = found.next()?;
    return found.next().is_none().then_some(registration);
}
