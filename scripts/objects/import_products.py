"""
blend/main-scene.blend — re-import the product and prop GLBs at authored scale.

Run from Blender's Scripting workspace, or via the MCP bridge, calling
`run_batch(names)` with the products to bring in. Idempotent: importing a
product that is already present replaces it rather than stacking a duplicate.

WHY THE FIT IS COMPUTED RATHER THAN HARD-CODED
----------------------------------------------
The raw files in `assets/models/` carry none of the scene's placement — they are
whatever scale their author exported at, and they disagree wildly:
`perfume.glb` arrives ~1113 units tall, `hand_watch.glb` ~0.12. Dropping them
in unscaled puts a wristwatch inside a shelf and a perfume bottle through the
roof.

`assets/references/product_placements.json` holds the world-space bounding box each product
occupied in the pre-removal .blend, recovered headlessly from
`backups/mehul-portfolio_20260824_231510_pre-shelf-vending-text-removal.blend`.
Each import is rotated to the authored orientation, scaled uniformly so its
longest axis matches the recorded box, then translated so the two box centres
coincide. Uniform scale keeps the model's proportions; matching the longest
axis (rather than fitting each axis independently) is what prevents a
non-uniform squash when the source mesh has slightly different proportions.

The imported hierarchy is re-parented under one Empty named exactly as the
original node — `Hero_Drone_Imported`, `Storefront_Lamp`, and so on. Those names
are the contract the web pipeline relies on: `frontend/scripts/separatedModels.mjs`
extracts each product by node name, and `build-model.mjs` strips it from the
storefront by the same name. Renaming would silently break both.
"""

import contextlib
import io
import itertools
import json
import math
import os

import bpy
from mathutils import Matrix, Quaternion, Vector


