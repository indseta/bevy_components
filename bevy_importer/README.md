# Bevy 0.20 importer

Companion to the Blender **Bevy Components** addon. Consumes glTF `extras.bevy_components` metadata, converts it into Bevy components, and builds Avian 3D colliders.

## Dependencies

See `Cargo.toml`: Bevy 0.20, Avian 0.8, serde, serde_json.

To use in an existing game, copy `src/lib.rs` into e.g. `src/bevy_components.rs`, or add this folder as a path dependency. If copying the module, add `avian3d = "0.8"`, `serde = { version = "1", features = ["derive"] }`, and `serde_json = "1"` to the game's dependencies. Ensure Bevy 0.20 has `bevy_gltf` enabled.

```rust
use bevy::prelude::*;
use avian3d::prelude::*;
use bevy_components_importer::BlenderBevyComponentsPlugin;

fn main() {
    App::new()
        .add_plugins((
            DefaultPlugins,
            PhysicsPlugins::default(),
            BlenderBevyComponentsPlugin,
        ))
        .add_systems(Startup, setup)
        .run();
}

fn setup(mut commands: Commands, asset_server: Res<AssetServer>) {
    commands.spawn(WorldAssetRoot(
        asset_server.load("static_level_a.glb#Scene0"),
    ));
}
```

### Semantics

- **Visibility Range**: applies Bevy `VisibilityRange` to mesh descendants of the tagged glTF object, so it works when Bevy creates primitive child entities. Sibling LODs must have aligned origins and exactly matching transition intervals.
- **Collider**: generates an Avian collider on each descendant `Mesh3d` (or the mesh itself). Mesh-based colliders wait for the mesh asset to load. Collider values for cuboid, sphere and capsule use **Bevy local coordinates**; cuboid size means full extents, not half-extents. Add the Collider component to a *single* LOD mesh or a dedicated collision mesh—otherwise each LOD receives a persistent collider.
- **Rigid Body**: on the tagged glTF object. A Collider component without a Rigid Body defaults to static.
- **Spawn Point**: inserts `BlenderSpawnPoint(tag)` on the glTF object node. Empty Blender objects work for markers.
- **Custom Component**: inserts `BlenderCustomComponents` containing `type_path` and JSON value on the node. It is **not** automatically converted into an arbitrary Rust type—your game must map these values to its own components.

### Important caveats

- glTF extras are per node; this importer reads node `GltfExtras`, not mesh-data `GltfMeshExtras`.
- Because mesh extras are processed after import, native glTF PBR assets are loaded unchanged. The importer runs during `Update`, including before any player has entered your gameplay scene if you spawn the GLB at startup.
- Blender's standard glTF exporter must have **Custom Properties** enabled. The addon’s dedicated exporter enables that automatically.
- Blender float dimensions and unit scale are not automatically converted to Bevy meters. Keep 1 Blender unit = 1 meter and apply mesh scale if collision shape sizes look wrong.
- Avoid triangle meshes on dynamic rigid bodies; use a convex hull for movable objects.
- Imported custom component types and markers are data; add your own game-specific spawning logic.
- Requires Blender and Rust/Bevy installed locally to runtime-test. Code was syntax-checked, not built against Bevy in the packaging environment.
