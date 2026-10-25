from io_scene_gltf2 import ExportGLTF2_Base

try:
    from annotationlib import get_annotations
except ImportError:  # before Python 3.14, which evaluates class annotations lazily

    def get_annotations(cls):
        return cls.__dict__.get("__annotations__", {})


LIMITS = ("use_selection", "use_visible", "use_renderable", "use_active_collection", "use_active_collection_with_nested")
SCENE_OPTIONS = ("use_mesh_edges", "use_mesh_vertices", "use_active_scene", "at_collection_center")


def _annotations():
    found = {}
    for cls in reversed(ExportGLTF2_Base.__mro__):
        found.update(get_annotations(cls))
    return found


GLTF_OPTIONS = tuple(name for name in _annotations() if name.startswith("export_") or name in LIMITS + SCENE_OPTIONS)


def changed(name, **keywords):
    deferred = _annotations()[name]
    return deferred.function(**{**{key: value for key, value in deferred.keywords.items() if key != "attr"}, **keywords})
