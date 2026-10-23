import decimal
import json
import math
import os
import posixpath
import re
import struct
import tomllib
from collections import namedtuple
from pathlib import Path

EXTRAS_KEY = "bevy_components"
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
NUMBERED = re.compile(r"\.\d+$")
GENERICS = re.compile(r"(?<!::)<")
WORDS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
KEYWORDS = {"Self", "abstract", "as", "async", "await", "become", "box", "break", "const", "continue", "crate", "do", "dyn", "else", "enum", "extern", "false", "final", "fn", "for", "gen", "if", "impl", "in", "let", "loop", "macro", "match", "mod", "move", "mut", "override", "priv", "pub", "ref", "return", "self", "static", "struct", "super", "trait", "true", "try", "type", "typeof", "unsafe", "unsized", "use", "virtual", "where", "while", "yield"}
PREFAB_PREFIX = "object_"
ASSET_ENTRIES = ("Mesh3d(", "MeshMaterial3d::", "Lightmap {")
INDENT = "    "
PLAIN_EXPONENTS = (-5, 15)
LIGHT_RANGE = 20.0
MAX_CASCADES = 4
DEFAULT_MEMBERSHIPS = 1
ALL_LAYERS = 0xFFFFFFFF
DEFAULT_FRICTION = 0.5
DEFAULT_RESTITUTION = 0.0
LIGHTS_EXTENSION = "KHR_lights_punctual"
COLLIDER_SHAPES = {
    "cuboid": "Collider::cuboid({0}, {1}, {2})",
    "sphere": "Collider::sphere({3})",
    "capsule": "Collider::capsule({3}, {4})",
    "trimesh": "ColliderConstructor::TrimeshFromMesh",
    "convex": "ColliderConstructor::ConvexHullFromMesh",
}
MESH_SHAPES = {"trimesh", "convex"}
BODIES = {
    "static": "RigidBody::Static",
    "dynamic": "RigidBody::Dynamic",
    "kinematic": "RigidBody::Kinematic",
}
JOINTS = {
    "fixed": "FixedJoint",
    "revolute": "RevoluteJoint",
    "prismatic": "PrismaticJoint",
    "spherical": "SphericalJoint",
}
SYMBOLS = {
    "AnimatedBy": "animation",
    "AnimationTargetId": "animation",
    "CascadeShadowConfigBuilder": "light",
    "EmptySceneEffect": "scene",
    "EntityTemplate": "ecs::template",
    "FogVolume": "light",
    "Gltf": "gltf",
    "GeneratedEnvironmentMapLight": "light",
    "IrradianceVolume": "light",
    "LightProbe": "light",
    "Lightmap": "pbr",
    "NotShadowCaster": "light",
    "NotShadowReceiver": "light",
    "ParallaxCorrection": "light",
    "PlaybackMode": "audio",
    "ResolveContext": "scene",
    "ResolveSceneError": "scene",
    "ResolvedScene": "scene",
    "ScalingMode": "camera",
    "SceneDependencies": "scene",
    "SpatialScale": "audio",
    "Template": "ecs::template",
    "VisibilityRange": "camera::visibility",
    "Volume": "audio",
    "VolumetricLight": "light",
    "WorldAssetRoot": "world_serialization",
}
HELPERS = {
    "preload": ("Gltf", "ResolveContext", "ResolveSceneError", "ResolvedScene", "SceneDependencies"),
    "joint": ("EntityTemplate", "Template"),
    "animation": (),
    "animated_by": ("AnimatedBy", "EntityTemplate", "Template"),
    "ambient_light": ("EmptySceneEffect",),
}
HELPER_SOURCES = {
    "preload": """fn preload(path: &'static str) -> impl Scene {
    return Preload(path);
}

struct Preload(&'static str);

impl Scene for Preload {
    fn resolve(self, _context: &mut ResolveContext, _scene: &mut ResolvedScene) -> Result<(), ResolveSceneError> {
        return Ok(());
    }

    fn register_dependencies(&self, dependencies: &mut SceneDependencies) {
        dependencies.register::<Gltf>(self.0.into());
    }
}""",
    "joint": """fn joint<J: Component + Clone>(body1: EntityTemplate, body2: EntityTemplate, build: fn(Entity, Entity) -> J) -> impl Scene {
    return bsn! {
        template(move |context| Ok(build(body1.build_template(context)?, body2.build_template(context)?)))
    };
}""",
    "animation": """fn animation(clips: &'static [(&'static str, f32, bool)]) -> impl Scene {
    return bsn! {
        template(move |context| {
            let asset_server = context.resource::<AssetServer>().clone();
            let graph = AnimationGraph::from_clips(clips.iter().map(|(path, _speed, _repeat)| asset_server.load(*path))).0;
            return Ok(AnimationGraphHandle(context.resource_mut::<Assets<AnimationGraph>>().add(graph)));
        })
        template(move |_context| {
            let mut player = AnimationPlayer::default();
            for (index, (_path, speed, repeat)) in clips.iter().enumerate() {
                let active = player.play(AnimationNodeIndex::new(index + 1));
                active.set_speed(*speed);
                if *repeat {
                    active.repeat();
                }
            }
            return Ok(player);
        })
    };
}""",
    "animated_by": """fn animated_by(player: EntityTemplate) -> impl Scene {
    return bsn! {
        template(move |context| Ok(AnimatedBy(player.build_template(context)?)))
    };
}""",
    "ambient_light": """fn ambient_light(light: GlobalAmbientLight) -> impl Scene {
    return bsn! {
        template(move |context| {
            *context.resource_mut::<GlobalAmbientLight>() = light.clone();
            return Ok(EmptySceneEffect);
        })
    };
}""",
}

Entity = namedtuple("Entity", ("node", "head", "transform", "body", "mesh", "mesh_parts", "parts", "children", "shareable"))
Isometry = namedtuple("Isometry", ("translation", "rotation"))


class BsnError(ValueError):
    pass


def cargo_project(path):
    for folder in Path(os.path.abspath(path)).parents:
        if (folder / "Cargo.toml").is_file():
            return folder
    return None


def binary_crate(project):
    if project is None or (project / "src" / "lib.rs").is_file():
        return None
    try:
        with open(project / "Cargo.toml", "rb") as file:
            manifest = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    name = manifest.get("package", {}).get("name")
    if "lib" in manifest or not isinstance(name, str):
        return None
    return name.replace("-", "_")


