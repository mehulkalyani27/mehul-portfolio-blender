"""
blend/main-scene.blend — procedural ceiling track light rail with four spotlights.

Run from Blender's Scripting workspace with `blend/main-scene.blend` open: open
this file in the Text Editor and press "Run Script". It is idempotent — every
object it creates is deleted by name first, so re-running replaces the rig
instead of stacking a second one on top of it.

WHERE THE NUMBERS CAME FROM
---------------------------
The brief asks for the rail "centred horizontally along the storefront interior
ceiling / upper window header beam" but gives no height, so the ceiling was
measured out of this .blend rather than guessed:

  * Downward ray casts from z = 5.10 across the whole target span
    (x -0.80 … 0.80, y -1.90 … -1.20) hit `Shop_Structure` at z = 3.8775 every
    single time, and upward casts from z = 3.40 hit the same plane. The interior
    ceiling is flat at **z = 3.8775** and everything under it is empty air, so
    the rail surface-mounts there and the heads hang into clear space.

  * `Interior_LED_Strips` sits at z 4.035 … 4.065 — *above* that ceiling, i.e.
    buried in the parapet and invisible from the shop side. This rig is
    therefore the only interior ceiling fixture that actually reads.

  * The rail sits at y = -1.60, over the middle of the display shelves
    (`Slab_*` span y -1.79 … -1.49, tiers at z 1.400 / 2.350 / 3.300) and
    0.40 m behind the shopfront glass at y = -2.005. At the aiming angles below
    the lowest point of any head is z ≈ 3.70 and the furthest forward reach is
    y ≈ -1.69, so nothing touches the glass, the shelves or the window frame.

  * Visibility: `Facade_Glass` tops out at z = 3.80 and `Facade_Storefront`'s
    head trim covers z 3.80 … 3.85. The rail body (z 3.8465 … 3.8715) therefore
    tucks up behind the trim the way real surface-mount track does, while the
    heads — whose tops sit at z ≈ 3.7755 — hang below the trim line and read
    through the window. That is the intended look, not an oversight; raise
    `ceiling_z` in CONFIG if you want more of the rail on show.

COLOUR SPACE
------------
Blender stores `default_value` on shader sockets in **linear** light, while the
colour picker (and the brief) speaks sRGB hex. Writing 0x12/255 straight into
the socket would produce a washed-out grey roughly #3A3D42. Every hex in CONFIG
is therefore run through `srgb_to_linear`, which is what makes `#121417` show up
as `#121417` in the picker. The existing materials in this file are authored the
same way — `Mat_WarmInterior` reads (1.0, 0.5711, 0.1714) linear, which is the
warm amber #FFC773.

HOW THE FIXTURES ARE ARTICULATED, AND WHY IT IS SPLIT IN TWO
------------------------------------------------------------
A real track head swivels in two places: the adapter twists about the vertical
axis in the track slot (yaw), and the can tilts on a pin between the yoke arms
(tilt). Modelling both on one object would swing the adapter out of the rail as
soon as you tilt it 40 deg, so each fixture is two objects:

  Track_Spotlight_0N_Mount   adapter, stem and yoke fork. Its yaw is baked into
                             the mesh at build time, so the object transform
                             stays identity and it is safe to `transform_apply`
                             even though it is a parent.
  Track_Spotlight_0N         knuckle, can, bezel, reflector cup and lens. Its
                             origin *is* the swivel pin, and its rotation_euler
                             is left live: X is the tilt, Z is the yaw. Scrub X
                             in the N-panel and the can pivots exactly like the
                             real fitting.

TILT CONVENTION
---------------
"35 deg to 50 deg downward tilt" is read as the architectural-lighting aiming
angle — degrees off nadir, the way accent lighting is always specified — not
degrees below horizontal. That is also the only reading the geometry supports:
the shelves are directly beneath the rail, and a beam 40 deg *below horizontal*
would fly over the display and hit the parapet. At 35–50 deg off nadir the beam
washes down the window display, which is what the fixture is for. The rest pose
therefore hangs straight down and rotation_euler.x = -radians(tilt) swings it
forward toward the glass.

THE ONE PLACE THIS DEPARTS FROM THE BRIEF
-----------------------------------------
Spec 5 asks both for origins at the swivel pivot "for easy rotational
adjustment" *and* for `transform_apply(rotation=True, scale=True)`. Those
cancel: applying rotation bakes the aim into the mesh and zeroes the euler, so
the adjustable pivot stops adjusting anything. Rotation and scale are applied to
everything that does not carry a live aim (rail, end caps, anchors, all four
mounts), and the four heads keep their rotation. Set
CONFIG["apply_head_rotation"] = True to bake them too — the heads are leaf
objects, so it is safe, it just costs you the handle.
"""

