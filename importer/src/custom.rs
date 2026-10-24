use bevy::{prelude::*, reflect::{TypeRegistration, TypeRegistry, serde::TypedReflectDeserializer}};
use serde::de::DeserializeSeed;
use serde_json::Value;
use crate::name::object_name;

pub fn reflected_component(registry: &TypeRegistry, type_path: &str, data: &Value, name: Option<&Name>) -> Option<Box<dyn PartialReflect>> {
    let registration = registration(registry, type_path)?;
    if registration.data::<ReflectComponent>().is_none() {
        warn!("{}: {} is registered for reflection but not as a component, add #[reflect(Component)] to insert it", object_name(name), type_path);
        return None;
    }
    let value = match TypedReflectDeserializer::new(registration, registry).deserialize(data) {
        Ok(value) => value,
        Err(error) => {
            warn!("{}: Custom component {} does not match the Rust type, so it stays in BlenderCustomComponents: {}", object_name(name), type_path, error);
            return None;
        }
    };
    if let Some(component) = registration.data::<ReflectFromReflect>().and_then(|from_reflect| from_reflect.from_reflect(value.as_ref())) {
        return Some(component.into_partial_reflect());
    }
    let Some(mut component) = registration.data::<ReflectDefault>().map(ReflectDefault::default) else {
        warn!("{}: Custom component {} leaves out fields, add #[reflect(Default)] to fill them in", object_name(name), type_path);
        return None;
    };
    if let Err(error) = component.try_apply(value.as_ref()) {
        warn!("{}: Custom component {} does not match the Rust type, so it stays in BlenderCustomComponents: {}", object_name(name), type_path, error);
        return None;
    }
    return Some(component.into_partial_reflect());
}

fn registration<'a>(registry: &'a TypeRegistry, type_path: &str) -> Option<&'a TypeRegistration> {
    if let Some(registration) = registry.get_with_type_path(type_path) {
        return Some(registration);
    }
    let crate_name = type_path.split_once("::").map(|(name, _)| name);
    let short_path = short_path(type_path);
    let in_crate = |registration: &&TypeRegistration| crate_name.is_none_or(|name| registration.type_info().type_path_table().crate_name() == Some(name));
    if !registry.is_ambiguous(&short_path) {
        return registry.get_with_short_type_path(&short_path).filter(in_crate);
    }
    let mut found = registry.iter().filter(|registration| registration.type_info().type_path_table().short_path() == short_path).filter(in_crate);
    let registration = found.next()?;
    return found.next().is_none().then_some(registration);
}

fn short_path(type_path: &str) -> String {
    let mut short = String::new();
    let mut segment = String::new();
    for character in type_path.chars() {
        if character.is_alphanumeric() || character == '_' || character == ':' {
            segment.push(character);
            continue;
        }
        short.push_str(segment.rsplit("::").next().unwrap_or_default());
        segment.clear();
        short.push(character);
    }
    short.push_str(segment.rsplit("::").next().unwrap_or_default());
    return short;
}
