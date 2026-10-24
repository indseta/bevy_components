# Texture compression

The exporter can compress textures to KTX2 and embed them in the GLB, so the scene stays one file but is smaller on disk and in GPU memory.

1. Install [KTX-Software](https://github.com/KhronosGroup/KTX-Software/releases) 4.4 or newer. The addon looks for `ktx` on your `PATH` and in the default install folders (`C:\Program Files\KTX-Software\bin`, `/usr/local/bin`, `/opt/homebrew/bin`). If it lives elsewhere, set its path under **Edit > Preferences > Add-ons > Bevy Components**, which also shows the version it found. KTX-Software is only needed to export, not to run your game.
2. In **File > Export > Bevy Scene (.glb)**, open **Texture Compression** and pick a mode:
   - **Disabled** (default): ordinary PNG and JPEG textures.
   - **ETC1S**: smallest files, lower quality.
   - **UASTC**: best quality, larger files. **Supercompression** shrinks them on disk.
   - **Automatic**: UASTC for normal maps, metallic-roughness, occlusion and textures set to Closest interpolation, ETC1S for other color textures.

A 4K texture takes 10 to 25 seconds to encode. Blender stays usable meanwhile: the status bar shows how many textures are done, and its **X** button cancels the export and keeps the previous file. Exports started from a script still finish before the call returns. The exporter encodes up to four textures at once at a lower CPU priority and caches the results in the add-on's user folder (up to 2 GB), so later exports only encode textures that changed. Leave compression Disabled while you iterate for the fastest exports.

Base color, normal, metallic-roughness, occlusion and emissive textures are converted with mipmaps and stored with the `KHR_texture_basisu` glTF extension. Samplers, UV maps, texture transforms, alpha modes and color spaces are kept, and a texture shared by several materials is stored once. Textures whose size is not a multiple of 4 pixels are scaled up to one, and the export warns when it does. Your Blender images are not changed.

Loading needs no extra code. `BlenderBevyComponentsPlugin` registers a GLB loader that converts the textures to a format the GPU supports (ASTC, BC7 or ETC2, otherwise uncompressed RGBA) and passes the file on to Bevy's glTF loader, so `asset_server.load("scene.glb#Scene0")` works the same for compressed and ordinary scenes. It relies on Bevy's default `ktx2` feature; `basis-universal` is not needed.

## Limitations

- Bevy logs `Duplicate AssetLoader registered for Asset type bevy_gltf::assets::Gltf with extensions ["glb"]` once at startup. That is the plugin's loader taking over `.glb` files, and the advice about `.meta` files in the warning does not apply.
- Without the plugin, Bevy 0.20 cannot load compressed scenes, because it does not support `KHR_texture_basisu`.
- Only `.glb` files with embedded textures are handled.
- ETC1S smears per-pixel detail such as pixel art. Use UASTC or Automatic for those textures.
