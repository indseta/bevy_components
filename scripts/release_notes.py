from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/indseta/bevy_components"


def section(changelog, version):
    lines = []
    found = False
    for line in changelog.splitlines():
        if line.startswith("## "):
            if found:
                break
            found = line.split()[1:2] == [version]
            continue
        if found:
            lines.append(line)
    return "\n".join(lines).strip()


def notes(version, changelog):
    name = version.replace(".", "_")
    download = f"Download bevy_components_{name}.zip for the Blender addon and bevy_components_importer_{name}.zip for the Rust importer. See the README for installation."
    changes = re.sub(r"\]\((?!https?://|#)([^)]+)\)", rf"]({REPOSITORY}/blob/bevy_components_{name}/\1)", section(changelog, version))
    return f"{download}\n\n{changes}\n" if changes else f"{download}\n"


if __name__ == "__main__":
    print(notes(sys.argv[1], (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")), end="")
