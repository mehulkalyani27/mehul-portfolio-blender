"""blend/main-scene.blend — check every material survives a glTF export.

    blender --background blend/main-scene.blend \
            --python scripts/materials/audit_materials.py

Read-only. It never edits the scene; it reports and sets an exit code, so it
can be run before an export or in CI.

WHY
---
A material that looks right in Blender's viewport is not the same thing as a
material that survives `export_scene.gltf`. glTF has no procedural node graph:
the exporter walks a Principled BSDF and the image textures feeding it, and
anything it cannot read is baked down to a flat value without warning. The
material still renders perfectly in Blender, so the regression is only visible
in the browser.

This scene has already been bitten by exactly that. The PV (solar cell)
material was authored with a procedural Brick Texture driven by Generated
texture coordinates. In Blender it read as a cell grid; through the exporter it
collapsed to a single solid colour. The fix was to bake it to an image texture
sampled by a real UV map — `Tex_PVCell_BaseColor` and `Tex_PVCell_Normal`, both
packed into the .blend. This script exists so that fix cannot be quietly undone.

WHAT IT FLAGS
-------------
1. Procedural texture nodes (Brick, Noise, Musgrave, Voronoi, Wave, Magic,
   Checker, Gradient, IES) anywhere in a material that reaches a surface.
2. Texture coordinate sources other than UV — Generated, Object, Camera,
   Reflection — feeding an image texture.
3. Image textures with no UV map to sample, or an object with no UV layer.
4. Materials with no Principled BSDF (glTF's only supported surface model).
5. Image textures whose source file is neither packed nor present on disk.
"""

import os
import sys

import bpy

PROCEDURAL = {
    "TEX_BRICK", "TEX_NOISE", "TEX_MUSGRAVE", "TEX_VORONOI", "TEX_WAVE",
    "TEX_MAGIC", "TEX_CHECKER", "TEX_GRADIENT", "TEX_IES", "TEX_POINTDENSITY",
}

#: Texture-coordinate outputs the glTF exporter cannot represent.
NON_UV_COORDS = {"Generated", "Object", "Camera", "Window", "Reflection", "Normal"}


def log(msg: str = "") -> None:
    print(f"[audit-materials] {msg}" if msg else "")


def materials_in_use():
    """Materials actually assigned to a mesh, in scene order."""
    seen = {}
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        for slot in obj.material_slots:
            if slot.material is not None:
                seen.setdefault(slot.material.name, []).append(obj.name)
    return seen


def audit_material(mat):
    """Returns a list of problem strings for one material."""
    problems = []
    if not mat.use_nodes:
        return problems                      # a flat diffuse colour exports fine

    nodes = list(mat.node_tree.nodes)

    if not any(n.type == 'BSDF_PRINCIPLED' for n in nodes):
        if any(n.type in {'EMISSION', 'BSDF_TRANSPARENT', 'MIX_SHADER', 'ADD_SHADER'}
               for n in nodes):
            pass                             # emission/transparent set-ups are handled
        else:
            problems.append("no Principled BSDF — glTF has no other surface model")

    for n in nodes:
        if n.type in PROCEDURAL:
            problems.append(
                f"procedural node {n.type} ({n.name!r}) — bakes to a flat colour on export")

        if n.type == 'TEX_COORD':
            for out in n.outputs:
                if out.name in NON_UV_COORDS and out.is_linked:
                    problems.append(
                        f"Texture Coordinate > {out.name} is linked — glTF samples by UV only")

        if n.type == 'TEX_IMAGE':
            img = n.image
            if img is None:
                problems.append(f"image node {n.name!r} has no image")
                continue
            if not img.packed_file:
                path = bpy.path.abspath(img.filepath_raw)
                if not path or not os.path.exists(path):
                    problems.append(f"image {img.name!r} is neither packed nor on disk")
            # "//" is Blender's own relative-to-the-.blend prefix, so it must be
            # tested before os.path.isabs, which sees a leading slash and agrees.
            raw = img.filepath_raw
            if raw and not raw.startswith("//") and os.path.isabs(raw):
                problems.append(
                    f"image {img.name!r} has a machine-absolute path: {raw}")

    return problems


def audit_uvs(used):
    """Meshes carrying an image-textured material but no UV layer."""
    problems = []
    textured = {name for name in used
                if bpy.data.materials[name].use_nodes
                and any(n.type == 'TEX_IMAGE' and n.image
                        for n in bpy.data.materials[name].node_tree.nodes)}
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        names = {s.material.name for s in obj.material_slots if s.material}
        if names & textured and not obj.data.uv_layers:
            problems.append(obj.name)
    return problems


def main() -> None:
    used = materials_in_use()
    log(f"{len(bpy.data.materials)} materials in file, {len(used)} assigned to meshes")
    log()

    failures = 0
    for name in sorted(used):
        problems = audit_material(bpy.data.materials[name])
        if problems:
            failures += len(problems)
            users = used[name]
            shown = ", ".join(users[:3]) + (f" (+{len(users) - 3} more)" if len(users) > 3 else "")
            log(f"FAIL {name}  [on: {shown}]")
            for p in problems:
                log(f"       - {p}")

    no_uv = audit_uvs(used)
    if no_uv:
        failures += len(no_uv)
        log(f"FAIL {len(no_uv)} textured mesh(es) with no UV layer:")
        for n in no_uv:
            log(f"       - {n}")

    log()
    if failures:
        log(f"{failures} problem(s) found — see docs in this file before exporting.")
        sys.exit(1)
    log("PASS — every assigned material is glTF-safe.")


main()
