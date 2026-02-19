# Grease Mesh

A Blender addon that turns Grease Pencil drawings into 3D meshes. Draw a shape, click a button, get a mesh — with modifiers you can tweak afterwards.

Located in **3D Viewport > N-Panel > GPTools**.

## Features

### Create
- **Add New Grease Pencil** — Creates a new Grease Pencil object ready for drawing.
- **Apply All Modifiers** — Bakes all modifiers on the selected mesh into the geometry.

### Convert
Quick conversions from Grease Pencil strokes:
- **To Curve** — Bezier curve from strokes.
- **To Mesh** — Edge mesh from strokes.
- **To Line** — Simplified line mesh from strokes.

### Solid Mesh
Turn drawn shapes into extruded 3D objects with thickness.
- **Solid Mesh** — Fills the drawn shape, adds Solidify for thickness. Toggle **Round** for beveled edges.

### Screw Mesh
Profile-based revolution with manual axis control.
- **Screw** — Revolves a drawn profile around a chosen axis (X/Y/Z) with configurable segments.
- **Square Screw** — Same as Screw but with 4 steps for a square cross-section.

### Lattice Wrap
Conform one mesh onto another mesh's surface.
1. Select two meshes (the one to deform + the target surface).
2. Click **Lattice Wrap** — creates a fitted lattice around the source mesh with a Shrinkwrap modifier targeting the other mesh.
3. The source mesh conforms to the target's curvature. Edit the lattice control points for fine-tuning.

Useful for wrapping decorative elements onto curved surfaces like columns, domes, or organic shapes.

## Installation

### Blender 4.2+ (Extensions)
1. Download as ZIP
2. `Edit > Preferences > Add-ons > Install from Disk...`
3. Select the ZIP and enable "Grease Mesh"

## Tips
- **Solid Mesh**: Draw closed shapes for best results. Toggle **Round** for smooth edges.
- **Screw Mesh**: Draw an open profile on one side of the axis.
- **Lattice Wrap**: Add subdivisions to the source mesh before wrapping for smoother results. Adjust the **Resolution** slider to control lattice detail.
- All operators leave modifiers non-destructive — tweak settings in the Properties > Modifiers panel after creation.

## License
GPL-3.0-or-later
