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

**Shadows** (under Rendering) stops the meshes on and under an object from casting or receiving shadows. **Audio Player** (under Audio) plays a sound from your game's `assets` folder, such as `sounds/fire.ogg`, and its folder button fills in that path from a picked file. Spatial sounds play at full volume within their Distance and fade beyond it. The viewport shows that distance and the one where the sound is down to 1% as spheres, with an arrow to drag the distance.

**Joint** (under Physics) connects two bodies with an Avian Fixed, Hinge, Slider or Ball joint. Put it on an empty at the pivot, or on one of the bodies, and pick Body 1 and Body 2 from objects with a Rigid Body or Collider. Leave one empty to pin the other to that spot in the level. The object's position and its Axis set the pivot, and limits count from where the bodies sit in Blender.

**Scene Reference** (under Scene) spawns a scene from another glTF file at the object, like a prefab: export the prop as its own Bevy level, then point an empty at it. The path is stored relative to the exported level, so keep both in your game's `assets` folder. The viewport draws the bounds of the referenced scene. **Animation** (under Animation) plays an action when the level loads, looping or once, at a speed where 1 matches Blender. It starts out with the object's active action. Keep **Include Animations** on in the export; each clip starts at its first keyframe.

Collider sizes are in Bevy coordinates (Y up). Colliders also set friction, restitution and collision layers 0 to 31, the same numbers as Avian's layer bits. Dynamic Rigid Bodies can set a total mass, gravity scale, damping, locked axes and continuous collision, and moving bodies can start with a velocity and spin. Viewport previews are editor-only and are not exported; set them up under **Overlays > Bevy Components** in the 3D Viewport header. They show while the **Bevy Components** panel in Properties is expanded, and resize handles show on the selected object. Joints show their axis and limits, and also show when one of their bodies is selected. Arrows show the velocity bodies start with. Triangle Mesh and Convex Hull colliders are built from every mesh on or under the object, and Convex Hull previews draw the hull the game gets, one per material.

## Checks

**Validate All Objects** in the dropdown next to **Add Component** lists problems in the scene, and clicking one selects its object. The export dialog lists them under **Checks**, and each component shows its own. Errors, such as invalid custom JSON, a joint limit whose Min is above its Max, shadow cascade distances out of order, or a light probe file that is missing or that Bevy cannot use, block the export. Warnings point out setups that behave differently in Bevy than they look in Blender:

- a Triangle Mesh or Convex Hull collider, or a Visibility Range, with no mesh on or under its object
- a Dynamic Rigid Body with no collider, a Rigid Body inside a moving one, and Triangle Mesh colliders on Dynamic bodies
- a collider rotated inside an unevenly scaled parent, which Avian sizes wrong
- a Dynamic body with every axis locked
- a Joint with no bodies, the same body twice, only static bodies, or a body that has no Rigid Body or Collider, is part of another body or is left out of the export
- levels of detail at the same spot whose fade distances leave a gap, overlap or don't crossfade
- Custom Component type paths that aren't Rust paths, or that repeat on one object
- Shadows with no mesh on or under its object
- an Audio Player with no sound, a path outside the `assets` folder, or a file type Bevy cannot play
- a Scene Reference to a missing or non-glTF file, a scene number the file doesn't have, or the exported level itself (a file on another drive than the level is an error)
- an Animation with no clip, a clip that animates nothing in its object's hierarchy, or Include Animations turned off
- a Fog Volume with a density of 0, and a Reflection Probe or Irradiance Volume with no file
- an area light without a Light component, which glTF leaves out, a disk or ellipse area light or a square spot light, which Bevy cannot draw, and a Volumetric light without shadows
- a light probe file in a block-compressed format, which only loads on GPUs that support it

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

## Lights

glTF already carries a light's color, power, spot cone and Custom Distance range. Add a **Light** component (under Rendering) to a light for the rest:

- shadows from the light's own **Shadow** checkbox, plus contact shadows, depth and normal bias, and for sun lights the shadow cascades
- **Volumetric** for light shafts through Fog Volumes, and **Baked** for lights already baked into lightmaps, so they only add reflections there
- an **Intensity** in Bevy's lumens or lux, in place of Blender's watts at 683 lm/W

Area lights become Bevy `RectLight`s, which need Bevy's `area_light_luts` feature and cast no shadows. Contact shadows need `ContactShadows` and a depth prepass on the camera. The viewport draws how far each light reaches, 20 m unless Custom Distance is on.

**Properties > World > Bevy Ambient Light** sets the level's ambient light, from the World color or a color and brightness of its own.

## Fog and light probes

**Fog Volume**, **Reflection Probe** and **Irradiance Volume** (under Rendering) are boxes. Set their size on Bevy's axes or drag the arrows in the viewport, where the inner box of a probe shows where its falloff starts.