def load_paths():
    """Import scripts/setup/paths.py without touching sys.path.

    Located relative to this file, so it resolves both under
    `blender --python` and from Blender's Text Editor.
    """
    import importlib.util

    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:                       # Text Editor with no file path
        root = os.path.dirname(os.path.dirname(bpy.data.filepath))
        here = os.path.join(root, "scripts", "objects")
    target = os.path.join(os.path.dirname(here), "setup", "paths.py")
    spec = importlib.util.spec_from_file_location("bp_paths", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_paths = load_paths()

#: Source GLBs live in assets/models/, the recovered boxes in assets/references/.
ASSETS = _paths.MODELS
PLACEMENTS = _paths.PLACEMENTS

#: node name -> source file, mirroring frontend/scripts/separatedModels.mjs
PRODUCTS = {
    # Six products behind the vending machine glass.
    "Hero_Drone_Imported": ("drone.glb", "Vending_TechLocker"),
    "AirPods_Pro_Imported": ("airpods_pro.glb", "Vending_TechLocker"),
    "Insta360_Imported": ("insta360.glb", "Vending_TechLocker"),
    "RayBan_Imported": ("rayban.glb", "Vending_TechLocker"),
    "PowerBank_Imported": ("powerbank.glb", "Vending_TechLocker"),
    "Hero_AppleVisionPro": ("apple_vision_pro.glb", "Vending_TechLocker"),
    # Eight props on the window-display shelves.
    "Storefront_WallClock": ("wall_clock.glb", "Shop_Structure"),
    "Storefront_Perfume": ("perfume.glb", "Shop_Structure"),
    "Storefront_HandWatch": ("hand_watch.glb", "Shop_Structure"),
    "Storefront_Handbag": ("handbag.glb", "Shop_Structure"),
    "Storefront_FlowerVase": ("flower_vase.glb", "Shop_Structure"),
    "Storefront_StanleyTumbler": ("stanley.glb", "Shop_Structure"),
    "Storefront_ToyRobot": ("toy_robot.glb", "Shop_Structure"),
    "Storefront_Lamp": ("lamp.glb", "Shop_Structure"),
}

COLLECTION = "Imported_Products"

#: "exact"   — scale each axis independently so the import reproduces the box the
#:             scene actually had. Six of these props were non-uniformly squashed
#:             by hand before being baked into mesh data (the flower vase is a
#:             0.41 m-wide model that sat in a 0.18 m footprint), so this is what
#:             restores the shelves to how they looked.
#: "uniform" — one scale factor for all axes. Keeps the source model's true
#:             proportions, at the cost of overhanging its authored footprint.
FIT_MODE = "exact"

with open(PLACEMENTS) as handle:
    PLACEMENT_DATA = json.load(handle)


def get_collection() -> bpy.types.Collection:
    col = bpy.data.collections.get(COLLECTION)
    if col is None:
        col = bpy.data.collections.new(COLLECTION)
        bpy.context.scene.collection.children.link(col)
    return col


def subtree_bbox(root):
    """World-space bounding box of `root` and everything under it."""
    deps = bpy.context.evaluated_depsgraph_get()
    mn = Vector((1e18,) * 3)
    mx = Vector((-1e18,) * 3)
    found = False
    for obj in [root] + list(root.children_recursive):
        if obj.type not in {"MESH", "CURVE", "FONT", "SURFACE"}:
            continue
        evaluated = obj.evaluated_get(deps)
        try:
            mesh = evaluated.to_mesh()
        except Exception:
            continue
        if mesh is None or not len(mesh.vertices):
            evaluated.to_mesh_clear()
            continue
        for vert in mesh.vertices:
            point = obj.matrix_world @ vert.co
            for i in range(3):
                mn[i] = min(mn[i], point[i])
                mx[i] = max(mx[i], point[i])
            found = True
        evaluated.to_mesh_clear()
    return (mn, mx) if found else (None, None)


def axis_aligned_rotations():
    """The 24 rotations that map a box onto itself, as quaternions.

    Built by taking every signed axis permutation and keeping the ones with
    determinant +1 (the improper ones are mirrors, which would flip the model).
    """
    out = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            mat = Matrix(((0.0,) * 3, (0.0,) * 3, (0.0,) * 3))
            for row, col in enumerate(perm):
                mat[row][col] = float(signs[row])
            if round(mat.determinant()) == 1:
                out.append(mat.to_quaternion())
    return out


ROTATION_CANDIDATES = axis_aligned_rotations()


def orient_to_target(holder, target_size) -> tuple[Quaternion, float]:
    """Finds the axis-aligned rotation whose bounding box best matches the scene.

    The raw `assets/models/*.glb` files do not share the orientation the in-scene copies
    used — `airpods_pro.glb` arrives with X and Y transposed. Because an
    axis-aligned rotation only permutes the bounding-box extents, the correct one
    can be found by comparing size vectors rather than by re-measuring the mesh
    24 times: the local box is measured once and each candidate scored against
    the authored extents.
    """
    base = holder.rotation_quaternion.copy()
    mn, mx = subtree_bbox(holder)
    if mn is None:
        return base, float("inf")

    # Extents in the holder's own frame, before any candidate is applied.
    inverse = holder.matrix_world.inverted()
    corners = [Vector((x, y, z)) for x in (mn[0], mx[0])
               for y in (mn[1], mx[1]) for z in (mn[2], mx[2])]
    local = [inverse @ c for c in corners]
    local_size = Vector((max(c[i] for c in local) - min(c[i] for c in local) for i in range(3)))

    wanted = Vector(target_size)
    scale = max(wanted) / max(local_size) if max(local_size) > 1e-12 else 1.0

    best, best_score = base, float("inf")
    for candidate in ROTATION_CANDIDATES:
        rotated = candidate.to_matrix()
        size = Vector((sum(abs(rotated[i][j]) * local_size[j] for j in range(3)) for i in range(3)))
        score = sum(abs(size[i] * scale - wanted[i]) for i in range(3))
        if score < best_score:
            best, best_score = (base @ candidate), score
    return best, best_score


def purge(name: str) -> bool:
    """Removes an existing import so a re-run replaces rather than duplicates."""
    existing = bpy.data.objects.get(name)
    if existing is None:
        return False
    for obj in list(existing.children_recursive) + [existing]:
        bpy.data.objects.remove(obj, do_unlink=True)
    return True


def import_product(name: str) -> str:
    source, parent_name = PRODUCTS[name]
    path = os.path.join(ASSETS, source)
    if not os.path.exists(path):
        return f"! {source} not found in assets/"

    target = PLACEMENT_DATA.get(name)
    if not target or not target.get("present") or not target.get("bbox"):
        return f"! no authored placement recorded for {name}"

    replaced = purge(name)

    before = set(bpy.data.objects)
    # The glTF importer logs one INFO line per mesh node; drone.glb alone emits
    # ~700 of them, which buries the actual result.
    with contextlib.redirect_stdout(io.StringIO()):
        bpy.ops.import_scene.gltf(filepath=path)
    imported = [o for o in bpy.data.objects if o not in before]
    if not imported:
        return f"! import produced no objects for {source}"

    # One Empty carrying the authored node name, with every imported root under it.
    holder = bpy.data.objects.new(name, None)
    holder.empty_display_size = 0.05
    get_collection().objects.link(holder)

    for obj in imported:
        if obj.parent is None:
            obj.parent = holder

    bpy.context.view_layer.update()

    # 1. Authored orientation first, so the bbox below is measured in the pose
    #    the object will actually sit in.
    holder.rotation_mode = "QUATERNION"
    holder.rotation_quaternion = Quaternion(target["world_quat"])
    bpy.context.view_layer.update()

    # 2. Correct the source file's own orientation onto the authored one.
    oriented, _ = orient_to_target(holder, target["bbox"]["size"])
    holder.rotation_quaternion = oriented
    bpy.context.view_layer.update()

    # 3. Uniform scale so the longest axis matches what the scene had.
    mn, mx = subtree_bbox(holder)
    if mn is None:
        return f"! {name}: imported hierarchy has no geometry"
    current = Vector((mx[i] - mn[i] for i in range(3)))
    wanted = Vector(target["bbox"]["size"])
    if max(current) <= 1e-9:
        return f"! {name}: degenerate source bounds"

    uniform = max(wanted) / max(current)
    if FIT_MODE == "exact":
        holder.scale = Vector((wanted[i] / current[i] if current[i] > 1e-9 else uniform
                               for i in range(3)))
    else:
        holder.scale = Vector((uniform, uniform, uniform))
    factor = uniform
    bpy.context.view_layer.update()

    # 4. Refine the scale, keeping the best result rather than the last.
    #
    #    A single pass is exact only when every child shares the holder's axes.
    #    Where a child carries its own off-axis rotation (the handbag, the
    #    watch), the subtree's world box is not a per-axis multiple of the
    #    holder's scale — the relationship is sheared — so re-measuring and
    #    correcting can overshoot and then diverge, which drove the handbag from
    #    13% out to 175% out. Scoring every pass and restoring the best one makes
    #    the refinement monotonic: it can only improve on the opening fit.
    #
    #    The transform is deliberately left live on the holder rather than baked.
    #    `transform_apply` across a parent *and* its children double-counts the
    #    parent transform — it stretched the toy robot from 0.28 m to 1.81 m —
    #    and a non-uniform scale above a rotated child is a shear, which Blender
    #    cannot store in an object transform at all. Both Blender and glTF express
    #    parent-scale-then-child-rotation correctly as a hierarchy, and the build
    #    pipeline runs with `--flatten false`, so it survives to the browser.
    def measure() -> Vector | None:
        lo, hi = subtree_bbox(holder)
        return None if lo is None else Vector((hi[i] - lo[i] for i in range(3)))

    def score(size) -> float:
        return max(abs(size[i] - wanted[i]) / max(wanted[i], 1e-6) for i in range(3))

    best_scale = holder.scale.copy()
    best_score = score(measure() or Vector((0, 0, 0)))

    for _ in range(4):
        if best_score < 1e-4:
            break
        measured = measure()
        if measured is None or min(measured) <= 1e-9:
            break
        if FIT_MODE == "exact":
            holder.scale = Vector((holder.scale[i] * (wanted[i] / measured[i]) for i in range(3)))
        else:
            holder.scale = Vector((s * (max(wanted) / max(measured)) for s in holder.scale))
        bpy.context.view_layer.update()

        current_score = score(measure() or Vector((0, 0, 0)))
        if current_score < best_score:
            best_scale, best_score = holder.scale.copy(), current_score

    holder.scale = best_scale
    bpy.context.view_layer.update()
    scale_is_uniform = max(holder.scale) - min(holder.scale) < 1e-6

    # 5. Position: centre on X and Y, but seat on Z. Must follow the scaling,
    #    since scaling about the holder's origin moves the box.
    #
    #    Matching the centre on every axis looks right only while the fit is
    #    exact. Where a residual height error remains it spills evenly above and
    #    below, which buries the object in its shelf — the handbag's 13% surplus
    #    sank it 30 mm into the slab. Aligning the base to the authored base
    #    instead keeps whatever rests on a surface resting on it, and matches how
    #    a prop is actually placed.
    mn, mx = subtree_bbox(holder)
    want_min = Vector(target["bbox"]["min"])
    want_max = Vector(target["bbox"]["max"])
    delta = Vector((
        (want_min[0] + want_max[0]) / 2 - (mn[0] + mx[0]) / 2,
        (want_min[1] + want_max[1]) / 2 - (mn[1] + mx[1]) / 2,
        want_min[2] - mn[2],
    ))
    holder.location += delta
    bpy.context.view_layer.update()

    # 6. Re-parent to the node the original hung off, keeping the world pose.
    parent = bpy.data.objects.get(parent_name)
    if parent is not None:
        holder.parent = parent
        holder.matrix_parent_inverse = parent.matrix_world.inverted()
        bpy.context.view_layer.update()

    mn, mx = subtree_bbox(holder)
    size = [round(mx[i] - mn[i], 4) for i in range(3)]
    drift = max(abs((mn[i] + mx[i]) / 2 - target["bbox"]["center"][i]) for i in range(3))
    # Worst per-axis disagreement with the authored box, as a share of that axis.
    fit = max(abs(size[i] - wanted[i]) / max(wanted[i], 1e-6) for i in range(3))

    flag = "" if fit < 0.02 else f"  <-- CHECK, {fit * 100:.0f}% off authored box"
    shape = "uniform" if scale_is_uniform else "non-uniform fit (source proportions differ)"
    return (f"{'replaced' if replaced else 'added':8s} x{factor:<10.5g} "
            f"size={size}  drift {drift * 1000:.2f}mm  "
            f"{len(imported)} objs, {shape}{flag}")


def run_batch(names) -> None:
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for name in names:
        if name not in PRODUCTS:
            print(f"  ! {name}: not a known product")
            continue
        print(f"  {name}: {import_product(name)}")


if __name__ == "__main__":
    run_batch(list(PRODUCTS))
