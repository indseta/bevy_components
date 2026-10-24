import os
import re
from pathlib import Path

WORDS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def inside(path, root):
    try:
        Path(os.path.abspath(path)).relative_to(os.path.abspath(root))
    except ValueError:
        return False
    return True


def write_if_changed(path, data):
    path = Path(path)
    try:
        if path.read_bytes() == data:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.tmp")
    try:
        staging.write_bytes(data)
        os.replace(staging, path)
    except OSError:
        staging.unlink(missing_ok=True)
        raise
    return True


def snake_case(text):
    words = WORDS.findall(text)
    return "_".join(word.lower() for word in words)
