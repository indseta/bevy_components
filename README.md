# Bevy Components

Blender addon for adding Bevy components to objects and exporting levels as a single GLB, plus a Rust importer that turns them back into components in Bevy.

Requires Blender 4.2+, Bevy 0.20 and Avian 0.8.

## Install the addon

1. Download `bevy_components_<version>.zip` from the [latest release](https://github.com/indseta/bevy_components/releases/latest).
2. In Blender, open **Edit > Preferences > Get Extensions**, then **Install from Disk...** and pick the ZIP.
3. Enable **Bevy Components** if it isn't enabled already.
4. Find it under **Properties > Object > Bevy Components** or **3D Viewport > N > Bevy**.

## Install the importer

1. Download `bevy_components_importer_<version>.zip` from the same release and unzip it into your project. It extracts to a `bevy_components_importer/` folder.
2. Add it as a path dependency:

```toml
[dependencies]
bevy_components_importer = { path = "bevy_components_importer" }
```

3. Register the plugin and spawn the exported level:

```rust
use avian3d::prelude::*;
use bevy::prelude::*;
use bevy_components_importer::BlenderBevyComponentsPlugin;

fn main() {
    let mut app = App::new();
    app.add_plugins(DefaultPlugins);
    app.add_plugins(PhysicsPlugins::default());
    app.add_plugins(BlenderBevyComponentsPlugin);
    app.add_systems(Startup, setup);
    app.run();
}

fn setup(mut commands: Commands, asset_server: Res<AssetServer>) {
    commands.spawn(WorldAssetRoot(asset_server.load("level.glb#Scene0")));
}
```

## Usage

1. Select an object, press **Add Component** and pick a component, or start typing to search.
2. Each component works like a modifier: collapse it, untick it to leave it out of the export, or use its dropdown to duplicate, copy to selected, reset or reorder it.
3. Export with **File > Export > Bevy Level (.glb)**, or from the dropdown next to **Add Component**.
4. Put the GLB in your game's `assets/` folder.

Collider sizes are in Bevy coordinates (Y up). Viewport previews are editor-only and are not exported; set them up under **Overlays > Bevy Components** in the 3D Viewport header. They show while the **Bevy Components** panel in Properties is expanded, and resize handles show on the selected object. Triangle Mesh and Convex Hull colliders are built from every mesh on or under the object, and Convex Hull previews draw the hull the game gets, one per material.

## Checks

**Validate All Objects** in the dropdown next to **Add Component** lists problems in the scene, and clicking one selects its object. The export dialog lists them under **Checks**, and each component shows its own. Errors, such as invalid custom JSON, block the export. Warnings point out setups that behave differently in Bevy than they look in Blender:

- a Triangle Mesh or Convex Hull collider, or a Visibility Range, with no mesh on or under its object
- a Dynamic Rigid Body with no collider, a Rigid Body inside a moving one, and Triangle Mesh colliders on Dynamic bodies
- a collider rotated inside an unevenly scaled parent, which Avian sizes wrong
- levels of detail at the same spot whose fade distances leave a gap, overlap or don't crossfade
- Custom Component type paths that aren't Rust paths, or that repeat on one object

## Custom components

A **Custom Component** carries any of your game's components as a Rust type path and its data as JSON. To edit one with normal inputs instead, define its fields once:

1. In **Properties > Scene > Bevy Custom Components**, press **+** and double-click the new entry to set the type path, such as `my_game::Health`.
2. Add fields with a name, a type and a default. The default is used when the component is added to an object.
3. The type now appears under **Add Component**. Objects that already have it as JSON switch to the fields and keep their values.

**Define Fields** in a JSON component's dropdown does steps 1 and 2 for you from its data. Changes to a definition reach every object that uses it, and removing a definition turns its components back into JSON with the same values.

The fields export as the JSON object that serde reads into a struct with the same field names, so `serde_json::from_value` turns the data into your component:

| Field | Rust type |
| --- | --- |
| Float | `f32` |
| Integer | `i32` or another integer type |
| Boolean | `bool` |
| String | `String` |
| Vector | `Vec3`, on Bevy's axes (Y up) and not converted |
| Color | `Color`, in sRGB |

## Texture compression

The exporter can compress textures to KTX2 and embed them in the GLB, so the level stays one file but is smaller on disk and in GPU memory.

1. Install [KTX-Software](https://github.com/KhronosGroup/KTX-Software/releases) 4.4 or newer. The addon looks for `ktx` on your `PATH` and in the default install folders (`C:\Program Files\KTX-Software\bin`, `/usr/local/bin`, `/opt/homebrew/bin`). If it lives elsewhere, set its path under **Edit > Preferences > Add-ons > Bevy Components**, which also shows the version it found. KTX-Software is only needed to export, not to run your game.
2. In **File > Export > Bevy Level (.glb)**, open **Texture Compression** and pick a mode:
   - **Disabled** (default): ordinary PNG and JPEG textures.
   - **ETC1S**: smallest files, lower quality.
   - **UASTC**: best quality, larger files. **Supercompression** shrinks them on disk.
   - **Automatic**: UASTC for normal maps, metallic-roughness, occlusion and textures set to Closest interpolation, ETC1S for other color textures.

A 4K texture takes 10 to 25 seconds to encode, and Blender does not respond until the export is done. The exporter encodes up to four textures at once and caches the results in the add-on's user folder (up to 2 GB), so later exports only encode textures that changed. Leave compression Disabled while you iterate for the fastest exports.

Base color, normal, metallic-roughness, occlusion and emissive textures are converted with mipmaps and stored with the `KHR_texture_basisu` glTF extension. Samplers, UV maps, texture transforms, alpha modes and color spaces are kept, and a texture shared by several materials is stored once. Textures whose size is not a multiple of 4 pixels are scaled up to one, and the export warns when it does. Your Blender images are not changed.

Loading needs no extra code. `BlenderBevyComponentsPlugin` registers a GLB loader that converts the textures to a format the GPU supports (ASTC, BC7 or ETC2, otherwise uncompressed RGBA) and passes the file on to Bevy's glTF loader, so `asset_server.load("level.glb#Scene0")` works the same for compressed and ordinary levels. It relies on Bevy's default `ktx2` feature; `basis-universal` is not needed.

Limitations:

- Bevy logs `Duplicate AssetLoader registered for Asset type bevy_gltf::assets::Gltf with extensions ["glb"]` once at startup. That is the plugin's loader taking over `.glb` files, and the advice about `.meta` files in the warning does not apply.
- Without the plugin, Bevy 0.20 cannot load compressed levels, because it does not support `KHR_texture_basisu`.
- Only `.glb` files with embedded textures are handled.
- ETC1S smears per-pixel detail such as pixel art. Use UASTC or Automatic for those textures.

## Development

```sh
python -m unittest discover -s tests
python scripts/build_addon.py
cargo test --manifest-path importer/Cargo.toml
```

The Blender tests install the built addon into Blender's `bpy` module, build a sample level and export it. `bpy` only installs on the Python version its Blender ships with (3.11 for 4.2, 3.13 for 5.1 and later):

```sh
pip install bpy==4.2.23
python tests/blender/run.py
```

The importer tests load `importer/tests/assets/sample_level.glb` and its compressed copies `sample_level_etc1s.glb`, `sample_level_uastc.glb` and `sample_level_automatic.glb`, which `python tests/blender/sample_level.py` regenerates (it needs KTX-Software). The Blender tests fail if they no longer match a fresh export. The texture compression tests are skipped when KTX-Software is missing, unless `BEVY_COMPONENTS_REQUIRE_KTX=1` is set.

The rendering test compares compressed and uncompressed levels on a real GPU and is skipped by default. Run it with `cargo test --manifest-path importer/Cargo.toml -- --include-ignored`. On Linux without a GPU, Mesa's `mesa-vulkan-drivers` package provides one in software. Set `BEVY_COMPONENTS_RENDER_OUTPUT` to a folder to save the renders.

`addon/` holds the Blender extension and `importer/` the Rust crate. When CI passes on `main`, a GitHub release with both downloads is published whenever the version changes. The addon and importer share one version, kept in `addon/blender_manifest.toml`, `addon/__init__.py` and `importer/Cargo.toml`, and a test checks they match.

## License

See [LICENSE](LICENSE).
