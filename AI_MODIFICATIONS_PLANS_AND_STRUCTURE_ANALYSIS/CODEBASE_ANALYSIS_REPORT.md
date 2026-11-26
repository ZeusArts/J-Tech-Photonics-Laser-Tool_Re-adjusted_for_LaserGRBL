# J-Tech Photonics Laser Tool - Inkscape Extension Codebase Analysis Report

## Overview

This is an **Inkscape extension** that converts SVG vector graphics into **G-code** for controlling diode laser cutting/engraving machines (specifically targeting LaserGRBL-compatible devices). The extension is called "J Tech Community Laser Tool" and integrates into Inkscape's **Extensions → Generate Laser Gcode** menu.

---

## File Structure

```
laser/
├── laser.inx          # Inkscape extension manifest (UI definition)
├── laser.py           # Main entry point (Inkscape EffectExtension)
└── svg_to_gcode/      # Core conversion library
    ├── __init__.py    # Exports TOLERANCES, UNITS
    ├── formulas.py    # Mathematical utilities
    ├── compiler/      # G-code compilation pipeline
    │   ├── __init__.py
    │   ├── _compiler.py       # Main Compiler class
    │   └── interfaces/        # Machine-specific G-code dialects
    │       ├── __init__.py
    │       ├── _abstract_interface.py  # Abstract base class
    │       ├── _gcode.py               # Standard G-code implementation
    │       └── _fan_controlled_gcode.py
    ├── geometry/      # Geometric primitives & curve approximation
    │   ├── __init__.py
    │   ├── _vector.py           # 2D vector math
    │   ├── _matrix.py           # 4x4 transformation matrices
    │   ├── _abstract_curve.py   # Abstract Curve base class
    │   ├── _line.py             # Line segment
    │   ├── _circular_arc.py     # Circular arc
    │   ├── _elliptical_arc.py   # Elliptical arc
    │   ├── _quadratic_bazier.py # Quadratic Bezier
    │   ├── _cubic_bazier.py     # Cubic Bezier
    │   ├── _abstract_chain.py   # Abstract Chain base class
    │   ├── _line_segment_chain.py  # Adaptive line approximation
    │   └── _smooth_arc_chain.py
    └── svg_parser/    # SVG → Geometry parser
        ├── __init__.py
        ├── _path.py             # SVG path 'd' attribute parser
        ├── _parser_methods.py   # SVG DOM tree traversal
        ├── _transformation.py   # SVG transform attribute parser
        └── debug_methods.py     # Debug visualization in Inkscape
```

---

## Data Flow Architecture

```
┌─────────────────────┐
│   Inkscape SVG      │  (User draws vector graphics)
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  laser.py           │  Inkscape EffectExtension entry point
│  GcodeExtension     │  - Reads UI parameters from .inx
│  .effect()          │  - Orchestrates the pipeline
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  svg_parser.parse_root()  │  Recursive DOM traversal
│                       │  - Finds <path> elements
│                       │  - Applies inherited transforms
│                       │  - Handles visibility/display
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Path._parse_commands()  │  Parses SVG path 'd' string
│                       │  - Tokenizes commands (M, L, C, Q, A, Z...)
│                       │  - Handles absolute/relative coordinates
│                       │  - Builds geometric Curve objects
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Transformation     │  4x4 affine matrix composition
│  .apply_affine_transformation()
│                       │  - Translate, scale, rotate, skew
│                       │  - SVG origin (top-left) → Cartesian (bottom-left)
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Compiler.append_curves()  │  Curve → G-code compilation
│                       │  - LineSegmentChain.line_segment_approximation()
│                       │    Adaptive subdivision (error-controlled)
│                       │  - Generates G1 moves with laser on/off
│                       │  - Handles multi-pass cutting (Z-axis stepping)
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Gcode Interface    │  Machine-specific command generation
│  (custom or default)│  - M3 S### (laser power 0-255)
│                       │  - M5 (laser off)
│                       │  - G1 X... Y... F... (coordinated moves)
│                       │  - G20/G21 (inch/mm)
│                       │  - G90/G91 (abs/rel coords)
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Output .gcode file │  Ready for LaserGRBL
└─────────────────────┘
```

---

## Key Components Detail

### 1. `laser.inx` - Inkscape Extension Manifest

Defines the **UI tabs and parameters** exposed to users:

| Tab | Key Parameters |
|-----|----------------|
| **Important Settings** | Unit (mm/in), Travel Speed, Cutting Speed, Passes, Pass Depth, Output Directory, Filename |
| **Advanced Settings** | Laser Power Command (default `M3 S255`), Laser Off Command (`M5`), Dwell Time, Debug Drawing, Approximation Tolerance |
| **Header/Footer** | Custom header/footer G-code files, Z-axis start, Move to origin at end, Laser off at start/end |
| **Coordinate System** | Machine Origin (bottom-left/center/top-left), Invert Y-axis, Bed size, Offsets, Scaling Factor |

