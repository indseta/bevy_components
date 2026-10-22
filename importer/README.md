# Bevy Components importer

Reads the `bevy_components` glTF extras exported by the Blender addon and inserts the matching Bevy and Avian components. See the [main README](../README.md) for installation.

- **Visibility Range**: `VisibilityRange` on mesh descendants of the object.
- **Collider**: cuboid, sphere and capsule colliders go on the object itself, so they also work on empties. Triangle mesh and convex hull colliders are built from each mesh under the object. Each collider gets Avian `Friction`, `Restitution` and `CollisionLayers`. Layer N is bit N of `LayerMask`, so it matches the Nth variant, counting from 0, of a `#[derive(PhysicsLayer)]` enum. Defaults to a static body when neither the object nor a parent has a Rigid Body.
- **Rigid Body**: Avian `RigidBody` on the object. A set Mass on a dynamic body becomes `Mass` plus `NoAutoMass`, so it is the total mass of the body and its child colliders. Without one, Avian computes the mass from the collider volumes at 1 kg per cubic meter. Colliders on child objects join the nearest parent's body, so an empty with a Rigid Body can hold child empties that each carry a collider shape.
- **Custom**: `BlenderCustomComponents` with the type path and JSON value, for your game to map to its own components.
- **Compressed textures**: KTX2 textures from the exporter's Texture Compression option are converted at load time to ASTC, BC7, ETC2 or RGBA, whichever the GPU supports, without changing how you load the level.
