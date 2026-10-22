"""Inspect Bevy Components metadata stored in the glTF JSON chunk of a .glb file."""

import json
import struct
import sys
from pathlib import Path


def inspect(path):
    raw = Path(path).read_bytes()
    if raw[:4] != b"glTF" or len(raw) < 20:
        raise ValueError("Not a valid GLB header")
    version, length = struct.unpack_from("<II", raw, 4)
    if version != 2 or length != len(raw):
        raise ValueError("Unsupported GLB version or length")
    chunk_length, chunk_type = struct.unpack_from("<I4s", raw, 12)
    if chunk_type != b"JSON":
        raise ValueError("Expected a JSON glTF chunk")
    gltf = json.loads(raw[20:20 + chunk_length])
    count = 0
    for node in gltf.get("nodes", []):
        raw_components = node.get("extras", {}).get("bevy_components")
        if raw_components is None:
            continue
        parsed = json.loads(raw_components) if isinstance(raw_components, str) else raw_components
        print(f'{node.get("name", "<unnamed node>")}:')
        for component in parsed.get("components", []):
            print("  -", component)
            count += 1
    print(f"Found {count} Bevy component(s) in {path}")
    return count


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python inspect_glb.py path/to/level.glb")
        sys.exit(2)
    inspect(sys.argv[1])