import contextlib
import math

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------

CONFIG = {
    # --- placement, measured from this .blend (see the header) ---------------
    "ceiling_z": 3.8775,      # Shop_Structure interior ceiling, confirmed by raycast
    "rail_y": -1.60,          # over the shelves, 0.405 m behind the glass
    "rail_center_x": 0.0,     # centred on the shopfront
    "mount_gap": 0.006,       # anchor plate thickness; rail hangs this far off the ceiling

    # --- rail (brief: 1.6 x 0.04 x 0.025) ------------------------------------
    "rail_length": 1.600,
    "rail_width": 0.040,
    "rail_height": 0.025,
    "anchor_x": (-0.62, 0.62),
    "end_cap_thickness": 0.010,

    # --- spotlight heads (brief: r 0.035, len 0.08, recess 0.015) ------------
    "head_count": 4,
    "head_spacing": 0.35,
    "can_radius": 0.035,
    "can_length": 0.080,
    "lens_recess": 0.015,
    "pivot_drop": 0.055,      # swivel pin, below the rail underside

    # Aiming. Tilt is degrees off nadir (see the header), one per head, all
    # inside the 35-50 band the brief allows. Yaw is the literal sequence from
    # the brief: +Z turns a head toward +X, so heads 1 and 4 splay outward over
    # the full 6 m shelf run while 2 and 3 converge. Flipping the signs aims all
    # four inward, which piles every beam onto the same 1.6 m of glass.
    "tilt_deg": (44.0, 36.0, 39.0, 47.0),
    "yaw_deg": (-10.0, 5.0, -5.0, 10.0),

    # --- materials (brief) ---------------------------------------------------
    "body_hex": "121417",
    "body_metallic": 0.85,
    "body_roughness": 0.35,
    "reflector_hex": "20242A",
    "reflector_metallic": 0.95,
    "reflector_roughness": 0.15,
    "lens_hex": "FFF4E0",
    "lens_emission_hex": "FFE8B8",
    "lens_emission_strength": 4.0,

    # --- build -------------------------------------------------------------
    "segments": 24,           # facets around every cylinder
    "smooth_angle_deg": 30.0, # smooths the 15 deg barrel facets, keeps 45 deg chamfers sharp
    "collection": "Storefront_Architecture",
    "apply_transforms": True,
    "apply_head_rotation": False,   # see the header
}

ROOT_NAME = "Rig_Storefront_TrackLights"
RAIL_NAME = "Track_Light_Rail"
ANCHOR_FMT = "Track_Rail_Anchor_{:02d}"
HEAD_FMT = "Track_Spotlight_{:02d}"
MOUNT_FMT = "Track_Spotlight_{:02d}_Mount"

#: Everything this script owns. Deleted on entry so re-running is idempotent.
OWNED_PREFIXES = (RAIL_NAME, "Track_Rail_Anchor_", "Track_Spotlight_", ROOT_NAME)

MAT_BODY = "Mat_TrackLight_Black"
MAT_REFLECTOR = "Mat_TrackLight_Reflector"
MAT_LENS = "Mat_TrackLight_Lens"

#: Every mesh carries the same three slots in the same order, so a material
#: index means the same thing everywhere. Unused slots cost nothing — the glTF
#: exporter only emits a primitive for indices a face actually references.
SLOTS = (MAT_BODY, MAT_REFLECTOR, MAT_LENS)
BODY, REFLECTOR, LENS = 0, 1, 2

report: list[str] = []


def log(line: str) -> None:
    report.append(line)
    print(line)