def default_assets_folder(rust_file):
    rust_file = Path(os.path.abspath(rust_file))
    project = cargo_project(rust_file)
    if project is None:
        return rust_file.parent / "assets" / rust_file.stem
    return project / "assets" / "scenes" / rust_file.stem


def asset_root(folder):
    folder = Path(os.path.abspath(folder))
    candidates = [parent for parent in (folder, *folder.parents) if parent.name.lower() == "assets"]
    if not candidates:
        return folder
    return next((candidate for candidate in candidates if (candidate.parent / "Cargo.toml").is_file()), candidates[0])


def inside(path, root):
    try:
        Path(os.path.abspath(path)).relative_to(os.path.abspath(root))
    except ValueError:
        return False
    return True


def node_components(node):
    return _decode(node.get("extras"))


def strip_components(gltf):
    for item in (*gltf.get("nodes", []), *gltf.get("scenes", [])):
        extras = item.get("extras")
        if isinstance(extras, dict) and EXTRAS_KEY in extras:
            del extras[EXTRAS_KEY]
            if not extras:
                del item["extras"]


def load_path(path, root):
    return Path(os.path.relpath(os.path.abspath(path), os.path.abspath(root))).as_posix()


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


def identifier(text):
    return bool(IDENTIFIER.fullmatch(text)) and text not in KEYWORDS and text != "_"


def rust_path(type_path, crate=None):
    if crate and (type_path == crate or type_path.startswith(f"{crate}::")):
        type_path = "crate" + type_path[len(crate):]
    return GENERICS.sub("::<", type_path, count=1)


def custom_literal(type_path, data, crate=None):
    path = rust_path(type_path, crate)
    if isinstance(data, dict):
        if not data:
            return path
        names = [name for name in data if not identifier(name)]
        if names:
            raise BsnError(f"{type_path} has fields that are not Rust names, so the BSN export cannot write it: {', '.join(names)}")
        return f"{path} {{ {', '.join(f'{name}: {_value(type_path, value)}' for name, value in data.items())} }}"
    if isinstance(data, list):
        return f"{path}({', '.join(_value(type_path, value) for value in data)})"
    if data is None:
        return path
    return f"{path}({_value(type_path, data)})"


def _value(type_path, value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _float(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list) and len(value) in (2, 3, 4) and all(_numeric(number) for number in value):
        return f"Vec{len(value)}::new({_floats(value)})"
    if isinstance(value, dict) and len(value) == 1:
        space, channels = next(iter(value.items()))
        if space in {"Srgba", "LinearRgba"} and isinstance(channels, dict) and all(_numeric(channels.get(channel, 1.0)) for channel in ("red", "green", "blue", "alpha")):
            constructor = "srgba" if space == "Srgba" else "linear_rgba"
            return f"Color::{constructor}({_floats(channels.get(channel, 1.0) for channel in ('red', 'green', 'blue', 'alpha'))})"
    raise BsnError(f"{type_path} holds {json.dumps(value, ensure_ascii=False)}, which the BSN export cannot write as Rust. Use numbers, text, booleans, vectors or colors")


def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _single(value):
    try:
        return struct.unpack("f", struct.pack("f", value))[0]
    except OverflowError:
        return math.copysign(math.inf, value)


def _float(value):
    value = float(value)
    if math.isnan(value):
        return "f32::NAN"
    single = _single(value)
    if math.isinf(single):
        return "f32::INFINITY" if single > 0 else "f32::NEG_INFINITY"
    text = f"{single:.9g}"
    for digits in range(1, 10):
        candidate = f"{single:.{digits}g}"
        if _single(float(candidate)) == single:
            text = candidate
            break
    if "e" in text:
        mantissa, exponent = text.split("e")
        if not PLAIN_EXPONENTS[0] <= int(exponent) <= PLAIN_EXPONENTS[1]:
            return f"{mantissa}e{int(exponent)}"
        text = format(decimal.Decimal(text), "f")
    return text if "." in text else f"{text}.0"


def _floats(values):
    return ", ".join(_float(value) for value in values)


def _string(text):
    escaped = []
    for character in text:
        if character in "\\\"":
            escaped.append("\\" + character)
        elif character == "\n":
            escaped.append("\\n")
        elif character == "\t":
            escaped.append("\\t")
        elif ord(character) < 32 or ord(character) == 127:
            escaped.append(f"\\u{{{ord(character):x}}}")
        else:
            escaped.append(character)
    return f"\"{''.join(escaped)}\""


def _vector(values):
    return f"Vec3::new({_floats(values)})"


def _quaternion(values):
    return f"Quat::from_xyzw({_floats(values)})"


def _multiply_quaternions(first, second):
    x1, y1, z1, w1 = first
    x2, y2, z2, w2 = second
    return (w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2, w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2, w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2)


def _conjugate(rotation):
    x, y, z, w = rotation
    return (-x, -y, -z, w)


def _rotate(rotation, vector):
    x, y, z, _w = _multiply_quaternions(_multiply_quaternions(rotation, (*vector, 0.0)), _conjugate(rotation))
    return (x, y, z)


def _rotation_columns(rotation):
    x, y, z, w = rotation
    return ((1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)), (2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)), (2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)))


def _affine(translation, rotation, scale):
    columns = _rotation_columns(rotation)
    return (tuple(tuple(value * factor for value in column) for column, factor in zip(columns, scale)), tuple(translation))


def _transform_point(columns, point):
    return tuple(sum(columns[axis][row] * point[axis] for axis in range(3)) for row in range(3))


def _compose(parent, child):
    columns, translation = parent
    child_columns, child_translation = child
    return (tuple(_transform_point(columns, column) for column in child_columns), tuple(value + offset for value, offset in zip(_transform_point(columns, child_translation), translation)))


def _determinant(columns):
    (a, b, c), (d, e, f), (g, h, i) = columns
    return a * (e * i - f * h) - d * (b * i - c * h) + g * (b * f - c * e)


def _decompose(affine):
    columns, translation = affine
    sign = -1.0 if _determinant(columns) < 0 else 1.0
    scale = (math.hypot(*columns[0]) * sign, math.hypot(*columns[1]), math.hypot(*columns[2]))
    axes = [tuple(value / factor for value in column) if factor else column for column, factor in zip(columns, scale)]
    return scale, _quaternion_from_axes(*axes), translation


