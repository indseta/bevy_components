# Exporting

**File > Export** has two Bevy exports, and both write each object's components in its glTF extras:

- **Bevy glTF (.glb/.gltf)** is Blender's own glTF export, with the same dialog and options such as **Limit to Selected Objects**, made for Bevy. It always writes the Bevy components and Blender's physics, lights and audio as Bevy sees them, without ticking **Custom Properties**, and writes rigid bodies where the simulation starts. Use it to export a single object, a prop or anything else you would export as glTF. It can also be a collection's exporter under **Properties > Collection > Exporters**. When a component cannot export, such as a Custom Component with broken JSON, it leaves that one out and says so.
- **Bevy Scene (.glb)** writes a whole level. It runs the checks first, can compress textures, writes prefabs and has Export Again, Export on Save and Play. The same export sits in the dropdown next to **Add Component**, and the rest of this page is about it. To make the GLB smaller, see [texture compression](texture_compression.md).

Blender's plain **glTF 2.0** export writes the components only when **Include > Custom Properties** is ticked.

## Options

The export holds the active scene. Under **Include**, **Limit to** can leave out objects that aren't selected, are hidden in the viewport or are turned off for renders, and the checks look at the same objects. **Apply Modifiers**, on by default, exports meshes as the viewport shows them, though glTF then leaves out the shape keys of meshes with modifiers. The file is written once the export succeeds, so a failed export keeps the previous one.

## Export Again

After the first export, **Export Again** in **File > Export**, the dropdown next to **Add Component** and **3D Viewport > N > Bevy > Export** writes the same file with the same settings, without the file dialog. `bpy.ops.export_scene.bevy_components_glb(again=True)` does the same from a script, also from the command line with prefabs and texture compression, as long as the add-on is enabled there:

```sh
blender -b level.blend --addons bl_ext.user_default.bevy_components --python-expr "import bpy; bpy.ops.export_scene.bevy_components_glb(again=True)"
```

`user_default` is the repository the add-on was installed into. With more than one scene in the file, **Export All Scenes (.glb)** exports every scene that was exported before to its own GLB, with that scene's settings.

## Hot reload

Turn on **Export on Save** in the export dialog or under **3D Viewport > N > Bevy > Export**, and every save of the .blend file exports the scene again with the same settings. When that export fails, a message says why and the previous file stays. Enable Bevy's `file_watcher` feature in your game, and it reloads the scene while it runs, with the components rebuilt once:

```toml
bevy = { version = "0.20", features = ["file_watcher"] }
```

## Prefabs

Tick **Properties > Collection > Bevy Prefab** on a collection and pick its GLB file. Its collection instances then export as a Scene Reference to that file instead of copies of its objects, while the viewport keeps showing the collection. Each scene export writes the prefab's GLB first, but only when the collection's objects, components or transforms or the export settings changed since its last export. The collection's **Instance Offset** is the prefab's origin, and prefabs can hold instances of other prefabs. Keep the prefab collections in another scene or in a collection excluded from the view layer; scene exports leave their objects out either way. An instance's **Game Components** panel shows the same checkbox and file, since an excluded collection has no Collection tab.

**Export Prefab** in that panel writes just the prefab. Any collection can also export on its own from **Properties > Collection > Exporters > Add > Bevy Scene (.glb)**, which writes the prefabs inside it as well.

## Checks

**Validate All Objects** in the dropdown next to **Add Component** lists problems in the scene, and clicking one selects its object. The export dialog lists them under **Checks**, and each component shows its own.

Errors block the export, and a collection's component shows its error once, for the first object that gets it: invalid custom JSON, a number its field's Rust type cannot hold, a joint limit whose Min is above its Max, shadow cascade distances out of order, a light probe file that is missing or that Bevy cannot use, and a prefab with no GLB file or one that ends up inside itself.

Warnings point out setups that behave differently in Bevy than they look in Blender:

- a Triangle Mesh, Convex Hull or Collision Only collider, or a Visibility Range, with no mesh on or under its object
- a Dynamic Rigid Body with no collider, a Rigid Body inside a moving one, and Triangle Mesh colliders on Dynamic bodies
- a collider rotated inside an unevenly scaled parent, which Avian sizes wrong
- a Dynamic body with every axis locked
- a Joint with no bodies, the same body twice, only static bodies, or a body that has no Rigid Body or Collider, is part of another body or is left out of the export
- levels of detail at the same spot whose fade distances leave a gap, overlap or don't crossfade
- an object that gets the same component from two collections, neither inside the other, with different settings
- Custom Component type paths that aren't Rust paths, or that repeat on one object, game components with fields Blender cannot set but no `#[reflect(Default)]`, and game tuple structs with such fields, which the game cannot insert
- Shadows with no mesh on or under its object, and Navigation with no mesh or collider on or under its object
- an Audio Player or Speaker with no sound, a path outside the `assets` folder, a sound packed into the .blend file, or a file type Bevy cannot play
- a Scene Reference to a missing or non-glTF file, a scene number the file doesn't have, or the exported scene itself (a file on another drive than the exported scene is an error)
- a prefab with no objects or a GLB file outside the `assets` folder (two prefabs with one file, a prefab writing the exported scene's own file, or a Scene Reference on a prefab instance is an error)
- an Animation with no clip, a clip that animates nothing in its object's hierarchy, or Include Animations turned off
- a Fog Volume with a density of 0, and a Reflection Probe, Irradiance Volume, light probe or Bevy Sky with no file
- a fog box with another volume shader than Principled Volume, textures plugged into its inputs, Emission or Blackbody, more than one material, a mesh that is not a box or not centered on its origin, and Plane light probes, which Bevy has no equivalent for
- Bevy Ambient Light from the World color next to the Bevy Sky's Environment Light, which light the scene twice
- a lightmap, light probe or sky baked before the meshes, lamps or World it lights changed, so it needs another bake
- a disk or ellipse area light or a square spot light, which Bevy cannot draw, and a Volumetric light without shadows
- a light probe file in a block-compressed format, which only loads on GPUs that support it
- a material that glTF flattens: one that mixes shaders, has no Principled BSDF, or drives Principled BSDF inputs with procedural nodes instead of images
- shape keys on a mesh with modifiers while **Apply Modifiers** is on