# ----------------------------------------------------------------------------
# Colour
# ----------------------------------------------------------------------------

def srgb_to_linear(channel: float) -> float:
    """The IEC 61966-2-1 transfer function Blender applies to picker colours."""
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def hex_rgba(value: str, alpha: float = 1.0) -> tuple:
    value = value.lstrip("#")
    return tuple(
        srgb_to_linear(int(value[i:i + 2], 16) / 255.0) for i in (0, 2, 4)
    ) + (alpha,)


def socket(bsdf, *names):
    """Blender 4.0 renamed the Principled emission sockets; try both spellings."""
    for name in names:
        found = bsdf.inputs.get(name)
        if found is not None:
            return found
    return None


def ensure_material(name, base_hex, metallic, roughness,
                    emission_hex=None, emission_strength=0.0):
    """Creates or *rewrites* the material, so a re-run updates values in place
    rather than leaving a `Mat_TrackLight_Black.001` behind."""
    mat = bpy.data.materials.get(name)
    created = mat is None
    if created:
        mat = bpy.data.materials.new(name)
    # `use_nodes` is deprecated and goes away in Blender 6.0, where every
    # material has a node tree already. Only reach for it if there isn't one.
    if getattr(mat, "node_tree", None) is None:
        mat.use_nodes = True

    tree = mat.node_tree
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        tree.nodes.clear()
        out = tree.nodes.new("ShaderNodeOutputMaterial")
        bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (-300, 0)
        tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    base = hex_rgba(base_hex)
    bsdf.inputs["Base Color"].default_value = base
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness

    emit_colour = socket(bsdf, "Emission Color", "Emission")
    emit_strength = socket(bsdf, "Emission Strength")
    if emit_colour is not None:
        emit_colour.default_value = hex_rgba(emission_hex or "FFFFFF")
    if emit_strength is not None:
        emit_strength.default_value = emission_strength

    mat.diffuse_color = base          # solid-shading swatch in the viewport
    log(f"  {'+' if created else '=':1s} {name}: #{base_hex.lstrip('#').upper()} "
        f"metallic {metallic} roughness {roughness}"
        + (f" emission #{emission_hex} @ {emission_strength}" if emission_strength else ""))
    return mat


def run_materials() -> dict:
    log("\n[2] Materials")
    return {
        MAT_BODY: ensure_material(
            MAT_BODY, CONFIG["body_hex"],
            CONFIG["body_metallic"], CONFIG["body_roughness"]),
        MAT_REFLECTOR: ensure_material(
            MAT_REFLECTOR, CONFIG["reflector_hex"],
            CONFIG["reflector_metallic"], CONFIG["reflector_roughness"]),
        MAT_LENS: ensure_material(
            MAT_LENS, CONFIG["lens_hex"], 0.0, 0.25,
            CONFIG["lens_emission_hex"], CONFIG["lens_emission_strength"]),
    }


# ----------------------------------------------------------------------------
# bmesh primitives
# ----------------------------------------------------------------------------

#: Blender 3.0 renamed create_cone's diameter1/2 to radius1/2. Probe once.
_CONE_RADIUS_API = True
try:
    _probe = bmesh.new()
    bmesh.ops.create_cone(_probe, cap_ends=True, cap_tris=False, segments=3,
                          radius1=1.0, radius2=1.0, depth=1.0)
    _probe.free()
except TypeError:
    _CONE_RADIUS_API = False


@contextlib.contextmanager
def slot(bm, index):
    """Assigns `index` to every face created inside the block."""
    before = set(bm.faces)
    yield
    for face in bm.faces:
        if face not in before:
            face.material_index = index


def box(bm, size, center=(0.0, 0.0, 0.0), rot=None):
    bmesh.ops.create_cube(
        bm, size=1.0,
        matrix=Matrix.LocRotScale(Vector(center), rot, Vector(size)))


