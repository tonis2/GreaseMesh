# Grease Mesh - Blender Addon

Easy-to-use toolbox for creating meshes from Blender Grease Pencil.

## Installation

### Blender 5.0+ (Recommended)
1. Download this folder as a ZIP file
2. Open Blender 5.0+
3. Go to `Edit > Preferences > Add-ons > Install from Disk...`
4. Select the ZIP file
5. Enable the addon by checking "Grease Mesh"

### Legacy Method (Blender 3.6 - 4.x)
1. Copy the `grease_mesh` folder to your Blender addons directory:
   - Windows: `%APPDATA%\Blender Foundation\Blender\5.0\scripts\addons\`
   - macOS: `~/Library/Application Support/Blender/5.0/scripts/addons/`
   - Linux: `~/.config/blender/5.0/scripts/addons/`
2. Enable in Blender: `Edit > Preferences > Add-ons > Search "Grease Mesh"`

## Usage

The addon panel is located in the **3D Viewport > N-Panel > GPTools**

### Features

#### 1. Create
- **Add New Grease Pencil**: Creates a new Grease Pencil object with a default layer

#### 2. Convert
- **To Curve**: Converts Grease Pencil strokes to a Bezier curve object
- **To Mesh**: Converts strokes to a mesh with edges
- **To Line**: Simplified line representation from strokes

#### 3. Solid Mesh
- Set **Thickness** in the panel
- Click **Create Solid Mesh** to generate an extruded 3D mesh from strokes

#### 4. Screw Mesh
- Select **Axis** (X, Y, or Z) to revolve around
- Set **Segments** for mesh resolution
- Click **Create Screw Mesh** to generate a lathe/spun mesh

## Tips
- Draw your profile on one side of the axis when using Screw Mesh
- Solid Mesh works best with closed or thick strokes
- All created objects maintain the original Grease Pencil for further editing

## License
GPL-3.0-or-later
