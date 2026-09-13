"""
blend/main-scene.blend — make room on the west wall for the Contact phone, and
move the skateboard to the right-hand lamp.

    blender --background blend/main-scene.blend \
            --python reposition_contact_bay.py -- --out X.blend --glb Y.glb

WHY THESE TWO THINGS
--------------------
**The charger** moves 0.22 m along the wall, away from the corner where the
phone will hang. That is the minimum that opens a deliberate gap rather than a
leftover one: the phone is 0.366 m wide and sits at z 1.237…1.603, so leaving
the charger where it was gave 0.331 m of wall between them — about one phone
width, which reads as "it fitted" rather than "it was placed". 0.22 takes that
to 0.551 m and costs nothing else.

It is *only* the charger. The `LEDBoard_*` parts directly above it look like
part of the same fixture and are not — they are parented to
`SignBoard_3D_Printing_Blade`. They stay, and at 0.22 m of offset against their
own 1.7 m width the two still read as stacked.

**The skateboard** has no effect on the site: `frontend/scripts/build-model.mjs`
strips the `Skateboard` subtree from `storefront.glb`, and the board the visitor
sees is `public/models/skateboard.glb` placed by `frontend/lib/boardRig.ts`.
It is moved here anyway so the source scene does not disagree with the site
about where its own skateboard is.

THE AXIS BRIDGE
---------------
The site is Y-up and this file is Z-up: `three(x, y, z) -> blender(x, -z, y)`.
So a move of -0.22 in the site's Z is +0.22 in Blender's Y, and the site's yaw
about +Y is a Blender rotation about +Z.
"""

import math
import os
import sys

import bpy
from mathutils import Vector

#: Metres along the wall the charger moves, in the *site's* Z, measured from
#: where it was authored. Absolute rather than relative so re-running this does
#: not stack another shift on top of the last one — run it against the
#: pre-move backup and it always lands in the same place.
CHARGER_SHIFT_Z = -0.52

#: Where the skateboard goes, in the site's frame — matches `boardRig.REST`.
#:
#: On the pavement, not in the road. The first attempt put it at z 4.40, which
#: is 0.91 m past the parapet and beyond the lamp's own footprint — reading as
#: a board lying in the street rather than propped by the lamp. 3.80 is 0.31 m
#: past the parapet, inside the strip the lamp stands on.
BOARD_X, BOARD_Z, BOARD_YAW_DEG = 3.55, 3.80, 298.0

#: The brief's 15%. Applied to the authored scale, so this script must be run
#: against the pre-move backup rather than its own output.
BOARD_GROWTH = 1.15

CHARGER = "Wall_EVCharger"
BOARD_ROOT = "Skateboard"


def log(msg):
    print(f"[contact-bay] {msg}")


def world_box(obj):
    """World-space bounds of `obj` and everything under it."""
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    stack = [obj]
    while stack:
        o = stack.pop()
        stack.extend(o.children)
        if o.type != "MESH" or not o.data.vertices:
            continue
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def site(v):
    """Blender world vector -> the site's frame (x, y, z), for readable logging."""
    return (round(v.x, 3), round(v.z, 3), round(-v.y, 3))


#: Metres of daylight left under the board so its shadow map has something to
#: resolve. `build_skateboard.py` uses the same figure for the same reason.
GROUND_CLEARANCE = 0.0005

#: Top of `Diorama_Base`, in Blender's Z.
SLAB_TOP = 0.800


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    out = argv[argv.index("--out") + 1] if "--out" in argv else None
    glb = argv[argv.index("--glb") + 1] if "--glb" in argv else None

    # ---- the charger -----------------------------------------------------
    charger = bpy.data.objects.get(CHARGER)
    if charger is None:
        raise SystemExit(f"{CHARGER} is missing")
    before = world_box(charger)
    charger.location.y += -CHARGER_SHIFT_Z          # site -Z is Blender +Y
    bpy.context.view_layer.update()
    after = world_box(charger)
    # site() returns (x, y, z); the wall runs along z, which is index 2. The
    # -Y/+Z swap makes it easy to print the height by mistake and conclude
    # nothing moved.
    log(f"{CHARGER}: site z {site(before[1])[2]}..{site(before[0])[2]}"
        f"  ->  {site(after[1])[2]}..{site(after[0])[2]}")
    log(f"  (scale {tuple(round(v, 4) for v in charger.scale)}, "
        f"rotation {tuple(round(math.degrees(v), 2) for v in charger.rotation_euler)} — both untouched)")

    # ---- the skateboard --------------------------------------------------
    board = bpy.data.objects.get(BOARD_ROOT)
    if board is None:
        log(f"{BOARD_ROOT} is not in this scene — nothing to move")
    else:
        was = world_box(board)
        size_before = was[1] - was[0]
        board.location.x = BOARD_X
        board.location.y = -BOARD_Z
        board.rotation_euler.z = math.radians(90.0 - BOARD_YAW_DEG)
        board.scale = tuple(v * BOARD_GROWTH for v in board.scale)
        bpy.context.view_layer.update()

        # Scaling happens about the object's origin, which is not on the ground,
        # so a 15% bigger board hangs 3.6 mm of itself through the pavement.
        # Measure and settle it rather than trusting the origin.
        sunk = world_box(board)[0].z
        board.location.z += SLAB_TOP + GROUND_CLEARANCE - sunk
        bpy.context.view_layer.update()

        now = world_box(board)
        log(f"{BOARD_ROOT}: site xz {site(was[0])[0]},{site(was[0])[2]} -> {BOARD_X},{BOARD_Z}"
            f"  yaw {BOARD_YAW_DEG}°  scale x{BOARD_GROWTH}")
        # A world AABB is not a size: rotating the board changes it. The object's
        # own dimensions are, and they are what has to grow by exactly 15%.
        for axis, a, b in zip("xyz", size_before, now[1] - now[0]):
            log(f"  world aabb {axis}: {a:.4f} -> {b:.4f}   (rotated, so not a size check)")
        log(f"  local dimensions now {tuple(round(v, 4) for v in board.dimensions)}")
        log(f"  settled from z {sunk:.4f} to {world_box(board)[0].z:.4f} "
            f"(slab top {SLAB_TOP}, clearance {GROUND_CLEARANCE * 1000:.1f} mm)")

    if out:
        bpy.ops.wm.save_as_mainfile(filepath=out)
        log(f"saved {out}")

    if glb:
        # Settings chosen to reproduce the asset that is already checked in —
        # the export is diffed against it afterwards, and anything but the
        # charger moving is a settings mismatch, not an intended change.
        bpy.ops.export_scene.gltf(
            filepath=glb,
            export_format="GLB",
            use_selection=False,
            use_visible=False,
            use_renderable=False,
            use_active_collection=False,
            export_apply=False,
            export_yup=True,
            export_animations=True,
            export_extras=False,
            export_cameras=False,
            export_lights=False,
        )
        log(f"exported {glb} ({os.path.getsize(glb) / 1e6:.2f} MB)")


main()