def cylinder(bm, radius, depth, center=(0.0, 0.0, 0.0), rot=None,
             segments=None, cap=True, radius_top=None):
    segments = segments or CONFIG["segments"]
    kwargs = {
        "cap_ends": cap,
        "cap_tris": False,
        "segments": segments,
        "depth": depth,
        "matrix": Matrix.LocRotScale(Vector(center), rot, Vector((1.0, 1.0, 1.0))),
    }
    top = radius if radius_top is None else radius_top
    if _CONE_RADIUS_API:
        kwargs.update(radius1=radius, radius2=top)
    else:
        kwargs.update(diameter1=radius * 2.0, diameter2=top * 2.0)
    bmesh.ops.create_cone(bm, **kwargs)


def revolve(bm, profile, pairs):
    """Lathes (radius, z) profile points about +Z, one edge per pair.

    Each pair is spun independently so the caller can give each band of the
    surface its own material. Every spin starts from the same y = 0 profile
    plane and takes the same number of steps, so the shared rings land on
    identical coordinates and `clean()` welds them into one continuous shell.
    """
    steps = CONFIG["segments"]
    for i, j in pairs:
        r0, z0 = profile[i]
        r1, z1 = profile[j]
        v0 = bm.verts.new((r0, 0.0, z0))
        v1 = bm.verts.new((r1, 0.0, z1))
        edge = bm.edges.new((v0, v1))
        bmesh.ops.spin(bm, geom=[v0, v1, edge], cent=(0.0, 0.0, 0.0),
                       axis=(0.0, 0.0, 1.0), dvec=(0.0, 0.0, 0.0),
                       angle=2.0 * math.pi, steps=steps,
                       use_merge=True, use_duplicate=False)


def extrude(bm, profile_yz, length):
    """Sweeps a closed (y, z) outline along X into a capped solid.

    Explicit caps and quads rather than `extrude_face_region`, so the result is
    manifold by construction and does not depend on which way that operator
    leaves the original face.
    """
    x0, x1 = -length / 2.0, length / 2.0
    near = [bm.verts.new((x0, y, z)) for y, z in profile_yz]
    far = [bm.verts.new((x1, y, z)) for y, z in profile_yz]
    bm.faces.new(near)
    bm.faces.new(far[::-1])
    for i in range(len(profile_yz)):
        j = (i + 1) % len(profile_yz)
        bm.faces.new((near[i], near[j], far[j], far[i]))


def clean(bm):
    """Welds the seams between separately-built parts, collapses the degenerate
    quads a lathe leaves at r = 0 poles, and fixes winding. Same three ops
    `optimize_storefront.py` uses for mesh hygiene."""
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-5, edges=bm.edges)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)


def finish(bm, name, location, materials, rotation=None, yaw_bake=0.0):
    """Bakes a bmesh into a named object at `location`."""
    if yaw_bake:
        bmesh.ops.rotate(bm, cent=(0.0, 0.0, 0.0), verts=bm.verts,
                         matrix=Matrix.Rotation(yaw_bake, 3, "Z"))
    clean(bm)

    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    obj.location = Vector(location)
    if rotation is not None:
        obj.rotation_euler = rotation
    for slot_name in SLOTS:
        mesh.materials.append(materials[slot_name])
    target_collection().objects.link(obj)
    return obj


def target_collection():
    name = CONFIG["collection"]
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
    scene = bpy.context.scene.collection
    if coll is not scene and not any(c is coll for c in scene.children_recursive):
        scene.children.link(coll)
    return coll


# ----------------------------------------------------------------------------
# 1. Cleanup
# ----------------------------------------------------------------------------

def run_cleanup() -> None:
    log("\n[1] Cleanup of any previous run")
    doomed = [o for o in bpy.data.objects if o.name.startswith(OWNED_PREFIXES)]
    for obj in doomed:
        log(f"  - removed {obj.name}")
        bpy.data.objects.remove(obj, do_unlink=True)

    orphans = [m for m in bpy.data.meshes
               if m.users == 0 and m.name.startswith(OWNED_PREFIXES)]
    for mesh in orphans:
        bpy.data.meshes.remove(mesh)

    if not doomed:
        log("  nothing from a previous run, building fresh")
    else:
        log(f"  {len(doomed)} objects and {len(orphans)} orphan meshes cleared")


# ----------------------------------------------------------------------------
# 3. Geometry
# ----------------------------------------------------------------------------