- **Fog Volume** fills its box with volumetric fog. Bevy only draws it for cameras with `VolumetricFog`, such as `commands.spawn((Camera3d::default(), VolumetricFog::default()))`, and once a light in the level has **Volumetric** on in its Light component.
- **Reflection Probe** gives the meshes in its box reflections and soft light from a cubemap. Bevy filters the cubemap when the level loads, so it needs six square faces whose size is a power of two, and no mipmaps. **Bake** makes one (see [Baked lighting](#baked-lighting)), or KTX-Software from six renders: `ktx create --format R16G16B16A16_SFLOAT --cubemap px.exr nx.exr py.exr ny.exr pz.exr nz.exr room.ktx2`.
- **Irradiance Volume** lights the meshes in its box from a grid of light samples, like Godot's VoxelGI. Its file is a 3D texture in Bevy's layout, where X × Y × Z samples take X × 2Y × 3Z texels, and **Bake** makes one.

The export embeds each probe's `.ktx2` file in the GLB, so the level stays one file and needs no extra loading code. Save them uncompressed, such as RGBA16F. Bevy cannot use Basis Universal here, and block-compressed formats only load on GPUs that support them.

## Baked lighting

The addon bakes Reflection Probes and Irradiance Volumes with Cycles, a static alternative to Godot's VoxelGI.

1. Size the probe's box, then set its **Bake Size** (pixels per cubemap face) or **Bake Voxels** (light samples along X, Y and Z).
2. Click **Bake** on the component to bake that probe, or pick **Bake Lighting...** in the components dropdown to bake every probe in the scene. The dialog sets the Cycles samples and the folder, `//baked_lighting/` next to the `.blend` file by default.

A second Blender bakes a copy of the scene in the background, so you can keep working. The status bar shows the progress and its **X** cancels; probes that already finished keep their new files. Each probe's file is set to its result, and the export embeds it like any other. Bakes started from a script finish before the call returns.

- Irradiance volumes hold the light that bounces off surfaces and the light from the sky and emissive materials. They leave out the light lamps shine straight at them, since Bevy lights meshes with the exported lamps itself. Turn on **Direct Lamp Light** for lamps you do not export.
- Bevy adds its ambient light on top of irradiance volumes, so turn off **Bevy Ambient Light** in the World properties when volumes cover the level, or the sky lights it twice.
- A probe's **Intensity** starts at 683, which converts Blender's light units the way the glTF export converts lamps, so baked light matches them.
- Let each box reach a little past the floors and walls it should light, since Bevy skips surfaces right on its edge. A Reflection Probe renders its cubemap from the center of its box, so keep that spot clear of meshes.
- The bake uses your Cycles settings, such as the device, light bounces and denoising, and skips objects that are disabled in renders.

## Texture compression

The exporter can compress textures to KTX2 and embed them in the GLB, so the level stays one file but is smaller on disk and in GPU memory.

1. Install [KTX-Software](https://github.com/KhronosGroup/KTX-Software/releases) 4.4 or newer. The addon looks for `ktx` on your `PATH` and in the default install folders (`C:\Program Files\KTX-Software\bin`, `/usr/local/bin`, `/opt/homebrew/bin`). If it lives elsewhere, set its path under **Edit > Preferences > Add-ons > Bevy Components**, which also shows the version it found. KTX-Software is only needed to export, not to run your game.
2. In **File > Export > Bevy Level (.glb)**, open **Texture Compression** and pick a mode:
   - **Disabled** (default): ordinary PNG and JPEG textures.
   - **ETC1S**: smallest files, lower quality.
   - **UASTC**: best quality, larger files. **Supercompression** shrinks them on disk.
   - **Automatic**: UASTC for normal maps, metallic-roughness, occlusion and textures set to Closest interpolation, ETC1S for other color textures.

A 4K texture takes 10 to 25 seconds to encode. Blender stays usable meanwhile: the status bar shows how many textures are done, and its **X** button cancels the export and keeps the previous file. Exports started from a script still finish before the call returns. The exporter encodes up to four textures at once at a lower CPU priority and caches the results in the add-on's user folder (up to 2 GB), so later exports only encode textures that changed. Leave compression Disabled while you iterate for the fastest exports.

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

The importer tests load `importer/tests/assets/sample_level.glb` and its compressed copies `sample_level_etc1s.glb`, `sample_level_uastc.glb` and `sample_level_automatic.glb`, plus the `props/windmill.glb` prop that the sample level references, which `python tests/blender/sample_level.py` regenerates (it needs KTX-Software). The Blender tests fail if they no longer match a fresh export. The texture compression tests are skipped when KTX-Software is missing, unless `BEVY_COMPONENTS_REQUIRE_KTX=1` is set.

The rendering tests compare compressed and uncompressed levels on a real GPU and check that light probes and fog show up. They are skipped by default. Run it with `cargo test --manifest-path importer/Cargo.toml -- --include-ignored`. On Linux without a GPU, Mesa's `mesa-vulkan-drivers` package provides one in software. Set `BEVY_COMPONENTS_RENDER_OUTPUT` to a folder to save the renders.

`addon/` holds the Blender extension and `importer/` the Rust crate. When CI passes on `main`, a GitHub release with both downloads is published whenever the version changes. The addon and importer share one version, kept in `addon/blender_manifest.toml`, `addon/__init__.py` and `importer/Cargo.toml`, and a test checks they match.

CI on pull requests and `main` runs only the Linux tests for the side that changed, plus the macOS and Windows texture compression tests when `addon/encoder.py` or `addon/compression.py` change. Every test on every platform runs when the version is not released yet, when the CI workflow changes, and when CI is started by hand from the Actions tab.

## License

See [LICENSE](LICENSE).
