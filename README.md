# Bevy Components

Blender addon for adding Bevy components to objects and exporting levels as a single GLB, plus a Rust importer that turns them back into components in Bevy.

Requires Blender 4.2+, Bevy 0.20 and Avian 0.8.

## Install the addon

1. Download `bevy_components_<version>.zip` from the [latest release](https://github.com/indseta/bevy_components/releases/latest).
2. In Blender, open **Edit > Preferences > Get Extensions**, then **Install from Disk...** and pick the ZIP.
3. Enable **Bevy Components** if it isn't enabled already.
4. Find it under **Object Properties > Bevy Components** or **3D Viewport > N > Bevy**.

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

1. Select an object, press **Add Component** and pick Visibility Range, Collider, Rigid Body, Spawn Point or Custom.
2. Export with **File > Export > Bevy Level (.glb)** or the **Export Level** button.
3. Put the GLB in your game's `assets/` folder.

Collider sizes are in Bevy coordinates (Y up). Viewport previews are editor-only and are not exported.

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

The importer tests load `importer/tests/assets/sample_level.glb`, which `python tests/blender/sample_level.py` regenerates. The Blender tests fail if it no longer matches a fresh export.

`addon/` holds the Blender extension and `importer/` the Rust crate. When CI passes on `main`, a GitHub release with both downloads is published whenever the version changes. The addon and importer share one version, kept in `addon/blender_manifest.toml`, `addon/__init__.py` and `importer/Cargo.toml`, and a test checks they match.

## License

See [LICENSE](LICENSE).
