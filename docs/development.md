# Development

`addon/` holds the Blender extension and `importer/` the Rust crate.

```sh
python -m unittest discover -s tests
python scripts/build_addon.py
cargo test --manifest-path importer/Cargo.toml
```

The Blender tests install the built addon into Blender's `bpy` module, build a sample scene and export it. `bpy` only installs on the Python version its Blender ships with (3.11 for 4.2, 3.13 for 5.1 and later):

```sh
pip install bpy==4.2.23
python tests/blender/run.py
```

The importer tests load `importer/tests/assets/sample_scene.glb` and its compressed copies `sample_scene_etc1s.glb`, `sample_scene_uastc.glb` and `sample_scene_automatic.glb`, plus the `props/windmill.glb` prop that the sample scene references and the `props/lamp_post.glb` and `props/lantern.glb` prefabs it writes, which `python tests/blender/sample_scene.py` regenerates (it needs KTX-Software). The Blender tests fail if they no longer match a fresh export. The sample scene takes two of its components from `importer/tests/assets/bevy_components_schema.json`, which `BEVY_COMPONENTS_WRITE_SCHEMA=1 cargo test --manifest-path importer/Cargo.toml --test schema` writes from the test crate's types. The texture compression tests are skipped when KTX-Software is missing, unless `BEVY_COMPONENTS_REQUIRE_KTX=1` is set.

The rendering tests compare compressed and uncompressed scenes on a real GPU and check that light probes and fog show up. They are skipped by default. Run them with `cargo test --manifest-path importer/Cargo.toml -- --include-ignored`. On Linux without a GPU, Mesa's `mesa-vulkan-drivers` package provides one in software. Set `BEVY_COMPONENTS_RENDER_OUTPUT` to a folder to save the renders.

## Releases

The addon and importer share one version, kept in `addon/blender_manifest.toml`, `addon/__init__.py` and `importer/Cargo.toml`, and a test checks they match. When CI passes on `main` and the version has no release yet, it publishes a GitHub release with both downloads, with that version's section of [CHANGELOG.md](../CHANGELOG.md) as its notes.

CI runs one Linux job on pull requests and pushes to `main`: the unit tests, the Blender 4.2 and 5.2 tests with KTX-Software, and the importer and GPU rendering tests. Changes to only Markdown files or `LICENSE` skip it. macOS and Windows are not tested in CI.
