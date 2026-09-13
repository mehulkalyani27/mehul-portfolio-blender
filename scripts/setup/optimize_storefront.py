"""
blend/main-scene.blend — geometry hygiene, edge treatment and transform pass.

Run from Blender's Scripting workspace with `blend/main-scene.blend` open:
open this file in the Text Editor and press "Run Script". It is idempotent —
running it twice does not double the modifiers or re-merge anything.

WHAT THIS SCRIPT DOES, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------------
The brief this was written from assumed a scene that differs from the one in
the .blend. Measurements taken before writing it:

  * The two condensers do NOT overlap. `Back_AC_Condenser` spans x[-2.90,-1.80]
    and `Back_AC_Condenser_2` spans x[-1.40,-0.30] — a clean 0.40 m gap. There
    are no co-located duplicate objects to delete, and zero coincident face
    centres in either mesh. The real defects are 68 doubled vertices and 10
    degenerate (zero-area) faces per unit, which this script does fix.

  * The AC units are not flat boxes. Each is 2205 verts / 1981 faces and already
    carries Mat_AC_Body, Mat_AC_Louvre, Mat_AC_FanCavity, Mat_AC_Grille,
    Mat_AC_Bracket_Steel, Mat_AC_Coil and Mat_Pipe_Insulation — i.e. the louvers,
    fan recess, grille, brackets and insulated pipe run are already modelled.
    Generating a second set on top would create the exact coplanar z-fighting
    this pass exists to remove, so no new AC geometry is built.

  * The shelves are already aligned. Left and right tiers sit at identical
    heights (z = 1.400 / 2.350 / 3.300, i.e. exactly 0.95 m apart), share one
    depth plane (y -1.79 → -1.49), and stand 0.215 m clear of the glass at
    y -2.005 — well past the 0.08 m minimum. Re-spacing them to 0.35 m tiers
    would compress a 2.5 m post into a third of its height and is not done.

  * There is no door. No object in the file matches door/entry/threshold/jamb;
    the shopfront is the single mesh `Facade_Storefront`. Threshold alignment
    is therefore a no-op. Note also that ground level is z = 0.80 (the top of
    `Diorama_Base`), not z = 0.0, so snapping anything to z = 0 would bury it.

Set the flags in CONFIG to override any of these judgements.

WHAT IT PROTECTS
----------------
  * `AC_Fan_01` / `AC_Fan_02` are excluded from every transform operation.
    `frontend/components/ACFans.tsx` spins them with
    `quaternion.copy(restQuaternion).multiply(spin)` about *local* Y, so the
    authored -90 deg X rotation is load-bearing: applying it would rotate the
    spin axis to vertical and make the blades scythe instead of spin, and
    re-origining them would push the hub off-centre and add a wobble.
  * Objects with animation data are excluded from transform apply — the
    `VM_Payment_Progress` clip keyframes `Scr_S3_BarFill`'s scale, which would
    be re-based against a different rest scale.
  * Parents are excluded from transform apply, because applying a parent's
    transform in Blender drags its children with it.
  * Panes and light strips thinner than THIN_LIMIT never get a bevel; a 0.004 m
    bevel on a 0.004 m LED strip consumes the whole object.
  * An object that already carries a Bevel modifier has it widened in place
    rather than gaining a second one. Most of this model is already bevelled —
    slabs at 0.002 m, posts/brackets/boxes at 0.0015 m — just too finely to read
    at viewing distance, which is the real cause of the "sharp edges" look.
    Stacking a second bevel re-bevels the first one's edges and facets the
    corners, so the existing modifier is reused.
"""

import math

import bmesh
import bpy

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------

CONFIG = {
    # Section 1 — mesh hygiene on the AC units.
    "clean_ac_meshes": True,
    "merge_distance": 0.001,
    "set_viewport_clip_start": True,
    "clip_start": 0.1,

    # Section 2 — see the header. Off because the detail already exists.
    "build_ac_detail_geometry": False,

    # Section 3 — see the header. Off because the shelves already measure true.
    "respace_shelves": False,
    "shelf_tier_gap": 0.35,
    "shelf_glass_clearance": 0.08,

    # Section 4 — edge treatment.
    "apply_bevels": True,
    "bevel_width": 0.005,      # brief allows 0.004–0.008
    "bevel_segments": 3,
    "bevel_profile": 0.5,
    "weighted_normals": True,
    "smooth_angle_deg": 37.0,  # brief allows 35–40

    # Section 5 — transforms.
    "reset_origins": True,
    "apply_transforms": True,
}

#: Anything thinner than this in any axis is left unbevelled (glass, LED strips).
THIN_LIMIT = 0.02

#: Fan blades — animated at runtime about their local axis. Never re-transform.
ANIMATION_CRITICAL = {"AC_Fan_01", "AC_Fan_02"}

