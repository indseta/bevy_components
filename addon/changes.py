import bpy
from bpy.app.handlers import persistent

DATA_TYPES = (bpy.types.Mesh, bpy.types.Curve, bpy.types.Light, bpy.types.Speaker, bpy.types.LightProbe)
SETTING_TYPES = {"BOOLEAN", "INT", "FLOAT", "ENUM", "STRING"}

_revisions = {}
_identities = {}
_members = {}
_settings = {}
_counter = [0]
_epoch = [0]


def revision(obj):
    return (_epoch[0], _revisions.get(obj.session_uid, 0))


def change_count():
    return (_epoch[0], _counter[0])


def flush_changes():
    try:
        bpy.context.evaluated_depsgraph_get()
    except (AttributeError, RuntimeError):
        pass


def touch(objects):
    _counter[0] += 1
    for obj in objects:
        _revisions[obj.session_uid] = _counter[0]


@persistent
def forget_revisions(*_arguments):
    _epoch[0] += 1
    _revisions.clear()
    _identities.clear()
    _members.clear()


@persistent
def depsgraph_changed(scene, depsgraph):
    touched = set()
    for update in depsgraph.updates:
        owner = update.id.original
        if isinstance(owner, bpy.types.Object):
            identity = _identity(owner)
            if update.is_updated_transform or update.is_updated_geometry or _identities.get(owner.session_uid) != identity:
                touched.add(owner)
            _identities[owner.session_uid] = identity
        elif isinstance(owner, bpy.types.Collection):
            touched.update(_membership_changes(owner))
            touched.update(_instancers(owner))
        elif isinstance(owner, bpy.types.Material):
            touched.update(_material_users({owner}))
        elif isinstance(owner, bpy.types.NodeTree):
            touched.update(_material_users({material for material in bpy.data.materials if material.node_tree == owner}))
        elif isinstance(owner, DATA_TYPES):
            touched.update(obj for obj in bpy.data.objects if obj.data == owner)
    if touched:
        touch(relatives(touched))


def collection_users(collection):
    return [*collection.all_objects, *_instancers(collection)]


def _instancers(collection):
    return [obj for obj in bpy.data.objects if obj.instance_type == "COLLECTION" and obj.instance_collection == collection]


def _identity(obj):
    constraint = getattr(obj, "rigid_body_constraint", None)
    body = getattr(obj, "rigid_body", None)
    return (
        obj.name,
        _uid(obj.parent),
        obj.parent_type,
        tuple(sorted(collection.session_uid for collection in obj.users_collection)),
        obj.instance_type,
        _uid(obj.instance_collection),
        _uid(obj.data),
        tuple(_uid(slot.material) for slot in obj.material_slots),
        obj.hide_render,
        obj.hide_viewport,
        obj.visible_shadow,
        (_uid(constraint.object1), _uid(constraint.object2), _values(constraint)) if constraint is not None else None,
        _values(body) if body is not None else None,
    )


def _values(struct):
    names = _settings.get(type(struct))
    if names is None:
        names = _settings[type(struct)] = tuple(prop.identifier for prop in struct.bl_rna.properties if prop.type in SETTING_TYPES and prop.identifier != "rna_type")
    return tuple(_value(getattr(struct, name)) for name in names)


def _value(value):
    return tuple(value) if hasattr(value, "__len__") and not isinstance(value, str) else value


def _uid(data):
    return data.session_uid if data is not None else 0


def _membership_changes(collection):
    current = {obj.session_uid: obj for obj in collection.all_objects}
    known = _members.get(collection.session_uid)
    _members[collection.session_uid] = frozenset(current)
    if known is None:
        return list(current.values())
    changed = [obj for uid, obj in current.items() if uid not in known]
    removed = known - current.keys()
    if removed:
        changed.extend(obj for obj in bpy.data.objects if obj.session_uid in removed)
    return changed


def relatives(objects):
    found = set(objects)
    children = {}
    for obj in bpy.data.objects:
        if obj.parent is not None:
            children.setdefault(obj.parent, []).append(obj)
    pending = list(found)
    while pending:
        obj = pending.pop()
        for child in children.get(obj, ()):
            if child not in found:
                found.add(child)
                pending.append(child)
    for obj in list(found):
        parent = obj.parent
        while parent is not None and parent not in found:
            found.add(parent)
            parent = parent.parent
    return found


def _material_users(materials):
    return [obj for obj in bpy.data.objects if any(slot.material in materials for slot in obj.material_slots)]
