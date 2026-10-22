# Bevy Components

Blender addon for adding Bevy components to objects and exporting levels as a single GLB, plus a Rust importer that turns them back into components in Bevy.

Requires Blender 4.2+, Bevy 0.20 and Avian 0.8.

## Install the addon

1. Download `bevy_components_<version>.zip` from the latest [addon release](https://github.com/indseta/bevy_components/releases).
2. In Blender, open **Edit > Preferences > Get Extensions**, then **Install from Disk...** and pick the ZIP.
3. Enable **Bevy Components** if it isn't enabled already.
4. Find it under **Object Properties > Bevy Components** or **3D Viewport > N > Bevy**.

## Install the importer

1. Download `bevy_components_importer_<version>.zip` from the latest [importer release](https://github.com/indseta/bevy_components/releases) and unzip it into your project. It extracts to a `bevy_components_importer/` folder.
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
cargo check --manifest-path importer/Cargo.toml
```

`addon/` holds the Blender extension and `importer/` the Rust crate. Every push to `main` that passes CI publishes both as GitHub releases.

## License

See [LICENSE](LICENSE).