def rail_planes() -> dict:
    """Every z the rig is measured from, derived once."""
    top = CONFIG["ceiling_z"] - CONFIG["mount_gap"]
    return {
        "ceiling": CONFIG["ceiling_z"],
        "rail_top": top,
        "rail_bottom": top - CONFIG["rail_height"],
        "rail_center": top - CONFIG["rail_height"] / 2.0,
    }


def head_x_positions() -> list:
    n = CONFIG["head_count"]
    span = CONFIG["head_spacing"] * (n - 1)
    return [CONFIG["rail_center_x"] - span / 2.0 + i * CONFIG["head_spacing"]
            for i in range(n)]


def rail_profile():
    """The C-channel cross-section in (y, z), traced once around the solid.

    Extruding one closed outline — rather than stacking a web box on two wall
    boxes on two lip boxes — is both how the real aluminium section is made and
    the only way to get a manifold rail. Abutting boxes share corner vertices;
    `clean()` welds them, and what is left is a non-manifold edge with two
    coplanar faces fighting for the same pixels.
    """
    half_w = CONFIG["rail_width"] / 2.0
    top = CONFIG["rail_height"] / 2.0
    bottom = -top
    wall_t, web_h = 0.007, 0.008
    lip_t, lip_h = 0.004, 0.004

    y_wall = half_w - wall_t                # wall inner face
    y_lip = y_wall - lip_t                  # lip tip, i.e. the slot mouth
    z_web = top - web_h                     # web underside, the slot ceiling
    z_lip = bottom + lip_h                  # lip top

    return [
        (-half_w, bottom),                  # outer bottom corner
        (-y_lip, bottom), (-y_lip, z_lip),  # in along the bottom, up the lip tip
        (-y_wall, z_lip), (-y_wall, z_web), # back over the lip, up the wall
        (y_wall, z_web),                    # across the slot ceiling
        (y_wall, z_lip), (y_lip, z_lip),    # down the far wall, over its lip
        (y_lip, bottom), (half_w, bottom),  # down the lip tip, out along the bottom
        (half_w, top), (-half_w, top),      # up the flank, across the ceiling face
    ]


def build_rail(materials):
    """The extruded C-channel, its two live conductors and two end caps."""
    length = CONFIG["rail_length"]
    half_w = CONFIG["rail_width"] / 2.0
    height = CONFIG["rail_height"]
    z_web = height / 2.0 - 0.008           # web underside

    bm = bmesh.new()
    with slot(bm, BODY):
        extrude(bm, rail_profile(), length)
        # End caps, a shade proud of the profile and sunk 2 mm into it. Butted
        # flush, a cap's inner face would land exactly on the channel's end face
        # and z-fight it; overlapping buries the joint instead.
        cap_t = CONFIG["end_cap_thickness"]
        cap_sink = 0.002
        for sign in (-1, 1):
            box(bm, (cap_t, half_w * 2 + 0.004, height + 0.004),
                (sign * (length / 2.0 + cap_t / 2.0 - cap_sink), 0.0, 0.0))

    with slot(bm, REFLECTOR):
        # The two live conductors, sunk 1 mm into the web and 1 mm into the
        # walls so no face of theirs is coplanar with a face of the channel.
        for sign in (-1, 1):
            box(bm, (length - 0.02, 0.005, 0.003),
                (0.0, sign * 0.0115, z_web - 0.0005))

    planes = rail_planes()
    obj = finish(bm, RAIL_NAME,
                 (CONFIG["rail_center_x"], CONFIG["rail_y"], planes["rail_center"]),
                 materials)
    log(f"  + {RAIL_NAME}: {length:.3f} x {half_w * 2:.3f} x {height:.3f} m "
        f"C-channel, top at z {planes['rail_top']:.4f}")
    return obj


