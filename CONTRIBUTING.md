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

Component extras are versioned JSON (`version: 1`). Coordinate format changes to `bevy_components/metadata.py` with `bevy_importer/src/data.rs`, `bevy_importer/src/system.rs` and tests.

## Style

Code follows the conventions of [bevy_game](https://github.com/indseta/bevy_game):

- Files are split by role. In Rust, `lib.rs` (or a module's `mod.rs`) declares modules, re-exports and builds the plugin, with types in `component.rs` and systems in `system.rs`. The addon mirrors this with `__init__.py` registering classes from `property.py`, `operator.py`, `panel.py`, `gizmo.py`, `overlay.py` and `system.py`.
- No comments or docstrings; names say what things are, in full words.
- Signatures, calls, imports and short arrays stay on one line; struct fields, enum variants and dict entries go one per line. No rustfmt or formatter config.
- Rust functions end in an explicit `return`; skip bad data with `let ... else { continue; };` and a `warn!` sentence.
- Imports are alphabetical by crate or module, then `crate`/relative imports.
- Python uses double quotes.
- Commit messages are a plain capitalized summary with no prefix or trailing period, optionally followed by a prose or bulleted body.
