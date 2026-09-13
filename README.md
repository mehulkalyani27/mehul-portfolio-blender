# mehul-portfolio-blender

Blender source for the **Mehul Kalyani 3D portfolio** — a storefront diorama
that is the website's interface, not a decorative background. Geometry,
materials, lighting and the vending-machine interaction contract are authored
here; the web runtime consumes a GLB exported from this scene.

The authoring file is **`blend/main-scene.blend`** (Blender 5.2 LTS, EEVEE,
metric, 24 fps, frames 1–250).

---

## Layout

```
blender-project/
├── blend/
│   └── main-scene.blend          the scene — all textures packed
├── scripts/
│   ├── setup/
│   │   ├── paths.py              repo-relative path resolver, imported by the rest
│   │   └── optimize_storefront.py  geometry hygiene, edge treatment, transforms
│   ├── materials/
│   │   └── audit_materials.py    read-only glTF-safety validator
│   ├── lighting/
│   │   └── build_track_lights.py procedural ceiling track rail + 4 spotlights
│   ├── objects/
│   │   ├── build_skateboard.py   the board the site navigates with
│   │   ├── import_products.py    re-imports the 14 products/props at authored scale
│   │   └── reposition_contact_bay.py  west-wall clearance for the Contact phone
│   ├── animation/
│   │   └── rebuild_vending.py    restores the vending product + delivery-clip system
│   └── export/
│       └── export_glb.py         the single source of truth for export settings
├── assets/
│   ├── textures/                 the scene's three textures, also packed in the .blend
│   ├── models/                   14 source GLBs consumed by import_products.py
│   └── references/
│       └── product_placements.json  recovered world-space boxes per product
├── exports/                      build output (git-ignored)
├── CLAUDE.md                     working rules for this repository
├── README.md
├── .gitignore
└── .gitattributes                Git LFS tracking
```

---

## Getting started

```bash
git clone https://github.com/mehulkalyani27/mehul-portfolio-blender.git
cd mehul-portfolio-blender

# One-off per machine, then fetch the binary assets.
git lfs install
git lfs pull
```

Open `blend/main-scene.blend` in **Blender 5.2 LTS or newer**. It opens with no
missing files: every texture is packed into the .blend, and the scene links no
external libraries, sounds or fonts.

Verify a clone is complete:

```bash
blender --background blend/main-scene.blend \
        --python scripts/materials/audit_materials.py
```

A healthy checkout prints `PASS — every assigned material is glTF-safe.`

---

## What the scene contains

| | |
|---|---|
| Objects | 227 (141 meshes, 20 lights, 0 cameras) |
| Materials | 108, of which 94 are assigned to meshes |
| Actions | 30, including six `VM_Product_Deliver_*` delivery clips |
| Collections | 12 — `Storefront_Architecture`, `StreetFixtures`, `Vending_Static_Inventory`, `Mehul_Diorama`, `Imported_Products`, … |

There is **no camera**: camera work and lighting response belong to the web
runtime, which builds its own. Blender's 20 lights drive material appearance
and baked-in look, and are not exported.

### The vending-machine contract

`Vending_TechLocker` carries the interaction contract as custom properties —
`vm_products`, `vm_keys`, `vm_states`, `vm_initial_state`, `vm_nfc` — and each
keypad object carries `vm_role`, `vm_slot`, `vm_product_node`, `vm_price` and
`vm_clip`. The website reads these **out of the GLB**, so they only work when
the export sets `export_extras=True`. That is exactly why
`scripts/export/export_glb.py` exists rather than exporting from the UI.

`vm_products` names six product nodes — `Hero_Drone_Imported`,
`AirPods_Pro_Imported`, `Insta360_Imported`, `RayBan_Imported`,
`PowerBank_Imported`, `Hero_AppleVisionPro`.

> **Note on the current scene state.** The `Imported_Products` collection is
> empty in the committed .blend, so those six nodes (and the eight shelf props)
> are not presently in the scene — `vm_products` points at names that must be
> restored. This is the state the file was last saved in and it has been
> preserved exactly. Run `scripts/objects/import_products.py` (or
> `scripts/animation/rebuild_vending.py`, which calls it) to bring them back
> from `assets/models/` before exporting a GLB the site can use.
> `export_glb.py` warns when it detects this.

---

## Script workflow

Every script is **idempotent**: each deletes the objects it owns by name before
rebuilding, so re-running replaces its output instead of stacking a duplicate.

