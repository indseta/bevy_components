import json
from pathlib import Path

from .metadata import FIELD_ZEROS, convert_value, variant_names

SCHEMA_FILE = "bevy_components_schema.json"
SCHEMA_VERSION = 1
FIELD_KINDS = {
    "float": "FLOAT",
    "int": "INT",
    "bool": "BOOL",
    "string": "STRING",
    "vector2": "VECTOR2",
    "vector": "VECTOR",
    "color": "COLOR",
    "enum": "ENUM",
}


class SchemaError(Exception):
    pass


class GameField:
    def __init__(self, name, field_type, rust_type, variants, default):
        self.identifier = name
        self.name = name
        self.field_type = field_type
        self.rust_type = rust_type
        self.variants = variants
        self.default = default


class GameType:
    def __init__(self, name, fields, others, has_default):
        self.name = name
        self.fields = fields
        self.others = others
        self.has_default = has_default


def short_name(type_path):
    base = type_path.split("<", 1)[0]
    return base.rsplit("::", 1)[-1] + type_path[len(base):]


def parse_schema(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise SchemaError(f"It is not valid JSON: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("components"), list):
        raise SchemaError("It lists no components")
    if data.get("version") != SCHEMA_VERSION:
        raise SchemaError(f"It has version {data.get('version')}, and this add-on reads version {SCHEMA_VERSION}")
    types = {}
    for entry in data["components"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("type_path"), str) or not isinstance(entry.get("fields"), list) or not all(isinstance(field, dict) for field in entry["fields"]):
            raise SchemaError("A component has no type path or fields")
        fields = []
        others = []
        for field in entry["fields"]:
            name = str(field.get("name", ""))
            rust_type = str(field.get("rust_type", ""))
            kind = FIELD_KINDS.get(field.get("type"))
            if kind is None:
                others.append((name, rust_type))
                continue
            variants = ", ".join(variant for variant in field.get("variants", ()) if isinstance(variant, str)) if kind == "ENUM" else ""
            default = convert_value(kind, field.get("default"))
            if kind == "ENUM" and default not in variant_names(variants):
                default = next(iter(variant_names(variants)), "")
            fields.append(GameField(name, kind, rust_type, variants, FIELD_ZEROS[kind] if default is None else default))
        types[entry["type_path"]] = GameType(entry["type_path"], fields, others, entry.get("has_default") is True)
    return types


def find_schema(directory):
    folder = Path(directory)
    for candidate in (folder, *folder.parents):
        if (candidate / SCHEMA_FILE).is_file():
            return candidate / SCHEMA_FILE
    return None