def _quaternion_from_axes(x_axis, y_axis, z_axis):
    m00, m01, m02 = x_axis
    m10, m11, m12 = y_axis
    m20, m21, m22 = z_axis
    if m22 <= 0.0:
        difference = m11 - m00
        complement = 1.0 - m22
        if difference <= 0.0:
            four = complement - difference
            inverse = 0.5 / math.sqrt(four)
            return (four * inverse, (m01 + m10) * inverse, (m02 + m20) * inverse, (m12 - m21) * inverse)
        four = complement + difference
        inverse = 0.5 / math.sqrt(four)
        return ((m01 + m10) * inverse, four * inverse, (m12 + m21) * inverse, (m20 - m02) * inverse)
    total = m11 + m00
    complement = 1.0 + m22
    if total <= 0.0:
        four = complement - total
        inverse = 0.5 / math.sqrt(four)
        return ((m02 + m20) * inverse, (m12 + m21) * inverse, four * inverse, (m01 - m10) * inverse)
    four = complement + total
    inverse = 0.5 / math.sqrt(four)
    return ((m12 - m21) * inverse, (m20 - m02) * inverse, (m01 - m10) * inverse, four * inverse)


def _relative(body, joint):
    inverse = _conjugate(body.rotation)
    offset = tuple(value - origin for value, origin in zip(joint.translation, body.translation))
    return Isometry(_rotate(inverse, offset), _multiply_quaternions(inverse, joint.rotation))


def _node_transform(node):
    if "matrix" in node:
        values = node["matrix"]
        columns = (tuple(values[0:3]), tuple(values[4:7]), tuple(values[8:11]))
        scale, rotation, translation = _decompose((columns, tuple(values[12:15])))
        return tuple(translation), rotation, scale
    return tuple(node.get("translation", (0.0, 0.0, 0.0))), tuple(node.get("rotation", (0.0, 0.0, 0.0, 1.0))), tuple(node.get("scale", (1.0, 1.0, 1.0)))


def _transform_entry(translation, rotation, scale):
    fields = []
    if any(_single(value) != 0.0 for value in translation):
        fields.append(f"translation: {_vector(translation)}")
    if tuple(_single(value) for value in rotation) != (0.0, 0.0, 0.0, 1.0):
        fields.append(f"rotation: {_quaternion(rotation)}")
    if any(_single(value) != 1.0 for value in scale):
        fields.append(f"scale: {'Vec3::splat(' + _float(scale[0]) + ')' if scale[0] == scale[1] == scale[2] else _vector(scale)}")
    return f"Transform {{ {', '.join(fields)} }}" if fields else "Transform"


def _decode(extras):
    if not isinstance(extras, dict) or not isinstance(extras.get(EXTRAS_KEY), str):
        return []
    try:
        data = json.loads(extras[EXTRAS_KEY])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("components"), list):
        return []
    return [component for component in data["components"] if isinstance(component, dict) and isinstance(component.get("type"), str)]


def _first(components, kind):
    return next((component for component in components if component["type"] == kind), None)