The `<effect>` section restricts this extension to **path objects only** (`<object-type>path</object-type>`).

---

### 2. `laser.py` - Main Extension Class

**`GcodeExtension`** extends `inkex.EffectExtension` and implements:

- **`effect()`** - Main pipeline:
  1. Reads SVG root from Inkscape document
  2. Sets approximation tolerance from UI
  3. Validates output directory
  4. Constructs output filename (with optional numeric suffix)
  5. Loads custom header/footer G-code files
  6. Creates custom `Gcode` interface with user-defined laser commands
  7. Builds transformation matrix (offsets, scaling, origin)
  8. Calls `parse_root()` to extract curves from SVG
  9. Compiles curves to G-code via `Compiler`
  10. Writes output file
  11. Draws debug layers (toolpath visualization, reference points)

- **`draw_debug_traces()`** - Adds red arrow-marked paths showing laser toolpath
- **`draw_unit_reference()`** - Adds corner markers with coordinate labels
- **`select_non_debug_layer()`** - Creates/selects "content layer" to prevent accidental debug-layer edits
- **`clear_debug()`** - Removes previous debug layers before new generation
- **Dynamic argument parsing** - Reads `.inx` at runtime to auto-populate `self.options`

---

### 3. `svg_to_gcode/svg_parser/_path.py` - SVG Path Parser

**`Path` class** parses the SVG `d` attribute (path data string):

- **Tokenizer**: Character-by-character parsing handling:
  - Commands: `M/m` (move), `L/l` (line), `H/h` (horizontal), `V/v` (vertical), `C/c` (cubic Bezier), `S/s` (smooth cubic), `Q/q` (quadratic Bezier), `T/t` (smooth quadratic), `A/a` (elliptical arc), `Z/z` (close path)
  - Absolute (uppercase) vs relative (lowercase) coordinates
  - Implicit command repetition (e.g., `M 10 10 20 20` → move then line)
  - Scientific notation, implicit decimals (`.5`), negative numbers without delimiters

- **Coordinate Transformation**: Applies `Transformation` matrix to convert from SVG space (origin top-left, Y-down) to Cartesian space (origin bottom-left, Y-up)

- **Curve Generation**: Creates geometry objects:
  - `Line(start, end)`
  - `CubicBazier(start, end, control1, control2)`
  - `QuadraticBezier(start, end, control)`
  - `EllipticalArc(center, radii, rotation, start_angle, sweep_angle)` - uses `endpoint_to_center_parameterization()` from formulas

---

### 4. `svg_to_gcode/svg_parser/_parser_methods.py` - DOM Traversal

**`parse_root()`** recursively walks the SVG DOM tree:

- **Inheritance handling**: Transformations accumulate down the tree
- **Visibility filtering**: Respects `display="none"`, `visibility="hidden/collapse"`, `<defs>` elements
- **Canvas height**: Extracted from root `<svg height="...">` for Y-axis flip
- **Output**: Flat list of `Curve` objects (all transformations already applied)

---

### 5. `svg_to_gcode/svg_parser/_transformation.py` - Affine Transforms

**`Transformation` class** manages 4×4 homogeneous matrices:

- **Operations**: `translate(x,y)`, `scale(sx,sy)`, `rotate(deg)`, `skewX/Y(deg)`, `matrix(a,b,c,d,e,f)`
- **Composition**: Multiplies matrices in SVG-specified order
- **Application**:
  - `apply_affine_transformation(vector)` - Points (with translation)
  - `apply_linear_transformation(vector)` - Vectors (no translation, e.g., radii)
- **Deep-copyable** for recursive parser inheritance

---

### 6. `svg_to_gcode/geometry/_line_segment_chain.py` - Adaptive Approximation

**`LineSegmentChain.line_segment_approximation()`** converts any `Curve` to polyline:

```
Algorithm (adaptive subdivision):
├── Start with t=0, increment=5
├── While t < 1:
│   ├── Try step to t + increment
│   ├── Compute max distance from curve to line segment (Curve.max_distance)
│   ├── If error > error_cap:  increment /= growth_factor;  retry
│   ├── If error < error_floor: increment *= growth_factor
│   ├── Accept segment, advance t
│   └── Clamp final step to t=1
└── Return LineSegmentChain
```

- **Error-controlled**: Guarantees deviation ≤ `TOLERANCES["approximation"]` (default 0.01)
- **Efficient**: Grows segments in flat areas, shrinks in tight curves
- **Used by**: `Compiler.append_curves()` for all curve types

---

### 7. `svg_to_gcode/compiler/_compiler.py` - G-code Assembly

**`Compiler` class** orchestrates code generation:

- **Header**: `G90` (absolute), `G21/G20` (units), laser off, travel speed, custom header
- **Body**: For each curve → `append_line_chain()` → `linear_move()` calls with laser on
- **Passes**: Multi-pass support - repeats body, inserts `M5` + `G91 Z-{pass_depth} G90` between passes
- **Footer**: Custom footer, laser off, optional move to origin
- **State tracking**: `self.interface.position` for avoiding redundant moves

---

### 8. `svg_to_gcode/compiler/interfaces/_gcode.py` - G-code Dialect

**`Gcode` class** implements the `Interface` abstract base:

| Method | Output |
|--------|--------|
| `set_movement_speed(speed)` | Stores speed, emits on next move |
| `linear_move(x,y,z)` | `G1 X... Y... Z... F...` |
| `laser_off()` | `M5` |
| `set_laser_power(0-1)` | `M3 S{0-255}` (linear map) |
| `set_absolute_coordinates()` | `G90` |
| `set_relative_coordinates()` | `G91` |
| `dwell(ms)` | `G4 P...` |
| `set_origin_at_position()` | `G92 X0 Y0 Z0` |
| `set_unit("mm"/"in")` | `G21` / `G20` |
| `home_axes()` | `G28` |

**Custom Interface** (in `laser.py`): Wraps `Gcode` to override `laser_off()` and `set_laser_power()` with user-defined commands from UI (e.g., `M3 S255` vs `M4 S1000`).

---

### 9. `svg_to_gcode/formulas.py` - Math Utilities

Key functions:
- `linear_map(min, max, t)` - Maps [0,1] → [min,max] (laser power scaling)
- `endpoint_to_center_parameterization()` - SVG arc endpoint → center notation (W3C algorithm)
- `angle_between_vectors()` - Signed angle for arc sweep direction
- `tolerance_constrain()` - Floating-point tolerance clamping
- `center_to_endpoint_parameterization()` - Reverse of above

---

### 10. Debug Visualization (`debug_methods.py`)

Generates Inkscape SVG elements for verification:
- **Toolpath**: Red semi-transparent polyline with yellow arrow markers showing direction
- **Reference points**: Corner markers with G-code coordinate labels (adjusted for machine origin setting)
- **Layers**: Created as Inkscape layers (`inkscape:groupmode="layer"`) for easy toggling

---

## Supported SVG Features

| Feature | Support |
|---------|---------|
| `<path>` with all commands | ✅ Full |
| `<rect>`, `<circle>`, `<ellipse>`, `<line>`, `<polyline>`, `<polygon>` | ❌ Not implemented (TODO in parser) |
| Nested `<g>` with transforms | ✅ Full inheritance |
| `display="none"` / `visibility="hidden"` | ✅ Respected |
| Custom header/footer G-code files | ✅ |
| Multi-pass cutting (Z-stepping) | ✅ |
| mm/in units | ✅ |
| Machine origin variants | ✅ (3 modes) |
| Coordinate offsets & scaling | ✅ |

---

## Configuration for LaserGRBL

The default settings are tailored for **LaserGRBL / GRBL-based diode lasers**:

- **Laser ON**: `M3 S255` (spindle CW, max PWM)
- **Laser OFF**: `M5` (spindle stop)
- **Power scaling**: 0.0-1.0 → 0-255 (8-bit PWM)
- **Units**: G21 (mm) default
- **Coordinates**: G90 (absolute) default
- **Moves**: G1 (coordinated motion) with feed rate F

---

## Extension Points for Customization

1. **Custom G-code Interface**: Subclass `Interface` in `laser.py::generate_custom_interface()` for non-GRBL machines
2. **Header/Footer Files**: Inject machine-specific startup/shutdown sequences
3. **Approximation Tolerance**: Trade-off between G-code size and curve fidelity
4. **Debug Layers**: Visual verification before sending to machine

---

## Known Limitations / TODOs (from code comments)

- Shape elements (`<rect>`, `<circle>`, etc.) not parsed - only `<path>`
- Elliptical arc transformations "aren't applied correctly" (per comment in `_path.py`)
- `viewBox` handling not implemented
- `Interface` not yet formalized as `abc.ABC`
- G0 (rapid move) vs G1 (cutting move) distinction not implemented

---

## Usage Flow

1. **Install**: Copy `laser/` folder to Inkscape extensions directory
2. **Restart Inkscape**
3. **Draw** vector artwork (convert objects to paths: `Path → Object to Path`)
4. **Select** paths to cut/engrave
5. **Run**: `Extensions → Generate Laser Gcode → J Tech Community Laser Tool`
6. **Configure** settings in dialog tabs
7. **Apply** → Generates `.gcode` file + debug layers in Inkscape
8. **Load** `.gcode` into LaserGRBL and run