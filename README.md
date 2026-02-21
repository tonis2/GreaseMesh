# Grease Mesh

A Blender addon that turns Grease Pencil drawings into 3D meshes using Geometry Nodes. Draw a shape, click a button, get a mesh — non-destructively. Edit your strokes and the mesh updates live.

Located in **3D Viewport > N-Panel > GPTools**.

## Features

### Create
- **Add New Grease Pencil** — Creates a new Grease Pencil object ready for drawing.
- **Apply All Modifiers** — Bakes all modifiers on the selected object into the geometry.

### Mesh from GP (Geometry Nodes)
Non-destructive GP-to-mesh conversion powered by Geometry Nodes. The Grease Pencil object stays editable — modify your strokes and the mesh updates automatically.

- **Solid Mesh** — Fills drawn shapes and extrudes them into solid 3D objects with adjustable thickness.
- **Mirror Mesh** — Creates a mirrored solid mesh from a drawn half-shape. Draw one side, get both.
- **Path Mesh** — Sweeps a cross-section profile along a drawn path. Draw the path on one layer, the profile on another.

### Boolean
- **Bool Cut** — Draw a shape on a mesh surface with GP (Surface stroke placement), then cut it out with a boolean. Adjust cut depth and resolution in the popup dialog.

### Screw Mesh
Revolve a drawn profile into a 3D shape (vases, columns, turned objects).
- **Screw** — Revolves a drawn profile 360° with configurable segments. Auto-detects the revolution axis and centerline from the drawing.
- **Square Screw** — Same as Screw but with 4 steps for a square cross-section.

### Stamp Scatter
Scatter assets from a collection onto mesh surfaces using Grease Pencil marks. Perfect for placing windows, doors, props, or decorations on walls.
1. Create a collection with your assets (windows, doors, etc.).
2. Select the target mesh (wall) and create a Grease Pencil object.
3. Draw marks on the wall where you want assets placed (short strokes work best).
4. In GPTools, pick your asset collection and click **Scatter on Surface**.
5. The addon creates a Geometry Nodes modifier that instances random assets from your collection at each GP mark, aligned to the surface.

**Settings:**
- **Asset Collection** — Collection containing meshes to scatter
- **Scale** — Size multiplier for all scattered assets
- **Point Spacing** — Distance between points along GP strokes (lower = more instances)
- **Random Seed** — Change to get different random asset selections

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
- **Solid Mesh**: Draw closed shapes for best results. Adjust thickness in the modifier panel.
- **Mirror Mesh**: Draw one half of a symmetrical shape. The flat edge aligns to the mirror axis automatically.
- **Path Mesh**: Draw the sweep path first, then draw the cross-section profile on the second layer. Switch layers in Properties > Data.
- **Bool Cut**: Target mesh must be solid (has wall thickness). Thin shells from Screw need a Solidify modifier applied first.
- **Screw Mesh**: Draw half the silhouette of a round object. The axis and centerline are detected automatically.
- **Lattice Wrap**: Add subdivisions to the source mesh before wrapping for smoother results. Adjust the **Resolution** slider to control lattice detail.
- **Stamp Scatter**: Short GP strokes work best for precise placement. The addon samples points along each stroke and raycasts downward to find the surface. Use lower **Point Spacing** for dense scatter along lines (like placing fence posts).
- GN-based operators are fully non-destructive — tweak all settings in the Properties > Modifiers panel after creation.

## License
GPL-3.0-or-later
