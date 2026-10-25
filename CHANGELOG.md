# Changelog

## Unreleased

### Changed

- **File > Export** has one Bevy export, **Bevy glTF (.glb)**, which took over everything **Bevy Scene (.glb)** did: it runs the checks first, writes the prefabs it uses, compresses textures, embeds baked light probes and the sky, keeps the previous file when an export fails, and is the export that Export Again, Export on Save, Export All Scenes, Play and Bake Lighting repeat. Its dialog is Blender's glTF dialog with a **Bevy** panel for Export on Save, Texture Compression and the checks. See [Exporting](docs/exporting.md).
- **Bevy glTF** starts out with Bevy Scene's defaults ticked: **Apply Modifiers**, **Punctual Lights**, **Custom Properties**, **Active Scene** and **Set All glTF Animation Starting at 0**.
- **Remember Export Settings** decides which export Export Again repeats, so a one-off prop export with it unticked keeps Export Again writing the level.
- **Bevy glTF** writes .glb files only, which hold the compressed textures and baked lighting; a .gltf file name becomes .glb.
- Exports limited to the active collection leave out the World's **Bevy Ambient Light** and **Bevy Sky**, like exports limited to selected objects.
- A collection's **Bevy glTF** exporter can export at the collection's center with **Export at Collection Center**, and prefab offsets follow **+Y Up**.

### Removed

- **Bevy Scene (.glb)** in **File > Export**, the dropdown next to **Add Component** and **3D Viewport > N > Bevy > Export**, its collection exporter and `bpy.ops.export_scene.bevy_components_glb`.

### Upgrading from 0.5.1

- Export Again keeps exporting a scene's last Bevy Scene file with its settings.
- A collection exporter added as **Bevy Scene (.glb)** must be added again as **Bevy glTF**.
- Scripts call `bpy.ops.export_scene.bevy_gltf(again=True)` instead of `bpy.ops.export_scene.bevy_components_glb(again=True)`.

## 0.5.1 (2026-10-25)

### Added