def build_anchor(index, x, materials):
    """Ceiling canopy plate plus a saddle that hugs the rail sides."""
    gap = CONFIG["mount_gap"]
    half_w = CONFIG["rail_width"] / 2.0

    bury = 0.001

    bm = bmesh.new()
    with slot(bm, BODY):
        # Canopy plate: ceiling down to the rail top, then 1 mm into the rail so
        # the two faces do not end up coplanar.
        box(bm, (0.062, 0.050, gap + bury), (0.0, 0.0, -(gap + bury) / 2.0))
        # Saddle arms gripping the rail's outer flanks, sunk 1.5 mm in and
        # starting 1 mm up inside the canopy for the same reason.
        for sign in (-1, 1):
            box(bm, (0.012, 0.005, 0.017),
                (0.0, sign * (half_w + 0.001), -(gap + 0.0075)))

    name = ANCHOR_FMT.format(index)
    obj = finish(bm, name, (x, CONFIG["rail_y"], CONFIG["ceiling_z"]), materials)
    log(f"  + {name}: canopy at x {x:+.3f}, bridging the {gap * 1000:.0f} mm ceiling gap")
    return obj


def build_mount(index, x, yaw_deg, materials):
    """Track adapter, stem and yoke fork. Origin sits at the slot mouth; the yaw
    is baked into the mesh so the object transform stays identity."""
    drop = CONFIG["pivot_drop"]

    bm = bmesh.new()
    with slot(bm, BODY):
        # 0.024 / 0.016 wide, not the 0.026 / 0.018 the slot and its mouth
        # actually measure: 1 mm of air on each side keeps the adapter from
        # sitting exactly coplanar with the rail it slides into.
        box(bm, (0.030, 0.024, 0.0085), (0.0, 0.0, 0.00925))   # twist-lock head, in the slot
        box(bm, (0.030, 0.016, 0.005), (0.0, 0.0, 0.0025))     # neck through the slot mouth
        box(bm, (0.046, 0.040, 0.018), (0.0, 0.0, -0.009))     # adapter body under the rail
        cylinder(bm, 0.010, 0.012, (0.0, 0.0, -0.024))         # stem
        box(bm, (0.056, 0.022, 0.008), (0.0, 0.0, -0.034))     # yoke crossbar
        for sign in (-1, 1):                                   # fork arms, straddling the pin
            box(bm, (0.006, 0.020, 0.026), (sign * 0.025, 0.0, -0.049))
            cylinder(bm, 0.010, 0.006, (sign * 0.025, 0.0, -drop),
                     rot=Euler((0.0, math.radians(90.0), 0.0)), segments=16)

    with slot(bm, REFLECTOR):
        for sign in (-1, 1):                                   # pivot bolt heads
            cylinder(bm, 0.0045, 0.005, (sign * 0.0285, 0.0, -drop),
                     rot=Euler((0.0, math.radians(90.0), 0.0)), segments=12)

    name = MOUNT_FMT.format(index)
    obj = finish(bm, name,
                 (x, CONFIG["rail_y"], rail_planes()["rail_bottom"]),
                 materials, yaw_bake=math.radians(yaw_deg))
    return obj


