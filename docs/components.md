# Components

Physics, lights, shadows, speakers, light probes, fog and animation come from Blender's own settings, see [Physics](#physics), [Lighting](lighting.md) and below. **Properties > Object > Game Components** lists what each object gets from them, and its **Add Component** adds the rest: your game's components, **Navigation**, **Visibility Range**, **Lightmap** and **Scene Reference**, which Blender has no setting for. The same panel sits in **3D Viewport > N > Bevy**, and collections can give components to every object in them, see [Collections](#collections). **Add Component > Physics** adds Blender's Rigid Body and Rigid Body Constraint, and **Advanced** holds the built-in components that replace Blender's settings on one object, such as a collider with its own size. Typing searches every menu. For your game's own components, see [Custom components](custom_components.md). For lights, the sky, fog and light probes, see [Lighting](lighting.md).

## Working with components

Each component works like a modifier: collapse it, untick it to leave it out of the export, or use its dropdown to copy it, copy it to the selected objects, reset or reorder it. Custom components can also be duplicated.

**Leave Out of Bevy** in the panel exports the object as plain glTF, for helper meshes, blockouts and reference objects: its Rigid Body, Constraint, light, speaker, light probe and fog settings and its collections' components stay out of the game, while the components added in the panel still export. A fog box then keeps its mesh, and a light reaches the game the way glTF describes it. The checkbox shows on objects that get something from Blender's settings or a collection. On a collection, under **Properties > Collection > Game Components**, it counts for every object in the collection and the collections inside it, and the object's panel names the collection that leaves it out.

**Copy Components** puts the active object's components on the clipboard and **Paste Components** adds them to the selected objects, also in another .blend file. Pasting replaces components of the same type. **Add Component > Presets > Save Components as Preset** keeps a set of components for every .blend file, and picking the preset adds them to the selected objects. Presets are JSON files in Blender's `scripts/presets/bevy_components` folder. Copying, presets and **Copy All to Selected** also carry the Blender settings the game reads: the Rigid Body and Rigid Body Constraint with their Bevy settings, Shadow and Receive Shadows, Autoplay, and the Bevy settings of a light, speaker or light probe. Rigid bodies only go to meshes, and light, speaker and probe settings only to objects of that type.

**3D Viewport > N > Bevy > Scene Overview** lists the objects with components, filtered by type or name, and clicking one selects it. **Select > Select by Bevy Component** selects them all at once. The Components and Bevy panel headers count the scene's errors and warnings and open the full list when clicked. The viewport labels the selected objects with what their components do, and other objects with their name and custom components. The **Object** menu and the right-click menu in the 3D Viewport have a **Bevy Components** submenu with these tools and Export Again, and F3 finds them too.

## Collections

**Properties > Collection > Game Components** gives its components to every object in the collection and in the collections inside it, also objects added later. Collections take custom and game components, **Navigation** and **Visibility Range**: a Walkable collection tags all the ground meshes in it, and a LOD1 collection fades its meshes alike. Navigation and Visibility Range go to the meshes, curves, text and empties in the collection, custom components to every object.

- Link objects to a collection with **Ctrl+L > Link to Collection** instead of moving them, so they stay in their other collections. Hiding or excluding a collection also hides the objects that are only in it.
- A component on the object replaces the collection's, and so does one from a collection inside it. Custom components count as the same when their type path is. When two collections that are not inside one another give an object the same component with different settings, it uses the one from the first collection by name and the checks warn.
- The object's Game Components panel lists what it gets from which collection, and the button next to each row shows that collection.
- A collection linked from another .blend file brings its components along. Edit them in that file.

## Viewport previews

Previews are editor-only and are not exported. Set them up under **Overlays > Bevy Components** in the 3D Viewport header. They show while the **Game Components** panel in Properties is expanded.

Handles on the selected object resize colliders, visibility ranges, light ranges, audio ranges, fog volumes and probes, and the dot in a collider moves its offset. Ctrl+Z undoes a drag. Joints show their axis and limits, and also show when one of their bodies is selected. Arrows show the velocity bodies start with. Triangle Mesh and Convex Hull Collider components are built from every mesh on or under the object, Blender's Mesh and Convex Hull shapes from the object's own mesh, and Convex Hull previews draw the hull the game gets, one per material. Blender's Rigid Body shapes show in the same colors as Collider components.

## Physics

Physics uses Blender's own **Rigid Body** and **Rigid Body Constraint** in **Properties > Physics**, and the export turns them into Avian components. **Add Component > Physics** has both at the top.

- **Rigid Body**: Active becomes a dynamic body, Passive a static one and **Animated** a kinematic one. An Active body with **Dynamic** turned off is static. Mass, friction, bounciness and damping go to the game unchanged, though Avian averages friction and bounciness between two colliders where Blender multiplies them.
- **Shape**: Box, Sphere, Capsule, Cylinder and Cone take their size from the mesh and sit on the object's origin, as they do in Blender. Convex Hull and Mesh use the object's own mesh, not its children's. **Compound Parent** makes one body from the direct children that have a Rigid Body: only their shapes count.
- **Collision Collections** become Avian collision layers 0 to 19, so two objects collide when they share a collection.
- **Rigid Body Constraint**: Fixed, Point, Hinge and Slider become Avian's fixed, ball, hinge and slider joints with their limits. A hinge turns around the constraint object's Z axis and a slider moves along its X axis. Piston, Generic, Generic Spring and Motor have no Avian joint, so the game leaves them out.
- **Scene > Gravity**: when the scene has a Rigid Body World and its gravity differs from Earth's, the scene sets Avian's `Gravity` when it loads, and the gravity from before comes back when the scene is despawned or reloads without it.

**Object > Rigid Body > Copy from Active with Bevy Settings** copies the active object's Rigid Body to the selected meshes like Blender's **Copy from Active**, and also its Bevy settings, which Blender's leaves out.

Each of those panels has a **Bevy** subpanel for what Blender lacks: mass from volume, gravity scale, swept CCD, locked axes and a starting velocity and spin under Rigid Body; Sensor, Collision Events, Collision Only and **Bevy Layers** (Avian's 32 layers, with separate Belongs To and Collides With) under Collisions; and the ball joint's swing limit and damping under Rigid Body Constraint. Axes there are Blender's.

The export writes bodies where the simulation starts, also when the timeline is on a later frame.

### Physics components

The **Collider**, **Rigid Body** and **Joint** components, under **Add Component > Advanced**, cover what Blender's physics cannot: an empty that holds child colliders, a collider with an offset or another size than the mesh, a mesh collider that covers child meshes, or joints along other axes. A component replaces Blender's setting of the same kind on that object.

**Collider** adds an Avian cuboid, sphere, capsule, cylinder, cone, convex hull or triangle mesh collider, or a sensor. Sizes and offsets are in Bevy coordinates (Y up), and **Fit to Mesh** sets them from the meshes on and under the object. Colliders also set friction, restitution and collision layers 0 to 31, the same numbers as Avian's layer bits. Name the layers in **Properties > Scene > Bevy Collision Layers** to see the names in every Collider.

- **Collision Events** adds Avian's `CollisionEventsEnabled`, so the collider sends `CollisionStart` and `CollisionEnd`. It is on by default for sensors.
- **Collision Only** hides the meshes on and under the object in the game with `Visibility::Hidden` and keeps their colliders, for invisible walls.
- An empty with a **Rigid Body** can hold child objects that each carry a collider; they all join its body.

**Rigid Body** makes the object Static, Dynamic or Kinematic. Dynamic bodies can set a total mass, gravity scale, damping, locked axes and continuous collision, and moving bodies can start with a velocity and spin. Objects with a Collider and no Rigid Body on them or a parent become static bodies.

**Joint** connects two bodies with an Avian Fixed, Hinge, Slider or Ball joint. Put it on an empty at the pivot, or on one of the bodies, and pick Body 1 and Body 2 from objects with a Rigid Body or Collider. Leave one empty to pin the other to that spot in the scene. The object's position and its Axis set the pivot, and limits count from where the bodies sit in Blender.

## Rendering

**Visibility Range** fades the meshes on and under the object in and out by camera distance, for levels of detail. Its LOD0, LOD1 and LOD2 presets set fades that crossfade with the neighbouring levels, and handles in the viewport drag the distances.

**Shadows** follow **Properties > Object > Visibility**: a mesh whose Ray Visibility **Shadow** is off casts no shadows in the game, and one with **Bevy > Receive Shadows** off receives none. The **Shadows** component (under Advanced) turns them off for every mesh on and under an object.

## Audio, animation and scenes

A **Speaker** plays its sound in the game. Keep the sound file in your game's `assets` folder, since the game loads it from its path there, such as `sounds/fire.ogg`. Volume, Pitch (the playback speed) and Distance Reference carry over, a muted speaker is left out, and **Properties > Speaker > Bevy** sets Loop, Autoplay and Spatial. Spatial sounds play at full volume within their distance and fade beyond it. The viewport shows that distance and the one where the sound is down to 1% as spheres, with an arrow to drag the distance.

The **Audio Player** component plays a sound on any object, and its folder button fills in the path from a picked file.

**Autoplay** in the Game Components panel plays the object's active action when the scene loads, at a Speed where 1 matches Blender. **Loop** next to it sets the action's Cyclic Animation, which makes the game repeat it. The **Animation** component plays another clip, such as one that animates the object's children. Keep **Include Animations** on in the export; each clip starts at its first keyframe.

**Scene Reference** spawns a scene from another glTF file at the object, like a prefab: export the prop as its own Bevy scene, then point an empty at it. The path is stored relative to the exported scene, so keep both in your game's `assets` folder. The viewport draws the bounds of the referenced scene. [Prefabs](exporting.md#prefabs) do the same for collection instances and export the prop for you.

## Navigation

**Navigation** tags the meshes and colliders on and under an object for a navmesh crate, unless a closer object has its own Navigation:

- **Walkable** for ground that agents walk on, imported as `NavigationWalkable`. Its **Cost** says how much agents avoid it when they find a path: 1 for plain ground, 3 for mud, 0.5 for a road.
- **Obstacle** for walls, crates and trees that agents go around, imported as `NavigationObstacle`.
- **Ignored** to leave an object out, such as a small prop on walkable ground under a tagged parent.

The viewport draws the faces of walkable ground that slope less than 45° and the bounds of obstacles. The importer only tags entities and builds no navmesh. No navmesh crate supports Bevy 0.20 yet (checked in October 2026: vleue_navigator 0.16, bevy_rerecast 0.5 and bevy_landmass 0.12 are on Bevy 0.19, oxidized_navigation on 0.15). Once one does, hand it the tagged entities:

- **bevy_rerecast** builds the navmesh from the tagged meshes alone with `NavmeshSettings { filter: Some(tagged.iter().collect()), ..default() }`, where `tagged` is a `Query<Entity, Or<(With<NavigationWalkable>, With<NavigationObstacle>)>>`.
- **vleue_navigator** cuts tagged obstacles out of the navmesh with `NavmeshUpdaterPlugin::<Collider, NavigationObstacle>`, and takes the walkable ground from `NavMesh::from_bevy_mesh` of a walkable mesh.
- **oxidized_navigation** reads colliders that have its `NavMeshAffector`, so insert one on each entity with a `Collider` and a navigation tag.
- **bevy_landmass** uses a navmesh from one of these, and its type index costs can come from `NavigationWalkable::cost`.

See the [importer README](../importer/README.md) for exactly what each component becomes in Bevy.

## Converting older files

**Bevy Components > Convert Components to Blender** in the 3D Viewport's Object and right-click menus replaces components with Blender's own settings wherever the game gets the same result. It keeps the components it cannot replace and lists those objects with the reason, such as a collider offset or a hinge on another axis.

- Collider, Rigid Body and Joint become Blender's Rigid Body and Rigid Body Constraint. A collider on the default layers moves to Collision Collection 0, unless another collider in the scene relies on touching it from another layer; then it keeps those layers under Bevy Layers.
- Light, Shadows and Animation move to the light's Bevy settings, the mesh's Shadow and Receive Shadows, and Autoplay with the action's Cyclic Animation. A light keeps its component when other lights share its light data.
- Audio Player, Fog Volume, Reflection Probe and Irradiance Volume become a Speaker, a box with a Principled Volume, or a Light Probe, added as a child of the object. A Speaker needs the sound in the game's `assets` folder and a volume up to 1. The fog box's density and absorption can differ from the component's, while the light it scatters and dims stays the same.
