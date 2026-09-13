"""
blend/main-scene.blend — the skateboard that is the site's navigation.

Run from Blender's Scripting workspace with `blend/main-scene.blend` open: open
this file in the Text Editor and press "Run Script". Idempotent, the same way
`scripts/lighting/build_track_lights.py` is — every object it creates is deleted by name first,
so re-running replaces the board instead of stacking a second one on top of it.

WHY IT IS BUILT RATHER THAN DOWNLOADED
--------------------------------------
The Sketchfab, Hyper3D Rodin and Hunyuan3D integrations are all switched off in
this Blender's MCP panel, so there is no asset to fetch. That turns out to be
the better outcome anyway: every other prop in this diorama is hand-authored,
and a photoscanned deck with a 4K albedo would be the one object in the scene
that came from somewhere else and looked it.

WHERE IT SITS, AND WHY THAT IS NOT WHERE THE PLAN SAID
------------------------------------------------------
The design proposal put the board on a "forecourt ledge, top face 1.42 m, 1.29 m
deep". That reading came from bounding boxes, and bounding boxes lied: the three
meshes inside `Forecourt_Barrier_Wall` each span the full 7 m width, so their
boxes union into a solid-looking slab that is mostly air.

Measured properly — up-facing polygons, then downward ray casts on a grid — the
forecourt is:

  * an open floor at z = 0.800 (and a step at z = 0.880 right at the shopfront),
    running from y = -2.05 back to about y = -3.25;
  * a low parapet along the street edge whose coping tops out at **z = 1.559**,
    y = -3.49 … -3.29, i.e. only **0.20 m wide**;
  * a gap in that parapet at x ~ +1.0, which is the way in from the street.

The board has been in three places, and the reason it moved twice is the same
reason each time: it has to be *seen*.

  1. On the parapet coping (z = 1.560). 0.20 m is exactly a board's width and
     chest height is where a control can be reached — but a board balanced along
     the top of a wall reads as a prop placed there to be a UI, not as a board.
  2. On the forecourt floor at y = -2.70, which fixed that. It also put the
     1.56 m parapet directly between the board and every camera on the street
     side, including the home framing the site opens on. A navigation object you
     cannot see is worse than a navbar.
  3. **On the pavement, street-side of the parapet**, which is where it is now.

So: z = 0.800, the top of `Diorama_Base`, ray cast and continuous from y = -3.50
out past -5.30; and y = -2.70 -> **-3.70**, which is 0.10 m clear of the
parapet's outer face at -3.49. The board spans y -3.592 … -3.808, parked just
off the wall the way a board leans by a shopfront.

Two things fall out of that, both good:

  * Nothing occludes it. The parapet is now *behind* the board from any street
    camera rather than in front of it, and it makes a dark backdrop for a lit
    board rather than a screen in front of one.
  * It is better lit than it was on the forecourt. `Spot_Awning_03` puts its
    floor-level pool centre at y = -3.352 with a 0.84 m radius, so at -3.70 the
    board sits 0.35 m off centre instead of the 0.65 m it was at -2.70.

What it costs is cover: `Awning_Front` spans y -3.39 … -2.00, so the board is
0.11 m beyond the awning's leading edge, under open sky. That is what dictates
where the read head hangs from — see below.

THE READ HEAD
-------------
The nav mechanic is that the board slides and a fixed light picks the active
destination.

Note what the awning's own wash does and does not do. `Spot_Awning_03` is a
30 deg cone tilted 12 deg out toward the street, which puts a 0.84 m pool radius
at pavement level. That is several times the 0.19 m slot pitch, so it has never
*isolated* one label and was never going to: all it establishes is that the
board is lit. Discriminating the active destination is the griptape canvas's
job, painted the way `IdentityBoard` and `SideLedPanel` paint theirs.

The frontend hangs its own narrow spot for the read head, and where it hangs
from is set by the board being past the awning's edge. Not from the recessed can
at (-0.95, -2.70, 3.895): reaching y = -3.70 from there is an 18.7 deg tilt, and
that emitter sits up inside a channel cut into the awning slab (z 3.477 …
4.190), so a steep ray risks being clipped by the channel itself. Instead it
hangs at the awning's **leading edge**, (-0.95, -3.39, 3.477), where 7.0 deg of
outward tilt reaches the board unobstructed.

Either way the tilt is *away* from the shop, which is the only direction that is
safe. `AwningLighting` documents the limit: from this mounting line any ray
leaning more than 13.1 deg *toward* the shop reaches `Facade_Glass` above its
sill, reflects off the outer face toward the camera, and the bloom pass turns it
into a flare. Head 03 itself must therefore never be re-aimed or widened to do
this job.

x = -0.95 is therefore the read-head position, and it is also clear of the
doorway (x 0.88 … 1.82) and of the parapet gap.

TRAVEL
------
Four destinations at a 0.19 m pitch means the board slides 3 x 0.19 = 0.57 m in
total, so its centre runs x = -1.235 (About lit) to x = -0.665 (Contact lit) and
its ends never leave x -1.66 … -0.24. The floor is continuous well past both, so
x = 0.0, so the whole travel is supported with room either side.

The board is built at REST_X, which is the About end of that travel — the
frontend animates `Skateboard` (the empty) along X from there.

WHAT THE FRONTEND NEEDS FROM THIS
---------------------------------
  Skateboard              EMPTY, the root. Slide this; everything follows.
  Skateboard_Griptape     the label surface. A separate object, offset 1.5 mm
                          along the deck normal, carrying its own planar UVs in
                          [0,1] so a canvas texture maps to it with no guesswork
                          — the same arrangement `IdentityBoard` uses on the
                          fascia and `SideLedPanel` on the blade sign.
  Skateboard_Wheel_*      four separate objects with origins on their own axles,
                          so spinning them is `rotation_euler.y += travel / r`
                          and nothing else.

GEOMETRY
--------
A 34" cruiser rather than a 32" street deck: 0.86 x 0.215 m. Slightly generous
for a real board, and it has to carry four words of type on its top face at a
distance of about 1.8 m, which a 32" deck makes genuinely tight.

The deck is one lofted surface — kick at both ends, concave across the width,
elliptical taper into rounded nose and tail — solidified to 11 mm. Building it
as a grid and solidifying is what keeps the concave and the kick continuous;
modelling top and bottom separately puts a seam down the rails.
"""

