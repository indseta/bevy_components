from collections import namedtuple

import bpy
from bpy.app.handlers import persistent

from .metadata import serialize_component
from .native import MESH_TYPES

COLLECTION_KINDS = ("CUSTOM", "NAVIGATION", "VISIBILITY_RANGE")
MEMBER_TYPES = MESH_TYPES | {"EMPTY"}
CHANGES = [0]

Entry = namedtuple("Entry", ("collection", "item", "rivals"))

_index = {"key": None, "members": {}, "inner": {}, "entries": {}, "left_out": {}}


@persistent
def collections_changed(*_arguments):
    CHANGES[0] += 1


def component_key(item):
    return (item.component_type, item.custom_type) if item.component_type == "CUSTOM" else item.component_type


def from_collection(item):
    return isinstance(getattr(item, "id_data", None), bpy.types.Collection)


def receives(obj, kind):
    return kind == "CUSTOM" or obj.type in MEMBER_TYPES


def _value(item):
    try:
        return serialize_component(item)
    except ValueError:
        return None


def _refresh():
    key = (CHANGES[0], len(bpy.data.collections))
    if _index["key"] == key:
        return _index
    members = {}
    inner = {}
    left_out = {}
    for collection in bpy.data.collections:
        if collection.bevy_component_data.leave_out:
            for obj in collection.all_objects:
                left_out.setdefault(obj.as_pointer(), collection)
        if not any(item.enabled and item.component_type in COLLECTION_KINDS for item in collection.bevy_component_data.components):
            continue
        for obj in collection.all_objects:
            members.setdefault(obj.as_pointer(), []).append(collection)
        inner[collection.as_pointer()] = {child.as_pointer() for child in collection.children_recursive}
    _index.update(key=key, members=members, inner=inner, entries={}, left_out=left_out)
    return _index


def left_out_by(obj):
    data = getattr(obj, "bevy_component_data", None)
    if data is None:
        return None
    if data.leave_out:
        return obj
    index = _refresh()
    return index["left_out"].get(obj.as_pointer()) if index["left_out"] else None


def left_out(obj):
    return left_out_by(obj) is not None


def collection_entries(obj):
    index = _refresh()
    if not index["members"] or left_out(obj):
        return []
    pointer = obj.as_pointer()
    if pointer not in index["entries"]:
        index["entries"][pointer] = _entries(obj, index["members"].get(pointer, ()), index["inner"])
    return index["entries"][pointer]


def _entries(obj, collections, inner):
    found = {}
    for collection in sorted(collections, key=lambda collection: collection.name_full):
        for item in collection.bevy_component_data.components:
            if item.enabled and item.component_type in COLLECTION_KINDS and receives(obj, item.component_type):
                found.setdefault(component_key(item), {}).setdefault(collection.as_pointer(), (collection, item))
    entries = []
    for sources in found.values():
        innermost = [source for pointer, source in sources.items() if inner[pointer].isdisjoint(sources)]
        collection, item = innermost[0]
        value = _value(item)
        entries.append(Entry(collection, item, [other for other, other_item in innermost[1:] if _value(other_item) != value]))
    return entries


def inherited_entries(obj, items):
    keys = {component_key(item) for item in items}
    return [entry for entry in collection_entries(obj) if component_key(entry.item) not in keys]


def with_collections(obj, items):
    return items + [entry.item for entry in inherited_entries(obj, items)]
