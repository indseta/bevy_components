# BSN export

**File > Export > Bevy Scene (BSN)** writes the scene as Rust code instead of a GLB with components: a `.rs` file whose `setup()` function builds the scene with `bsn!`, and an assets folder with a GLB for the meshes, materials and animations, plus the lightmap and probe files. It spawns the same entities and components as the GLB with the importer.

1. Pick a `.rs` file in your game's `src/` folder. **Assets Folder** sets where the files go; left empty, they go to `assets/scenes/<file name>` next to `Cargo.toml`. The dialog shows the path the game loads the GLB by.
2. Add the module and spawn the scene:

```rust
mod sample_scene;

fn setup(mut commands: Commands) {
    commands.queue_spawn_scene(sample_scene::setup());
}
```

With **Prefab Functions** on, objects that share a combination of components, such as a rigid body and collider, or a mesh with both, use one `object_<name>()` function below `setup()`. Turn it off to write every object out in full inside `setup()`. [Prefab collections](exporting.md#prefabs) become `prefab_<name>()` functions.

The export remembers its settings in the .blend file, so **Export Again** writes the same files in one click, and it only rewrites files that changed. It will not write over `main.rs`, `lib.rs` or another crate root, warns before it replaces a `.rs` file it did not write or one edited since the last export (Export Again refuses those), and removes files it copied into the assets folder earlier that the scene no longer uses. Rebuild the game after exporting again.

- Custom components are written as Rust values, so their types must exist at their type path (`my_game::Pickup` becomes `crate::Pickup` when the `.rs` file belongs to the `my_game` crate itself, such as a module of its `lib.rs`) and derive `Component`, `Clone` and `Default`. Fields can hold numbers, text, booleans, vectors, colors and enum variants. Custom JSON is written as it is typed, so give a float field `5.0`, not `5`.
- Navigation writes the importer's `NavigationWalkable` and `NavigationObstacle`, so a scene that uses it needs the importer crate, though not its plugin.
- The Bevy Sky sets the importer's `BlenderSky` resource, so a scene with a sky needs the importer crate and its plugin, which puts the sky on the cameras.
- Physics needs Avian with its `collider-from-mesh` feature. Add `BlenderBevyComponentsPlugin` when you compress textures or use a Scene Reference, since the referenced GLBs carry their components the usual way.
- Skins and shape keys are left out.