import math

import bpy
from mathutils import Vector

# ── CONFIG ───────────────────────────────────────────────────────────────────

CONFIG = {
    # Placement, in Blender's Z-up world. The frontend's three.js coordinates
    # relate as three(x, y, z) -> blender(x, -z, y).
    "ground_z": 0.800,   # top of Diorama_Base; ray cast, continuous x -1.85..-0.60
    "rest_y": -3.70,     # pavement, 0.10 m clear of the parapet's outer face
    # Half a millimetre of air under the wheels.
    #
    # Seated exactly on 0.800 the wheel's lowest edge and the top face of
    # `Diorama_Base` occupy the same depth, which is the setup for shadow acne
    # along the contact line and for the two surfaces trading places between
    # frames. 0.5 mm is far below anything visible at this scene's viewing
    # distances and removes the coincidence outright.
    "ground_clearance": 0.0005,
    "rest_x": -1.235,    # About end of the travel; read head is at x = -0.95

    # Deck
    "length": 0.86,
    "width": 0.215,
    "thickness": 0.011,
    "kick_start": 0.62,   # |u| beyond which the deck starts to rise
    "kick_rise": 0.052,   # height gained at the very tip
    "concave": 0.010,     # rails this much above the centre line
    "taper_start": 0.66,  # |u| beyond which the outline starts to round off
    "nose_width": 0.30,   # fraction of half-width remaining at the tip

    # Grip surface
    "grip_lift": 0.0015,
    "grip_u": 0.90,       # covers all but the last 10% of each tip
    "grip_inset": 0.006,  # pulled in from the rails, as real grip is

    # Trucks and wheels
    "wheelbase": 0.38,
    "wheel_radius": 0.027,
    "wheel_width": 0.032,
    "wheel_offset_y": 0.086,
    "hanger_half": 0.062,
    "deck_clear": 0.079,  # ground to underside of the deck at the flat middle

    # Mesh density
    "nx": 49,
    "ny": 15,
}

# Colours are authored as sRGB hex, the way the picker and the rest of this
# file's materials speak, and converted on the way into the shader socket —
# see the COLOUR SPACE note in `scripts/lighting/build_track_lights.py` for why this is needed.
COLOURS = {
    "deck":  "#6B4A2F",  # stained maple, seen only from underneath
    "grip":  "#141619",  # griptape: near-black and very rough
    "truck": "#B9BEC6",  # raw polished aluminium
    "wheel": "#E8E4DA",  # off-white urethane
    "bolt":  "#8E959E",
}

PREFIX = "Skateboard"


# ── helpers ──────────────────────────────────────────────────────────────────

def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_linear(h: str):
    h = h.lstrip("#")
    return tuple(srgb_to_linear(int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4))


