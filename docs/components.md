# Components

Add components with **Add Component** in **Properties > Object > Components** or **3D Viewport > N > Bevy**. Physics, Rendering and Lighting components sit in submenus, and typing searches them all. For your game's own components, see [Custom components](custom_components.md). For lights, the sky, fog and light probes, see [Lighting](lighting.md).

## Working with components

Each component works like a modifier: collapse it, untick it to leave it out of the export, or use its dropdown to copy it, copy it to the selected objects, reset or reorder it. Custom components can also be duplicated.

**Copy Components** puts the active object's components on the clipboard and **Paste Components** adds them to the selected objects, also in another .blend file. Pasting replaces components of the same type. **Add Component > Presets > Save Components as Preset** keeps a set of components for every .blend file, and picking the preset adds them to the selected objects. Presets are JSON files in Blender's `scripts/presets/bevy_components` folder.

**3D Viewport > N > Bevy > Scene Overview** lists the objects with components, filtered by type or name, and clicking one selects it. **Select > Select by Bevy Component** selects them all at once. The Components and Bevy panel headers count the scene's errors and warnings and open the full list when clicked. The viewport labels the selected objects with what their components do, and other objects with their name and custom components. The **Object** menu and the right-click menu in the 3D Viewport have a **Bevy Components** submenu with these tools and Export Again, and F3 finds them too.

## Viewport previews

Previews are editor-only and are not exported. Set them up under **Overlays > Components** in the 3D Viewport header. They show while the **Components** panel in Properties is expanded. Like Blender's own overlays, they draw through objects in Wireframe and X-Ray, and **In Front** draws them through objects all the time.

Selecting a **Rigid Body** also draws the colliders that join its body, on it and on the objects under it, with thinner lines, and its label counts them. Selecting one of those colliders draws the rest of its body and names the body in its label, and selecting a **Joint** draws the colliders of the bodies it connects.

Handles on the selected object resize colliders, visibility ranges, light ranges, audio ranges, fog volumes and probes, and the dot in a collider moves its offset. Ctrl+Z undoes a drag. Joints show their axis and limits, and also show when one of their bodies is selected. Arrows show the velocity bodies start with. Triangle Mesh and Convex Hull colliders are built from every mesh on or under the object, except levels of detail that only show from farther away, and Convex Hull previews draw the hull the game gets, one per material.

## Physics

**Collider** adds an Avian cuboid, sphere, capsule, cylinder, cone, convex hull or triangle mesh collider, or a sensor. Sizes and offsets are in Bevy coordinates (Y up), and **Fit to Mesh** sets them from the meshes on and under the object. Colliders also set friction, restitution and collision layers 0 to 31, the same numbers as Avian's layer bits. Name the layers in **Properties > Scene > Bevy Collision Layers** to see the names in every Collider.

- **Collision Events** adds Avian's `CollisionEventsEnabled`, so the collider sends `CollisionStart` and `CollisionEnd`. It is on by default for sensors.
- **Collision Only** hides the meshes on and under the object in the game with `Visibility::Hidden` and keeps their colliders, for invisible walls.
- An empty with a **Rigid Body** can hold child objects that each carry a collider; they all join its body.

**Rigid Body** makes the object Static, Dynamic or Kinematic. Dynamic bodies can set a total mass, gravity scale, damping, locked axes and continuous collision, and moving bodies can start with a velocity and spin. Objects with a Collider and no Rigid Body on them or a parent become static bodies.

**Joint** connects two bodies with an Avian Fixed, Hinge, Slider or Ball joint. Put it on an empty at the pivot, or on one of the bodies, and pick Body 1 and Body 2 from objects with a Rigid Body or Collider. Leave one empty to pin the other to that spot in the scene. The object's position and its Axis set the pivot, and limits count from where the bodies sit in Blender.

## Rendering

**Visibility Range** fades the meshes on and under the object in and out by camera distance, for levels of detail. Its LOD0, LOD1 and LOD2 presets set fades that crossfade with the neighbouring levels, and handles in the viewport drag the distances. A Triangle Mesh or Convex Hull collider on the parent of the levels is built from the first level only, the meshes whose Visibility Range starts at 0 m, unless a level has a collider of its own.

**Shadows** stops the meshes on and under an object from casting or receiving shadows.

## Audio, animation and scenes

**Audio Player** plays a sound from your game's `assets` folder, such as `sounds/fire.ogg`, and its folder button fills in that path from a picked file. Spatial sounds play at full volume within their Distance and fade beyond it. The viewport shows that distance and the one where the sound is down to 1% as spheres, with an arrow to drag the distance.

**Animation** plays an action when the scene loads, looping or once, at a speed where 1 matches Blender. It starts out with the object's active action. Keep **Animation** ticked in the export; each clip starts at its first keyframe.

**Scene Reference** spawns a scene from another glTF file at the object, like a prefab: export the prop to its own GLB, then point an empty at it. The path is stored relative to the exported scene, so keep both in your game's `assets` folder. The viewport draws the bounds of the referenced scene. [Prefabs](exporting.md#prefabs) do the same for collection instances and export the prop for you.

## Navigation

**Navigation** tags the meshes and colliders on and under an object for a navmesh crate, unless a closer object has its own Navigation:

- **Walkable** for ground that agents walk on, imported as `NavigationWalkable`. Its **Cost** says how much agents avoid it when they find a path: 1 for plain ground, 3 for mud, 0.5 for a road.
- **Obstacle** for walls, crates and trees that agents go around, imported as `NavigationObstacle`.
- **Ignored** to leave an object out, such as a small prop on walkable ground under a tagged parent.

The viewport draws the faces of walkable ground that slope less than 45° and the bounds of obstacles. The importer only tags entities and builds no navmesh, so hand the tagged entities to a navmesh crate. vleue_navigator 0.17, bevy_rerecast 0.6 and bevy_landmass 0.13 work with Bevy 0.20, while oxidized_navigation is still on Bevy 0.15 (checked in October 2026):

- **bevy_rerecast** builds the navmesh from the tagged meshes alone with `NavmeshSettings { filter: Some(tagged.iter().collect()), ..default() }`, where `tagged` is a `Query<Entity, Or<(With<NavigationWalkable>, With<NavigationObstacle>)>>`.
- **vleue_navigator** cuts tagged obstacles out of the navmesh with `NavmeshUpdaterPlugin::<Collider, NavigationObstacle>`, and takes the walkable ground from `NavMesh::from_bevy_mesh` of a walkable mesh.
- **oxidized_navigation** reads colliders that have its `NavMeshAffector`, so insert one on each entity with a `Collider` and a navigation tag.
- **bevy_landmass** uses a navmesh from one of these, and its type index costs can come from `NavigationWalkable::cost`.

See the [importer README](../importer/README.md) for exactly what each component becomes in Bevy.
