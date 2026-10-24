use bevy::{image::CompressedImageFormats, prelude::*, tasks::IoTaskPool};
use serde_json::{Value, json, value::{RawValue, to_raw_value}};
use std::collections::BTreeMap;
use super::transcode::transcode;

const EXTENSION: &str = "KHR_texture_basisu";
const HEADER_LENGTH: usize = 12;
const CHUNK_HEADER_LENGTH: usize = 8;
const JSON_CHUNK: u32 = 0x4E4F534A;
const BIN_CHUNK: u32 = 0x004E4942;
const ALIGNMENT: usize = 16;

struct Glb<'a> {
    json: &'a [u8],
    binary: &'a [u8],
}

pub fn transcode_glb(bytes: &[u8], formats: CompressedImageFormats) -> Result<Option<Vec<u8>>, BevyError> {
    let Some(glb) = split_glb(bytes) else { return Ok(None); };
    if !glb.json.windows(EXTENSION.len()).any(|window| window == EXTENSION.as_bytes()) {
        return Ok(None);
    }
    let mut root: BTreeMap<String, Box<RawValue>> = serde_json::from_slice(glb.json).map_err(|error| format!("Invalid glTF JSON: {error}"))?;
    let mut textures = section(&root, "textures")?;
    let mut sources = Vec::new();
    for texture in &mut textures {
        let Some(source) = texture.pointer(&format!("/extensions/{EXTENSION}/source")).and_then(Value::as_u64) else { continue; };
        texture["source"] = json!(source);
        if !sources.contains(&source) {
            sources.push(source);
        }
    }
    if sources.is_empty() {
        return Ok(None);
    }

    let mut images = section(&root, "images")?;
    let mut views = section(&root, "bufferViews")?;
    let mut buffers = section(&root, "buffers")?;
    let mut payloads: Vec<(u64, &[u8])> = Vec::new();
    for &source in &sources {
        let image = images.get(source as usize).ok_or_else(|| format!("Missing Basis Universal image {source}"))?;
        let Some(view) = image.get("bufferView").and_then(Value::as_u64) else {
            return Err(format!("Basis Universal image {source} is not embedded in the GLB binary chunk").into());
        };
        if !payloads.iter().any(|(existing, _)| *existing == view) {
            payloads.push((view, view_data(&views, glb.binary, view).ok_or_else(|| format!("Invalid buffer view {view} for Basis Universal image {source}"))?));
        }
    }

    let transcoded = transcode_all(&payloads, formats);
    let mut binary_length = glb.binary.len().next_multiple_of(ALIGNMENT);
    let mut appended = Vec::with_capacity(transcoded.len());
    for ((view, _), result) in payloads.iter().zip(transcoded) {
        let data = result.map_err(|error| format!("Could not transcode Basis Universal texture in buffer view {view}: {error}"))?;
        for image in &mut images {
            if image.get("bufferView").and_then(Value::as_u64) == Some(*view) {
                image["bufferView"] = json!(views.len());
            }
        }
        views.push(json!({"buffer": 0, "byteOffset": binary_length, "byteLength": data.len()}));
        binary_length = (binary_length + data.len()).next_multiple_of(ALIGNMENT);
        appended.push(data);
    }
    buffers.first_mut().and_then(Value::as_object_mut).ok_or("Missing glTF buffer")?.insert("byteLength".into(), json!(binary_length));
    let mut required = section(&root, "extensionsRequired")?;
    required.retain(|name| name != EXTENSION);
    if required.is_empty() {
        root.remove("extensionsRequired");
    } else {
        set_section(&mut root, "extensionsRequired", &required)?;
    }
    set_section(&mut root, "textures", &textures)?;
    set_section(&mut root, "images", &images)?;
    set_section(&mut root, "bufferViews", &views)?;
    set_section(&mut root, "buffers", &buffers)?;
    return Ok(Some(write_glb(&root, glb.binary, &appended, binary_length)?));
}

fn section(root: &BTreeMap<String, Box<RawValue>>, key: &str) -> Result<Vec<Value>, BevyError> {
    let Some(raw) = root.get(key) else { return Ok(Vec::new()); };
    return Ok(serde_json::from_str(raw.get()).map_err(|error| format!("Invalid glTF {key}: {error}"))?);
}