def material(name, hex_colour, roughness, metallic=0.0):
    """Create or reset a Principled material. Reset, so re-running is a no-op."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*hex_to_linear(hex_colour), 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def purge(prefix):
    """Delete every object this script owns, plus any orphaned mesh data."""
    for obj in [o for o in bpy.data.objects if o.name == prefix or o.name.startswith(prefix + "_")]:
        data = obj.data if obj.type == "MESH" else None
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            bpy.data.meshes.remove(data)


def new_mesh_object(name, verts, faces, collection, uvs=None):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    if uvs is not None:
        layer = mesh.uv_layers.new(name="UVMap")
        for loop in mesh.loops:
            layer.data[loop.index].uv = uvs[loop.vertex_index]
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


# ── deck surface ─────────────────────────────────────────────────────────────

def deck_height(u: float) -> float:
    """Kick profile along the length. `u` runs -1 (tail) to +1 (nose)."""
    a = abs(u)
    k = CONFIG["kick_start"]
    if a <= k:
        return 0.0
    t = (a - k) / (1.0 - k)
    # Smoothstep rather than a straight ramp: a real kick eases out of the flat
    # rather than creasing into it.
    return CONFIG["kick_rise"] * (t * t * (3.0 - 2.0 * t))


def deck_half_width(u: float) -> float:
    """Outline taper into the rounded nose and tail."""
    a = abs(u)
    t0 = CONFIG["taper_start"]
    half = CONFIG["width"] / 2.0
    if a <= t0:
        return half
    t = (a - t0) / (1.0 - t0)
    # Elliptical, so the tips round off instead of coming to a point.
    shrink = 1.0 - (1.0 - CONFIG["nose_width"]) * (1.0 - math.sqrt(max(0.0, 1.0 - t * t)))
    return half * shrink


def build_deck_grid(u_limit=1.0, inset=0.0, lift=0.0):
    """A grid of points on the deck's top surface, plus matching planar UVs."""
    nx, ny = CONFIG["nx"], CONFIG["ny"]
    verts, uvs = [], []
    for i in range(nx):
        u = -u_limit + 2.0 * u_limit * i / (nx - 1)
        x = u * CONFIG["length"] / 2.0
        hw = max(1e-4, deck_half_width(u) - inset)
        z0 = deck_height(u)
        for j in range(ny):
            v = -1.0 + 2.0 * j / (ny - 1)
            y = v * hw
            z = z0 + CONFIG["concave"] * v * v + lift
            verts.append((x, y, z))
            uvs.append((i / (nx - 1), j / (ny - 1)))
    faces = []
    for i in range(nx - 1):
        for j in range(ny - 1):
            a = i * ny + j
            faces.append((a, a + ny, a + ny + 1, a + 1))
    return verts, faces, uvs


# ── build ────────────────────────────────────────────────────────────────────