def build_head(index, x, tilt_deg, yaw_deg, materials):
    """Knuckle, can, bezel, reflector cup and COB lens. The object origin is the
    swivel pin, so rotation_euler.x is literally the tilt handle."""
    r_can = CONFIG["can_radius"]
    length = CONFIG["can_length"]
    recess = CONFIG["lens_recess"]

    z_top = -0.016                 # can top, clear of the knuckle barrel
    z_bot = z_top - length         # front rim
    z_lens = z_bot + recess        # lens face, inset by the brief's 0.015 m

    # (radius, z) — top pole, out over the chamfer, down the barrel, over the
    # bottom chamfer, across the bezel face, then up into the reflector cup.
    profile = [
        (0.0000, z_top),            # 0 top pole
        (0.0295, z_top),            # 1
        (r_can, z_top - 0.0055),    # 2 top chamfer   -> beveled edge
        (r_can, z_bot + 0.0055),    # 3 barrel
        (0.0315, z_bot),            # 4 bottom chamfer -> beveled edge
        (0.0295, z_bot),            # 5 bezel face
        (0.0275, z_bot + 0.0035),   # 6 bezel inner lip
        (0.0215, z_lens),           # 7 reflector cup, flaring out to the aperture
        (0.0000, z_lens),           # 8 lens pole
    ]

    bm = bmesh.new()
    with slot(bm, BODY):
        revolve(bm, profile, [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6)])
        cylinder(bm, 0.013, 0.042, (0.0, 0.0, 0.0),          # knuckle barrel, on the pin
                 rot=Euler((0.0, math.radians(90.0), 0.0)))
        box(bm, (0.022, 0.022, 0.020), (0.0, 0.0, -0.008))   # neck, barrel to can
    with slot(bm, REFLECTOR):
        revolve(bm, profile, [(6, 7)])
    with slot(bm, LENS):
        revolve(bm, profile, [(7, 8)])

    planes = rail_planes()
    name = HEAD_FMT.format(index)
    # Default XYZ euler composes as Rz @ Ry @ Rx, i.e. yaw about the vertical
    # first and tilt about the yawed pin second — the real fitting's kinematics.
    obj = finish(bm, name,
                 (x, CONFIG["rail_y"], planes["rail_bottom"] - CONFIG["pivot_drop"]),
                 materials,
                 rotation=Euler((math.radians(-tilt_deg), 0.0, math.radians(yaw_deg))))
    obj["aim_tilt_deg"] = tilt_deg
    obj["aim_yaw_deg"] = yaw_deg
    log(f"  + {name}: x {x:+.3f}, tilt {tilt_deg:.0f} deg off nadir, yaw {yaw_deg:+.0f} deg")
    return obj


def run_geometry(materials) -> dict:
    log("\n[3] Geometry")
    built = {"rail": build_rail(materials), "anchors": [], "mounts": [], "heads": []}

    for i, x in enumerate(CONFIG["anchor_x"], start=1):
        built["anchors"].append(build_anchor(i, x, materials))

    for i, x in enumerate(head_x_positions(), start=1):
        tilt = CONFIG["tilt_deg"][(i - 1) % len(CONFIG["tilt_deg"])]
        yaw = CONFIG["yaw_deg"][(i - 1) % len(CONFIG["yaw_deg"])]
        built["mounts"].append(build_mount(i, x, yaw, materials))
        built["heads"].append(build_head(i, x, tilt, yaw, materials))

    return built


# ----------------------------------------------------------------------------
# 4. Hierarchy
# ----------------------------------------------------------------------------

def parent_to(child, parent) -> None:
    """Keeps the child's world transform, the same thing Ctrl+P does."""
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()