- **Bevy glTF export**: **File > Export > Bevy glTF (.glb/.gltf)** is Blender's glTF export with the same dialog and options, made for Bevy. It always writes the Bevy components without ticking Custom Properties, so single objects and props export with their colliders. It also works as a collection exporter. See [Exporting](docs/exporting.md).
- **Cylinder** and **Cone** collider shapes along Bevy's Y axis, like the capsule, with **Fit to Mesh** and viewport handles for their radius and height.
- **Bevy glTF** lists the warnings of the checks for the objects it wrote, and warns when it leaves out a light with a Light component because **Punctual Lights** is off.
- A check for levels of detail with modifiers while **Apply Modifiers** is off, which then export at full detail.
- [Export a prop](docs/exporting.md#export-a-prop): levels of detail, colliders and lights in a prop's own GLB.

### Changed

- Objects no longer keep a copy of their components in a `bevy_components` custom property. The export builds them when it runs, so renamed joint bodies and other edits always reach the file, and saving removes the old property from older files.
- The viewport previews and labels redraw much faster in big scenes: with 2000 objects, a redraw where nothing changed takes about 8 ms instead of 430 ms, and only objects that changed are rebuilt.
- The checks behind the problem count, each component's warnings, Validate All Objects and the export run again only for objects that changed, so with 2000 objects they take about 15 ms instead of 180 ms when little changed. Adding, duplicating or deleting an object no longer makes every check or preview start over.
- Play runs the same export as Export Again instead of calling its operator, so when texture compression fails, Play says why.
- Bevy glTF exports, and Bevy Scene exports limited to selected objects, leave out the World's **Bevy Ambient Light** and **Bevy Sky**, so spawning a prop no longer changes the game's lighting.

### Fixed

- A **Triangle Mesh** or **Convex Hull** collider on the parent of levels of detail is built from the first level only, the meshes whose **Visibility Range** starts at 0 m, instead of one collider per level that all collide at every distance and add up the mass.
- **Bake Lighting** leaves out meshes hidden by a **Collision Only** collider, as the game does, and moving them no longer marks a bake out of date.
- Hints and warnings in panels wrap to the panel's real width, so they are no longer cut off in the Bevy sidebar.

### Removed

- The **BSN export** (**File > Export > Bevy Scene (BSN)**) is gone, so the addon writes GLB files only and the importer is the one way into Bevy. Its settings, the **Enum Type** of enum fields in **Bevy Custom Components** and the `enums` entry in custom component extras, which only that export read, went with it. Files that used it still open and export their GLB.

### Upgrading from 0.5.0

- A game that loaded the BSN export's Rust file now loads the scene's GLB with the importer instead.
- Update the importer together with the addon. The 0.5.0 importer warns "Unsupported collider shape" for Cylinder and Cone colliders, and builds a mesh collider for every level of detail.

## 0.5.0 (2026-10-24)

### Added

- **BSN export**: **File > Export > Bevy Scene (BSN)** writes the scene as a Rust file whose `setup()` builds it with `bsn!`, plus an assets folder with a GLB for the meshes, materials and animations. Objects that share components can share an `object_<name>()` function. See [BSN export](docs/bsn_export.md).
- **Play**: **3D Viewport > N > Bevy > Play** exports the scene and runs your game, with a stop button in the status bar, the game's output in a Text Editor and its importer warnings listed by object. Set the game's folder as the **Game Project** in the add-on preferences or per .blend file. `blender_view()` lets the game start its camera at the viewport's view. See [Play and the viewer](docs/play.md).
- **Viewer**: `cargo run --example viewer -- scene.glb` in the importer opens any exported scene with a fly camera, collider outlines and hot reload. Play uses it when no game project is set.
- **Prefabs**: **Properties > Collection > Bevy Prefab** exports a collection to its own GLB and its instances as Scene References to it. Changed prefabs export again before each scene export, and the BSN export writes them as `prefab_<name>()` functions. Collections can also export on their own from **Properties > Collection > Exporters**.
- **Game components**: `BlenderSchemaPlugin` writes `bevy_components_schema.json` with your game's reflected components, and the addon lists them under **Add Component** with typed fields. See [Custom components](docs/custom_components.md).
- **Navigation** component: tags meshes and colliders as Walkable (with a cost), Obstacle or Ignored, imported as `NavigationWalkable` and `NavigationObstacle` for a navmesh crate.
- **Bevy Sky**: **Properties > World > Bevy Sky** bakes the World into a cubemap that shows behind every camera and can light the scene.
- **Export Again** in **File > Export**, the Bevy menus and the new **3D Viewport > N > Bevy > Export** panel writes the last export again without the file dialog. **Export All Scenes** does it for every scene in the file.
- **Export on Save** exports again every time the .blend file is saved, so a game with Bevy's `file_watcher` feature reloads the scene while it runs.
- Export options: **Apply Modifiers** (on by default), and **Limit to** visible or renderable objects next to selected ones.
- Collider: **Collision Events** (Avian's `CollisionEventsEnabled`, on by default for sensors), **Collision Only** for invisible walls, an **Offset** with **Fit to Mesh**, and collision layer names under **Properties > Scene > Bevy Collision Layers**.
- Viewport handles for visibility range fades, light ranges and collider offsets. Every handle drag can be undone.
- Custom components: Vector 2D and Enum fields, tuple structs, and **Edit as Text** to edit the data in a Text Editor.
- Scene Overview list, **Select by Bevy Component**, **Copy Components** and **Paste Components** (also between .blend files), component presets, a **Bevy Components** submenu in the 3D Viewport's Object and right-click menus, and error and warning counts in the panel headers.
- **Bake Lighting** can export the scene again when the bake finishes.
- New checks: lighting baked before the scene changed, materials that glTF flattens, shape keys that Apply Modifiers drops, prefab problems, and BSN files the export should not write over.
- Importer: the `BlenderSceneReady` event fires once a scene is fully built and after every reload. Warnings start with the Blender object's name, and the importer warns when a scene comes from a newer addon. Scenes record the addon version that exported them.

### Changed

- The GLB export is now **File > Export > Bevy Scene (.glb)**, was Bevy Level. The output is still one GLB.
- The importer runs right after Bevy spawns the glTF scene, so the components are there on the first frame the scene shows.
- Custom components whose type derives `Reflect` with `#[reflect(Component)]` are inserted as that component, found by type path, by crate and type name or by a bare type name. Only other types still arrive in `BlenderCustomComponents`.
- Spot lights start with a radius of 0, like point lights, instead of their range.
- The export holds only the active scene, and a failed export keeps the previous file.
- Viewport previews are cached per object, so the viewport stays fast in large scenes. Objects that aren't selected get one short label.
- The importer crate is now MIT licensed. The Blender addon stays GPL-3.0-or-later.
- The importer download leaves out the importer's tests, and both downloads include their license.
- The README is shorter, with the details in [docs](docs).

### Fixed

- Export on Save with both a GLB and a BSN export no longer fails the BSN export while the GLB's textures compress.
- A custom component with invalid JSON no longer drops the object's other components from the export, so their previews stay too.
- **Define Fields** keeps enum variants and Rust types.
- **Bake Lighting** stores its files on the right probe or lightmap after its component moved in the list.
- Prefabs export again after an addon update.
- Game tuple structs with fields Blender cannot set now warn that the game cannot insert them, and block the BSN export, which cannot write them.
- Play gives the game's error log line as the reason it stopped.
- JPEG textures with padded markers no longer fail the texture size check.
- BSN export: a collision-only mesh with one material keeps its navigation tag.
- Hot reload no longer duplicates joint anchors.
- The Bevy Sky leaves the cameras when its scene is despawned, or reloads without a sky.
- The importer's GLB loader no longer overflows on a chunk length that runs past the end of the file.
- The export buttons in the 3D Viewport no longer stay greyed out after a background export.
- Cancelling the export or bake dialog no longer logs an error.

### Upgrading from 0.4.0

- A game that read its reflected components from `BlenderCustomComponents` now finds them inserted as the components themselves.
- Update the addon and the importer together. The 0.4.0 importer skips the new components, such as Navigation, with an "Unsupported Bevy component" warning. From 0.5.0 on, the importer warns when a scene comes from a newer addon.