fn set_section(root: &mut BTreeMap<String, Box<RawValue>>, key: &str, values: &[Value]) -> Result<(), BevyError> {
    root.insert(key.to_string(), to_raw_value(values).map_err(|error| format!("Could not write glTF {key}: {error}"))?);
    return Ok(());
}

fn split_glb(bytes: &[u8]) -> Option<Glb<'_>> {
    if bytes.len() < HEADER_LENGTH + CHUNK_HEADER_LENGTH || &bytes[..4] != b"glTF" || read_u32(bytes, 4)? != 2 {
        return None;
    }
    let length = (read_u32(bytes, 8)? as usize).min(bytes.len());
    let mut json = None;
    let mut binary: &[u8] = &[];
    let mut offset = HEADER_LENGTH;
    while offset + CHUNK_HEADER_LENGTH <= length {
        let chunk_length = read_u32(bytes, offset)? as usize;
        let chunk_type = read_u32(bytes, offset + 4)?;
        let end = (offset + CHUNK_HEADER_LENGTH).checked_add(chunk_length)?;
        let chunk = bytes.get(offset + CHUNK_HEADER_LENGTH..end)?;
        if chunk_type == JSON_CHUNK && json.is_none() {
            json = Some(chunk);
        } else if chunk_type == BIN_CHUNK && binary.is_empty() {
            binary = chunk;
        }
        offset = end;
    }
    return Some(Glb { json: json?, binary });
}

fn read_u32(bytes: &[u8], offset: usize) -> Option<u32> {
    return Some(u32::from_le_bytes(bytes.get(offset..offset + 4)?.try_into().ok()?));
}

fn view_data<'a>(views: &[Value], binary: &'a [u8], view: u64) -> Option<&'a [u8]> {
    let view = views.get(view as usize)?;
    if view.get("buffer").and_then(Value::as_u64) != Some(0) {
        return None;
    }
    let start = view.get("byteOffset").and_then(Value::as_u64).unwrap_or(0) as usize;
    let length = view.get("byteLength").and_then(Value::as_u64)? as usize;
    return binary.get(start..start.checked_add(length)?);
}

#[cfg(not(target_arch = "wasm32"))]
fn transcode_all(payloads: &[(u64, &[u8])], formats: CompressedImageFormats) -> Vec<Result<Vec<u8>, BevyError>> {
    if payloads.len() == 1 {
        return vec![transcode(payloads[0].1, formats)];
    }
    return IoTaskPool::get().scope(|scope| {
        for &(_, data) in payloads {
            scope.spawn(async move { transcode(data, formats) });
        }
    });
}

#[cfg(target_arch = "wasm32")]
fn transcode_all(payloads: &[(u64, &[u8])], formats: CompressedImageFormats) -> Vec<Result<Vec<u8>, BevyError>> {
    return payloads.iter().map(|&(_, data)| transcode(data, formats)).collect();
}

fn write_glb(root: &BTreeMap<String, Box<RawValue>>, binary: &[u8], appended: &[Vec<u8>], binary_length: usize) -> Result<Vec<u8>, BevyError> {
    let mut json = serde_json::to_vec(root).map_err(|error| format!("Could not write glTF JSON: {error}"))?;
    json.resize(json.len().next_multiple_of(4), b' ');
    let total = HEADER_LENGTH + CHUNK_HEADER_LENGTH + json.len() + CHUNK_HEADER_LENGTH + binary_length;
    let mut bytes = Vec::with_capacity(total);
    bytes.extend_from_slice(b"glTF");
    bytes.extend_from_slice(&2u32.to_le_bytes());
    bytes.extend_from_slice(&(total as u32).to_le_bytes());
    bytes.extend_from_slice(&(json.len() as u32).to_le_bytes());
    bytes.extend_from_slice(&JSON_CHUNK.to_le_bytes());
    bytes.extend_from_slice(&json);
    bytes.extend_from_slice(&(binary_length as u32).to_le_bytes());
    bytes.extend_from_slice(&BIN_CHUNK.to_le_bytes());
    let binary_start = bytes.len();
    bytes.extend_from_slice(binary);
    for data in appended {
        bytes.resize(binary_start + (bytes.len() - binary_start).next_multiple_of(ALIGNMENT), 0);
        bytes.extend_from_slice(data);
    }
    bytes.resize(total, 0);
    return Ok(bytes);
}
