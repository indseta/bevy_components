# Play and the viewer

## Play

**Play** in **3D Viewport > N > Bevy** exports the scene again and runs your game. Set **Game Project** to the folder with your game's `Cargo.toml` in the add-on preferences under **Play**, or for one .blend file in the Play panel. Play runs **Run Command** there, `cargo run` by default, where `{scene}` becomes the path of the exported GLB. Without a game project, set **Importer** to the `bevy_components_importer` folder and Play opens the scene in its [viewer](#viewer).

- Export the scene once with **File > Export > Bevy glTF (.glb)**, and Play repeats that export with the same settings.
- The status bar shows the game building and running, with an X to stop it. Play again restarts it.
- The Play panel lists the importer's warnings, and clicking one selects its object. It also says why the game stopped, and **Show Game Output** opens everything it printed in a Text Editor.
- The game starts with `BEVY_COMPONENTS_VIEW` set to the 3D Viewport's view. `blender_view()` reads it as a `Transform` in Bevy's axes, so the game can start its camera there:

```rust
use bevy_components_importer::blender_view;

fn setup(mut commands: Commands) {
    let start = blender_view().unwrap_or_else(|| Transform::from_xyz(0.0, 5.0, 10.0).looking_at(Vec3::ZERO, Vec3::Y));
    commands.spawn((Camera3d::default(), start));
}
```

With a game project, the GLB export starts at `assets/levels/<scene>.glb`, the sound, scene and probe file pickers start in `assets`, and the checks warn about sounds missing from `assets` and about GLB exports or scene references outside it.

## Viewer

The importer comes with a viewer: run `cargo run --example viewer -- path/to/scene.glb` in the `bevy_components_importer` folder. WASD, Q and E fly, the right mouse button looks around, P pauses physics and F1 hides or shows the collider and joint outlines. It reloads the scene when the file changes, so **Export Again** or **Export on Save** in Blender updates it, and it loads files from the nearest `assets` folder above the scene.
