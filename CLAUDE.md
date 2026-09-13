# CLAUDE.md — Blender source for the Mehul Kalyani 3D portfolio

Authoring repository for `blend/main-scene.blend`, the storefront diorama that
**is** the portfolio site's interface. This repo owns geometry, materials,
lighting and the vending-machine interaction contract. It does not own runtime
behaviour — camera moves, audio, state and UI live in the web project.

## Golden rule

Measure the scene before you change it. Make the smallest change that satisfies
the request, re-run the validator, and verify the exported GLB — not just the
viewport. A material that looks right in Blender is not evidence that it
survives glTF export.

## Commands

| | |
|---|---|
| Open the scene | `blender blend/main-scene.blend` |
| Validate materials | `blender -b blend/main-scene.blend --python scripts/materials/audit_materials.py` |
| Export GLB | `blender -b blend/main-scene.blend --python scripts/export/export_glb.py` |
| Headless script run | `blender -b blend/main-scene.blend --python scripts/<cat>/<name>.py -- --out /tmp/out.blend` |
| Fetch binaries after clone | `git lfs install && git lfs pull` |

## Safe editing

- **Never overwrite `blend/main-scene.blend` from a headless script.** Scripts
  that mutate the scene take `--out` and write to a copy. Scripts run from the
  Text Editor deliberately do not save — inspect, then `File > Save` yourself.
- Do not "tidy" the scene for the repository's benefit. Collection membership,
  object names, transforms and the empty `Imported_Products` collection are the
  saved state; preserve them unless the task is to change them.
- Renaming an object is a breaking change. `vm_products`, `vm_product_node` and
  the web build's extract/strip steps all address nodes **by name**. Names that
  are load-bearing: `Vending_TechLocker`, `VM_Key_*`, `VM_NFC_Reader`,
  `VM_Display_Screen`, `Shop_Structure`, `Skateboard*`, `Hero_Drone_Imported`,
  `Hero_AppleVisionPro`, `*_Imported`, `Storefront_*`, `Track_Spotlight_*`.
- Before a structural edit, capture a fingerprint (object transforms, mesh
  counts, material names, custom props) and diff it afterwards, so you can show
  what changed rather than assert it.
- Keep every script idempotent: delete what you own by name, then rebuild.
  Re-running must replace, never stack a second copy.
- Prefer Blender's data API over repeated `bpy.ops`. Avoid mode switches,
  selection juggling and viewport operators — they make scripts order-dependent
  and non-reproducible in `--background`.
- Scripts must not depend on what was selected or which collection was active.

## Script execution

- Scripts live in `scripts/<category>/`. Categories are meaningful: `setup`,
  `materials`, `lighting`, `objects`, `animation`, `export`.
- Resolve paths through `scripts/setup/paths.py`. Never hard-code an absolute
  path, and never assume the current working directory.
- Copy the existing `load_paths()` bootstrap when a new script needs paths — it
  locates `paths.py` relative to the calling script, so it works both under
  `blender --python` and from Blender's Text Editor (which may not set
  `__file__`).
- Document *why* a number is what it is. The scripts here record measurements —
  ray-cast ceiling heights, real bounding boxes — precisely because earlier
  briefs were written against bounding boxes that lied. Preserve that.

## Asset paths

- Textures are **packed into the .blend and also present in `assets/textures/`**.
  Keep both true: the packed copy makes the file open standalone, the file makes
  it reviewable.
- Every image datablock must use a `//`-relative filepath
  (`//../assets/textures/<name>`). An absolute path is a portability bug — it
  points at one machine and breaks for everyone else.
- Note that `//` is Blender's relative prefix. `os.path.isabs("//x")` returns
  `True` on POSIX, so test `startswith("//")` first when validating paths.
- If you pack a new texture, also write the file into `assets/textures/` and set
  the relative path. If you unpack one, do not leave an absolute path behind.
- Source models belong in `assets/models/`; add a new one only when a script in
  this repo actually references it.

## glTF-safe materials

The exporter reads a Principled BSDF and the image textures feeding it. It has
no procedural node graph, so anything it cannot read is silently baked to a flat
value — the material still looks perfect in Blender and is wrong in the browser.

- Use Principled BSDF, UV-mapped Image Textures, standard PBR inputs, and
  glTF-compatible emission/transparency/transmission.
- Never use procedural texture nodes (Brick, Noise, Voronoi, Musgrave, Wave,
  Checker, Gradient) or Generated/Object texture coordinates on anything that
  must export. Bake to an image sampled by a real UV map instead.
- **Do not regress the PV material.** `Mat_PV_Cell` once used a procedural Brick
  Texture with Generated coordinates and exported as a solid colour. It now uses
  UV + `Tex_PVCell_BaseColor` / `Tex_PVCell_Normal`. Keep that approach.
- Do not downsample or lossily compress the vending products' textures. They are
  viewed close up; earlier low-resolution sources were a visible defect.

## Validation

Run before every export, and before every commit that touches materials,
textures or object names:

```bash
blender -b blend/main-scene.blend --python scripts/materials/audit_materials.py
```

It is read-only and exits non-zero on failure. It flags procedural nodes,
non-UV texture coordinates, missing UV layers, materials with no Principled
BSDF, absolute image paths, and images that are neither packed nor on disk.

For a scene change, also confirm: the .blend opens with no missing files;
object and action names the web build relies on still exist; the custom
properties on `Vending_TechLocker` still parse; and the exported GLB loads in a
glTF viewer.

Never claim something was visually verified unless it actually was.

## Export workflow

`scripts/export/export_glb.py` is the **only** place export settings live. Do
not export from the File menu — the settings that matter are not defaults, and
a UI export silently drops them.

- `export_extras=True` carries `vm_products` and every other custom property.
  Without it the vending machine ships no catalogue and the site falls back to a
  hard-coded one.
- `export_yup=True` bridges Blender Z-up to glTF/three.js Y-up. The scripts
  document the mapping as `three(x, y, z) -> blender(x, -z, y)`.
- `export_animations=True`, and delivery actions must be **bound to objects** —
  an action kept alive only by a fake user is not exported.
- Cameras and lights are excluded; the web runtime owns both.
- Output goes to `exports/`, which is git-ignored. The GLB is a build artifact,
  not a source file. Do not commit it.
- Run `import_products.py` first if `Imported_Products` is empty, or the GLB
  will advertise products that are not in it. `export_glb.py` warns about this.

## Git

- `git lfs install` once per machine; binaries are tracked via `.gitattributes`
  (`.blend`, `.glb` and other 3D/high-bit-depth formats). Small 8-bit PNG
  textures are intentionally kept in git proper.
- Never commit: `*.blend1` and other rolling saves, `backups/`, `__pycache__/`,
  caches, renders, or anything in `exports/`.
- Blender rewrites the whole .blend on every save, so each commit that touches
  it costs a full copy in LFS. Commit scene changes deliberately, not as a
  side effect of having opened the file.
- Check `git status` before staging; `.DS_Store` and editor directories are
  ignored but worth confirming.

## Reporting

After a task, report briefly: **Implemented** (what changed and why) ·
**Files changed** (real paths) · **Verification** (commands run and their
results) · **Notes** (assumptions, limitations, anything excluded).
