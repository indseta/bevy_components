# Contributing

Issues and pull requests are welcome. Keep the Blender addon usable without external Python dependencies.

Run checks before submitting:

```sh
python -m unittest discover -s tests -v
python -m compileall -q bevy_components scripts tests
python scripts/build_addon.py
cargo check --manifest-path bevy_importer/Cargo.toml
```

The Rust importer targets Bevy 0.20 and Avian 0.8. Unit tests do not replace an interactive Blender smoke test; describe the Blender version used when reporting UI issues.

Component extras are versioned JSON (`version: 1`). Coordinate format changes to `bevy_components/metadata.py` with `bevy_importer/src/lib.rs` and tests.
