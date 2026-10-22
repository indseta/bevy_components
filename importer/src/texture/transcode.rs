use basisu::{DecodeFlags, SourceFormat, TargetFormat, Transcoder};
use bevy::{image::CompressedImageFormats, prelude::*};
use ktx2::{Format, Header, Index, LevelIndex, Reader, TransferFunction, dfd::{Basic, Block}};

const ALIGNMENT: usize = 16;

pub fn transcode(data: &[u8], formats: CompressedImageFormats) -> Result<Vec<u8>, BevyError> {
    let reader = Reader::new(data).map_err(|error| format!("Invalid KTX2 texture: {error:?}"))?;
    let transcoder = Transcoder::new(data).map_err(|error| format!("Invalid Basis Universal texture: {error:?}"))?;
    if !matches!(transcoder.source_format(), SourceFormat::Etc1s | SourceFormat::UastcLdr) {
        return Err(format!("Unsupported Basis Universal format {:?}", transcoder.source_format()).into());
    }
    if transcoder.layer_count() > 1 || transcoder.face_count() > 1 || transcoder.is_video() {
        return Err("Only 2D Basis Universal textures are supported".into());
    }
    let (width, height) = transcoder.base_dimensions();
    let target = target_format(&transcoder, formats);
    let format = texture_format(target, reader.transfer_function() == Some(TransferFunction::SRGB));
    let (basic, type_size) = Basic::from_format(format).map_err(|error| format!("Unsupported texture format {format:?}: {error:?}"))?;
    let descriptor = Block::Basic(basic).to_vec();
    let levels = transcoder.level_count() as usize;
    let descriptor_offset = Header::LENGTH + levels * LevelIndex::LENGTH;
    let descriptor_length = 4 + descriptor.len();
    let mut sizes = Vec::with_capacity(levels);
    for level in 0..levels {
        sizes.push(transcoder.output_size(level as u32, target).map_err(|error| format!("Invalid Basis Universal level {level}: {error:?}"))?);
    }
    let mut indices = vec![LevelIndex { byte_offset: 0, byte_length: 0, uncompressed_byte_length: 0 }; levels];
    let mut length = descriptor_offset + descriptor_length;
    for level in (0..levels).rev() {
        length = length.next_multiple_of(ALIGNMENT);
        indices[level] = LevelIndex { byte_offset: length as u64, byte_length: sizes[level] as u64, uncompressed_byte_length: sizes[level] as u64 };
        length += sizes[level];
    }
    let mut bytes = vec![0; length];
    for (level, index) in indices.iter().enumerate() {
        let start = index.byte_offset as usize;
        transcoder.transcode_into(level as u32, target, DecodeFlags::HIGH_QUALITY, &mut bytes[start..start + sizes[level]]).map_err(|error| format!("Could not transcode level {level} to {target:?}: {error:?}"))?;
        bytes[Header::LENGTH + level * LevelIndex::LENGTH..][..LevelIndex::LENGTH].copy_from_slice(&index.as_bytes());
    }
    let header = Header {
        format: Some(format),
        type_size,
        pixel_width: width,
        pixel_height: height,
        pixel_depth: 0,
        layer_count: 0,
        face_count: 1,
        level_count: levels as u32,
        supercompression_scheme: None,
        index: Index {
            dfd_byte_offset: descriptor_offset as u32,
            dfd_byte_length: descriptor_length as u32,
            kvd_byte_offset: 0,
            kvd_byte_length: 0,
            sgd_byte_offset: 0,
            sgd_byte_length: 0,
        },
    };
    bytes[..Header::LENGTH].copy_from_slice(&header.as_bytes());
    bytes[descriptor_offset..descriptor_offset + 4].copy_from_slice(&(descriptor_length as u32).to_le_bytes());
    bytes[descriptor_offset + 4..descriptor_offset + descriptor_length].copy_from_slice(&descriptor);
    return Ok(bytes);
}

fn target_format(transcoder: &Transcoder, formats: CompressedImageFormats) -> TargetFormat {
    let (width, height) = transcoder.base_dimensions();
    if width % 4 != 0 || height % 4 != 0 {
        return TargetFormat::Rgba32;
    }
    let etc2 = if transcoder.has_alpha() { TargetFormat::Etc2Rgba } else { TargetFormat::Etc1Rgb };
    let candidates = match transcoder.source_format() {
        SourceFormat::Etc1s => [(etc2, CompressedImageFormats::ETC2), (TargetFormat::Bc7Rgba, CompressedImageFormats::BC), (TargetFormat::Astc4x4Rgba, CompressedImageFormats::ASTC_LDR)],
        _ => [(TargetFormat::Astc4x4Rgba, CompressedImageFormats::ASTC_LDR), (TargetFormat::Bc7Rgba, CompressedImageFormats::BC), (etc2, CompressedImageFormats::ETC2)],
    };
    return candidates.into_iter().find(|(target, required)| formats.contains(*required) && transcoder.supports(*target)).map(|(target, _)| target).unwrap_or(TargetFormat::Rgba32);
}

fn texture_format(target: TargetFormat, srgb: bool) -> Format {
    return match (target, srgb) {
        (TargetFormat::Astc4x4Rgba, false) => Format::ASTC_4x4_UNORM_BLOCK,
        (TargetFormat::Astc4x4Rgba, true) => Format::ASTC_4x4_SRGB_BLOCK,
        (TargetFormat::Bc7Rgba, false) => Format::BC7_UNORM_BLOCK,
        (TargetFormat::Bc7Rgba, true) => Format::BC7_SRGB_BLOCK,
        (TargetFormat::Etc2Rgba, false) => Format::ETC2_R8G8B8A8_UNORM_BLOCK,
        (TargetFormat::Etc2Rgba, true) => Format::ETC2_R8G8B8A8_SRGB_BLOCK,
        (TargetFormat::Etc1Rgb, false) => Format::ETC2_R8G8B8_UNORM_BLOCK,
        (TargetFormat::Etc1Rgb, true) => Format::ETC2_R8G8B8_SRGB_BLOCK,
        (_, false) => Format::R8G8B8A8_UNORM,
        (_, true) => Format::R8G8B8A8_SRGB,
    };
}