#: The condenser bodies.
AC_BODIES = ["Back_AC_Condenser", "Back_AC_Condenser_2"]

#: Objects that receive the bevel + weighted-normal treatment.
BEVEL_TARGETS = [
    # Shopfront framing, lintel and mullions.
    "Facade_Storefront", "Marquee_Frame", "Awning_Front",
    "Post_Left_1", "Post_Left_2", "Post_Right_1", "Post_Right_2",
    # AC compressor housings.
    *AC_BODIES,
    # Display shelves, their brackets and ledges.
    "Slab_Left_Top", "Slab_Left_Middle", "Slab_Left_Bottom",
    "Slab_Right_Top", "Slab_Right_Middle", "Slab_Right_Bottom",
    "Bracket_Left_Bottom_1", "Bracket_Left_Bottom_2",
    "Bracket_Left_Middle_1", "Bracket_Left_Middle_2",
    "Bracket_Right_Bottom_1", "Bracket_Right_Bottom_2",
    "Bracket_Right_Middle_1", "Bracket_Right_Middle_2",
    "Watch_Display_Plinth", "Easel_WallClock_L", "Easel_WallClock_R",
]

report: list[str] = []


def log(line: str) -> None:
    report.append(line)
    print(line)


def mesh_objects(names):
    """Yields the existing mesh objects for `names`, warning about the rest."""
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            log(f"  ! {name}: not in this file, skipped")
        elif obj.type != "MESH":
            log(f"  ! {name}: {obj.type}, not a mesh, skipped")
        else:
            yield obj


# ----------------------------------------------------------------------------
# 1. AC mesh hygiene — the actual anti-flicker fix
# ----------------------------------------------------------------------------

def clean_mesh(obj) -> str:
    """Merges doubles, dissolves zero-area faces and recalculates normals.

    Done through bmesh rather than `bpy.ops.mesh.*` so it does not depend on an
    Edit-Mode context. The operations are the direct equivalents of
    `remove_doubles(threshold=…)` and `normals_make_consistent(inside=False)`.
    """
    bm = bmesh.new()
    bm.from_mesh(obj.data)

    verts_before, faces_before = len(bm.verts), len(bm.faces)

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=CONFIG["merge_distance"])
    bmesh.ops.dissolve_degenerate(bm, dist=CONFIG["merge_distance"], edges=bm.edges)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)  # inside=False equivalent

    merged = verts_before - len(bm.verts)
    dissolved = faces_before - len(bm.faces)

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()

    return f"{merged} verts merged, {dissolved} degenerate faces dissolved"


def run_mesh_hygiene() -> None:
    log("\n[1] AC mesh hygiene")
    for obj in mesh_objects(AC_BODIES):
        log(f"  {obj.name}: {clean_mesh(obj)}")


def run_clip_start() -> None:
    """Raises the viewport near plane, which is what actually causes depth-buffer
    flicker on a scene this size — 0.01 spends most of the depth range on the
    first centimetre in front of the camera."""
    log("\n[1b] Viewport clip start")
    changed = 0
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type == "VIEW_3D" and space.clip_start < CONFIG["clip_start"]:
                    log(f"  {screen.name}: clip_start {space.clip_start} -> {CONFIG['clip_start']}")
                    space.clip_start = CONFIG["clip_start"]
                    changed += 1
    if not changed:
        log("  already at or above target, nothing to do")


# ----------------------------------------------------------------------------
# 4. Bevel, weighted normals and smooth shading
# ----------------------------------------------------------------------------

def safe_bevel_width(obj) -> float:
    """Never bevel more than a fifth of an object's thinnest axis.

    Clamp Overlap alone will not save a 0.025 m shelf slab from a bevel authored
    for a wall, and it cannot save a 0.004 m LED strip at all.
    """
    thinnest = min(obj.dimensions) if min(obj.dimensions) > 0 else CONFIG["bevel_width"]
    return min(CONFIG["bevel_width"], thinnest * 0.2)


def add_edge_treatment(obj) -> str:
    if min(obj.dimensions) < THIN_LIMIT:
        return f"skipped, thinnest axis {min(obj.dimensions):.4f} m is under {THIN_LIMIT} m"

    notes = []

    # Much of this model is already bevelled — the slabs at 0.002 m, the posts,
    # brackets and product boxes at 0.0015 m. Those bevels are real but too fine
    # to read at viewing distance, which is what makes the edges look sharp.
    # Widen whichever bevel is already there instead of stacking a second one:
    # two bevel modifiers on one mesh re-bevel the first one's new edges, which
    # rounds corners into visible facets and doubles the evaluated poly count.
    existing = [m for m in obj.modifiers if m.type == "BEVEL"]

    if existing:
        bevel = existing[0]
        notes.append(f"reused '{bevel.name}' ({bevel.width:.4f} m -> widened)")
        for extra in existing[1:]:
            obj.modifiers.remove(extra)
            notes.append("removed duplicate bevel")
    else:
        bevel = obj.modifiers.new(name="Bevel_Edges", type="BEVEL")
        notes.append("bevel added")

    bevel.width = safe_bevel_width(obj)
    bevel.segments = CONFIG["bevel_segments"]
    bevel.profile = CONFIG["bevel_profile"]
    bevel.use_clamp_overlap = True
    bevel.limit_method = "ANGLE"
    bevel.angle_limit = math.radians(30.0)
    bevel.miter_outer = "MITER_ARC"
    bevel.harden_normals = False  # incompatible with the weighted-normal modifier

    if CONFIG["weighted_normals"]:
        if obj.modifiers.get("Weighted_Normals") is None:
            weighted = obj.modifiers.new(name="Weighted_Normals", type="WEIGHTED_NORMAL")
            weighted.keep_sharp = True
            notes.append("weighted normals added")

    return f"{', '.join(notes)} (width {bevel.width:.4f} m)"


