use bevy::prelude::*;

pub fn object_name(name: Option<&Name>) -> &str {
    return name.map_or("Unnamed object", Name::as_str);
}
