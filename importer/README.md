# Bevy Components importer

Reads the `bevy_components` glTF extras exported by the Blender addon and inserts the matching Bevy and Avian components. See the [main README](../README.md) for installation.

- **Visibility Range**: `VisibilityRange` on mesh descendants of the object.
- **Collider**: Avian collider on each descendant mesh. Defaults to a static body without a Rigid Body.
- **Rigid Body**: Avian `RigidBody` on the object.
- **Spawn Point**: `BlenderSpawnPoint(tag)` on the object.
- **Custom**: `BlenderCustomComponents` with the type path and JSON value, for your game to map to its own components.
