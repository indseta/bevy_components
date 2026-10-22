import re
import textwrap
from collections import namedtuple

import bpy
from mathutils import Matrix, Quaternion, Vector

from .metadata import EXTRAS_KEY, component_errors, visibility_range_problems
from .system import MESH_TYPES, children_map, component_of, components_for, has_faces, inherited, mesh_sources, subtree

Issue = namedtuple("Issue", ("level", "obj", "item", "message"))

TYPE_PATH = re.compile(r"[A-Za-z_]\w*(::[A-Za-z_]\w*)*(<.+>)?")
SHAPE_LABELS = {
    "TRIMESH": "Triangle Mesh",
    "CONVEX": "Convex Hull",
}


def describe(issue):
    return f"{issue.obj.name}: {issue.message}"


def count(number, word):
    return f"{number} {word}" if number == 1 else f"{number} {word}s"


def issue_summary(issues):
    errors = sum(1 for issue in issues if issue.level == "ERROR")
    return ", ".join(count(number, word) for number, word in ((errors, "error"), (len(issues) - errors, "warning")) if number)


def draw_message(layout, text, icon="ERROR", width=300):
    scale = (bpy.context.preferences.system.ui_scale if bpy.context.preferences else 0.0) or 1.0
    column = layout.column(align=True)
    for index, line in enumerate(textwrap.wrap(text, max(20, int((width - 40) / (7 * scale))))):
        column.label(text=line, icon=icon if index == 0 else "BLANK1")


def draw_issues(layout, rows, limit, more, select=False, width=300):
    for level, name, message in rows[:limit]:
        icon = "CANCEL" if level == "ERROR" else "ERROR"
        if select:
            layout.operator("bevy_components.select_object", text=f"{name}: {message}", icon=icon).name = name
        else:
            draw_message(layout, f"{name}: {message}", icon, width)
    if len(rows) > limit:
        layout.label(text=f"{len(rows) - limit} more {more}", icon="BLANK1")


def check_objects(objects):
    objects = list(objects)
    children = children_map(objects)
    issues = []
    for obj in objects:
        issues.extend(_object_issues(obj, children))
    issues.extend(_visibility_range_issues(objects))
    return issues


def check_object(obj, objects):
    objects = list(objects)
    return _object_issues(obj, children_map(objects)) + _visibility_range_issues(objects, obj)


def _object_issues(obj, children):
    issues = []
    custom_types = set()
    for item in components_for(obj):
        issues.extend(Issue("ERROR", obj, item, error) for error in component_errors(item))
        if item.component_type == "COLLIDER":
            issues.extend(Issue("WARNING", obj, item, message) for message in _collider_warnings(obj, item, children))
        elif item.component_type == "RIGID_BODY":
            issues.extend(Issue("WARNING", obj, item, message) for message in _rigid_body_warnings(obj, item, children))
        elif item.component_type == "VISIBILITY_RANGE":
            issues.extend(Issue("WARNING", obj, item, message) for message in _visibility_range_warnings(obj, item, children))
        elif item.component_type == "CUSTOM" and item.custom_type.strip():
            if not TYPE_PATH.fullmatch(item.custom_type):
                issues.append(Issue("WARNING", obj, item, f"\"{item.custom_type}\" is not a Rust type path such as my_game::Health"))
            if item.custom_type in custom_types:
                issues.append(Issue("WARNING", obj, item, f"Added more than once, but an entity holds only one {item.custom_type}"))
            custom_types.add(item.custom_type)
    return issues


def _collider_warnings(obj, item, children):
    warnings = []
    targets = [obj]
    if item.collider_shape in SHAPE_LABELS:
        sources = [source for source, _matrix in mesh_sources(obj, children, "COLLIDER")]
        if not sources:
            warnings.append(f"No mesh on this object or under it, so no {SHAPE_LABELS[item.collider_shape]} collider is built")
        if item.collider_shape == "TRIMESH":
            bodies = [owner for owner, body in (inherited(source, "RIGID_BODY") for source in sources) if body is not None and body.rigid_body_kind == "DYNAMIC"]
            if bodies:
                warnings.append("Triangle meshes collide poorly on Dynamic bodies, use Convex Hull" if bodies[0] == obj else f"Triangle meshes collide poorly on Dynamic bodies such as {bodies[0].name}, use Convex Hull")
        targets = [source for source, _matrix in mesh_sources(obj, children, "COLLIDER", instances=False)]
    for target in targets:
        ancestor = _uneven_scale_ancestor(target)
        if ancestor is not None:
            warnings.append(f"{'This' if target == obj else target.name} is rotated inside {ancestor.name}, which is scaled unevenly, so the game sizes its collider wrong. Apply scale to {ancestor.name}")
            break
    return warnings


