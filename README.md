# Grease Mesh

A Blender addon that turns Grease Pencil drawings into 3D meshes using Geometry Nodes. Draw a shape, click a button, get a mesh — non-destructively. Edit your strokes and the mesh updates live.

Located in **3D Viewport > N-Panel > GMesh**.

## Features

### Create
- **Add New Grease Pencil** — Creates a new Grease Pencil object and enters Draw mode automatically.
- **Apply All Modifiers** — Bakes all modifiers on the selected object into the geometry. On a Grease Pencil object it creates a real mesh (keeping materials, per-stroke colours and attributes) and turns scattered props into linked duplicates.

### Mesh from GP (Geometry Nodes)
Non-destructive GP-to-mesh conversion powered by Geometry Nodes. The Grease Pencil object stays editable — modify your strokes and the mesh updates automatically.

- **Solid Mesh** — Fills drawn shapes and extrudes them into solid 3D objects with adjustable thickness.
- **Mirror Mesh** — Creates a mirrored solid mesh from a drawn half-shape. Draw one side, get both.
- **Path Mesh** — Sweeps a cross-section profile along a drawn path. Click **Path** and the panel walks you through it: draw the path → **Next**, draw the profile → **Done**. Strokes you've already drawn are used as the path.
- **Blocks Mesh** — Each closed stroke on the `Paint` layer becomes its own extruded block (stones, bricks, tiles), with per-block rotation/scale/thickness jitter. Strokes on the other layer define the plane.
- **Wall Mesh** — Generates a wall mesh from a drawn floor plan. Toggle **Closed** off for open wall runs.
- **Stroke Mesh** — Turns the drawing into a mesh that still looks like the drawing: flat ribbons (or round tubes) that follow stroke thickness, with per-stroke materials and vertex colours kept. Set a **Surface Object** to lay ribbons flat on a surface; **Project onto Surface** snaps the strokes onto it — **Nearest** for strokes drawn on or close to the surface, **Drawing Direction** to project a drawing made in front of it, like a projector.
- **Scatter** — Draw on the ground to place props from a collection. **Along Stroke** places them along the line (fences, rocks along a path; **Follow Stroke** turns them along it). **Fill Area** fills closed shapes — strokes drawn inside another stroke become holes. Props are snapped down onto the **Ground Object**, with random rotation/scale and optional tilt to the ground normal. Apply turns them into linked duplicates.

### Cutting
- **Bool Cut** — Draw a shape on a mesh surface with GP (Surface stroke placement), then cut it out with a boolean. Adjust cut depth in the popup dialog.
- **Knife** — Project a drawn shape onto a mesh as new edges (optionally cutting through).

### Screw Mesh
Revolve a drawn profile into a 3D shape (vases, columns, turned objects).
- **Screw** — Revolves a drawn profile 360° with configurable segments. Auto-detects the revolution axis and centerline from the drawing.

### Array on Pencil
- **Array on Pencil** — Distributes copies of the selected mesh along a drawn GP path.

### Rigging drawings (Bind to Surface)
Draw on a character (e.g. a facial expression on the face) and make it follow the rig:
1. Draw on the character mesh with Surface stroke placement.
2. Select the character mesh, then the GP, and click **Stroke** — the character becomes the Surface Object.
3. **Apply All Modifiers** to get a real mesh.
4. Click **Bind to Surface** — copies the character's vertex-group weights onto the drawing, adds the same Armature modifier and parents it to the armature.

If the surface isn't rigged, also select an armature: **Bind to Surface** then parents the drawing to it with Automatic Weights. Copied weights follow the surface more closely, so rig the surface when you can.

## Installation

### Blender 5.0+ (Extensions)
1. Download as ZIP
2. `Edit > Preferences > Add-ons > Install from Disk...`
3. Select the ZIP and enable "Grease Mesh"

## Tips
- **Solid Mesh**: Draw closed shapes for best results. Adjust thickness in the modifier panel.
- **Mirror Mesh**: Draw one half of a symmetrical shape. The flat edge aligns to the mirror axis automatically.
- **Path Mesh**: Draw the profile anywhere, from any view; it's centred and flattened automatically, but its size is kept. Use the ✕ next to Done to stop the steps; your strokes are kept.
- **Bool Cut**: Target mesh must be solid (has wall thickness).
- **Screw Mesh**: Draw half the silhouette of a round object. The axis and centerline are detected automatically.
- **Scatter**: Points are raycast straight down (GP local −Z) onto the Ground Object, so keep the GP object unrotated. Fill Area fills in the XY plane — draw area shapes roughly horizontally on the ground. Increase **Min Distance** to stop props overlapping.
- **Stroke Mesh**: Without a Surface Object, ribbons lie flat in the plane the drawing was made in.
- GN-based operators are fully non-destructive — tweak all settings in the Properties > Modifiers panel after creation.

## License
GPL-3.0-or-later