Two ways to run them:

**From the UI** — open `blend/main-scene.blend`, go to the *Scripting*
workspace, open the script in the Text Editor, press **Run Script**. The
build scripts do *not* save the file; inspect the result, then `File > Save`.

**Headless** — for the scripts that accept `--out`, which write to a copy and
never touch the source:

```bash
blender --background blend/main-scene.blend \
        --python scripts/animation/rebuild_vending.py -- --out /tmp/out.blend
```

### Typical order

| Step | Script | Purpose |
|---|---|---|
| 1 | `scripts/objects/import_products.py` | Bring the 14 GLBs in at authored scale and placement |
| 2 | `scripts/animation/rebuild_vending.py` | Re-bind delivery actions, retime clips, restore VM properties |
| 3 | `scripts/lighting/build_track_lights.py` | Rebuild the interior track rail |
| 4 | `scripts/objects/build_skateboard.py` | Rebuild the navigation board |
| 5 | `scripts/setup/optimize_storefront.py` | Merge doubles, drop degenerate faces, tidy transforms |
| 6 | `scripts/materials/audit_materials.py` | Confirm every material still exports cleanly |
| 7 | `scripts/export/export_glb.py` | Write `exports/main-scene.glb` |

Steps 3–5 are only needed when you are changing what they own.

### Placement is computed, not hard-coded

The GLBs in `assets/models/` carry none of the scene's placement — they arrive
at whatever scale their authors exported at, and they disagree wildly
(`perfume.glb` is ~1113 units tall, `hand_watch.glb` ~0.12).
`assets/references/product_placements.json` holds the world-space bounding box
each product occupied in the scene, recovered headlessly from a pre-removal
revision. `import_products.py` rotates each import to the authored orientation,
scales it to match the recorded box, and translates the box centres together.

The node names it produces — `Hero_Drone_Imported`, `Storefront_Lamp`, … — are
a contract with the web build, which extracts and strips subtrees by name.
**Renaming them silently breaks the site.**

---

## Exporting

```bash
blender --background blend/main-scene.blend \
        --python scripts/export/export_glb.py
# -> exports/main-scene.glb
```

`exports/` is git-ignored. The GLB is a build artifact of this .blend; keeping
it out of the repository means there is one thing to keep current, not two.

All export settings and the reasoning behind each live in the header of
`scripts/export/export_glb.py`. The load-bearing ones are `export_extras=True`
(carries the vending contract), `export_yup=True` (Blender Z-up → glTF Y-up)
and `export_animations=True` (the delivery clips).

The downstream web project consumes the exported GLB and performs its own
splitting, stripping and compression; none of that happens here.

---

## Assets

`assets/models/` holds the 14 GLBs `import_products.py` names — six vending
products (drone, AirPods, Insta360, Ray-Ban, power bank, Vision Pro) and eight
window-display props (wall clock, perfume, watch, handbag, flower vase, Stanley
tumbler, toy robot, lamp). Nothing else from the wider working directory was
copied in; see **Dependencies deliberately excluded** below.

`assets/textures/` holds the scene's three textures — `led_dot_matrix.png`
(LED board) and `Tex_PVCell_BaseColor.png` / `Tex_PVCell_Normal.png` (solar
cells). They are **both packed in the .blend and present as files**. The .blend
therefore opens standalone, while the files remain reviewable and editable, and
each image datablock points at a `//`-relative path inside this repository
rather than an absolute path on one machine.

### Dependencies deliberately excluded

Four files sit alongside this scene in the wider working directory and were
**not** copied in, because nothing in this .blend or its scripts references
them — they are inputs to the separate web project's build:

| File | Consumed by |
|---|---|
| `car_lego.glb` | web build (`scripts/build-car.mjs`) |
| `wall_phone.glb` | web build (`scripts/build-phone.mjs`) |
| `security_drone.glb` | web build (`scripts/build-drone.mjs`) |
| `logo.png` | web UI |

Also excluded: the `backups/` directory of dated `.blend` snapshots (~2.5 GB,
several single files over 400 MB), `*.blend1` rolling saves, `__pycache__/`,
and previously exported GLBs. These are history and build output, not source.

---

## Licensing

The GLBs in `assets/models/` are third-party downloads. Only use assets this
project has permission to use, and retain attribution and licence information
where the source requires it. Downloadable is not the same as free.
