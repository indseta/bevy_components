import bpy
from bpy.app.handlers import persistent

DATA_TYPES = (bpy.types.Mesh, bpy.types.Curve, bpy.types.Light, bpy.types.Speaker, bpy.types.LightProbe)

_revisions = {}
_counter = [0]
_epoch = [0]


def revision(obj):
    return (_epoch[0], _revisions.get(obj.session_uid, 0))


def change_count():
    return (_epoch[0], _counter[0])


def touch(objects):
    _counter[0] += 1
    for obj in objects:
        _revisions[obj.session_uid] = _counter[0]


@persistent
def forget_revisions(*_arguments):
    _epoch[0] += 1
    _revisions.clear()


@persistent
def depsgraph_changed(scene, depsgraph):
    touched = set()
    for update in depsgraph.updates:
        owner = update.id.original
        if isinstance(owner, bpy.types.Object):
            touched.add(owner)
        elif isinstance(owner, bpy.types.Collection):
            if not _physics_collection(scene, owner):
                touched.update(collection_users(owner))
        elif isinstance(owner, bpy.types.Material):
            touched.update(_material_users({owner}))
        elif isinstance(owner, bpy.types.NodeTree):
            touched.update(_material_users({material for material in bpy.data.materials if material.node_tree == owner}))
        elif isinstance(owner, DATA_TYPES):
            touched.update(obj for obj in bpy.data.objects if obj.data == owner)
    if touched:
        touch(relatives(touched))


def collection_users(collection):
    return [*collection.all_objects, *(obj for obj in bpy.data.objects if obj.instance_type == "COLLECTION" and obj.instance_collection == collection)]


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


def _physics_collection(scene, collection):
    world = getattr(scene, "rigidbody_world", None)
    return world is not None and collection in (world.collection, world.constraints)


def _material_users(materials):
    return [obj for obj in bpy.data.objects if any(slot.material in materials for slot in obj.material_slots)]