class _Generator:
    def __init__(self, gltf, glb, name, prefabs, files, crate):
        self.gltf = gltf
        self.glb = glb
        self.name = name
        self.prefabs = prefabs
        self.files = files or {}
        self.crate = crate
        self.nodes = gltf.get("nodes", [])
        self.meshes = gltf.get("meshes", [])
        self.lights = gltf.get("extensions", {}).get(LIGHTS_EXTENSION, {}).get("lights", [])
        self.cameras = gltf.get("cameras", [])
        self.warnings = []
        self.symbols = set()
        self.helpers = set()
        self.physics = False
        self.labels = False
        self.camera_found = False
        self.custom_names = {}
        scenes = gltf.get("scenes", [])
        scene = scenes[gltf.get("scene", 0)] if scenes else {}
        self.scene = scene
        self.roots = list(scene.get("nodes", []))
        self.parents = {}
        for index, node in enumerate(self.nodes):
            for child in node.get("children", []):
                self.parents[child] = index
        self.components = [_decode(node.get("extras")) for node in self.nodes]
        self.locals = [_node_transform(node) for node in self.nodes]
        self.worlds = {}
        self.signs = {}
        for root in self.roots:
            self._walk_world(root, ((((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0))), (1.0, 1.0, 1.0))
        self.order = list(self.worlds)
        self.clips = {animation.get("name"): index for index, animation in enumerate(gltf.get("animations", [])) if animation.get("name")}
        targets = {channel.get("target", {}).get("node") for animation in gltf.get("animations", []) for channel in animation.get("channels", [])}
        self.targets = {target for target in targets if target is not None and target in self.worlds}
        self.animation_roots = {self._root_of(target) for target in self.targets}
        self.names = [self._node_name(index) for index in range(len(self.nodes))]
        self.referenced = set(self.animation_roots)
        self.joints = {}
        self.anchors = []
        for index in self.order:
            joint = _first(self.components[index], "joint")
            if joint is not None:
                self._plan_joint(index, joint)
        self.root_ident = self._unique_ident(snake_case(name) or "scene", set())
        self.idents = {}
        self._assign_idents()

    def _walk_world(self, index, parent, scales):
        if index in self.worlds or not 0 <= index < len(self.nodes):
            return
        translation, rotation, scale = self.locals[index]
        world = _compose(parent, _affine(translation, rotation, scale))
        signs = tuple(first * second for first, second in zip(scales, scale))
        self.worlds[index] = world
        self.signs[index] = signs
        for child in self.nodes[index].get("children", []):
            self._walk_world(child, world, signs)

    def _root_of(self, index):
        while index in self.parents:
            index = self.parents[index]
        return index

    def _ancestors(self, index):
        found = [index]
        while index in self.parents:
            index = self.parents[index]
            found.append(index)
        return found

    def _node_name(self, index):
        name = self.nodes[index].get("name")
        return name if isinstance(name, str) else f"GltfNode{index}"

    def _isometry(self, index):
        _scale, rotation, translation = _decompose(self.worlds[index])
        return Isometry(translation, rotation)

    def _find_body(self, target, joint):
        ancestors = self._ancestors(joint)
        candidates = [index for index in self.order if self.names[index] == target]
        if not candidates:
            return None
        return min(candidates, key=lambda candidate: next((position for position, ancestor in enumerate(ancestors) if ancestor in self._ancestors(candidate)), len(ancestors)))

    def _plan_joint(self, index, joint):
        kind = joint.get("kind")
        label = self.names[index]
        if kind not in JOINTS:
            self.warnings.append(f"{label}: unsupported joint type {kind}")
            return
        if joint.get("body1") is None and joint.get("body2") is None:
            self.warnings.append(f"{label}: the joint connects no bodies")
            return
        pose = self._isometry(index)
        ends = []
        for target in (joint.get("body1"), joint.get("body2")):
            if target is None:
                ends.append(None)
                continue
            body = self._find_body(target, index)
            if body is None:
                self.warnings.append(f"{label}: the joint found no object named {target}")
                return
            ends.append(body)
        frames = []
        for end in ends:
            if end is None:
                self.anchors.append((index, pose))
                frames.append(("anchor", len(self.anchors) - 1, Isometry((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))))
                continue
            self.referenced.add(end)
            frames.append(("node", end, _relative(self._isometry(end), pose)))
        self.joints[index] = (joint, frames)

    def _unique_ident(self, base, taken):
        base = base if identifier(base) else f"entity_{base}" if base else "entity"
        name = base
        number = 2
        while name in taken or name == getattr(self, "root_ident", None):
            name = f"{base}_{number}"
            number += 1
        taken.add(name)
        return name

    def _assign_idents(self):
        counts = {}
        for index in self.order:
            counts[self.names[index]] = counts.get(self.names[index], 0) + 1
        taken = {self.root_ident}
        for index in self.order:
            name = self.names[index]
            if identifier(name) and counts[name] == 1 and name not in taken:
                self.idents[index] = name
                taken.add(name)
        for index in self.order:
            if index in self.referenced and index not in self.idents:
                self.idents[index] = self._unique_ident(snake_case(self.names[index]), taken)
        self.anchor_idents = [self._unique_ident(f"{snake_case(self.names[joint])}_anchor", taken) for joint, _pose in self.anchors]

    def _use(self, *symbols):
        self.symbols.update(symbols)

    def _helper(self, name):
        self.helpers.add(name)
        self._use(*HELPERS[name])

    def _label(self, kind, index):
        self.labels = True
        return f"{self.glb}#{kind}{index}"

    def build(self):
        root_body = ["Transform", "Visibility"]
        ambient = _first(_decode(self.scene.get("extras")), "ambient_light")
        if ambient is not None:
            self._helper("ambient_light")
            color = ambient.get("color", [1.0, 1.0, 1.0])
            root_body.append(f"@ambient_light(GlobalAmbientLight {{ color: Color::linear_rgb({_floats(color)}), brightness: {_float(ambient.get('brightness', 80.0))}, affects_lightmapped_meshes: {'false' if ambient.get('baked') else 'true'} }})")
        children = [self._entity(index) for index in self.roots if index in self.worlds]
        for (joint, pose), ident in zip(self.anchors, self.anchor_idents):
            self.physics = True
            children.append(_part([f"#{ident}", f"Name({_string(self.names[joint] + ' anchor')})"], _transform_entry(pose.translation, pose.rotation, (1.0, 1.0, 1.0)), ["RigidBody::Static"]))
        prefabs = self._prefabs(children) if self.prefabs else {}
        if self.labels:
            self._helper("preload")
            root_body.append(f"@preload({_string(self.glb)})")
        setup = [f"#{self.root_ident}", *root_body]
        setup.extend(self._children_lines(children, prefabs))
        functions = [_function("pub fn setup() -> impl Scene", setup)]
        for name, entity, _position, shared in sorted(prefabs.values(), key=lambda value: value[2]):
            lines = [entity.body[0], *(entity.mesh if shared else _settings(entity.mesh)), *entity.body[1:]]
            functions.append(_function(f"pub fn {name}() -> impl Scene", lines + self._children_lines((entity.mesh_parts if shared else []) + entity.parts)))
        for helper in ("preload", "joint", "animation", "animated_by", "ambient_light"):
            if helper in self.helpers:
                functions.append(HELPER_SOURCES[helper])
        header = []
        if self.physics:
            header.append("use avian3d::prelude::*;")
        header.append(f"use bevy::{_use_tree(self.symbols)};")
        return "\n".join(header) + "\n\n" + "\n\n".join(functions) + "\n", self.warnings

    def _children_lines(self, children, prefabs=None):
        if not children:
            return []
        lines = ["Children ["]
        for position, child in enumerate(children):
            if position:
                lines.append(INDENT + "--")
            lines.extend(INDENT + line for line in self._entity_lines(child, prefabs))
        lines.append("]")
        return lines

    def _entity_lines(self, entity, prefabs):
        prefab = (prefabs or {}).get(_behavior(entity)) if entity.shareable else None
        if prefab is None:
            return [*entity.head, entity.transform, entity.body[0], *entity.mesh, *entity.body[1:], *self._children_lines(entity.mesh_parts + entity.parts + entity.children, prefabs)]
        name, _entity, _position, shared = prefab
        return [*entity.head, f"@{name}()", entity.transform, *([] if shared else _assets(entity.mesh)), *self._children_lines(([] if shared else entity.mesh_parts) + entity.children, prefabs)]

    def _prefabs(self, roots):
        groups = {}
        pending = list(roots)
        position = 0
        while pending:
            entity = pending.pop(0)
            pending[0:0] = entity.children
            behavior = _behavior(entity)
            if not entity.shareable or not any(behavior[1:]):
                continue
            groups.setdefault(behavior, []).append((position, entity))
            position += 1
        taken = set()
        prefabs = {}
        for signature, members in sorted(groups.items(), key=lambda item: item[1][0][0]):
            if len(members) < 2:
                continue
            name = self._unique_prefab([entity for _position, entity in members], taken)
            shared = len({_mesh_signature(entity) for _position, entity in members}) == 1
            prefabs[signature] = (name, members[0][1], members[0][0], shared)
        return prefabs

    def _unique_prefab(self, entities, taken):
        bases = [snake_case(NUMBERED.sub("", self.names[entity.node])) for entity in entities]
        common = []
        for words in zip(*(base.split("_") for base in bases)):
            if len(set(words)) != 1:
                break
            common.append(words[0])
        base = "_".join(common) or self._behavior_name(entities[0]) or bases[0]
        name = f"{PREFAB_PREFIX}{base or 'shared'}"
        unique = name
        number = 2
        while unique in taken:
            unique = f"{name}_{number}"
            number += 1
        taken.add(unique)
        return unique

    def _behavior_name(self, entity):
        words = []
        for entry in [*entity.body[1:], *_settings(entity.mesh), *(entry for part in entity.mesh_parts for entry in _settings(part.body))]:
            kind = next((kind for kind, template in BODIES.items() if entry == template), None)
            shape = next((shape for shape, template in COLLIDER_SHAPES.items() if entry.startswith(template.split("(")[0])), None)
            word = kind or shape or ("sensor" if entry == "Sensor" else self.custom_names.get(entry))
            if word is not None and all(word != existing for _order, existing in words):
                words.append((0 if kind else 1 if shape else 2, word))
        return "_".join(word for _order, word in sorted(words, key=lambda item: item[0]))

    def _head(self, index):
        name = self.names[index]
        ident = self.idents.get(index)
        if ident is None:
            return [f"Name({_string(name)})"]
        if ident == name:
            return [f"#{ident}"]
        return [f"#{ident}", f"Name({_string(name)})"]

    def _entity(self, index):
        node = self.nodes[index]
        components = self.components[index]
        translation, rotation, scale = self.locals[index]
        body = ["Visibility"]
        mesh = []
        mesh_parts = []
        parts = []
        animated = self._root_of(index) in self.animation_roots
        shareable = index not in self.joints and not animated and _first(components, "animation") is None
        mesh_entries = self._mesh_entries(index)
        primitives = self._primitives(index)
        if len(primitives) == 1:
            mesh.extend(primitives[0] + mesh_entries)
        else:
            mesh_parts.extend(_part([], "Transform", primitive + mesh_entries) for primitive in primitives)
        body.extend(self._collider_entries(index, components))
        body.extend(self._body_entries(index, components))
        body.extend(self._light_entries(index, components))
        camera = self._camera_entries(node)
        if camera:
            shareable = False
            body.extend(camera)
        for component in components:
            kind = component["type"]
            if kind == "audio_player":
                body.extend(self._audio_entries(component))
            elif kind == "scene_reference":
                path = self._reference(index, component.get("path") or "")
                if path is not None:
                    body.append(f"WorldAssetRoot({_string(path + '#Scene' + str(int(component.get('scene', 0))))})")
                    self._use("WorldAssetRoot")
            elif kind == "custom":
                type_path = component.get("type_path", "")
                entry = custom_literal(type_path, component.get("data"), self.crate)
                self.custom_names[entry] = snake_case(GENERICS.split(type_path)[0].split("::")[-1])
                body.append(entry)
            elif kind == "fog_volume":
                parts.append(self._fog_volume(component))
            elif kind == "reflection_probe":
                probe = self._reflection_probe(index, component)
                if probe is not None:
                    parts.append(probe)
            elif kind == "irradiance_volume":
                volume = self._irradiance_volume(index, component)
                if volume is not None:
                    parts.append(volume)
            elif kind == "ambient_light":
                self.warnings.append(f"{self.names[index]}: ambient light belongs on the scene")
        if index in self.joints:
            parts.append(self._joint_entity(index))
        if index in self.animation_roots:
            clips = self._clips(index)
            if clips:
                self._helper("animation")
                body.append(f"@animation(&[{', '.join(clips)}])")
        if animated:
            root = self._root_of(index)
            names = [self.names[ancestor] for ancestor in reversed(self._ancestors(index))]
            self._use("AnimationTargetId")
            self._helper("animated_by")
            body.append(f"~AnimationTargetId::from_names([{', '.join(f'Name::new({_string(name)})' for name in names)}].iter())")
            body.append(f"@animated_by(#{self.idents[root]})")
        if node.get("skin") is not None:
            self.warnings.append(f"{self.names[index]}: BSN scenes leave out skins, so the mesh does not follow its armature")
        if any(primitive.get("targets") for primitive in self._mesh(index).get("primitives", [])):
            self.warnings.append(f"{self.names[index]}: BSN scenes leave out shape key weights")
        children = [self._entity(child) for child in node.get("children", []) if child in self.worlds]
        return Entity(index, self._head(index), _transform_entry(translation, rotation, scale), body, mesh, mesh_parts, parts, children, shareable)

    def _mesh(self, index):
        mesh = self.nodes[index].get("mesh")
        return self.meshes[mesh] if mesh is not None and 0 <= mesh < len(self.meshes) else {}

    def _reference(self, index, path):
        if path in self.files:
            return self.files[path]
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(self.glb), path))
        if not path or resolved.startswith("../") or resolved == "..":
            self.warnings.append(f"{self.names[index]}: {path or 'the scene reference'} is outside the assets folder, so it is left out")
            return None
        return resolved

    def _primitives(self, index):
        mesh = self.nodes[index].get("mesh")
        if mesh is None or not 0 <= mesh < len(self.meshes):
            return []
        inverted = sum(1 for value in self.signs[index] if value < 0) % 2 == 1
        found = []
        for position, primitive in enumerate(self.meshes[mesh].get("primitives", [])):
            material = primitive.get("material")
            label = "DefaultMaterial/std" if material is None else f"Material{material}{' (inverted)' if inverted else ''}/std"
            found.append([f"Mesh3d({_string(self._label('Mesh', mesh) + f'/Primitive{position}')})", f"MeshMaterial3d::<StandardMaterial>({_string(self._label(label, ''))})"])
        return found

    def _inherited(self, index, kind):
        for ancestor in self._ancestors(index):
            component = _first(self.components[ancestor], kind)
            if component is not None:
                return component
        return None

    def _mesh_entries(self, index):
        if not self._primitives(index):
            return []
        entries = []
        visibility = self._inherited(index, "visibility_range")
        if visibility is not None:
            start = visibility.get("start", [0.0, 0.0])
            end = visibility.get("end", [0.0, 0.0])
            if start[0] <= start[1] <= end[0] <= end[1]:
                fields = [f"start_margin: {{{_float(start[0])}..{_float(start[1])}}}", f"end_margin: {{{_float(end[0])}..{_float(end[1])}}}"]
                if visibility.get("use_aabb"):
                    fields.append("use_aabb: true")
                entries.append(f"VisibilityRange {{ {', '.join(fields)} }}")
                self._use("VisibilityRange")
            else:
                self.warnings.append(f"{self.names[index]}: invalid visibility range")
        collider = self._inherited(index, "collider")
        if collider is not None and collider.get("shape") in MESH_SHAPES:
            entries.extend(self._collider_settings(collider, True))
        shadows = self._inherited(index, "shadows")
        if shadows is not None:
            if not shadows.get("cast", True):
                entries.append("NotShadowCaster")
                self._use("NotShadowCaster")
            if not shadows.get("receive", True):
                entries.append("NotShadowReceiver")
                self._use("NotShadowReceiver")
        lightmap = _first(self.components[index], "lightmap")
        if lightmap is not None:
            path = self._file(index, lightmap, "lightmap")
            if path is not None:
                entries.append(f"Lightmap {{ image: {_string(path)}, uv_rect: Rect::new(0.0, 0.0, 1.0, 1.0), bicubic_sampling: {'true' if lightmap.get('bicubic') else 'false'} }}")
                self._use("Lightmap")
        return entries

    def _file(self, index, component, label):
        file = component.get("file")
        path = self.files.get(file) if file else None
        if path is None:
            self.warnings.append(f"{self.names[index]}: no {label} file, so it is left out")
        return path

    def _collider_settings(self, collider, mesh):
        self.physics = True
        size = [_float(value) for value in collider.get("size", [1.0, 1.0, 1.0])]
        entries = [COLLIDER_SHAPES[collider["shape"]].format(*size, _float(collider.get("radius", 0.5)), _float(collider.get("height", 1.0)))]
        if collider.get("sensor"):
            entries.append("Sensor")
        friction = collider.get("friction")
        if friction is not None and _single(friction) != DEFAULT_FRICTION:
            entries.append(f"Friction::new({_float(friction)})")
        restitution = collider.get("restitution")
        if restitution is not None and _single(restitution) != DEFAULT_RESTITUTION:
            entries.append(f"Restitution::new({_float(restitution)})")
        memberships = collider.get("memberships")
        filters = collider.get("filters")
        if memberships is not None or filters is not None:
            memberships = DEFAULT_MEMBERSHIPS if memberships is None else int(memberships)
            filters = ALL_LAYERS if filters is None else int(filters)
            if (memberships, filters) != (DEFAULT_MEMBERSHIPS, ALL_LAYERS):
                entries.append(f"CollisionLayers::from_bits({_bits(memberships)}, {_bits(filters)})")
        return entries

    def _collider_entries(self, index, components):
        collider = _first(components, "collider")
        if collider is None:
            return []
        if collider.get("shape") not in COLLIDER_SHAPES:
            self.warnings.append(f"{self.names[index]}: unsupported collider shape")
            return []
        if collider["shape"] in MESH_SHAPES:
            return []
        return self._collider_settings(collider, False)

    def _body_entries(self, index, components):
        body = _first(components, "rigid_body")
        collider = _first(components, "collider")
        if body is None:
            if collider is not None and collider.get("shape") in COLLIDER_SHAPES and not any(_first(self.components[ancestor], "rigid_body") is not None and _first(self.components[ancestor], "rigid_body").get("kind") in BODIES for ancestor in self._ancestors(index)[1:]):
                self.physics = True
                return ["RigidBody::Static"]
            return []
        kind = body.get("kind")
        if kind not in BODIES:
            self.warnings.append(f"{self.names[index]}: unsupported rigid body type")
            return []
        self.physics = True
        entries = [BODIES[kind]]
        mass = body.get("mass")
        if mass is not None:
            if mass > 0:
                entries.extend([f"Mass({_float(mass)})", "NoAutoMass"])
            else:
                self.warnings.append(f"{self.names[index]}: invalid mass")
        for key, component, default in (("gravity_scale", "GravityScale", 1.0), ("linear_damping", "LinearDamping", 0.0), ("angular_damping", "AngularDamping", 0.0)):
            value = body.get(key)
            if value is not None and _single(value) != default:
                entries.append(f"{component}({_float(value)})")
        translation_locks = body.get("lock_translation")
        rotation_locks = body.get("lock_rotation")
        if translation_locks is not None or rotation_locks is not None:
            bits = 0
            for locked in list(translation_locks or [False] * 3) + list(rotation_locks or [False] * 3):
                bits = (bits << 1) | int(bool(locked))
            if bits:
                entries.append(f"LockedAxes::from_bits({bits:#08b})")
        ccd = body.get("ccd")
        if ccd == "all":
            entries.append("SweptCcd::new().with_filter(CcdFilter::ALL)")
        elif ccd == "off":
            entries.append("SweptCcd::new().with_filter(CcdFilter::NONE)")
        elif ccd not in (None, "default"):
            self.warnings.append(f"{self.names[index]}: unsupported continuous collision setting")
        for key, component, locks in (("linear_velocity", "LinearVelocity", translation_locks), ("angular_velocity", "AngularVelocity", rotation_locks)):
            velocity = body.get(key)
            if velocity is None:
                continue
            velocity = [0.0 if (locks or [False] * 3)[axis] else float(value) for axis, value in enumerate(velocity)]
            if any(_single(value) != 0.0 for value in velocity):
                entries.append(f"{component}({_vector(velocity)})")
        return entries

    def _joint_entity(self, index):
        joint, frames = self.joints[index]
        kind = joint["kind"]
        references = []
        constructor = f"{JOINTS[kind]}::new(body1, body2)"
        for position, (target, value, frame) in enumerate(frames, start=1):
            references.append(f"#{self.anchor_idents[value]}" if target == "anchor" else f"#{self.idents[value]}")
            if any(_single(number) != 0.0 for number in frame.translation) or tuple(_single(number) for number in frame.rotation) != (0.0, 0.0, 0.0, 1.0):
                constructor += f".with_local_frame{position}(Isometry3d::new({_vector(frame.translation)}, {_quaternion(frame.rotation)}))"
        axis = joint.get("axis") or [0.0, 1.0, 0.0]
        length = math.sqrt(sum(value * value for value in axis))
        axis = [value / length for value in axis] if length > 1e-12 else [0.0, 1.0, 0.0]
        angles = joint.get("angle_limits")
        if kind == "revolute":
            constructor += f".with_hinge_axis({_vector(axis)})"
            if angles is not None:
                constructor += f".with_angle_limits({_floats(angles)})"
        elif kind == "prismatic":
            constructor += f".with_slider_axis({_vector(axis)})"
            distances = joint.get("distance_limits")
            if distances is not None:
                constructor += f".with_limits({_floats(distances)})"
        elif kind == "spherical":
            constructor += f".with_twist_axis({_vector(axis)})"
            swing = joint.get("swing_limit")
            if swing is not None:
                constructor += f".with_swing_limits(0.0, {_float(swing)})"
            if angles is not None:
                constructor += f".with_twist_limits({_floats(angles)})"
        self.physics = True
        self._helper("joint")
        body = [f"@joint({references[0]}, {references[1]}, |body1, body2| {constructor})"]
        if kind != "fixed":
            body.append(f"JointDamping {{ linear: {_float(joint.get('linear_damping') or 0.0)}, angular: {_float(joint.get('angular_damping') or 0.0)} }}")
        if not joint.get("collide"):
            body.append("template(|_context| Ok(JointCollisionDisabled))")
        return _part([f"Name({_string(self.names[index] + ' joint')})"], "Transform", body)

    def _clips(self, root):
        found = []
        for index in self.order:
            component = _first(self.components[index], "animation")
            if component is None:
                continue
            player = next((ancestor for ancestor in self._ancestors(index) if ancestor in self.animation_roots), None)
            if player is None:
                if root == self.order[0] or index == root:
                    self.warnings.append(f"{self.names[index]}: animation {component.get('clip')} animates nothing on or above it")
                continue
            if player != root:
                continue
            clip = self.clips.get(component.get("clip"))
            if clip is None:
                self.warnings.append(f"{self.names[index]}: no animation named {component.get('clip')}")
                continue
            found.append(f"({_string(self._label('Animation', clip))}, {_float(component.get('speed', 1.0))}, {'true' if component.get('repeat') else 'false'})")
        return found

    def _light_entries(self, index, components):
        settings = _first(components, "light")
        light_index = self.nodes[index].get("extensions", {}).get(LIGHTS_EXTENSION, {}).get("light")
        if settings is not None and settings.get("kind") == "area":
            return [self._rect_light(settings)]
        if light_index is None or not 0 <= light_index < len(self.lights):
            if settings is not None:
                self.warnings.append(f"{self.names[index]}: no glTF light for the light settings, turn on Include Lights")
            return []
        light = self.lights[light_index]
        kind = light.get("type")
        color = light.get("color", [1.0, 1.0, 1.0])
        intensity = float(light.get("intensity", 1.0))
        fields = [f"color: Color::srgb({_floats(color)})"]
        if kind == "directional":
            component = "DirectionalLight"
            illuminance = settings.get("intensity") if settings is not None and settings.get("intensity") is not None else intensity
            fields.append(f"illuminance: {_float(illuminance)}")
        elif kind in ("point", "spot"):
            component = "PointLight" if kind == "point" else "SpotLight"
            power = settings.get("intensity") if settings is not None and settings.get("intensity") is not None else intensity * 4 * math.pi
            fields.append(f"intensity: {_float(power)}")
            fields.append(f"range: {_float(light.get('range', LIGHT_RANGE))}")
            radius = settings.get("radius") if settings is not None and settings.get("radius") is not None else 0.0
            fields.append(f"radius: {_float(radius)}")
            if kind == "spot":
                spot = light.get("spot", {})
                fields.append(f"inner_angle: {_float(spot.get('innerConeAngle', 0.0))}")
                fields.append(f"outer_angle: {_float(spot.get('outerConeAngle', math.pi / 4))}")
        else:
            self.warnings.append(f"{self.names[index]}: unsupported glTF light type {kind}")
            return []
        entries = []
        if settings is not None:
            if settings.get("shadows"):
                fields.append("shadow_maps_enabled: true")
            if settings.get("contact_shadows"):
                fields.append("contact_shadows_enabled: true")
            if settings.get("baked"):
                fields.append("affects_lightmapped_mesh_diffuse: false")
            for key, field in (("depth_bias", "shadow_depth_bias"), ("normal_bias", "shadow_normal_bias")):
                if settings.get(key) is not None:
                    fields.append(f"{field}: {_float(settings[key])}")
            if kind != "directional" and settings.get("near_clip") is not None:
                fields.append(f"shadow_map_near_z: {_float(settings['near_clip'])}")
            cascades = settings.get("cascades")
            if kind == "directional" and cascades is not None:
                if _valid_cascades(cascades):
                    entries.append(f"~{{CascadeShadowConfigBuilder {{ num_cascades: {int(cascades['count'])}, minimum_distance: {_float(cascades['minimum_distance'])}, maximum_distance: {_float(cascades['maximum_distance'])}, first_cascade_far_bound: {_float(cascades['first_cascade_far_bound'])}, overlap_proportion: {_float(cascades['overlap_proportion'])} }}.build()}}")
                    self._use("CascadeShadowConfigBuilder")
                else:
                    self.warnings.append(f"{self.names[index]}: invalid shadow cascades")
            if settings.get("volumetric"):
                entries.append("VolumetricLight")
                self._use("VolumetricLight")
        return [f"{component} {{ {', '.join(fields)} }}", *entries]

    def _rect_light(self, settings):
        fields = [f"color: Color::linear_rgb({_floats(settings.get('color') or [1.0, 1.0, 1.0])})"]
        if settings.get("intensity") is not None:
            fields.append(f"intensity: {_float(settings['intensity'])}")
        if settings.get("range") is not None:
            fields.append(f"range: {_float(settings['range'])}")
        width, height = settings.get("size") or [1.0, 1.0]
        fields.extend([f"width: {_float(width)}", f"height: {_float(height)}"])
        return f"RectLight {{ {', '.join(fields)} }}"

    def _camera_entries(self, node):
        camera_index = node.get("camera")
        if camera_index is None or not 0 <= camera_index < len(self.cameras):
            return []
        camera = self.cameras[camera_index]
        entries = ["Camera3d"]
        if camera.get("type") == "orthographic":
            settings = camera.get("orthographic", {})
            entries.append(f"~{{Projection::Orthographic(OrthographicProjection {{ near: {_float(settings.get('znear', 0.0))}, far: {_float(settings.get('zfar', 1000.0))}, scaling_mode: ScalingMode::FixedHorizontal {{ viewport_width: {_float(settings.get('xmag', 1.0))} }}, ..OrthographicProjection::default_3d() }})}}")
            self._use("ScalingMode")
        else:
            settings = camera.get("perspective", {})
            fields = [f"fov: {_float(settings.get('yfov', math.pi / 4))}", f"near: {_float(settings.get('znear', 0.1))}"]
            if settings.get("zfar") is not None:
                fields.append(f"far: {_float(settings['zfar'])}")
            if settings.get("aspectRatio") is not None:
                fields.append(f"aspect_ratio: {_float(settings['aspectRatio'])}")
            entries.append(f"~{{Projection::Perspective(PerspectiveProjection {{ {', '.join(fields)}, ..default() }})}}")
        if self.camera_found:
            entries.append("Camera { is_active: false }")
        self.camera_found = True
        return entries

    def _audio_entries(self, component):
        path = component.get("path", "")
        if not path:
            self.warnings.append("an Audio Player has no sound file, so it is left out")
            return []
        fields = []
        if component.get("loop"):
            fields.append("mode: PlaybackMode::Loop")
            self._use("PlaybackMode")
        volume = max(float(component.get("volume", 1.0)), 0.0)
        if _single(volume) != 1.0:
            fields.append(f"volume: Volume::Linear({_float(volume)})")
            self._use("Volume")
        if not component.get("autoplay", True):
            fields.append("paused: true")
        if component.get("spatial"):
            fields.append("spatial: true")
            distance = float(component.get("distance", 0.0))
            if distance > 0.0:
                fields.append(f"spatial_scale: {{Some(SpatialScale::new({_float(1.0 / distance)}))}}")
                self._use("SpatialScale")
        entries = [f"AudioPlayer({_string(path)})"]
        if fields:
            entries.append(f"PlaybackSettings {{ {', '.join(fields)} }}")
        return entries

    def _fog_volume(self, component):
        self._use("FogVolume")
        fields = [f"fog_color: Color::srgb({_floats(component.get('color', [1.0, 1.0, 1.0]))})", f"density_factor: {_float(component.get('density', 0.1))}", f"absorption: {_float(component.get('absorption', 0.3))}", f"scattering: {_float(component.get('scattering', 0.3))}", f"scattering_asymmetry: {_float(component.get('anisotropy', 0.5))}", f"light_tint: Color::srgb({_floats(component.get('light_tint', [1.0, 1.0, 1.0]))})", f"light_intensity: {_float(component.get('light_intensity', 1.0))}"]
        return _part(["Name(\"Fog Volume\")"], _scale_entry(component), [f"template(|_context| Ok(FogVolume {{ {', '.join(fields)}, ..default() }}))"])

    def _reflection_probe(self, index, component):
        path = self._file(index, component, "cubemap")
        if path is None:
            return None
        self._use("LightProbe", "GeneratedEnvironmentMapLight")
        body = [f"LightProbe {{ falloff: {_vector(component.get('falloff', [0.0, 0.0, 0.0]))} }}", f"GeneratedEnvironmentMapLight {{ environment_map: {_string(path)}, intensity: {_float(component.get('intensity', 1.0))}, affects_lightmapped_mesh_diffuse: true }}"]
        if not component.get("parallax_correction", True):
            body.append("ParallaxCorrection::None")
            self._use("ParallaxCorrection")
        return _part(["Name(\"Reflection Probe\")"], _scale_entry(component), body)

    def _irradiance_volume(self, index, component):
        path = self._file(index, component, "voxel texture")
        if path is None:
            return None
        self._use("LightProbe", "IrradianceVolume")
        body = [f"LightProbe {{ falloff: {_vector(component.get('falloff', [0.0, 0.0, 0.0]))} }}", f"IrradianceVolume {{ voxels: {_string(path)}, intensity: {_float(component.get('intensity', 1.0))}, affects_lightmapped_meshes: true }}"]
        return _part(["Name(\"Irradiance Volume\")"], _scale_entry(component), body)


