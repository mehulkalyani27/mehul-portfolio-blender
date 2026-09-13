"""Canonical locations inside this repository, resolved relatively.

Every other script imports this instead of hard-coding a path, so the repo can
be cloned anywhere and the scripts still find the .blend, the source GLBs and
the texture sources. Nothing here is machine-specific.

Layout this module assumes (and verifies):

    <root>/blend/main-scene.blend
    <root>/assets/{models,textures,references}
    <root>/exports
    <root>/scripts/<category>/<script>.py

To use it from a script in scripts/<category>/, copy the `load_paths()`
bootstrap used in scripts/objects/import_products.py — it locates this file
relative to the calling script, so it works both from `blender --python` and
from Blender's Text Editor.
"""

import os

try:
    import bpy
except ImportError:          # allows `python3 paths.py` outside Blender
    bpy = None


def repo_root():
    """Absolute path to the repository root.

    Prefers this file's own location. Falls back to the open .blend, which
    covers the case where Blender's Text Editor has not set `__file__`.
    """
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(os.path.dirname(here))   # scripts/setup -> scripts -> root
        if os.path.isdir(os.path.join(root, "blend")):
            return root
    except NameError:
        pass

    if bpy is not None and bpy.data.filepath:
        # <root>/blend/main-scene.blend
        root = os.path.dirname(os.path.dirname(bpy.data.filepath))
        if os.path.isdir(os.path.join(root, "assets")):
            return root

    raise RuntimeError(
        "Cannot locate the repository root. Run this script from its checked-out "
        "location with blend/main-scene.blend open."
    )


ROOT       = repo_root()
BLEND_DIR  = os.path.join(ROOT, "blend")
MAIN_BLEND = os.path.join(BLEND_DIR, "main-scene.blend")
ASSETS     = os.path.join(ROOT, "assets")
MODELS     = os.path.join(ASSETS, "models")
TEXTURES   = os.path.join(ASSETS, "textures")
REFERENCES = os.path.join(ASSETS, "references")
EXPORTS    = os.path.join(ROOT, "exports")
SCRIPTS    = os.path.join(ROOT, "scripts")

#: Recovered world-space product placements consumed by import_products.py.
PLACEMENTS = os.path.join(REFERENCES, "product_placements.json")


if __name__ == "__main__":
    for k in ("ROOT", "MAIN_BLEND", "MODELS", "TEXTURES", "REFERENCES", "EXPORTS", "PLACEMENTS"):
        v = globals()[k]
        print("%-11s %-70s %s" % (k, v, "ok" if os.path.exists(v) else "MISSING"))
