# Bevy Components

Blender addon for adding Bevy components to objects and exporting them as GLB files, plus a Rust importer that turns the GLB's components back into components in Bevy.

Requires Blender 4.2+, Bevy 0.20 and Avian 0.8.

## Install the addon

1. Download `bevy_components_<version>.zip` from the [latest release](https://github.com/indseta/bevy_components/releases/latest).
2. In Blender, open **Edit > Preferences > Get Extensions**, then **Install from Disk...** and pick the ZIP.
3. Enable **Bevy Components** if it isn't enabled already.
4. Find it under **Properties > Object > Game Components**, **3D Viewport > N > Bevy** or **3D Viewport > Object > Bevy Components**.

## Install the importer

1. Download `bevy_components_importer_<version>.zip` from the same release and unzip it into your project. It extracts to a `bevy_components_importer/` folder.
2. Add it as a path dependency:

```toml
[dependencies]
bevy_components_importer = { path = "bevy_components_importer" }
```

3. Register the plugin and spawn the exported scene:

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
    commands.spawn(WorldAssetRoot(asset_server.load("scene.glb#Scene0")));
}
```

4. To start gameplay once a scene is complete, observe `BlenderSceneReady`. It fires on the `WorldAssetRoot` entity after the importer has added everything, including mesh colliders, joints, lightmaps, probes and referenced scenes, and again whenever the scene reloads:

```rust
commands.spawn(WorldAssetRoot(asset_server.load("scene.glb#Scene0"))).observe(|ready: On<BlenderSceneReady>| info!("{} is ready", ready.entity));
```

The importer's warnings start with the Blender object's name, such as `crate: Invalid mass`, and it warns once when a scene comes from a newer addon than itself.

## Usage

1. Set up physics, lights, speakers and light probes with Blender's own tools. For your game's components, select an object, press **Add Component** in **Properties > Object > Game Components** and pick one, or start typing to search.
2. Export the scene with **File > Export > Bevy Scene (.glb)**. After that, **Export Again** writes the same file with the same settings, without the file dialog. To export single objects with the options of Blender's glTF export, use **File > Export > Bevy glTF (.glb/.gltf)**.
3. Put the GLB in your game's `assets/` folder and load it as above. Or set your game's folder as the **Game Project** and press **Play** in **3D Viewport > N > Bevy** to export and run the game in one click.

Turn on **Export on Save** and enable Bevy's `file_watcher` feature, and the running game reloads the scene every time you save the .blend file.

| Component | In Bevy |
| --- | --- |
| Blender's Rigid Body and Rigid Body Constraint | Avian bodies, colliders and joints, with a Bevy subpanel in Properties > Physics for sensors, layers and starting velocity |
| Blender's lights, speakers, light probes, volume boxes and active actions | Bevy lights, `AudioPlayer`, reflection probes, irradiance volumes, `FogVolume` and autoplaying animations, with Bevy settings in each Properties tab |
| Collider | Avian cuboid, sphere, capsule, cylinder, cone, convex hull or triangle mesh collider, with friction, restitution, collision layers and events |
| Rigid Body | Avian static, dynamic or kinematic body with mass, damping, locked axes and a starting velocity |
| Joint | Avian fixed, hinge, slider or ball joint between two bodies |
| Visibility Range | `VisibilityRange` for levels of detail |
| Shadows | `NotShadowCaster` and `NotShadowReceiver` |
| Light | Per-light Bevy settings in place of the light data's |
| Lightmap, Reflection Probe, Irradiance Volume | Baked lighting, rendered by Cycles in the background |
| Fog Volume | `FogVolume` |
| Audio Player | `AudioPlayer` with `PlaybackSettings` |
| Animation | Plays an action when the scene loads |
| Scene Reference | Spawns another exported scene at the object |
| Navigation | `NavigationWalkable` and `NavigationObstacle` tags for a navmesh crate |
| Custom Component | Any of your game's components, as JSON or with typed fields read from your game |

The World properties add **Bevy Sky** and **Bevy Ambient Light**. In the Collection properties, **Game Components** gives custom components, Navigation and Visibility Range to every object in the collection, and **Bevy Prefab** turns it into a prefab with its own GLB.

## Guides

- [Components](docs/components.md): collections, physics, rendering, audio, animation, scene references, navigation and the viewport previews
- [Custom components](docs/custom_components.md): your game's own components, from its code or defined by hand
- [Lighting](docs/lighting.md): lights, ambient light, the sky, fog, light probes and baked lighting
- [Exporting](docs/exporting.md): export options, Export Again, hot reload, prefabs and the checks
- [Texture compression](docs/texture_compression.md): KTX2 textures embedded in the GLB
- [Play and the viewer](docs/play.md): run your game from Blender, or open any scene in the importer's viewer
- [Development](docs/development.md): tests, CI and releases

What changed in each version is in the [changelog](CHANGELOG.md). The [importer README](importer/README.md) lists what each component becomes in Bevy.

## License

The Blender addon is GPL-3.0-or-later, see [LICENSE](LICENSE). The importer crate is MIT, see [importer/LICENSE](importer/LICENSE), so games that use it can have any license.