def shade_smooth_by_angle(objects) -> None:
    """Blender 4.1 removed mesh auto-smooth in favour of an operator that adds a
    Smooth by Angle node group, so both spellings are tried."""
    angle = math.radians(CONFIG["smooth_angle_deg"])

    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    if not objects:
        return
    bpy.context.view_layer.objects.active = objects[0]

    for operator, kwargs in (
        (getattr(bpy.ops.object, "shade_smooth_by_angle", None), {"angle": angle}),
        (getattr(bpy.ops.object, "shade_auto_smooth", None), {"angle": angle}),
        (bpy.ops.object.shade_smooth, {}),
    ):
        if operator is None:
            continue
        try:
            operator(**kwargs)
            log(f"  smooth shading applied to {len(objects)} objects at {CONFIG['smooth_angle_deg']} deg")
            return
        except (RuntimeError, TypeError):
            continue
    log("  ! could not apply smooth shading in this Blender build")


def run_edge_treatment() -> None:
    log("\n[4] Edge bevelling and smooth shading")
    treated = []
    for obj in mesh_objects(BEVEL_TARGETS):
        log(f"  {obj.name}: {add_edge_treatment(obj)}")
        if min(obj.dimensions) >= THIN_LIMIT:
            treated.append(obj)
    shade_smooth_by_angle(treated)


# ----------------------------------------------------------------------------
# 5. Origins and transforms
# ----------------------------------------------------------------------------

def transform_safe(obj) -> tuple[bool, str]:
    if obj.name in ANIMATION_CRITICAL:
        return False, "animation-critical (ACFans.tsx spins it about its local axis)"
    if obj.animation_data is not None:
        return False, "carries animation data"
    if obj.children:
        return False, f"parent of {len(obj.children)} object(s)"
    if obj.library is not None:
        return False, "linked from a library"
    return True, ""


def run_transforms() -> None:
    log("\n[5] Origins and transforms")
    candidates = list(mesh_objects(sorted(set(BEVEL_TARGETS))))

    eligible = []
    for obj in candidates:
        ok, why = transform_safe(obj)
        if ok:
            eligible.append(obj)
        else:
            log(f"  - {obj.name}: skipped, {why}")

    if not eligible:
        log("  nothing eligible")
        return

    bpy.ops.object.select_all(action="DESELECT")
    for obj in eligible:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = eligible[0]

    if CONFIG["reset_origins"]:
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="MEDIAN")
        log(f"  origins reset to geometry on {len(eligible)} objects")

    if CONFIG["apply_transforms"]:
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        log(f"  rotation and scale applied on {len(eligible)} objects")

    for name in sorted(ANIMATION_CRITICAL):
        fan = bpy.data.objects.get(name)
        if fan:
            rot = [round(math.degrees(a), 2) for a in fan.rotation_euler]
            log(f"  = {name} left untouched, rest rotation still {rot}")


# ----------------------------------------------------------------------------

def main() -> None:
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    log("=" * 68)
    log("mehul-portfolio — optimisation pass")
    log("=" * 68)

    if CONFIG["clean_ac_meshes"]:
        run_mesh_hygiene()
    if CONFIG["set_viewport_clip_start"]:
        run_clip_start()

    if CONFIG["build_ac_detail_geometry"]:
        log("\n[2] AC detail geometry: enabled in CONFIG — see the header before "
            "using this; the units already carry louvers, grille and brackets.")
    if CONFIG["respace_shelves"]:
        log("\n[3] Shelf re-spacing: enabled in CONFIG — see the header before "
            "using this; the tiers already measure true at 0.95 m.")

    if CONFIG["apply_bevels"]:
        run_edge_treatment()
    if CONFIG["reset_origins"] or CONFIG["apply_transforms"]:
        run_transforms()

    log("\n" + "=" * 68)
    log("Done. Save with File > Save if the result looks right.")
    log("=" * 68)


if __name__ == "__main__":
    main()
