"""
blend/main-scene.blend — restore the vending-machine product system.

Run headless, writing to a copy so the source is never clobbered:

    blender --background blend/main-scene.blend \
            --python rebuild_vending.py -- --out /tmp/out.blend

WHAT WAS BROKEN
---------------
Four separate failures, all of which ended with the web build falling back to a
catalogue authored in TypeScript:

1. **The fourteen imported props had been deleted from the scene.** The
   `Imported_Products` collection was empty, so every node `vm_products` points
   at — `Hero_Drone_Imported` and the rest — resolved to nothing, and
   `frontend/scripts/build-separated.mjs` could not have extracted them.

2. **`vm_products` never reached the GLB.** The property itself was on
   `Vending_TechLocker` and correct; the glTF exporter simply was not asked for
   custom properties. There was no export script in the repo, so the setting
   lived in whoever's UI last exported. `scripts/export/export_glb.py` now owns it.

3. **The delivery actions had no users.** `VM_Product_Deliver_01`…`06` survived
   only because they were marked with a fake user. glTF exports animation by
   walking objects, so an action nothing is bound to is not written out, which
   is why the GLB contained no `VM_Product_Deliver_*`.

4. **They were authored at ten times the length the site plays them at.** Each
   is a full turn over frames 1–250, which at the scene's 24 fps is 10.4 s. The
   site gives dispensing 900 ms (`FALLBACK_DISPENSE_MS`) and holds the camera
   locked for the duration, so exporting them as authored would have replaced a
   beat with a hang.

WHAT THIS DOES ABOUT (4)
------------------------
Retimes each clip to `DELIVER_SECONDS` and adds a small lift, so the item rises
off its riser, turns once to face the glass and settles back.

It presents rather than dispenses because the locker cannot do anything else:
there is no bin, chute, tray or flap anywhere in the model, and the body is
solid below the glass at z 1.167. A product falling out of this machine would
fall through it.

THE CATALOGUE HAS ONE AUTHOR
----------------------------
`vm_products` is rebuilt from the `vm_*` properties on the `VM_Key_NN` objects
rather than edited in place. Both carried the same six records, which is two
places to change a price and one of them to forget. The keys win because they
are where a slot's identity is already anchored — `vm_slot` is what the runtime
matches a keypad press against.
"""

import importlib.util
import json
import math
import os
import sys

import bpy

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:                       # Text Editor with no file path
    HERE = os.path.join(os.path.dirname(os.path.dirname(bpy.data.filepath)),
                        "scripts", "animation")

#: import_products.py lives under scripts/objects/, one category across.
IMPORT_PRODUCTS = os.path.join(os.path.dirname(HERE), "objects", "import_products.py")

#: Seconds each delivery clip should run for. Sized against the site's own
#: dispensing beat — `FALLBACK_DISPENSE_MS` in `components/VendingMachine.tsx`
#: is what plays when a clip is missing, and the clip should feel like that
#: beat rather than like a different scene.
DELIVER_SECONDS = 1.1

#: Metres the product rises off its riser at the middle of the turn.
DELIVER_LIFT = 0.025

#: Which product each keypad slot dispenses is read from the keys themselves.
KEY_PREFIX = "VM_Key_"
LOCKER = "Vending_TechLocker"


def log(msg: str) -> None:
    print(f"[rebuild-vending] {msg}")


# ---------------------------------------------------------------- 1. products


