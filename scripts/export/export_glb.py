"""blend/main-scene.blend — the one place the glTF export settings live.

    blender --background blend/main-scene.blend \
            --python scripts/export/export_glb.py

    # or to a chosen path
    blender --background blend/main-scene.blend \
            --python scripts/export/export_glb.py -- --out exports/main-scene.glb

Writes to `exports/` by default. That directory is git-ignored: the GLB is a
build artifact of this .blend, not a source file, and committing it would mean
two things to keep in step instead of one.

WHY THIS FILE EXISTS
--------------------
`rebuild_vending.py` documents a failure this script prevents. The vending
machine publishes its catalogue through a custom property, `vm_products` on
`Vending_TechLocker`, and the web build reads it out of the GLB. The property
was always correct in the .blend — but glTF only carries custom properties when
`export_extras=True`, and with no export script in the project that setting
lived in whoever's Blender UI last pressed File > Export. Export from the UI
with the box unticked and the catalogue silently vanishes from the GLB while
the .blend still looks perfect.

The same applies to animation: the `VM_Product_Deliver_*` actions only survive
if `export_animations=True` and the actions are bound to objects rather than
kept alive by a fake user.

SETTINGS, AND WHY EACH ONE
--------------------------
`export_extras=True`
    Carries `vm_products`, `vm_keys`, `vm_states`, `vm_role`, `vm_slot`,
    `aim_yaw_deg` and the rest. The interactive scene is unusable without it.

`export_yup=True`
    Blender is Z-up, glTF and three.js are Y-up. The scripts in this repo
    document the bridge as `three(x, y, z) -> blender(x, -z, y)`.

`export_animations=True`
    The 30 actions in this file, including the six delivery clips.

`export_cameras=False` / `export_lights=False`
    The scene carries 20 lights and no camera. Lighting and camera work are
    owned by the web runtime, which builds its own; exporting Blender's would
    give the viewer a second, conflicting set.

`export_apply=False`
    Modifiers are left unapplied so the export matches the .blend's own
    evaluated result rather than silently baking geometry.

`use_selection` / `use_visible` / `use_renderable` / `use_active_collection`
    All False, so the export never depends on what happened to be selected or
    which collection was active when it ran. This is what makes the output
    reproducible from a clean `--background` run.

Note the one deliberate difference from `reposition_contact_bay.py`, which
exports with `export_extras=False`. That script exists to diff its output
against a previously checked-in asset and must reproduce it byte-for-byte,
settings mismatch included. This script is the correct one for producing a GLB
the site will actually consume.
"""

import os
import sys

import bpy


def load_paths():
    """Import scripts/setup/paths.py without touching sys.path."""
    import importlib.util

    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:                       # Text Editor with no file path
        root = os.path.dirname(os.path.dirname(bpy.data.filepath))
        here = os.path.join(root, "scripts", "export")
    target = os.path.join(os.path.dirname(here), "setup", "paths.py")
    spec = importlib.util.spec_from_file_location("bp_paths", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def log(msg: str) -> None:
    print(f"[export-glb] {msg}")


def parse_out(paths) -> str:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
        return out if os.path.isabs(out) else os.path.abspath(out)
    return os.path.join(paths.EXPORTS, "main-scene.glb")


def preflight() -> None:
    """Fails loudly on the things that have silently broken this export before."""
    locker = bpy.data.objects.get("Vending_TechLocker")
    if locker is None:
        raise SystemExit("Vending_TechLocker is missing — wrong .blend?")
    if "vm_products" not in locker.keys():
        raise SystemExit("Vending_TechLocker has no vm_products property.")

    import json
    products = json.loads(locker["vm_products"]) if isinstance(locker["vm_products"], str) \
        else dict(locker["vm_products"])

    absent = [p["node"] for p in products.values() if p["node"] not in bpy.data.objects]
    if absent:
        log("WARNING: vm_products points at %d node(s) not in the scene: %s"
            % (len(absent), ", ".join(absent)))
        log("         run scripts/objects/import_products.py first, or the GLB")
        log("         will ship a catalogue whose products do not exist.")

    unbound = [p["clip"] for p in products.values()
               if p["clip"] in bpy.data.actions and bpy.data.actions[p["clip"]].users == 0]
    if unbound:
        log("WARNING: delivery clip(s) with no user will not be exported: %s"
            % ", ".join(unbound))

    missing_tex = [i.name for i in bpy.data.images
                   if i.source == 'FILE' and not i.packed_file
                   and not os.path.exists(bpy.path.abspath(i.filepath_raw))]
    if missing_tex:
        raise SystemExit("Missing texture source(s): %s" % ", ".join(missing_tex))


def main() -> None:
    paths = load_paths()
    out = parse_out(paths)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    preflight()

    bpy.ops.export_scene.gltf(
        filepath=out,
        export_format="GLB",
        # Never let selection or collection state influence the result.
        use_selection=False,
        use_visible=False,
        use_renderable=False,
        use_active_collection=False,
        export_apply=False,
        # Z-up (Blender) -> Y-up (glTF / three.js).
        export_yup=True,
        export_animations=True,
        # Carries vm_products and every other custom property. See the header.
        export_extras=True,
        # The web runtime owns camera and lighting.
        export_cameras=False,
        export_lights=False,
    )
    log(f"exported {out} ({os.path.getsize(out) / 1e6:.2f} MB)")


main()