def build():
    scene_collection = bpy.context.scene.collection
    target = bpy.data.collections.get("StreetFixtures") or scene_collection

    purge(PREFIX)

    mat_deck = material("Mat_Skate_Deck", COLOURS["deck"], 0.52)
    mat_grip = material("Mat_Skate_Grip", COLOURS["grip"], 0.94)
    mat_truck = material("Mat_Skate_Truck", COLOURS["truck"], 0.34, metallic=1.0)
    mat_wheel = material("Mat_Skate_Wheel", COLOURS["wheel"], 0.42)
    mat_bolt = material("Mat_Skate_Bolt", COLOURS["bolt"], 0.30, metallic=1.0)

    # Root empty. Everything hangs off this, so the frontend slides one object.
    root = bpy.data.objects.new(PREFIX, None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.12
    root.location = (
        CONFIG["rest_x"],
        CONFIG["rest_y"],
        CONFIG["ground_z"] + CONFIG["wheel_radius"] + CONFIG["ground_clearance"],
    )
    target.objects.link(root)

    # Local Z = 0 is the axle line; the deck sits `deck_clear - wheel_radius`
    # above it. Working in axle-space is what lets the wheels keep their origins
    # on their own axles without a second offset to reason about.
    deck_z = CONFIG["deck_clear"] - CONFIG["wheel_radius"]

    # ── deck ────────────────────────────────────────────────────────────────
    verts, faces, uvs = build_deck_grid()
    verts = [(x, y, z + deck_z + CONFIG["thickness"]) for (x, y, z) in verts]
    deck = new_mesh_object(f"{PREFIX}_Deck", verts, faces, target, uvs)
    deck.data.materials.append(mat_deck)

    solidify = deck.modifiers.new("Solidify", "SOLIDIFY")
    solidify.thickness = CONFIG["thickness"]
    solidify.offset = -1.0          # grow downward, keep the top surface put
    solidify.use_even_offset = True
    solidify.use_rim = True
    bpy.context.view_layer.objects.active = deck
    bpy.ops.object.modifier_apply(modifier="Solidify")
    for poly in deck.data.polygons:
        poly.use_smooth = True

    # ── griptape ────────────────────────────────────────────────────────────
    # A separate object rather than a material slot on the deck: the frontend
    # paints a canvas onto this and needs its UVs to be its own, filling [0,1].
    gverts, gfaces, guvs = build_deck_grid(
        u_limit=CONFIG["grip_u"], inset=CONFIG["grip_inset"], lift=CONFIG["grip_lift"]
    )
    gverts = [(x, y, z + deck_z + CONFIG["thickness"]) for (x, y, z) in gverts]
    grip = new_mesh_object(f"{PREFIX}_Griptape", gverts, gfaces, target, guvs)
    grip.data.materials.append(mat_grip)
    for poly in grip.data.polygons:
        poly.use_smooth = True

    # ── trucks and wheels ───────────────────────────────────────────────────
    half_wb = CONFIG["wheelbase"] / 2.0
    for end, sx in (("Front", 1.0), ("Rear", -1.0)):
        x = sx * half_wb

        # Baseplate: a flat pad bolted under the deck.
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, 0.0, deck_z - 0.006))
        base = bpy.context.active_object
        base.name = f"{PREFIX}_Truck_{end}_Base"
        base.scale = (0.052, 0.062, 0.006)
        base.data.materials.append(mat_truck)

        # Hanger: the cast arm the axle runs through, angled down and outward.
        bpy.ops.mesh.primitive_cone_add(
            vertices=6, radius1=0.026, radius2=0.013, depth=0.062,
            location=(x - sx * 0.016, 0.0, deck_z - 0.026),
            rotation=(0.0, math.radians(sx * 64.0), 0.0),
        )
        hanger = bpy.context.active_object
        hanger.name = f"{PREFIX}_Truck_{end}_Hanger"
        hanger.data.materials.append(mat_truck)

        # Axle.
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=12, radius=0.0045, depth=0.196,
            location=(x, 0.0, 0.0), rotation=(math.radians(90.0), 0.0, 0.0),
        )
        axle = bpy.context.active_object
        axle.name = f"{PREFIX}_Truck_{end}_Axle"
        axle.data.materials.append(mat_bolt)

        # Kingpin nut, just enough to read as hardware.
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=6, radius=0.007, depth=0.014,
            location=(x - sx * 0.030, 0.0, deck_z - 0.020),
            rotation=(0.0, math.radians(sx * 64.0), 0.0),
        )
        pin = bpy.context.active_object
        pin.name = f"{PREFIX}_Truck_{end}_Kingpin"
        pin.data.materials.append(mat_bolt)

        for side, sy in (("L", 1.0), ("R", -1.0)):
            # Origin on the axle, so a spin is one euler write and no offset.
            bpy.ops.mesh.primitive_cylinder_add(
                vertices=24,
                radius=CONFIG["wheel_radius"],
                depth=CONFIG["wheel_width"],
                location=(x, sy * CONFIG["wheel_offset_y"], 0.0),
                rotation=(math.radians(90.0), 0.0, 0.0),
            )
            wheel = bpy.context.active_object
            wheel.name = f"{PREFIX}_Wheel_{end[0]}{side}"
            wheel.data.materials.append(mat_wheel)
            for poly in wheel.data.polygons:
                poly.use_smooth = True

    # ── parent everything to the root ───────────────────────────────────────
    made = [o for o in bpy.data.objects
            if o.name.startswith(PREFIX + "_") and o.parent is None]
    for obj in made:
        # The parent inverse stays identity, so the children inherit the root's
        # placement and land on the floor with it.
        #
        # It used to be set to `root.matrix_world.inverted()`, which is the
        # recipe for the opposite case — children already authored in *world*
        # space, which parenting must then not move. These are not: every part
        # above is built in the root's own frame, in axle-space centred on the
        # origin. Cancelling the root against geometry that is already local
        # subtracts the placement twice, and the whole board rendered at the
        # world origin, 3.5 m away and buried under the ground slab (the deck
        # sat at z 0.05-0.13 against a `Diorama_Base` top of z 0.80). Only the
        # empty was ever in the right place, which is why it looked right in the
        # outliner.
        obj.parent = root

    # Objects created by bpy.ops land in the active collection; move any strays.
    for obj in made:
        for coll in list(obj.users_collection):
            if coll is not target:
                coll.objects.unlink(obj)
        if obj.name not in target.objects:
            target.objects.link(obj)

    bpy.context.view_layer.update()
    return root, deck, grip


if __name__ == "__main__":
    root, deck, grip = build()

    def world_box(obj):
        pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        return (
            Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))),
            Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))),
        )

    lo, hi = world_box(deck)
    print(f"{PREFIX}: root at {tuple(round(v, 3) for v in root.location)}")
    print(f"  deck  x[{lo.x:.3f},{hi.x:.3f}] y[{lo.y:.3f},{hi.y:.3f}] z[{lo.z:.3f},{hi.z:.3f}]")
    lo, hi = world_box(grip)
    print(f"  grip  x[{lo.x:.3f},{hi.x:.3f}] y[{lo.y:.3f},{hi.y:.3f}] z[{lo.z:.3f},{hi.z:.3f}]")
    print(f"  parts {len(root.children)}")
