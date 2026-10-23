use bevy::{prelude::*, reflect::{ReflectRef, TypeInfo, TypeRegistration, TypeRegistry, enums::VariantInfo, serde::SerializationData}};
use serde_json::{Map, Value, json};
use std::any::TypeId;

const SCHEMA_VERSION: u32 = 1;

pub fn component_schema(registry: &TypeRegistry, crates: &[String]) -> Value {
    let mut components: Vec<Value> = registry.iter().filter(|registration| registration.data::<ReflectComponent>().is_some()).filter(|registration| registration.type_info().type_path_table().crate_name().is_some_and(|name| crates.iter().any(|wanted| wanted == name))).filter_map(|registration| component(registry, registration)).collect();
    components.sort_by(|first, second| first["type_path"].as_str().cmp(&second["type_path"].as_str()));
    return json!({"version": SCHEMA_VERSION, "components": components});
}

fn component(registry: &TypeRegistry, registration: &TypeRegistration) -> Option<Value> {
    let default = registration.data::<ReflectDefault>().map(ReflectDefault::default);
    let skipped = registration.data::<SerializationData>();
    let kept = |index: usize| skipped.is_none_or(|data| !data.is_field_skipped(index));
    let (kind, fields): (&str, Vec<Value>) = match registration.type_info() {
        TypeInfo::Struct(info) => ("struct", info.iter().enumerate().filter(|(index, _)| kept(*index)).map(|(index, field)| describe_field(registry, field.name().to_string(), field.type_id(), field.type_path(), field.type_info(), default_field(registry, default.as_deref(), index, field.type_id()))).collect()),
        TypeInfo::TupleStruct(info) => ("tuple_struct", info.iter().enumerate().filter(|(index, _)| kept(*index)).map(|(index, field)| describe_field(registry, index.to_string(), field.type_id(), field.type_path(), field.type_info(), default_field(registry, default.as_deref(), index, field.type_id()))).collect()),
        _ => return None,
    };
    return Some(json!({"type_path": registration.type_info().type_path(), "kind": kind, "has_default": default.is_some(), "fields": fields}));
}

fn default_field(registry: &TypeRegistry, default: Option<&dyn Reflect>, index: usize, type_id: TypeId) -> Option<Value> {
    if let Some(default) = default {
        let field = match default.reflect_ref() {
            ReflectRef::Struct(value) => value.field_at(index),
            ReflectRef::TupleStruct(value) => value.field(index),
            _ => None,
        };
        return field.and_then(value);
    }
    let field = registry.get(type_id)?.data::<ReflectDefault>()?.default();
    return value(field.as_partial_reflect());
}

fn describe_field(registry: &TypeRegistry, name: String, type_id: TypeId, type_path: &str, type_info: Option<&TypeInfo>, default: Option<Value>) -> Value {
    let type_info = type_info.or_else(|| registry.get_type_info(type_id));
    let kind = field_type(type_id, type_info);
    let mut field = Map::new();
    field.insert("name".to_string(), Value::from(name));
    field.insert("type".to_string(), Value::from(kind));
    field.insert("rust_type".to_string(), Value::from(type_path));
    if let Some(TypeInfo::Enum(info)) = type_info.filter(|_| kind == "enum") {
        field.insert("variants".to_string(), Value::from(info.variant_names().to_vec()));
    }
    if let Some(default) = default.filter(|_| kind != "other") {
        field.insert("default".to_string(), default);
    }
    return Value::Object(field);
}

fn field_type(type_id: TypeId, type_info: Option<&TypeInfo>) -> &'static str {
    let any = |types: &[TypeId]| types.contains(&type_id);
    if any(&[TypeId::of::<f32>(), TypeId::of::<f64>()]) {
        return "float";
    }
    if any(&[TypeId::of::<i8>(), TypeId::of::<i16>(), TypeId::of::<i32>(), TypeId::of::<i64>(), TypeId::of::<isize>(), TypeId::of::<u8>(), TypeId::of::<u16>(), TypeId::of::<u32>(), TypeId::of::<u64>(), TypeId::of::<usize>()]) {
        return "int";
    }
    if any(&[TypeId::of::<bool>()]) {
        return "bool";
    }
    if any(&[TypeId::of::<String>()]) {
        return "string";
    }
    if any(&[TypeId::of::<Vec2>()]) {
        return "vector2";
    }
    if any(&[TypeId::of::<Vec3>()]) {
        return "vector";
    }
    if any(&[TypeId::of::<Color>()]) {
        return "color";
    }
    if let Some(TypeInfo::Enum(info)) = type_info && info.variant_len() > 0 && info.iter().all(|variant| matches!(variant, VariantInfo::Unit(_))) {
        return "enum";
    }
    return "other";
}

fn value(field: &dyn PartialReflect) -> Option<Value> {
    if let Some(number) = field.try_downcast_ref::<f32>() {
        return float(*number);
    }
    if let Some(number) = field.try_downcast_ref::<f64>() {
        return number.is_finite().then(|| Value::from(*number));
    }
    if let Some(number) = integer(field) {
        return Some(number);
    }
    if let Some(flag) = field.try_downcast_ref::<bool>() {
        return Some(Value::from(*flag));
    }
    if let Some(text) = field.try_downcast_ref::<String>() {
        return Some(Value::from(text.clone()));
    }
    if let Some(vector) = field.try_downcast_ref::<Vec2>() {
        return vector.to_array().into_iter().map(float).collect::<Option<Vec<Value>>>().map(Value::from);
    }
    if let Some(vector) = field.try_downcast_ref::<Vec3>() {
        return vector.to_array().into_iter().map(float).collect::<Option<Vec<Value>>>().map(Value::from);
    }
    if let Some(color) = field.try_downcast_ref::<Color>() {
        let color = color.to_srgba();
        return Some(json!({"Srgba": {"red": channel(color.red)?, "green": channel(color.green)?, "blue": channel(color.blue)?, "alpha": channel(color.alpha)?}}));
    }
    if let ReflectRef::Enum(variant) = field.reflect_ref() {
        return Some(Value::from(variant.variant_name()));
    }
    return None;
}

fn integer(field: &dyn PartialReflect) -> Option<Value> {
    return field.try_downcast_ref::<i8>().map(|number| Value::from(*number)).or_else(|| field.try_downcast_ref::<i16>().map(|number| Value::from(*number))).or_else(|| field.try_downcast_ref::<i32>().map(|number| Value::from(*number))).or_else(|| field.try_downcast_ref::<i64>().map(|number| Value::from(*number))).or_else(|| field.try_downcast_ref::<isize>().map(|number| Value::from(*number))).or_else(|| field.try_downcast_ref::<u8>().map(|number| Value::from(*number))).or_else(|| field.try_downcast_ref::<u16>().map(|number| Value::from(*number))).or_else(|| field.try_downcast_ref::<u32>().map(|number| Value::from(*number))).or_else(|| field.try_downcast_ref::<u64>().map(|number| Value::from(*number))).or_else(|| field.try_downcast_ref::<usize>().map(|number| Value::from(*number)));
}

fn float(number: f32) -> Option<Value> {
    return number.is_finite().then(|| number.to_string().parse::<f64>().ok()).flatten().map(Value::from);
}

fn channel(value: f32) -> Option<Value> {
    return float((value * 1_000_000.0).round() / 1_000_000.0);
}
