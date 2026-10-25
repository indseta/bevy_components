# Exporting

**File > Export > Bevy glTF (.glb)** writes a level, a prop or anything else you would export as glTF to one GLB file, with each object's components in its glTF extras. It is Blender's own glTF export, with the same dialog and options such as **Include > Limit to > Selected Objects**, plus a **Bevy** panel with **Export on Save**, **Texture Compression** and the [checks](#checks). It always writes the Bevy components, also with **Include > Data > Custom Properties** off. The same export sits in the dropdown next to **Add Component** and in **3D Viewport > N > Bevy > Export**, and it can be a collection's exporter under **Properties > Collection > Exporters**. To make the GLB smaller, see [texture compression](texture_compression.md).

Blender's plain **glTF 2.0** export writes the components only when **Include > Custom Properties** is ticked, and leaves out prefabs, texture compression and the checks.

Exports limited to selected objects or the active collection leave out the World's **Bevy Ambient Light** and **Bevy Sky**, so spawning a prop doesn't change the game's lighting.

## Export a prop

A prop such as a lamp is an empty with its parts under it, exported to its own GLB:

1. Model the levels of detail as meshes under the empty, such as `lamp_lod0`, `lamp_lod1` and `lamp_lod2`. Give each a **Visibility Range** and pick its LOD0, LOD1 or LOD2 preset. A Decimate modifier can make the lower levels.
2. Add the **Collider** to the empty. A cylinder, capsule or other shape sits on the empty itself, and a Convex Hull or Triangle Mesh is built from the first level only. For a simpler collision shape, add another mesh under the empty with its own Collider and tick **Collision Only**.
3. Put a light that belongs to the prop, such as the lamp's bulb, under the empty too, and give it a **Light** component for its shadows and other Bevy settings.
4. Select the empty and its children and export with **Bevy glTF (.glb)**, with **Include > Limit to > Selected Objects** ticked. Modifiers are applied and lights exported by default. When the prop comes out of a level's .blend file, untick **Remember Export Settings**, so [Export Again](#export-again) keeps writing the level. When the .blend file holds just this prop, you can leave **Selected Objects** off and use Export Again and Export on Save for the prop. Delete Blender's default light first, since lights export, and leave the World's Bevy Ambient Light and Bevy Sky off.
5. Spawn the GLB in the game like a scene, with a `Transform`, place it in a level with a Scene Reference, or make it a [prefab](#prefabs):

```rust
commands.spawn((WorldAssetRoot(asset_server.load("props/lamp.glb#Scene0")), Transform::from_xyz(4.0, 0.0, 2.0)));
```

## Options

The options are glTF's, and a few start out ticked for Bevy: **Include > Limit to > Active Scene**, **Include > Data > Custom Properties** and **Punctual Lights**, **Data > Mesh > Apply Modifiers** and **Animation > Rest & Ranges > Set All glTF Animation Starting at 0**. **Limit to** can leave out objects that aren't selected, are hidden in the viewport, are turned off for renders or aren't in the active collection, and the checks look at the same objects. **Apply Modifiers** exports meshes as the viewport shows them, though glTF then leaves out the shape keys of meshes with modifiers.

The export runs the checks first and stops when one finds an error. The file is written once the export succeeds, so a failed export keeps the previous one. It is always a .glb file, which holds the compressed textures and baked lighting too. When a component cannot export, the export leaves it out and says so, and it says when it left out a light with a Light component because **Include > Data > Punctual Lights** is off.

## Export Again

After the first export, **Export Again** in **File > Export**, the dropdown next to **Add Component** and **3D Viewport > N > Bevy > Export** writes the same file with the same settings, without the file dialog, and the dialog opens with them. **Remember Export Settings**, ticked by default, makes an export the one that Export Again, Export on Save and Play repeat; untick it for a one-off export. `bpy.ops.export_scene.bevy_gltf(again=True)` does the same from a script, also from the command line with prefabs and texture compression, as long as the add-on is enabled there:

```sh
blender -b level.blend --addons bl_ext.user_default.bevy_components --python-expr "import bpy; bpy.ops.export_scene.bevy_gltf(again=True)"
```

`user_default` is the repository the add-on was installed into. With more than one scene in the file, **Export All Scenes (.glb)** exports every scene that was exported before to its own GLB, with that scene's settings.

## Hot reload

Turn on **Export on Save** in the export dialog's **Bevy** panel or under **3D Viewport > N > Bevy > Export**, and every save of the .blend file exports the scene again with the same settings. When that export fails, a message says why and the previous file stays. Enable Bevy's `file_watcher` feature in your game, and it reloads the scene while it runs, with the components rebuilt once:

```toml
bevy = { version = "0.20", features = ["file_watcher"] }
```

## Prefabs

Tick **Properties > Collection > Bevy Prefab** on a collection and pick its GLB file. Its collection instances then export as a Scene Reference to that file instead of copies of its objects, while the viewport keeps showing the collection. Each scene export writes the prefab's GLB first, but only when the collection's objects, components or transforms or the export settings changed since its last export. The collection's **Instance Offset** is the prefab's origin, and prefabs can hold instances of other prefabs. Keep the prefab collections in another scene or in a collection excluded from the view layer; scene exports leave their objects out either way. An instance's **Components** panel shows the same checkbox and file, since an excluded collection has no Collection tab.

**Export Prefab** in that panel writes just the prefab, with the settings of the scene's last export. Any collection can also export on its own from **Properties > Collection > Exporters > Add > Bevy glTF**, which writes the prefabs inside it as well. Its origin is the collection's **Instance Offset**, or the center of its objects with **Collection > Export at Collection Center**, except for a prefab writing its own GLB, which keeps its Instance Offset so its instances line up.

## Checks

**Validate All Objects** in the dropdown next to **Add Component** lists problems in the scene, and clicking one selects its object. The export dialog lists them under **Bevy > Checks**, and each component shows its own.

Errors block the export: invalid custom JSON, a number its field's Rust type cannot hold, a joint limit whose Min is above its Max, shadow cascade distances out of order, a light probe file that is missing or that Bevy cannot use, and a prefab with no GLB file or one that ends up inside itself.

Warnings point out setups that behave differently in Bevy than they look in Blender:

- a Triangle Mesh, Convex Hull or Collision Only collider, or a Visibility Range, with no mesh on or under its object
- a Dynamic Rigid Body with no collider, a Rigid Body inside a moving one, and Triangle Mesh colliders on Dynamic bodies
- a collider rotated inside an unevenly scaled parent, which Avian sizes wrong
- a Dynamic body with every axis locked
- a Joint with no bodies, the same body twice, only static bodies, or a body that has no Rigid Body or Collider, is part of another body or is left out of the export
- levels of detail at the same spot whose fade distances leave a gap, overlap or don't crossfade
- Custom Component type paths that aren't Rust paths, or that repeat on one object, game components with fields Blender cannot set but no `#[reflect(Default)]`, and game tuple structs with such fields, which the game cannot insert
- Shadows with no mesh on or under its object, and Navigation with no mesh or collider on or under its object
- an Audio Player with no sound, a path outside the `assets` folder, or a file type Bevy cannot play
- a Scene Reference to a missing or non-glTF file, a scene number the file doesn't have, or the exported scene itself (a file on another drive than the exported scene is an error)
- a prefab with no objects or a GLB file outside the `assets` folder (two prefabs with one file, a prefab writing the exported scene's own file, or a Scene Reference on a prefab instance is an error)
- an Animation with no clip, a clip that animates nothing in its object's hierarchy, or **Animation** turned off in the export
- a Fog Volume with a density of 0, and a Reflection Probe, Irradiance Volume or Bevy Sky with no file
- Bevy Ambient Light from the World color next to the Bevy Sky's Environment Light, which light the scene twice
- a lightmap, light probe or sky baked before the meshes, lamps or World it lights changed, so it needs another bake
- an area light without a Light component, which glTF leaves out, a disk or ellipse area light or a square spot light, which Bevy cannot draw, and a Volumetric light without shadows
- a light probe file in a block-compressed format, which only loads on GPUs that support it
- a material that glTF flattens: one that mixes shaders, has no Principled BSDF, or drives Principled BSDF inputs with procedural nodes instead of images
- shape keys on a mesh with modifiers while **Apply Modifiers** is on, and a level of detail with modifiers while it is off
