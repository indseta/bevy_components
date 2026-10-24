# Changelog

## Unreleased

### Added

- **Blender physics**: the export reads Blender's own **Rigid Body**, **Rigid Body Constraint** and scene gravity into Avian bodies, colliders, joints and `Gravity`. A **Bevy** subpanel under each Physics panel holds what Blender lacks, such as sensors, Avian's 32 collision layers and a starting velocity. See [Physics](docs/components.md#physics).
- **Blender lighting and audio**: every light exports its Bevy settings from **Properties > Light > Bevy**, Speakers become Audio Players (Pitch is the playback speed), Sphere and Volume Light Probes become Reflection Probes and Irradiance Volumes that bake from their Bevy panel, and meshes whose material is only a Principled Volume become fog volumes. Ray Visibility's **Shadow** and a new **Receive Shadows** setting under Visibility control mesh shadows, and **Autoplay** plays an object's active action, looping when the action is Cyclic. See [Lighting](docs/lighting.md) and [Components](docs/components.md#audio-animation-and-scenes).
- **Convert Components to Blender** replaces Collider, Rigid Body, Joint, Light, Shadows and Animation components with Blender's own settings, and Audio Player, Fog Volume and probe components with Speaker, fog box and Light Probe child objects, wherever the game gets the same result, and lists what it kept.
- **Collection components**: **Properties > Collection > Game Components** gives custom and game components, Navigation and Visibility Range to every object in the collection and the collections inside it. A component on the object, or from a collection inside, replaces the collection's, and the Components panel lists what each object gets from its collections. Collections linked from another .blend file bring their components along. See [Collections](docs/components.md#collections).
- **Leave Out of Bevy** on an object or a collection exports it as plain glTF, without what Blender's physics, light, speaker, light probe and fog settings and collection components would add, for helper and reference objects. Components added by hand still export.
- **Copy Components**, **Paste Components**, **Copy All to Selected** and presets carry Blender's Rigid Body and Rigid Body Constraint with their Bevy settings, shadows, Autoplay and the Bevy settings of lights, speakers and light probes, so a crate preset keeps its physics. **Object > Rigid Body > Copy from Active with Bevy Settings** copies a Rigid Body with the Bevy settings that Blender's Copy from Active leaves out.
- Cylinder and Cone colliders, for Collider components and Blender's shapes.
- **Bevy glTF export**: **File > Export > Bevy glTF (.glb/.gltf)** is Blender's glTF export with the same dialog and options, made for Bevy. It always writes the Bevy components and physics without ticking Custom Properties, so single objects and props export with their colliders. It also works as a collection exporter. See [Exporting](docs/exporting.md).
- New checks: objects that get the same component from two unrelated collections with different settings, Blender shapes on meshes that are not centered on their origin, constraint types Avian has no joint for, speakers without a sound or with a packed one, Plane light probes, and fog boxes that use another shader, textures or emission, or are off center.

### Changed

- The export writes rigid bodies where the simulation starts, also when the timeline is on a later frame.
- Importer: colliders from Blender's shapes cover only their own mesh, and scenes with custom gravity set Avian's `Gravity` when they load.
- Lights without a Light component now follow their Bevy settings too, so area lights export as `RectLight` without one, and a light's shadows follow its **Shadow** checkbox.
- Importer: shadow settings from Blender's Visibility apply only to the object's own mesh, and Audio Players read an optional playback speed.
- The Components panel is now **Game Components**. **Add Component** lists your game's components, Navigation, Visibility Range, Lightmap and Scene Reference, and the built-in components that replace Blender's settings moved to **Add Component > Advanced**.
- Scene Overview and **Select by Bevy Component** include what objects get from Blender's settings and from collections.
- Objects no longer keep a copy of their components in a `bevy_components` custom property. The export builds them when it runs, so renamed joint bodies and other edits always reach the file, and saving removes the old property from older files.
- The viewport previews and labels redraw much faster in big scenes: with 2000 objects, a redraw where nothing changed takes about 8 ms instead of 430 ms, and only objects that changed are rebuilt.
- The checks behind the problem count, each component's warnings, Validate All Objects and the export run again only for objects that changed, so with 2000 objects they take about 15 ms instead of 180 ms when little changed. Adding, duplicating or deleting an object no longer makes every check or preview start over.
- Play runs the same export as Export Again instead of calling its operator, so when texture compression fails, Play says why.
- The components panel in **3D Viewport > N > Bevy** is now called **Game Components**, like the one in Properties, and the Bevy subpanels under Rigid Body and Rigid Body Constraint show what the object exports as, such as a Dynamic Body or a Ball Joint.
- A Rigid Body Constraint marked **Breakable** gets a warning, since Avian joints don't break on their own.

### Fixed

- Changing a setting of Blender's Rigid Body or Rigid Body Constraint, such as a hinge limit or a collision shape, updates the checks and the problem count right away.
- When **Convert Physics to Blender** keeps an object as it was, its Bevy joint and body settings stay too.
- **Paste Components** and presets that hold only a body or only a joint keep the object's Bevy settings for the other one.
- Sphere Light Probes no longer show the box resize handle of Reflection Probes.
- The checks no longer stop when a script removes a collection's components.
- Sounds and other files in an `assets` folder inside another one follow the game project's `Cargo.toml`, also when it is added after the file was first exported.
- **Bake Lighting** leaves out meshes hidden by a **Collision Only** collider, as the game does, and moving them no longer marks a bake out of date.
- Importer: when a scene that set `Gravity` is despawned or reloads without it, the gravity from before comes back.
- Hints and warnings in panels wrap to the panel's real width, so they are no longer cut off in the Bevy sidebar.
- A light's Bevy panel no longer repeats Blender's Radius, its Shadows checkbox sits next to the arrow like Blender's own subpanels, and a speaker's Bevy panel says when no sound is picked.

### Removed

- The **BSN export** (**File > Export > Bevy Scene (BSN)**) is gone, so the addon writes GLB files only and the importer is the one way into Bevy. Its settings, the **Enum Type** of enum fields in **Bevy Custom Components** and the `enums` entry in custom component extras, which only that export read, went with it. Files that used it still open and export their GLB.

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
