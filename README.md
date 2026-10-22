# Bevy Components for Blender

A small, focused Blender addon for authoring Bevy ECS-style metadata on objects and exporting complete static levels as a single GLB. Jackdaw-inspired card inspector, non-exporting 3D viewport previews, and interactive collider resize handles, implemented directly in Blender.

**Version:** 0.2.0. **Targets:** Blender 4.2+ (Python add-on API) and Bevy 0.20 with Avian 0.8. Blender 5.x may work but has not been exercised here.

## Installation

1. Download the CI artifact or build `dist/bevy_components-0.2.0.zip` with `python scripts/build_addon.py`.
2. In Blender, open **Edit → Preferences → Get Extensions → Install from Disk...** and select that ZIP.
3. Enable **Bevy Components** if Blender doesn't activate it automatically.
4. Select a mesh and open **Object Properties → Bevy Components**, or **3D Viewport → N → Bevy**.

## Authoring components

1. Press **Add Component**, search for Visibility Range / Collider / Rigid Body / Spawn Point / Custom Component.
2. Edit each card's values. Add one collider to a mesh that should have collision. Put different Visibility Range components on each LOD mesh.
3. For two smoothly crossfading LOD meshes: LOD0 is `start: [0,0], end: [20,25]`, LOD1 is `start: [20,25], end: [80,85]`.
4. Use the LOD0/LOD1/LOD2 buttons to apply those defaults quickly. Use **Copy to Selected** to bulk-assign the active object's components to other selected objects.
5. Export with **File → Export → Bevy Level (.glb)** or the **Export Level** button on the inspector.
6. Place GLB in the Bevy project's `assets/` and spawn it with `WorldAssetRoot` and `#Scene0`.

## 3D Viewport previews (new in 0.2.0)

Go to **3D Viewport → N → Bevy → Viewport Previews**. The previews are **editor-only GPU overlays**; they do not create Blender objects and do not appear in the exported GLB.

- **Colliders** (green; orange for sensors): cuboid, sphere, and capsule wireframes follow the object's position, rotation and scale. Triangle-mesh colliders display actual mesh edges, up to an adjustable edge limit (2,000 by default); above that, they display an AABB wireframe to keep editing responsive. Convex hulls currently display their bounding box **as an approximation**; Avian will build the actual hull during game load.
- **Visibility ranges** (blue for fade-in, orange for fade-out): four distance boundaries, drawn as 3D wireframe spheres measured in world units, with separate faint start and stronger end circles. They respect the `Use AABB Center` toggle. Very large ranges can cover most of the viewport; toggle **LOD Ranges** off when not needed.
- **Spawn points** (magenta): a ground marker and a forward arrow. The arrow points along Blender local **+Y**, which exports as Bevy local **-Z**.
- **Labels**: above selected objects, the active component types, collider dimensions, and LOD fade limits are shown.
- **Selected / All Visible**: limit overlays to selected objects by default, or display them throughout the scene. You can also toggle see-through-meshes mode.
- **Edit Collider in Viewport**: with a cuboid/sphere/capsule object's collider component selected, drag the colored arrow gizmos to change dimensions directly. For a cuboid, red = Bevy X, green = Bevy Y (Blender Z), blue = Bevy Z (Blender -Y). For a sphere, red adjusts radius. For a capsule, red adjusts radius and green adjusts the overall top extent, changing cylinder height. The component fields and exported GLB metadata update together.

**Note:** The local XYZ size fields for primitive colliders are specified in **Bevy coordinates (Y up)**. Blender's viewport is Z up. Avoid non-uniform object scale for predictable physics; apply transforms where appropriate. Gizmo changes are undoable as Blender property edits, but should be validated interactively in your Blender build.

## What is stored in the file?

Blender stores the editable component settings in its native `.blend` object properties and mirrors them to the object's `bevy_components` custom property as a JSON **string**. The glTF exporter includes this property in each node's `extras`. For example:

```json
{
  "name": "lamp_lod_0",
  "extras": {
    "bevy_components": "{\"version\":1,\"components\":[{\"type\":\"visibility_range\",\"start\":[0,0],\"end\":[20,25],\"use_aabb\":false}]}"
  }
}
```

The companion Rust importer parses these values and adds ECS components to scene entities. You **do not need Skein**. It is a deliberately smaller, fixed-schema solution, not automatic Rust reflection or arbitrary component registration like Jackdaw or Skein.

The exported GLB also contains whatever ordinary Blender glTF 2.0 export supports: objects, transforms, compatible PBR materials, embedded textures, and optionally lights/animations/cameras. There is no automatic LOD mesh generation or mesh streaming; you author separate LOD objects, and all meshes remain loaded in memory.

## Caveats / troubleshooting

- Use Blender's dedicated export command to avoid forgetting the **Custom Properties** checkbox. Normal File → Export → glTF also works if Custom Properties is enabled and the object has been edited/saved since the addon was enabled.
- Collider generation requires the Rust importer plus Avian physics; GLB metadata alone cannot create runtime colliders.
- Collider on a parent with many mesh children creates a collider for every child. Keep collider metadata on your collision mesh or single highest-detail mesh rather than a parent of all LOD meshes.
- Each LOD mesh must line up spatially. Keep origins aligned; `use_aabb` defaults to false.
- When hiding LOD models in Blender, be careful about export filters (hidden or unselected models might be excluded). The dedicated exporter defaults to exporting **all** objects.
- Custom component JSON is exported and exposed to game code; it is not inserted as a Rust type automatically.
- The dedicated exporter validates fade-distance order and JSON fields but cannot test physics validity until the game loads the meshes.
- This release passes Python metadata and viewport-geometry unit tests and compileall syntax checks, but **has not been run in Blender or compiled with Bevy**, which are unavailable in this packaging environment. In particular, the actual Blender gizmo interaction should be smoke-tested in Blender 4.2/4.5/5.x. Report Blender console errors if any.

## Files

- `bevy_components/`: Blender addon package, including `viewport.py` draw handlers/gizmos and pure-Python `geometry.py`
- `bevy_importer/`: Rust companion crate
- `tests/`: pure Python tests for serialization

## References

- Jackdaw: https://jbuehler23.github.io/jackdaw/developer-guide/custom-components.html
- Blender glTF exporter: https://docs.blender.org/api/current/bpy.ops.export_scene.html
- Bevy glTF extras: https://bevy.org/examples/gltf/load-gltf-extras/
- Bevy visibility range: https://bevy.org/examples/3d-rendering/visibility-range/
- Avian 0.8: https://docs.rs/avian3d/

- Blender 4.2 Python gizmo examples: https://docs.blender.org/api/4.2/bpy.types.Gizmo.html
- Blender GPU drawing examples: https://docs.blender.org/api/current/gpu.html

## Repository development

This is a standard Blender **extension** (see `bevy_components/blender_manifest.toml`), not a single-file script. Build an installable ZIP using:

```sh
python scripts/build_addon.py
```

The output ZIP has `__init__.py` and `blender_manifest.toml` at its root, which Blender expects for extensions. Source is under `bevy_components/`, the standalone runtime importer is under `bevy_importer/`, and CI runs Python tests, packaging, and a Rust `cargo check`. The addon uses only Blender's bundled Python modules.

See [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md), and [LICENSE](LICENSE) (MIT).