def restore_products() -> list[str]:
    """Re-imports every product and prop, at the scale the scene was composed at."""
    spec = importlib.util.spec_from_file_location("import_products", IMPORT_PRODUCTS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    missing = [n for n in mod.PRODUCTS if n not in bpy.data.objects]
    if not missing:
        log("all fourteen props already present — nothing to import")
        return []
    log(f"importing {len(missing)} missing props: {', '.join(missing)}")
    mod.run_batch(missing)

    still = [n for n in mod.PRODUCTS if n not in bpy.data.objects]
    if still:
        raise SystemExit(f"import failed for: {still}")
    return missing


# ------------------------------------------------------------- 2. delivery


def slot_for(action, obj):
    """The action's slot that targets `obj`, or None."""
    for slot in action.slots:
        if slot.target_id_type == "OBJECT" and slot.name_display == obj.name:
            return slot
    return None


def channelbags(action):
    for layer in action.layers:
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                yield bag


def bag_for_slot(action, slot):
    for bag in channelbags(action):
        if bag.slot_handle == slot.handle:
            return bag
    return None


def retime(action, scale: float) -> None:
    """Scales every keyframe on `action` in time, handles included."""
    for bag in channelbags(action):
        for fcurve in bag.fcurves:
            for key in fcurve.keyframe_points:
                key.co.x *= scale
                key.handle_left.x *= scale
                key.handle_right.x *= scale
            fcurve.update()


def add_lift(bag, rest_z: float, last_frame: float) -> None:
    """Keys `location[2]` up and back over the clip, on top of the turn."""
    existing = next(
        (f for f in bag.fcurves if f.data_path == "location" and f.array_index == 2), None
    )
    if existing:
        bag.fcurves.remove(existing)
    fcurve = bag.fcurves.new("location", index=2)
    for frame, value in (
        (1.0, rest_z),
        (1.0 + (last_frame - 1.0) * 0.35, rest_z + DELIVER_LIFT),
        (last_frame, rest_z),
    ):
        key = fcurve.keyframe_points.insert(frame, value)
        key.interpolation = "BEZIER"
    fcurve.update()


def bind_delivery(catalogue: list[dict]) -> None:
    fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
    target_frames = DELIVER_SECONDS * fps

    for entry in catalogue:
        obj = bpy.data.objects.get(entry["node"])
        action = bpy.data.actions.get(entry["clip"])
        if obj is None or action is None:
            raise SystemExit(f"slot {entry['slot']}: node/clip missing ({entry})")

        # The turn is keyed on `rotation_euler`, which does nothing to an object
        # in quaternion mode — and `import_products` places these with a
        # quaternion. Euler is also what glTF wants for a single-axis spin.
        if obj.rotation_mode == "QUATERNION":
            obj.rotation_euler = obj.rotation_quaternion.to_euler("XYZ")
        obj.rotation_mode = "XYZ"

        start, end = action.frame_range
        scale = target_frames / max(1e-6, end - start)
        retime(action, scale)
        start, end = action.frame_range

        slot = slot_for(action, obj)
        if slot is None:
            raise SystemExit(f"{action.name} has no OBJECT slot named {obj.name}")
        bag = bag_for_slot(action, slot)
        if bag is None:
            raise SystemExit(f"{action.name}: slot {slot.name_display} has no channels")
        add_lift(bag, obj.location.z, end)

        obj.animation_data_create()
        obj.animation_data.action = action
        obj.animation_data.action_slot = slot
        log(f"  {entry['slot']} {action.name} -> {obj.name}  {end / fps:.2f}s")

        # `VM_Product_Deliver_02_Lid` opens the AirPods case, and its own slots
        # target objects inside that imported model. Same retime, so the two
        # clips finish together — the site waits for both before completing.
        lid = bpy.data.actions.get(f"{entry['clip']}_Lid")
        if lid is None:
            continue
        lstart, lend = lid.frame_range
        retime(lid, target_frames / max(1e-6, lend - lstart))
        bound = 0
        for slot in lid.slots:
            if slot.target_id_type != "OBJECT":
                continue
            target = bpy.data.objects.get(slot.name_display)
            if target is None:
                log(f"    ! {lid.name}: no object named {slot.name_display}")
                continue
            target.animation_data_create()
            target.animation_data.action = lid
            target.animation_data.action_slot = slot
            bound += 1
        log(f"    {lid.name} -> {bound} object(s)  {lid.frame_range[1] / fps:.2f}s")


# ------------------------------------------------------------ 3. catalogue


def read_catalogue() -> list[dict]:
    """The six records, read off the keypad keys."""
    out = []
    for obj in bpy.data.objects:
        if not obj.name.startswith(KEY_PREFIX) or obj.get("vm_role") != "select":
            continue
        out.append(
            {
                "slot": obj["vm_slot"],
                "node": obj["vm_product_node"],
                "title": obj["vm_title"],
                "bay": obj["vm_bay"],
                "price": obj["vm_price"],
                "clip": obj["vm_clip"],
                "name": obj["vm_name"],
            }
        )
    return sorted(out, key=lambda e: e["slot"])


def bake_catalogue(catalogue: list[dict]) -> None:
    locker = bpy.data.objects.get(LOCKER)
    if locker is None:
        raise SystemExit(f"{LOCKER} is missing")

    for entry in catalogue:
        for field, name in (("node", entry["node"]), ("bay", entry["bay"])):
            if name not in bpy.data.objects:
                raise SystemExit(f"slot {entry['slot']}: {field} '{name}' is not in the scene")

    blob = {
        e["slot"]: {k: e[k] for k in ("node", "title", "bay", "price", "clip", "name")}
        for e in catalogue
    }
    locker["vm_products"] = json.dumps(blob)
    log(f"vm_products baked onto {LOCKER}: {len(blob)} slots, {len(locker['vm_products'])} bytes")


# ------------------------------------------------------------------- main


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    out = argv[argv.index("--out") + 1] if "--out" in argv else bpy.data.filepath

    restore_products()

    catalogue = read_catalogue()
    if len(catalogue) != 6:
        raise SystemExit(f"expected 6 keypad products, read {len(catalogue)}")
    log(f"catalogue: {', '.join(e['slot'] + '=' + e['title'] for e in catalogue)}")

    bind_delivery(catalogue)
    bake_catalogue(catalogue)

    bpy.ops.wm.save_as_mainfile(filepath=out)
    log(f"saved {out}")


main()
