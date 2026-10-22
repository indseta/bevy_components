# Changelog

## Unreleased

- Restyle the addon and importer to the bevy_game conventions, with no behavior changes: the addon is split into property, operator, panel, overlay, gizmo and system modules, and the importer into component, data and system modules.
- CI installs the Linux libraries Bevy needs, so the importer `cargo check` can build.

## 0.2.0 (2026-10-22)

- Initial GitHub source release with Blender extension metadata and build script.
- Component inspector presets for visibility ranges, colliders, rigid bodies, spawn points and custom metadata.
- Per-object glTF extras export and Bevy 0.20 / Avian 0.8 importer.
- Editor-only wireframe collider previews, distance shells, spawn markers and drag-to-resize primitive handles.
- Independently toggleable viewport previews, labels and selection scope.

**Validation:** Python tests and ZIP packaging pass; interactive Blender behavior and Rust crate compilation have not been verified in this environment.