def _rigid_body_warnings(obj, item, children):
    warnings = []
    if item.rigid_body_kind == "DYNAMIC" and not any(_has_collider(member) for member, _matrix in subtree(obj, children, lambda child: component_of(child, "RIGID_BODY") is not None)):
        warnings.append("Dynamic body has no collider on it or under it, so it has no mass and collides with nothing")
    parent, body = inherited(obj.parent, "RIGID_BODY")
    if body is not None and body.rigid_body_kind != "STATIC":
        warnings.append(f"Moves on its own instead of with {parent.name}. Remove this Rigid Body to make {parent.name} one compound body")
    return warnings


def _visibility_range_warnings(obj, item, children):
    warnings = []
    if not mesh_sources(obj, children, "VISIBILITY_RANGE"):
        warnings.append("No mesh on this object or under it to show or hide")
    if not component_errors(item) and item.fade_out_end <= item.fade_in_start:
        warnings.append(f"Never visible, because Fade Out End is {item.fade_out_end:g} m")
    return warnings


def _visibility_range_issues(objects, only=None):
    if only is not None and component_of(only, "VISIBILITY_RANGE") is None:
        return []
    groups = {}
    for obj in objects:
        if only is not None and "visibility_range" not in str(obj.get(EXTRAS_KEY, "")) and obj != only:
            continue
        item = component_of(obj, "VISIBILITY_RANGE")
        if item is not None and not component_errors(item):
            groups.setdefault(_range_origin(obj, item), []).append((obj, item))
    issues = []
    for members in groups.values():
        if len(members) < 2:
            continue
        lookup = {obj.name: (obj, item) for obj, item in members}
        for name, message in visibility_range_problems([(obj.name, (item.fade_in_start, item.fade_in_end, item.fade_out_start, item.fade_out_end)) for obj, item in members]):
            obj, item = lookup[name]
            if only is None or obj == only:
                issues.append(Issue("WARNING", obj, item, message))
    return issues


def _range_origin(obj, item):
    point = obj.matrix_world.translation
    if item.use_aabb and obj.type in MESH_TYPES:
        point = obj.matrix_world @ (sum((Vector(corner) for corner in obj.bound_box), Vector()) / 8)
    return tuple(round(value, 3) for value in point)


def _has_collider(obj):
    if component_of(obj, "COLLIDER") is not None:
        return True
    _owner, collider = inherited(obj, "COLLIDER")
    return collider is not None and collider.collider_shape in SHAPE_LABELS and has_faces(obj)


def _uneven_scale_ancestor(obj):
    if obj.parent is None:
        return None
    chain = []
    current = obj
    while current is not None:
        chain.append(current)
        current = current.parent
    rotation = Quaternion()
    scale = Vector((1.0, 1.0, 1.0))
    for node in reversed(chain):
        local = node.matrix_world if node.parent is None else node.parent.matrix_world.inverted_safe() @ node.matrix_world
        _translation, local_rotation, local_scale = local.decompose()
        rotation = rotation @ local_rotation
        scale = Vector([total * part for total, part in zip(scale, local_scale)])
    actual = obj.matrix_world.to_3x3()
    approximated = rotation.to_matrix() @ Matrix.Diagonal(scale)
    size = max(1.0, max(abs(value) for row in actual for value in row))
    if all(abs(first - second) <= 0.001 * size for row, other in zip(actual, approximated) for first, second in zip(row, other)):
        return None
    for ancestor in chain[1:]:
        values = [abs(value) for value in ancestor.matrix_local.to_scale()]
        if max(values) > 1.001 * min(values):
            return ancestor
    return obj.parent