def run_hierarchy(built):
    log("\n[4] Hierarchy")
    planes = rail_planes()

    root = bpy.data.objects.new(ROOT_NAME, None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.12
    root.location = (CONFIG["rail_center_x"], CONFIG["rail_y"], planes["ceiling"])
    target_collection().objects.link(root)
    bpy.context.view_layer.update()

    for obj in [built["rail"], *built["anchors"], *built["mounts"]]:
        parent_to(obj, root)
    for mount, head in zip(built["mounts"], built["heads"]):
        parent_to(head, mount)

    bpy.context.view_layer.update()
    log(f"  {ROOT_NAME} at ({root.location.x:.3f}, {root.location.y:.3f}, "
        f"{root.location.z:.4f}) parents {len(root.children)} objects")
    log(f"  each head parented to its own mount, so yaw and tilt stay independent")
    return root


# ----------------------------------------------------------------------------
# 5. Shading and transforms
# ----------------------------------------------------------------------------

def select(objects) -> bool:
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    objects = [o for o in objects if o.name in bpy.context.view_layer.objects]
    if not objects:
        return False
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    return True


def shade_smooth_by_angle(objects) -> None:
    """Blender 4.1 dropped mesh auto-smooth for an operator that adds a Smooth
    by Angle node group, so both spellings are tried — same fallback ladder as
    optimize_storefront.py."""
    angle = math.radians(CONFIG["smooth_angle_deg"])
    if not select(objects):
        return
    for operator, kwargs in (
        (getattr(bpy.ops.object, "shade_smooth_by_angle", None), {"angle": angle}),
        (getattr(bpy.ops.object, "shade_auto_smooth", None), {"angle": angle}),
        (bpy.ops.object.shade_smooth, {}),
    ):
        if operator is None:
            continue
        try:
            operator(**kwargs)
            log(f"  smooth shading on {len(objects)} objects at "
                f"{CONFIG['smooth_angle_deg']:.0f} deg")
            return
        except (RuntimeError, TypeError):
            continue
    log("  ! could not apply smooth shading in this Blender build")


def run_transforms(built) -> None:
    log("\n[5] Shading and transforms")
    meshes = [built["rail"], *built["anchors"], *built["mounts"], *built["heads"]]
    shade_smooth_by_angle(meshes)

    if not CONFIG["apply_transforms"]:
        log("  transform apply disabled in CONFIG")
        return

    static = [built["rail"], *built["anchors"], *built["mounts"]]
    if select(static):
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        log(f"  rotation and scale applied on {len(static)} objects "
            f"(rail, end caps, anchors, mounts)")

    if CONFIG["apply_head_rotation"]:
        if select(built["heads"]):
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
            log(f"  aim baked into {len(built['heads'])} heads — eulers now zero")
    else:
        if select(built["heads"]):
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        log("  heads: scale applied, rotation left live so the swivel stays adjustable")
        log("         (set CONFIG['apply_head_rotation'] = True to bake it)")


# ----------------------------------------------------------------------------
# 6. Verification
# ----------------------------------------------------------------------------

GLASS_Y = -2.005      # Facade_Glass front plane
TOP_SHELF_Z = 3.325   # Slab_*_Top surface


def run_verify(built) -> None:
    log("\n[6] Verification")
    bpy.context.view_layer.update()

    def world_bounds(obj):
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        return ([min(c[i] for c in corners) for i in range(3)],
                [max(c[i] for c in corners) for i in range(3)])

    lo, hi = world_bounds(built["rail"])
    log(f"  rail world bounds  x[{lo[0]:.3f},{hi[0]:.3f}] "
        f"y[{lo[1]:.3f},{hi[1]:.3f}] z[{lo[2]:.4f},{hi[2]:.4f}]")

    z_lens = -0.016 - CONFIG["can_length"] + CONFIG["lens_recess"]
    lowest, nearest = 1e9, 1e9
    for head in built["heads"]:
        blo, bhi = world_bounds(head)
        lowest = min(lowest, blo[2])
        nearest = min(nearest, blo[1])

        matrix = head.matrix_world
        origin = matrix @ Vector((0.0, 0.0, z_lens))
        beam = (matrix.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()

        note = "beam misses the window plane"
        if beam.y < -1e-6:
            t = (GLASS_Y - origin.y) / beam.y
            hit_z = origin.z + beam.z * t
            note = f"crosses the glass plane at z {hit_z:.3f}"
            if beam.z < -1e-6:
                t_shelf = (TOP_SHELF_Z - origin.z) / beam.z
                note += f", reaches shelf height at y {origin.y + beam.y * t_shelf:.3f}"
        log(f"  {head.name}: lens at ({origin.x:.3f}, {origin.y:.3f}, {origin.z:.3f}), {note}")

    log(f"  lowest point of any head z {lowest:.4f} "
        f"(top shelf is z {TOP_SHELF_Z:.3f}, {lowest - TOP_SHELF_Z:.3f} m of clearance)")
    log(f"  closest approach to the glass y {nearest:.3f} "
        f"(glass at y {GLASS_Y:.3f}, {nearest - GLASS_Y:.3f} m of clearance)")

    tris = 0
    for obj in [built["rail"], *built["anchors"], *built["mounts"], *built["heads"]]:
        obj.data.calc_loop_triangles()
        tris += len(obj.data.loop_triangles)
    log(f"  {len(built['heads'])} heads, {len(built['anchors'])} anchors, "
        f"1 rail — {tris} triangles total")


# ----------------------------------------------------------------------------

def main() -> None:
    log("=" * 74)
    log("Storefront ceiling track lighting")
    log("=" * 74)

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    run_cleanup()
    materials = run_materials()
    built = run_geometry(materials)
    run_hierarchy(built)
    run_transforms(built)
    run_verify(built)

    log("\nDone. The .blend is NOT saved — check it, then File > Save.")
    log("=" * 74)


if __name__ == "__main__":
    main()
