# Bevy Components importer

Reads the `bevy_components` glTF extras exported by the Blender addon and inserts the matching Bevy and Avian components. See the [main README](../README.md) for installation.

- **Visibility Range**: `VisibilityRange` on mesh descendants of the object.
- **Collider**: cuboid, sphere and capsule colliders go on the object itself, so they also work on empties. Triangle mesh and convex hull colliders are built from each mesh under the object. Defaults to a static body without a Rigid Body.
- **Rigid Body**: Avian `RigidBody` on the object.
- **Spawn Point**: `BlenderSpawnPoint(tag)` on the object.
- **Custom**: `BlenderCustomComponents` with the type path and JSON value, for your game to map to its own components.
