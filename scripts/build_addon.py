"""Package the Blender extension without requiring Blender to be installed."""

from pathlib import Path
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "bevy_components"


def build():
    meta = tomllib.loads((PACKAGE / "blender_manifest.toml").read_text(encoding="utf-8"))
    version = meta["version"]
    files = [PACKAGE / name for name in ("__init__.py", "metadata.py", "geometry.py", "viewport.py", "blender_manifest.toml")]
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path)
    output = ROOT / "dist" / f"bevy_components-{version}.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=path.name)
    with ZipFile(output) as archive:
        assert len(archive.namelist()) == len(files)
        assert "__init__.py" in archive.namelist()
        assert "blender_manifest.toml" in archive.namelist()
        assert archive.testzip() is None
    print(output)
    return output


if __name__ == "__main__":
    build()
