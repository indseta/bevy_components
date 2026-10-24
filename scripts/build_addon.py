from pathlib import Path
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "addon"


def build():
    manifest = tomllib.loads((PACKAGE / "blender_manifest.toml").read_text(encoding="utf-8"))
    version = manifest["version"]
    files = [PACKAGE / name for name in ("__init__.py", "bake.py", "changes.py", "collection.py", "compression.py", "convert.py", "encoder.py", "files.py", "fingerprint.py", "geometry.py", "gizmo.py", "gltf.py", "menu.py", "metadata.py", "native.py", "operator.py", "overlay.py", "panel.py", "play.py", "prefab.py", "preferences.py", "probe.py", "project.py", "property.py", "reference.py", "schema.py", "system.py", "validation.py", "blender_manifest.toml")] + [ROOT / "LICENSE"]
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path)
    output = ROOT / "dist" / f"bevy_components_{version.replace('.', '_')}.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=path.name)
    with ZipFile(output) as archive:
        assert len(archive.namelist()) == len(files)
        assert "__init__.py" in archive.namelist()
        assert "blender_manifest.toml" in archive.namelist()
        assert "LICENSE" in archive.namelist()
        assert archive.testzip() is None
    print(output)
    return output


if __name__ == "__main__":
    build()