def _bits(value):
    return f"{value:#x}" if value > 0xFF else str(value)


def _valid_cascades(cascades):
    try:
        count = int(cascades["count"])
        near = float(cascades["minimum_distance"])
        far = float(cascades["maximum_distance"])
        first = float(cascades["first_cascade_far_bound"])
        overlap = float(cascades["overlap_proportion"])
    except (KeyError, TypeError, ValueError):
        return False
    return 1 <= count <= MAX_CASCADES and near >= 0.0 and far > near and (count == 1 or near < first) and 0.0 <= overlap < 1.0


def _part(head, transform, body):
    return Entity(None, head, transform, body, [], [], [], [], False)


def _scale_entry(component):
    return _transform_entry((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), component.get("size", [1.0, 1.0, 1.0]))


def _signature(entity):
    return (tuple(entity.body), tuple(_signature(part) for part in entity.parts))


def _mesh_signature(entity):
    return (tuple(entity.mesh), tuple(_signature(part) for part in entity.mesh_parts))


def _behavior(entity):
    return (entity.body[0], tuple(entity.body[1:]), tuple(_settings(entity.mesh)), tuple(tuple(_settings(part.body)) for part in entity.mesh_parts if _settings(part.body)), tuple(_signature(part) for part in entity.parts))


def _asset(entry):
    return entry.startswith(ASSET_ENTRIES)


def _assets(entries):
    return [entry for entry in entries if _asset(entry)]


def _settings(entries):
    return [entry for entry in entries if not _asset(entry)]


def _function(signature, lines):
    body = "\n".join(INDENT * 2 + line for line in lines)
    return f"{signature} {{\n{INDENT}return bsn! {{\n{body}\n{INDENT}}};\n}}"


def _use_tree(symbols):
    tree = {}
    for symbol in symbols:
        branch = tree
        for part in SYMBOLS[symbol].split("::"):
            branch = branch.setdefault(part, {})
        branch[symbol] = None
    tree["prelude"] = {"*": None}
    return _branch(tree)


def _branch(tree):
    items = []
    for key in sorted(tree):
        value = tree[key]
        if value is None:
            items.append(key)
        else:
            items.append(f"{key}::{_branch(value)}")
    return items[0] if len(items) == 1 else "{" + ", ".join(items) + "}"


def scene_source(gltf, glb, name, prefabs=True, files=None, crate=None):
    return _Generator(gltf, glb, name, prefabs, files, crate).build()
