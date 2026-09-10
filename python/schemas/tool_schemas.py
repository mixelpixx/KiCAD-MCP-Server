"""
Comprehensive tool schema definitions for all KiCAD MCP commands

Following MCP 2025-06-18 specification for tool definitions.
Each tool includes:
- name: Unique identifier
- title: Human-readable display name
- description: Detailed explanation of what the tool does
- inputSchema: JSON Schema for parameters
- outputSchema: Optional JSON Schema for return values (structured content)
"""

from typing import Any, Dict

from utils.duplicate_strategies import DEFAULT_DUPLICATE_STRATEGIES, DUPLICATE_STRATEGIES
from utils.pin_types import PIN_STYLES, PIN_TYPES

# =============================================================================
# PROJECT TOOLS
# =============================================================================

PROJECT_TOOLS = [
    {
        "name": "create_project",
        "title": "Create New KiCAD Project",
        "description": "Creates a new KiCAD project with PCB board file and optional project configuration. Automatically creates project directory and initializes board with default settings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectName": {
                    "type": "string",
                    "description": "Name of the project (used for file naming)",
                    "minLength": 1,
                },
                "path": {
                    "type": "string",
                    "description": "Directory path where project will be created (defaults to current working directory)",
                },
                "template": {
                    "type": "string",
                    "description": "Optional path to template board file to copy settings from",
                },
            },
            "required": ["projectName"],
        },
    },
    {
        "name": "open_project",
        "title": "Open Existing KiCAD Project",
        "description": "Opens an existing KiCAD project file (.kicad_pro or .kicad_pcb) and loads the board into memory for manipulation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Path to .kicad_pro or .kicad_pcb file",
                }
            },
            "required": ["filename"],
        },
    },
    {
        "name": "close_project",
        "title": "Close Current Project",
        "description": "Closes the currently loaded project: optionally saves the board, then drops the in-memory board (SWIG and IPC) and clears all session state. Symmetric counterpart to open_project/create_project. Use this to release the project so the user or agent can edit project files directly without a later MCP save clobbering those changes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "save": {
                    "type": "boolean",
                    "description": "Save the board to disk before closing (default true). If false and there are unsaved changes, the close proceeds but the response warns they were discarded.",
                },
                "forceExternalChanges": {
                    "type": "boolean",
                    "default": False,
                    "description": "Save despite external changes to the loaded SWIG board file",
                },
                "force": {
                    "type": "boolean",
                    "default": False,
                    "description": "Backward-compatible alias for forceExternalChanges",
                },
            },
        },
    },
    {
        "name": "save_project",
        "title": "Save Current Project",
        "description": (
            "Saves the current board to disk. Can optionally save to a new location. "
            "If the board file's contents changed on disk since it was loaded (an "
            "external edit), the save is refused to avoid clobbering those changes "
            "unless force=true is passed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Optional new path to save the board (if not provided, saves to current location)",
                },
                "path": {
                    "type": "string",
                    "description": "Alias for filename",
                },
                "force": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Overwrite the loaded board file even if its on-disk contents "
                        "changed externally since this session loaded it"
                    ),
                },
                "forceExternalChanges": {
                    "type": "boolean",
                    "default": False,
                    "description": "Explicit alias for force; takes precedence when both are provided",
                },
                "overwrite": {
                    "type": "boolean",
                    "default": False,
                    "description": "Replace an existing destination when saving to a different path",
                },
            },
        },
    },
    {
        "name": "open_board",
        "title": "Open PCB Board",
        "description": "Opens a specific .kicad_pcb file and refreshes MCP's in-memory board state.",
        "inputSchema": {
            "type": "object",
            "properties": {"boardPath": {"type": "string"}},
            "required": ["boardPath"],
        },
    },
    {
        "name": "reload_board",
        "title": "Reload PCB Board",
        "description": "Reloads the current or specified .kicad_pcb from disk, discarding stale in-memory state.",
        "inputSchema": {"type": "object", "properties": {"boardPath": {"type": "string"}}},
    },
    {
        "name": "save_board",
        "title": "Save PCB Board",
        "description": "Saves the loaded board with the external disk-change guard.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "boardPath": {"type": "string"},
                "force": {"type": "boolean", "default": False},
                "forceExternalChanges": {"type": "boolean", "default": False},
                "overwrite": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "save_as",
        "title": "Save Board As",
        "description": "Saves the loaded board to a new .kicad_pcb path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "boardPath": {"type": "string"},
                "overwrite": {"type": "boolean", "default": False},
                "force": {"type": "boolean", "default": False},
                "forceExternalChanges": {"type": "boolean", "default": False},
            },
            "required": ["boardPath"],
        },
    },
    {
        "name": "is_dirty",
        "title": "Board Dirty State",
        "description": "Reports whether MCP knows the loaded board has unsaved memory changes or external disk changes.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "discard_or_reload",
        "title": "Discard or Reload Board",
        "description": "Discards the in-memory board and reloads it from disk.",
        "inputSchema": {"type": "object", "properties": {"boardPath": {"type": "string"}}},
    },
    {
        "name": "snapshot_project",
        "title": "Snapshot Project (Checkpoint)",
        "description": "Copies the entire project folder to a new timestamped snapshot directory so you can resume from this checkpoint later without redoing earlier steps. Call this after every successfully completed design step (e.g. after Step 1 schematic, after Step 2 PCB layout) before asking for user confirmation to proceed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "step": {
                    "type": "string",
                    "description": "Step number or name to include in snapshot folder name, e.g. '1' or '2'",
                },
                "label": {
                    "type": "string",
                    "description": "Optional short label, e.g. 'schematic_ok' or 'layout_ok'",
                },
                "projectPath": {
                    "type": "string",
                    "description": "Project directory path. Auto-detected from loaded board if omitted.",
                },
            },
        },
    },
    {
        "name": "get_project_info",
        "title": "Get Project Information",
        "description": "Retrieves metadata and properties of the currently open project including name, paths, and board status.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

# =============================================================================
# BOARD TOOLS
# =============================================================================

BOARD_TOOLS = [
    {
        "name": "set_board_size",
        "title": "Set Board Dimensions",
        "description": "Sets the PCB board dimensions. The board outline must be added separately using add_board_outline.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "width": {
                    "type": "number",
                    "description": "Board width in millimeters",
                    "minimum": 1,
                },
                "height": {
                    "type": "number",
                    "description": "Board height in millimeters",
                    "minimum": 1,
                },
            },
            "required": ["width", "height"],
        },
    },
    {
        "name": "set_board_origin",
        "title": "Set Board Aux/Grid Origin",
        "description": (
            "Set the auxiliary (drill/place) origin and/or grid origin of a "
            ".kicad_pcb. The aux origin is the datum used by export_drill's "
            "drillOrigin:'plot' option and by pick-and-place / plot exports "
            "with useAuxOrigin."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "boardPath": {
                    "type": "string",
                    "description": "Path to the .kicad_pcb file",
                },
                "type": {
                    "type": "string",
                    "enum": ["aux", "grid", "both"],
                    "description": "Which origin to set (default: aux)",
                    "default": "aux",
                },
                "x": {"type": "number", "description": "Origin X coordinate"},
                "y": {"type": "number", "description": "Origin Y coordinate"},
                "unit": {
                    "type": "string",
                    "enum": ["mm", "mil", "inch"],
                    "description": "Coordinate unit (default: mm)",
                    "default": "mm",
                },
            },
            "required": ["boardPath", "x", "y"],
        },
    },
    {
        "name": "get_board_origin",
        "title": "Get Board Aux/Grid Origin",
        "description": (
            "Read back the auxiliary (drill/place) origin and grid origin of a " ".kicad_pcb in mm."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "boardPath": {
                    "type": "string",
                    "description": "Path to the .kicad_pcb file",
                },
            },
            "required": ["boardPath"],
        },
    },
    {
        "name": "add_board_outline",
        "title": "Add Board Outline",
        "description": "Adds a board outline shape (rectangle, rounded_rectangle, circle, or polygon) on the Edge.Cuts layer. By default the board top-left corner is placed at (0, 0) so all coordinates are positive. Use x/y to set a different top-left corner position.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "shape": {
                    "type": "string",
                    "enum": ["rectangle", "rounded_rectangle", "circle", "polygon"],
                    "description": "Shape type for the board outline",
                },
                "width": {
                    "type": "number",
                    "description": "Width in mm (for rectangle/rounded_rectangle)",
                    "minimum": 1,
                },
                "height": {
                    "type": "number",
                    "description": "Height in mm (for rectangle/rounded_rectangle)",
                    "minimum": 1,
                },
                "x": {
                    "type": "number",
                    "description": "X coordinate of the top-left corner in mm (default: 0). Board extends from x to x+width.",
                },
                "y": {
                    "type": "number",
                    "description": "Y coordinate of the top-left corner in mm (default: 0). Board extends from y to y+height.",
                },
                "radius": {
                    "type": "number",
                    "description": "Corner radius in mm for rounded_rectangle, or radius for circle",
                    "minimum": 0,
                },
                "points": {
                    "type": "array",
                    "description": "Array of {x, y} point objects in mm (for polygon shape only)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                        },
                        "required": ["x", "y"],
                    },
                    "minItems": 3,
                },
            },
            "required": ["shape"],
        },
    },
    {
        "name": "clear_board_outline",
        "title": "Clear Board Outline",
        "description": "Deletes all Edge.Cuts graphic items from the current PCB.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "replace_board_outline",
        "title": "Replace Board Outline",
        "description": "Clears existing Edge.Cuts items and adds a new board outline.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "shape": {
                    "type": "string",
                    "enum": ["rectangle", "rounded_rectangle", "circle", "polygon"],
                },
                "width": {"type": "number"},
                "height": {"type": "number"},
                "x": {"type": "number"},
                "y": {"type": "number"},
                "radius": {"type": "number"},
                "cornerRadius": {"type": "number"},
                "points": {"type": "array"},
                "unit": {"type": "string", "enum": ["mm", "mil", "inch"], "default": "mm"},
            },
            "required": ["shape"],
        },
    },
    {
        "name": "list_graphics",
        "title": "List PCB Graphics",
        "description": "Lists board drawing items, optionally filtered by layer.",
        "inputSchema": {"type": "object", "properties": {"layer": {"type": "string"}}},
    },
    {
        "name": "delete_graphic",
        "title": "Delete PCB Graphic",
        "description": "Deletes a board drawing item by KiCad UUID.",
        "inputSchema": {
            "type": "object",
            "properties": {"uuid": {"type": "string"}},
            "required": ["uuid"],
        },
    },
    {
        "name": "update_graphic",
        "title": "Update PCB Graphic",
        "description": "Updates common board graphic properties by KiCad UUID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uuid": {"type": "string"},
                "layer": {"type": "string"},
                "width": {"type": "number"},
                "start": {"type": "object"},
                "end": {"type": "object"},
                "center": {"type": "object"},
                "position": {"type": "object"},
                "text": {"type": "string"},
                "unit": {"type": "string", "enum": ["mm", "mil", "inch"], "default": "mm"},
            },
            "required": ["uuid"],
        },
    },
    {
        "name": "add_layer",
        "title": "Enable Copper Layer",
        "description": (
            "Enables a copper layer in the board stackup and gives it a name. "
            "Copper layers only — KiCad's technical and user layers (silkscreen, "
            "mask, courtyard, Dwgs.User, ...) are a fixed set that always exists "
            "and cannot be added."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Name for the layer. Stored alongside KiCad's canonical name "
                        "(e.g. name 'PWR' on In1.Cu is written as "
                        '(4 "In1.Cu" signal "PWR")).'
                    ),
                },
                "type": {
                    "type": "string",
                    "enum": ["copper", "signal", "power", "mixed", "jumper"],
                    "description": "Copper layer type",
                },
                "position": {
                    "type": "string",
                    "enum": ["top", "bottom", "inner"],
                    "description": "Which copper layer to target",
                },
                "number": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30,
                    "description": (
                        "Inner-layer ORDINAL, 1-based: 1 = In1.Cu, 2 = In2.Cu. This is "
                        "not a KiCad layer ID (In1.Cu's id is 4). Required when "
                        "position is 'inner'. The response echoes the resolved "
                        "canonicalName and id."
                    ),
                },
            },
            "required": ["name", "type", "position"],
        },
    },
    {
        "name": "set_active_layer",
        "title": "Set Active Layer",
        "description": "Sets the currently active layer for drawing operations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "layer": {
                    "type": "string",
                    "description": "Name of the layer to make active (e.g., F.Cu, B.Cu, Edge.Cuts)",
                }
            },
            "required": ["layer"],
        },
    },
    {
        "name": "get_layer_list",
        "title": "List Board Layers",
        "description": "Returns a list of all layers in the board with their properties.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_board_info",
        "title": "Get Board Information",
        "description": "Retrieves comprehensive board information including dimensions, layer count, component count, and design rules.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_board_2d_view",
        "title": "Render Board Preview",
        "description": (
            "Renders a 2D image of the PCB via kicad-cli (no pcbnew/cffi dependency). "
            "Supports PNG, JPG, and SVG output. "
            "Use responseMode to control how the image is returned. "
            'responseMode="inline" (default) returns the image as base64-encoded imageData — '
            "convenient for small boards but may exceed message-size limits on large designs. "
            'responseMode="file" writes the image next to the .kicad_pcb file as '
            "<board>_2d_view.<ext> and returns a filePath; prefer this mode for large boards."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pcbPath": {
                    "type": "string",
                    "description": "Absolute path to the .kicad_pcb file. Falls back to the currently loaded board if omitted.",
                },
                "width": {
                    "type": "number",
                    "description": "Image width in pixels (default: 1600)",
                    "minimum": 100,
                    "default": 1600,
                },
                "height": {
                    "type": "number",
                    "description": "Image height in pixels (default: 1200)",
                    "minimum": 100,
                    "default": 1200,
                },
                "format": {
                    "type": "string",
                    "enum": ["png", "jpg", "svg"],
                    "description": "Output image format (default: png)",
                    "default": "png",
                },
                "layers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'Layer names to include, e.g. ["F.Cu","B.Cu","Edge.Cuts"]. Omit for all layers.',
                },
                "responseMode": {
                    "type": "string",
                    "enum": ["inline", "file"],
                    "default": "inline",
                    "description": (
                        "How to return the image. "
                        '"inline" (default): base64-encoded bytes in imageData. '
                        '"file": write to <board>_2d_view.<ext> next to the PCB and return filePath.'
                    ),
                },
            },
        },
    },
    {
        "name": "get_board_extents",
        "title": "Get Board Bounding Box",
        "description": "Returns the bounding box extents of the PCB board including all edge cuts, components, and traces.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "unit": {
                    "type": "string",
                    "enum": ["mm", "mil", "inch"],
                    "description": "Unit for returned coordinates (default: mm)",
                    "default": "mm",
                }
            },
        },
    },
    {
        "name": "add_mounting_hole",
        "title": "Add Mounting Hole",
        "description": "Adds a mounting hole at the specified position with given diameter. Defaults to non-plated (NPTH) with mask-only pad layers; set plated=true for a PTH with copper pad.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "position": {
                    "type": "object",
                    "description": "Position of the mounting hole",
                    "properties": {
                        "x": {"type": "number", "description": "X coordinate"},
                        "y": {"type": "number", "description": "Y coordinate"},
                        "unit": {
                            "type": "string",
                            "enum": ["mm", "mil", "inch"],
                            "default": "mm",
                            "description": "Unit for x/y (default mm)",
                        },
                    },
                    "required": ["x", "y"],
                },
                "diameter": {
                    "type": "number",
                    "description": "Hole (drill) diameter in millimeters",
                    "minimum": 0.1,
                },
                "padDiameter": {
                    "type": "number",
                    "description": "Pad diameter in millimeters (defaults to diameter + 1mm). For NPTH this only affects the solder-mask opening, not copper.",
                    "minimum": 0.1,
                },
                "plated": {
                    "type": "boolean",
                    "default": False,
                    "description": "True for plated through-hole (PTH) with copper pad; false (default) for NPTH (mask only).",
                },
                "footprintLibId": {
                    "type": "string",
                    "description": "Optional library:name FPID (e.g. 'MountingHole:MountingHole_3.2mm'). Defaults to MountingHole:MountingHole_<diameter>mm. A non-empty FPID is required for the footprint to be selectable in KiCad's GUI Move tool.",
                },
            },
            "required": ["position", "diameter"],
        },
    },
    {
        "name": "import_svg_logo",
        "title": "Import SVG Logo to PCB",
        "description": "Imports an SVG file as filled graphic polygons onto a KiCAD PCB layer (default F.SilkS). Curves are linearised automatically. Supports path, rect, circle, ellipse, polygon and group transforms.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pcbPath": {
                    "type": "string",
                    "description": "Path to the .kicad_pcb file",
                },
                "svgPath": {
                    "type": "string",
                    "description": "Path to the SVG logo file",
                },
                "x": {
                    "type": "number",
                    "description": "X position of the logo top-left corner in mm",
                },
                "y": {
                    "type": "number",
                    "description": "Y position of the logo top-left corner in mm",
                },
                "width": {
                    "type": "number",
                    "description": "Target width of the logo in mm (height scaled to preserve aspect ratio)",
                    "minimum": 0.1,
                },
                "layer": {
                    "type": "string",
                    "description": "PCB layer name, e.g. F.SilkS or B.SilkS (default: F.SilkS)",
                    "default": "F.SilkS",
                },
                "strokeWidth": {
                    "type": "number",
                    "description": "Outline stroke width in mm (0 = no outline, default 0)",
                    "default": 0,
                },
                "filled": {
                    "type": "boolean",
                    "description": "Fill polygons with solid layer colour (default true)",
                    "default": True,
                },
            },
            "required": ["pcbPath", "svgPath", "x", "y", "width"],
        },
    },
    {
        "name": "add_board_text",
        "title": "Add Text to Board",
        "description": "Adds text annotation to the board on a specified layer (e.g., F.SilkS for top silkscreen).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text content to add",
                    "minLength": 1,
                },
                "x": {"type": "number", "description": "X coordinate in millimeters"},
                "y": {"type": "number", "description": "Y coordinate in millimeters"},
                "layer": {
                    "type": "string",
                    "description": "Layer name (e.g., F.SilkS, B.SilkS, F.Cu)",
                    "default": "F.SilkS",
                },
                "size": {
                    "type": "number",
                    "description": "Text size in millimeters",
                    "minimum": 0.1,
                    "default": 1.0,
                },
                "thickness": {
                    "type": "number",
                    "description": "Text thickness in millimeters",
                    "minimum": 0.01,
                    "default": 0.15,
                },
            },
            "required": ["text", "x", "y"],
        },
    },
]

# =============================================================================
# COMPONENT TOOLS
# =============================================================================

COMPONENT_TOOLS = [
    {
        "name": "place_component",
        "title": "Place Component",
        "description": "Places a component with specified footprint at given coordinates on the board.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator (e.g., R1, C2, U3)",
                },
                "footprint": {
                    "type": "string",
                    "description": "Footprint library:name (e.g., Resistor_SMD:R_0805_2012Metric)",
                },
                "x": {"type": "number", "description": "X coordinate in millimeters"},
                "y": {"type": "number", "description": "Y coordinate in millimeters"},
                "rotation": {
                    "type": "number",
                    "description": "Rotation angle in degrees (0-360)",
                    "minimum": 0,
                    "maximum": 360,
                    "default": 0,
                },
                "layer": {
                    "type": "string",
                    "enum": ["F.Cu", "B.Cu"],
                    "description": "Board layer (top or bottom)",
                    "default": "F.Cu",
                },
            },
            "required": ["reference", "footprint", "x", "y"],
        },
    },
    {
        "name": "move_component",
        "title": "Move Component",
        "description": "Moves an existing component to a new position on the board.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator",
                },
                "x": {
                    "type": "number",
                    "description": "New X coordinate in millimeters",
                },
                "y": {
                    "type": "number",
                    "description": "New Y coordinate in millimeters",
                },
            },
            "required": ["reference", "x", "y"],
        },
    },
    {
        "name": "batch_move_components",
        "title": "Batch Move Components",
        "description": "Moves multiple PCB components transactionally and saves by default.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "moves": {"type": "object"},
                "save": {"type": "boolean", "default": True},
                "dryRun": {"type": "boolean", "default": False},
            },
            "required": ["moves"],
        },
    },
    {
        "name": "rotate_component",
        "title": "Rotate Component",
        "description": "Rotates a component by specified angle. Rotation is cumulative with existing rotation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator",
                },
                "angle": {
                    "type": "number",
                    "description": "Rotation angle in degrees (positive = counterclockwise)",
                },
            },
            "required": ["reference", "angle"],
        },
    },
    {
        "name": "delete_component",
        "title": "Delete Component",
        "description": "Removes a component from the board.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator",
                }
            },
            "required": ["reference"],
        },
    },
    {
        "name": "edit_component",
        "title": "Edit Component Properties",
        "description": "Modifies properties of an existing component (value, footprint, etc.).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator",
                },
                "value": {"type": "string", "description": "New component value"},
                "footprint": {
                    "type": "string",
                    "description": "New footprint library:name",
                },
            },
            "required": ["reference"],
        },
    },
    {
        "name": "get_component_properties",
        "title": "Get Component Properties",
        "description": "Retrieves detailed properties of a specific component.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator",
                }
            },
            "required": ["reference"],
        },
    },
    {
        "name": "get_component_list",
        "title": "List All Components",
        "description": "Returns a list of all components on the board with their properties.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_component_geometry",
        "title": "Get Component Geometry",
        "description": "Returns separated footprint bboxes for body, pads, courtyard, keepout, fab, silk and text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {"type": "string"},
                "refs": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "find_component",
        "title": "Find Components",
        "description": "Searches for components matching specified criteria. Supports partial matching on reference, value, or footprint patterns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Reference designator pattern to match (e.g., 'R1', 'U', 'C2')",
                },
                "value": {
                    "type": "string",
                    "description": "Value pattern to match (e.g., '10k', '100nF')",
                },
                "footprint": {
                    "type": "string",
                    "description": "Footprint pattern to match (e.g., '0805', 'SOIC')",
                },
            },
        },
    },
    {
        "name": "get_component_pads",
        "title": "Get Component Pads",
        "description": "Returns all pads for a component with their positions, net connections, sizes, and shapes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator (e.g., U1, R5)",
                }
            },
            "required": ["reference"],
        },
    },
    {
        "name": "get_pads",
        "title": "Get Pads",
        "description": "Returns pads for one component, selected refs, or all components.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {"type": "string"},
                "refs": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "get_net_pads",
        "title": "Get Net Pads",
        "description": "Returns every pad attached to a net name or net code.",
        "inputSchema": {
            "type": "object",
            "properties": {"net": {"type": "string"}, "netCode": {"type": "number"}},
        },
    },
    {
        "name": "get_pad_position",
        "title": "Get Pad Position",
        "description": "Returns the position and properties of a specific pad on a component.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Component reference designator",
                },
                "padName": {
                    "type": "string",
                    "description": "Pad name or number (e.g., '1', '2', 'A1')",
                },
                "padNumber": {
                    "type": "string",
                    "description": "Alternative to padName - pad number",
                },
            },
            "required": ["reference"],
        },
    },
    {
        "name": "get_ratsnest",
        "title": "Get Ratsnest",
        "description": "Estimates ratsnest/airwire segments and lengths from current pad positions grouped by net.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "nets": {"type": "array", "items": {"type": "string"}},
                "maxPadsPerNet": {"type": "number", "default": 128},
            },
        },
    },
    {
        "name": "estimate_airwire_lengths",
        "title": "Estimate Airwire Lengths",
        "description": "Alias for get_ratsnest.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "nets": {"type": "array", "items": {"type": "string"}},
                "maxPadsPerNet": {"type": "number", "default": 128},
            },
        },
    },
    {
        "name": "check_placement_clearance",
        "title": "Check Placement Clearance",
        "description": "Classifies placement conflicts as body, courtyard, keepout, silk/text, or pad-clearance issues.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "refs": {"type": "array", "items": {"type": "string"}},
                "margin": {"type": "number", "default": 0},
                "padClearance": {"type": "number", "default": 0},
            },
        },
    },
    {
        "name": "move_footprint_text",
        "title": "Move Footprint Text",
        "description": "Moves a footprint Reference/Value/user text field without moving the footprint.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {"type": "string"},
                "field": {"type": "string"},
                "x": {"type": "number"},
                "y": {"type": "number"},
                "rotation": {"type": "number"},
                "layer": {"type": "string"},
                "visible": {"type": "boolean"},
            },
            "required": ["reference", "field"],
        },
    },
    {
        "name": "place_component_array",
        "title": "Place Component Array",
        "description": "Places multiple copies of a component in a grid or circular pattern.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "referencePrefix": {
                    "type": "string",
                    "description": "Reference prefix (e.g., 'R' for R1, R2, R3...)",
                },
                "startNumber": {
                    "type": "integer",
                    "description": "Starting number for references",
                    "minimum": 1,
                    "default": 1,
                },
                "footprint": {
                    "type": "string",
                    "description": "Footprint library:name",
                },
                "pattern": {
                    "type": "string",
                    "enum": ["grid", "circular"],
                    "description": "Array pattern type",
                },
                "count": {
                    "type": "integer",
                    "description": "Total number of components to place",
                    "minimum": 1,
                },
                "startX": {
                    "type": "number",
                    "description": "Starting X coordinate in millimeters",
                },
                "startY": {
                    "type": "number",
                    "description": "Starting Y coordinate in millimeters",
                },
                "spacingX": {
                    "type": "number",
                    "description": "Horizontal spacing in mm (for grid pattern)",
                },
                "spacingY": {
                    "type": "number",
                    "description": "Vertical spacing in mm (for grid pattern)",
                },
                "radius": {
                    "type": "number",
                    "description": "Circle radius in mm (for circular pattern)",
                },
                "rows": {
                    "type": "integer",
                    "description": "Number of rows (for grid pattern)",
                    "minimum": 1,
                },
                "columns": {
                    "type": "integer",
                    "description": "Number of columns (for grid pattern)",
                    "minimum": 1,
                },
            },
            "required": [
                "referencePrefix",
                "footprint",
                "pattern",
                "count",
                "startX",
                "startY",
            ],
        },
    },
    {
        "name": "align_components",
        "title": "Align Components",
        "description": "Aligns multiple components horizontally or vertically.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "references": {
                    "type": "array",
                    "description": "Array of component reference designators to align",
                    "items": {"type": "string"},
                    "minItems": 2,
                },
                "direction": {
                    "type": "string",
                    "enum": ["horizontal", "vertical"],
                    "description": "Alignment direction",
                },
                "spacing": {
                    "type": "number",
                    "description": "Spacing between components in mm (optional, for even distribution)",
                },
            },
            "required": ["references", "direction"],
        },
    },
    {
        "name": "check_courtyard_overlaps",
        "title": "Check Courtyard Overlaps",
        "description": (
            "Detects courtyard overlaps between footprints and (optionally) flags "
            "footprints whose courtyard extends past the board outline. "
            "Returns overlap pairs with intersection extents and per-component "
            "boundary violations, both in mm. Accepts a 'positions' dict to "
            "evaluate a HYPOTHETICAL placement without modifying the board — "
            "use this before committing a move_component / place_component call "
            "to know if it will trigger DRC. "
            "Approach ported from morningfire-pcb-automation "
            "(https://github.com/NiNjA-CodE/morningfire-pcb-automation, "
            "scripts/placement/check_overlaps.py); this version reads real "
            "courtyard polygons from the board (not a static lookup table) and "
            "supports virtual placement + rotation + clearance margin."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "positions": {
                    "type": "object",
                    "description": (
                        "Virtual placements: map of reference designator to "
                        "[x, y] or [x, y, rotation_degrees] in mm. Each listed "
                        "ref is checked AS IF it were at the given coordinates. "
                        "Unspecified refs use their current board position."
                    ),
                    "additionalProperties": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 3,
                    },
                },
                "refs": {
                    "type": "array",
                    "description": (
                        "Limit the check to these refs (default: every " "footprint on the board)."
                    ),
                    "items": {"type": "string"},
                },
                "margin": {
                    "type": "number",
                    "description": (
                        "Extra clearance in mm added around every courtyard "
                        "(default 0). Useful to enforce a manufacturing keepout "
                        "wider than the symbol's declared courtyard."
                    ),
                    "default": 0,
                },
                "include_boundary": {
                    "type": "boolean",
                    "description": (
                        "Also flag courtyards that extend past the board outline " "(default true)."
                    ),
                    "default": True,
                },
                "board_outline": {
                    "type": "object",
                    "description": (
                        "Optional override for the board outline bbox. Default: "
                        "derived from Edge.Cuts."
                    ),
                    "properties": {
                        "x1": {"type": "number"},
                        "y1": {"type": "number"},
                        "x2": {"type": "number"},
                        "y2": {"type": "number"},
                        "unit": {
                            "type": "string",
                            "enum": ["mm", "mil", "inch"],
                            "default": "mm",
                        },
                    },
                    "required": ["x1", "y1", "x2", "y2"],
                },
            },
        },
    },
    {
        "name": "suggest_placement",
        "title": "Suggest Placement",
        "description": (
            "Propose an optimized PCB footprint placement that shortens net "
            "length, orients parts toward their partners, and removes courtyard "
            "overlaps — the heuristic an engineer does by eye against the "
            "ratsnest. Force-directed clustering pulls connected parts together "
            "(a converter's feedback divider and decoupling caps end up hugging "
            "its IC), power/high-current nets are weighted to stay short & "
            "direct, and each part is rotated (0/90/180/270) to face its "
            "neighbours so airwires stop crossing. PCB ONLY — it does not touch "
            "the schematic. DRY RUN by default: returns proposals "
            "{ref:[x,y,rot]} plus a score (HPWL before/after, overlap counts) "
            "WITHOUT modifying the board. Validate proposals via "
            "check_courtyard_overlaps(positions=proposals), then re-run with "
            "apply=true (or move_component per ref) before autoroute."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "refs": {
                    "type": "array",
                    "description": (
                        "References to move (default: every non-locked " "footprint on the board)."
                    ),
                    "items": {"type": "string"},
                },
                "locked": {
                    "type": "array",
                    "description": (
                        "References to hold fixed as anchors — connectors, "
                        "mounting-constrained parts, RF, edge parts. They still "
                        "pull movable parts. Footprints KiCad marks locked are "
                        "added automatically."
                    ),
                    "items": {"type": "string"},
                },
                "apply": {
                    "type": "boolean",
                    "description": (
                        "If true, move + rotate the components to the proposed "
                        "positions. Default false (dry run — board untouched)."
                    ),
                    "default": False,
                },
                "iterations": {
                    "type": "integer",
                    "description": "Force-directed relaxation passes (default 200).",
                    "default": 200,
                },
                "grid_mm": {
                    "type": "number",
                    "description": "Snap proposed positions to this grid (default 0.5).",
                    "default": 0.5,
                },
                "margin_mm": {
                    "type": "number",
                    "description": ("Extra keepout enforced between courtyards (default 0.3)."),
                    "default": 0.3,
                },
                "rotate": {
                    "type": "boolean",
                    "description": (
                        "Enable pin-facing rotation (default true). Disable to "
                        "keep every part's current orientation."
                    ),
                    "default": True,
                },
                "spread": {
                    "type": "boolean",
                    "description": (
                        "Enable density spreading (default true). The springs "
                        "pack parts into a blob denser than they physically fit; "
                        "spreading diffuses them across free board area so the "
                        "result is legal (few/zero courtyard overlaps) instead "
                        "of over-packed. Leave on for whole-board runs."
                    ),
                    "default": True,
                },
                "align": {
                    "type": "boolean",
                    "description": (
                        "Tidy the result into rows/columns (default true). Snaps "
                        "near-collinear part centers onto shared row (Y) and "
                        "column (X) lines so passives line up cleanly with their "
                        "centers aligned — like KiCad's Align Centers + "
                        "Distribute — instead of organic offsets. Disable for a "
                        "pure shortest-wire layout."
                    ),
                    "default": True,
                },
                "align_tol_mm": {
                    "type": "number",
                    "description": (
                        "Max center spacing (mm) for parts to be pulled onto the "
                        "same row/column line during align (default 1.5)."
                    ),
                    "default": 1.5,
                },
                "rotation_steps": {
                    "type": "array",
                    "description": (
                        "Candidate orientations in degrees " "(default [0, 90, 180, 270])."
                    ),
                    "items": {"type": "number"},
                    "default": [0, 90, 180, 270],
                },
                "power_nets": {
                    "type": "array",
                    "description": (
                        "Net-name fragments treated as high-current and pulled "
                        "short & direct (case-insensitive substring match). "
                        "Defaults to common power rails (VBAT, VBUS, VCC, 3V3, "
                        "5V, ...). Pass [] to disable power weighting."
                    ),
                    "items": {"type": "string"},
                },
                "power_weight": {
                    "type": "number",
                    "description": "Pull multiplier for power nets (default 3.0).",
                    "default": 3.0,
                },
                "decoupling_boost": {
                    "type": "number",
                    "description": (
                        "Extra pull for 2-pin-passive <-> multi-pin-IC links so "
                        "caps / feedback parts hug their IC (default 2.0)."
                    ),
                    "default": 2.0,
                },
                "bounds": {
                    "type": "object",
                    "description": (
                        "SCOPED REGROUP: confine the MOVABLE parts to this box "
                        "(mm) — e.g. the empty area beside one IC. Combine with "
                        "`refs` (just that IC's passives) to regroup one cluster "
                        "at a time; unlisted parts stay put as anchors. Far more "
                        "reliable than a whole-board run on a dense board, which "
                        "over-packs. Default: parts may use the whole board."
                    ),
                    "properties": {
                        "x1": {"type": "number"},
                        "y1": {"type": "number"},
                        "x2": {"type": "number"},
                        "y2": {"type": "number"},
                        "unit": {
                            "type": "string",
                            "enum": ["mm", "mil", "inch"],
                            "default": "mm",
                        },
                    },
                    "required": ["x1", "y1", "x2", "y2"],
                },
                "board_outline": {
                    "type": "object",
                    "description": (
                        "Optional override for the board containment bbox. "
                        "Default: derived from Edge.Cuts."
                    ),
                    "properties": {
                        "x1": {"type": "number"},
                        "y1": {"type": "number"},
                        "x2": {"type": "number"},
                        "y2": {"type": "number"},
                        "unit": {
                            "type": "string",
                            "enum": ["mm", "mil", "inch"],
                            "default": "mm",
                        },
                    },
                    "required": ["x1", "y1", "x2", "y2"],
                },
            },
        },
    },
    {
        "name": "duplicate_component",
        "title": "Duplicate Component",
        "description": "Creates a copy of an existing component with new reference designator.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sourceReference": {
                    "type": "string",
                    "description": "Reference of component to duplicate",
                },
                "newReference": {
                    "type": "string",
                    "description": "Reference designator for the new component",
                },
                "offsetX": {
                    "type": "number",
                    "description": "X offset from original position in mm",
                    "default": 0,
                },
                "offsetY": {
                    "type": "number",
                    "description": "Y offset from original position in mm",
                    "default": 0,
                },
            },
            "required": ["sourceReference", "newReference"],
        },
    },
]

# =============================================================================
# ROUTING TOOLS
# =============================================================================

ROUTING_TOOLS = [
    {
        "name": "add_net",
        "title": "Create Electrical Net",
        "description": "Creates a new electrical net for signal routing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the net (e.g., VCC, GND, SDA)",
                    "minLength": 1,
                },
                "netClass": {
                    "type": "string",
                    "description": "Optional net class to assign (must exist first)",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "route_trace",
        "title": "Route PCB Trace",
        "description": "Routes a copper trace between two points or pads on a specified layer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "netName": {"type": "string", "description": "Net name for this trace"},
                "layer": {
                    "type": "string",
                    "description": "Layer to route on (e.g., F.Cu, B.Cu)",
                    "default": "F.Cu",
                },
                "width": {
                    "type": "number",
                    "description": "Trace width in millimeters",
                    "minimum": 0.1,
                },
                "points": {
                    "type": "array",
                    "description": "Array of [x, y] waypoints in millimeters",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "minItems": 2,
                },
            },
            "required": ["points", "width"],
        },
    },
    {
        "name": "add_via",
        "title": "Add Via",
        "description": "Adds a via (plated through-hole) to connect traces between layers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "X coordinate in millimeters"},
                "y": {"type": "number", "description": "Y coordinate in millimeters"},
                "diameter": {
                    "type": "number",
                    "description": "Via diameter in millimeters",
                    "minimum": 0.1,
                },
                "drill": {
                    "type": "number",
                    "description": "Drill diameter in millimeters",
                    "minimum": 0.1,
                },
                "netName": {
                    "type": "string",
                    "description": "Net name to assign to this via",
                },
            },
            "required": ["x", "y", "diameter", "drill"],
        },
    },
    {
        "name": "delete_trace",
        "title": "Delete Trace",
        "description": "Removes traces from the board. Can delete by UUID, position, or bulk-delete all traces on a net.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "traceUuid": {
                    "type": "string",
                    "description": "UUID of a specific trace to delete",
                },
                "position": {
                    "type": "object",
                    "description": "Delete trace nearest to this position",
                    "properties": {
                        "x": {"type": "number", "description": "X coordinate"},
                        "y": {"type": "number", "description": "Y coordinate"},
                        "unit": {
                            "type": "string",
                            "enum": ["mm", "mil", "inch"],
                            "default": "mm",
                        },
                    },
                    "required": ["x", "y"],
                },
                "net": {
                    "type": "string",
                    "description": "Delete all traces on this net (bulk delete)",
                },
                "layer": {
                    "type": "string",
                    "description": "Filter by layer when using net-based deletion",
                },
                "includeVias": {
                    "type": "boolean",
                    "description": "Include vias in net-based deletion",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "query_traces",
        "title": "Query Traces",
        "description": "Queries traces on the board with optional filters by net, layer, or bounding box. Returns trace details including UUID, positions, width, and length.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "net": {
                    "type": "string",
                    "description": "Filter by net name (e.g., 'GND', 'VCC')",
                },
                "layer": {
                    "type": "string",
                    "description": "Filter by layer name (e.g., 'F.Cu', 'B.Cu')",
                },
                "boundingBox": {
                    "type": "object",
                    "description": "Filter by bounding box region",
                    "properties": {
                        "x1": {"type": "number", "description": "Left X coordinate"},
                        "y1": {"type": "number", "description": "Top Y coordinate"},
                        "x2": {"type": "number", "description": "Right X coordinate"},
                        "y2": {"type": "number", "description": "Bottom Y coordinate"},
                        "unit": {
                            "type": "string",
                            "enum": ["mm", "mil", "inch"],
                            "default": "mm",
                        },
                    },
                },
                "includeVias": {
                    "type": "boolean",
                    "description": "Include vias in the result",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "query_zones",
        "title": "Query Zones",
        "description": "Queries copper zones (filled pours) on the board with optional filters by net, layer, or bounding box. Returns one entry per zone with net, layers, priority, fill state, and bounding box. Useful for auditing power planes and GND pours, which 'query_traces' does not include.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "net": {
                    "type": "string",
                    "description": "Filter by net name (e.g., 'GND', '+3V3')",
                },
                "layer": {
                    "type": "string",
                    "description": "Filter by layer name (e.g., 'In1.Cu', 'B.Cu'). Matches zones that include this layer in their layer set.",
                },
                "boundingBox": {
                    "type": "object",
                    "description": "Filter to zones whose bounding box overlaps this region",
                    "properties": {
                        "x1": {"type": "number", "description": "Left X coordinate"},
                        "y1": {"type": "number", "description": "Top Y coordinate"},
                        "x2": {"type": "number", "description": "Right X coordinate"},
                        "y2": {"type": "number", "description": "Bottom Y coordinate"},
                        "unit": {
                            "type": "string",
                            "enum": ["mm", "mil", "inch"],
                            "default": "mm",
                        },
                    },
                },
            },
        },
    },
    {
        "name": "add_gnd_stitching_vias",
        "title": "Add GND Stitching Vias",
        "description": (
            "Drop GND stitching vias across the board with collision "
            "checking against every non-GND segment, via, and pad on "
            "every copper layer (PTH vias penetrate the full stackup, "
            "so missing one layer is the classic silent-short failure "
            "mode that other GND-stitching tools have). Combines three "
            "strategies: a regular `grid` across the interior, "
            "`around_refs` (densify around named ICs like an MCU or "
            "switching regulator), and `in_zones` (only place vias "
            "where they actually land on a GND copper zone so they "
            "stitch real polygons together rather than floating on "
            "silkscreen). Supports `dryRun` to preview placements "
            "without writing to the board. "
            "Approach ported from morningfire-pcb-automation "
            "(https://github.com/NiNjA-CodE/morningfire-pcb-automation, "
            "scripts/ground/add_gnd_vias.py); this version reads "
            "obstacles via the pcbnew API (handles rotation, picks up "
            "net classes, integrates with the live in-memory board) "
            "and adds the in-zones strategy + maxVias cap + dry-run."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "gndNet": {
                    "type": "string",
                    "description": (
                        "Name of the ground net (default: auto-detect "
                        "GND / GROUND / VSS / /GND)."
                    ),
                },
                "strategies": {
                    "type": "array",
                    "description": (
                        "Which placement strategies to combine (default: "
                        "['grid']). Pass ['grid', 'around_refs', "
                        "'in_zones'] for full coverage."
                    ),
                    "items": {
                        "type": "string",
                        "enum": ["grid", "around_refs", "in_zones"],
                    },
                },
                "viaSize": {
                    "type": "number",
                    "description": "Via pad diameter in mm (default 0.6).",
                    "default": 0.6,
                },
                "viaDrill": {
                    "type": "number",
                    "description": (
                        "Via drill diameter in mm (default 0.3). " "Must be smaller than viaSize."
                    ),
                    "default": 0.3,
                },
                "clearance": {
                    "type": "number",
                    "description": (
                        "Extra clearance beyond required between each new "
                        "via and existing copper, in mm. Default 0.2."
                    ),
                    "default": 0.2,
                },
                "spacing": {
                    "type": "number",
                    "description": (
                        "Grid spacing in mm for the `grid` and "
                        "`around_refs` strategies. Default 5.0."
                    ),
                    "default": 5.0,
                },
                "densifyRefs": {
                    "type": "array",
                    "description": (
                        "Reference designators to densify ground around "
                        "(used by `around_refs` strategy). Good targets: "
                        "MCUs, switching regulators, RF parts."
                    ),
                    "items": {"type": "string"},
                },
                "densifyRadius": {
                    "type": "integer",
                    "description": (
                        "How many grid cells around each ref to try "
                        "(default 2 = 5x5 candidate field per ref)."
                    ),
                    "default": 2,
                },
                "edgeMargin": {
                    "type": "number",
                    "description": ("Keep-out from the board edge in mm. Default 0.5."),
                    "default": 0.5,
                },
                "maxVias": {
                    "type": "integer",
                    "description": (
                        "Cap on total placements across all strategies "
                        "(default unlimited). Useful when iterating."
                    ),
                },
                "dryRun": {
                    "type": "boolean",
                    "description": (
                        "If true, return the placements that would be "
                        "made but don't modify the board. Default false."
                    ),
                    "default": False,
                },
            },
        },
    },
    {
        "name": "modify_trace",
        "title": "Modify Trace",
        "description": "Modifies properties of an existing trace. Find trace by UUID or position, then change width, layer, or net assignment.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "traceUuid": {
                    "type": "string",
                    "description": "UUID of the trace to modify",
                },
                "position": {
                    "type": "object",
                    "description": "Find trace nearest to this position",
                    "properties": {
                        "x": {"type": "number", "description": "X coordinate"},
                        "y": {"type": "number", "description": "Y coordinate"},
                        "unit": {
                            "type": "string",
                            "enum": ["mm", "mil", "inch"],
                            "default": "mm",
                        },
                    },
                    "required": ["x", "y"],
                },
                "width": {"type": "number", "description": "New trace width in mm"},
                "layer": {
                    "type": "string",
                    "description": "New layer name (e.g., 'F.Cu', 'B.Cu')",
                },
                "net": {"type": "string", "description": "New net name to assign"},
            },
        },
    },
    {
        "name": "copy_routing_pattern",
        "title": "Copy Routing Pattern",
        "description": "Copies routing pattern from source components to target components. Enables routing replication between identical component groups by calculating and applying position offset.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sourceRefs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Source component references (e.g., ['U1', 'U2', 'U3'])",
                },
                "targetRefs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target component references (e.g., ['U4', 'U5', 'U6'])",
                },
                "includeVias": {
                    "type": "boolean",
                    "description": "Include vias in the pattern copy",
                    "default": True,
                },
                "traceWidth": {
                    "type": "number",
                    "description": "Override trace width in mm (uses original if not specified)",
                },
            },
            "required": ["sourceRefs", "targetRefs"],
        },
    },
    {
        "name": "get_nets_list",
        "title": "List All Nets",
        "description": "Returns a list of all electrical nets defined on the board.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "create_netclass",
        "title": "Create Net Class",
        "description": "Defines a net class with specific routing rules (trace width, clearance, etc.).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Net class name",
                    "minLength": 1,
                },
                "traceWidth": {
                    "type": "number",
                    "description": "Default trace width in millimeters",
                    "minimum": 0.1,
                },
                "clearance": {
                    "type": "number",
                    "description": "Clearance in millimeters",
                    "minimum": 0.1,
                },
                "viaDiameter": {
                    "type": "number",
                    "description": "Via diameter in millimeters",
                },
                "viaDrill": {
                    "type": "number",
                    "description": "Via drill diameter in millimeters",
                },
            },
            "required": ["name", "traceWidth", "clearance"],
        },
    },
    {
        "name": "set_net_color",
        "title": "Set Net Color",
        "description": "Sets or clears a net's display color override (PCB editor's 'Net colors' panel). Cosmetic only — does not affect routing or design rules.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "net": {"type": "string", "description": "Name of the net"},
                "color": {
                    "type": "string",
                    "description": "Hex color, e.g. '#FF7D00'. Required unless clear is true.",
                },
                "clear": {
                    "type": "boolean",
                    "description": "If true, remove the color override and revert to the automatic/class color",
                },
            },
            "required": ["net"],
        },
    },
    {
        "name": "add_copper_pour",
        "title": "Add Copper Pour",
        "description": "Creates a copper pour/zone (typically for ground or power planes).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "net": {
                    "type": "string",
                    "description": "Net to connect this copper pour to (e.g., GND, VCC)",
                },
                "layer": {
                    "type": "string",
                    "description": "Layer for the copper pour (e.g., F.Cu, B.Cu)",
                },
                "priority": {
                    "type": "integer",
                    "description": "Pour priority (higher priorities fill first)",
                    "minimum": 0,
                    "default": 0,
                },
                "clearance": {
                    "type": "number",
                    "description": "Clearance from other objects in millimeters",
                    "minimum": 0.1,
                },
                "outline": {
                    "type": "array",
                    "description": "Array of [x, y] points defining the pour boundary",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "minItems": 3,
                },
            },
            "required": ["net", "layer", "outline"],
        },
    },
    {
        "name": "route_differential_pair",
        "title": "Route Differential Pair",
        "description": "Routes a differential signal pair with matched lengths and spacing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "positiveName": {
                    "type": "string",
                    "description": "Positive signal net name",
                },
                "negativeName": {
                    "type": "string",
                    "description": "Negative signal net name",
                },
                "layer": {"type": "string", "description": "Layer to route on"},
                "width": {
                    "type": "number",
                    "description": "Trace width in millimeters",
                },
                "gap": {
                    "type": "number",
                    "description": "Gap between traces in millimeters",
                },
                "points": {
                    "type": "array",
                    "description": "Waypoints for the pair routing",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "minItems": 2,
                },
            },
            "required": ["positiveName", "negativeName", "width", "gap", "points"],
        },
    },
]

# =============================================================================
# LIBRARY TOOLS
# =============================================================================

LIBRARY_TOOLS = [
    {
        "name": "list_libraries",
        "title": "List Footprint Libraries",
        "description": "Lists all available footprint libraries accessible to KiCAD.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_footprints",
        "title": "Search Footprints",
        "description": "Searches for footprints matching a query string across all libraries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g., '0805', 'SOIC', 'QFP')",
                    "minLength": 1,
                },
                "library": {
                    "type": "string",
                    "description": "Optional library to restrict search to",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_library_footprints",
        "title": "List Footprints in Library",
        "description": "Lists all footprints available in a specific library.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "library": {
                    "type": "string",
                    "description": "Library name (e.g., Resistor_SMD, Connector_PinHeader)",
                    "minLength": 1,
                }
            },
            "required": ["library"],
        },
    },
    {
        "name": "list_library_table",
        "title": "List Library Table Entries",
        "description": (
            "Read a sym-lib-table or fp-lib-table: nickname, type, URI and description of "
            "every registered library. Each URI is resolved through ${KIPRJMOD}, KiCad's "
            "built-in library directories (KICAD*_SYMBOL_DIR and friends), the path "
            "variables configured in kicad_common.json and the environment, and reported "
            "alongside whether the file is actually there -- which is how a stale row left "
            'over from a library migration shows itself. A (type "Table") row is flagged '
            "as an indirection, with a count of the libraries it stands for."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tableType": {
                    "type": "string",
                    "enum": ["symbol", "footprint"],
                    "default": "symbol",
                    "description": "sym-lib-table ('symbol') or fp-lib-table ('footprint')",
                },
                "scope": {
                    "type": "string",
                    "enum": ["project", "global"],
                    "default": "project",
                    "description": "Project table (needs projectPath) or KiCad's user config",
                },
                "projectPath": {
                    "type": "string",
                    "description": "Path to the .kicad_pro or its directory, for scope=project",
                },
                "tablePath": {
                    "type": "string",
                    "description": "Path to the table file itself, bypassing scope resolution",
                },
            },
        },
    },
    {
        "name": "remove_library_table_entry",
        "title": "Remove Library Table Entry",
        "description": (
            "Remove one or more entries from a sym-lib-table or fp-lib-table by nickname -- "
            "the counterpart to register_symbol_library / register_footprint_library. The "
            "table is re-parsed before it is written, so an edit that would leave it "
            "unbalanced is refused rather than saved; the write is atomic and the previous "
            "contents are kept in a sibling .mcp-backups/ directory. Use dryRun first when "
            "the target is scope='global', which every project on the machine loads. "
            'Removing a (type "Table") row unregisters every library in the table it '
            "points at, and the result says so."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tableType": {
                    "type": "string",
                    "enum": ["symbol", "footprint"],
                    "default": "symbol",
                    "description": "sym-lib-table ('symbol') or fp-lib-table ('footprint')",
                },
                "scope": {
                    "type": "string",
                    "enum": ["project", "global"],
                    "default": "project",
                    "description": "Project table (needs projectPath) or KiCad's user config",
                },
                "projectPath": {
                    "type": "string",
                    "description": "Path to the .kicad_pro or its directory, for scope=project",
                },
                "tablePath": {
                    "type": "string",
                    "description": "Path to the table file itself, bypassing scope resolution",
                },
                "libraryName": {"type": "string", "description": "Nickname to remove"},
                "libraryNames": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Several nicknames to remove in one pass",
                },
                "dryRun": {
                    "type": "boolean",
                    "default": False,
                    "description": "Report what would be removed without writing the table",
                },
            },
            # A destructive tool with no required argument can be fired with none
            # at all; at least one nickname has to be named.
            "anyOf": [{"required": ["libraryName"]}, {"required": ["libraryNames"]}],
        },
    },
    {
        "name": "set_library_table_uri",
        "title": "Repoint Library Table Entry",
        "description": (
            "Repoint an existing library-table entry at a different file, keeping its "
            "nickname, type and description. Use it to move a project onto "
            "${KIPRJMOD}-relative paths, or to follow a library that was relocated, without "
            "unregistering and re-registering it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tableType": {
                    "type": "string",
                    "enum": ["symbol", "footprint"],
                    "default": "symbol",
                    "description": "sym-lib-table ('symbol') or fp-lib-table ('footprint')",
                },
                "scope": {
                    "type": "string",
                    "enum": ["project", "global"],
                    "default": "project",
                    "description": "Project table (needs projectPath) or KiCad's user config",
                },
                "projectPath": {
                    "type": "string",
                    "description": "Path to the .kicad_pro or its directory, for scope=project",
                },
                "tablePath": {
                    "type": "string",
                    "description": "Path to the table file itself, bypassing scope resolution",
                },
                "libraryName": {
                    "type": "string",
                    "description": "Nickname of the entry to repoint",
                },
                "uri": {
                    "type": "string",
                    "description": (
                        "New URI, e.g. ${KIPRJMOD}/../FOG_components.kicad_sym. Path variables "
                        "are stored verbatim and only expanded to check the file exists."
                    ),
                },
                "dryRun": {
                    "type": "boolean",
                    "default": False,
                    "description": "Report the new URI without writing the table",
                },
            },
            "required": ["libraryName", "uri"],
        },
    },
    {
        "name": "get_footprint_info",
        "title": "Get Footprint Details",
        "description": "Retrieves detailed information about a specific footprint including pad layout, dimensions, and description.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "library": {"type": "string", "description": "Library name"},
                "footprint": {"type": "string", "description": "Footprint name"},
            },
            "required": ["library", "footprint"],
        },
    },
]

# =============================================================================
# DESIGN RULE TOOLS
# =============================================================================

DESIGN_RULE_TOOLS = [
    {
        "name": "set_design_rules",
        "title": "Set Design Rules",
        "description": "Configures board design rules including clearances, trace widths, and via sizes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "clearance": {
                    "type": "number",
                    "description": "Minimum clearance between copper in millimeters",
                    "minimum": 0.1,
                },
                "trackWidth": {
                    "type": "number",
                    "description": "Minimum track width in millimeters",
                    "minimum": 0.1,
                },
                "viaDiameter": {
                    "type": "number",
                    "description": "Minimum via diameter in millimeters",
                },
                "viaDrill": {
                    "type": "number",
                    "description": "Minimum via drill diameter in millimeters",
                },
                "microViaDiameter": {
                    "type": "number",
                    "description": "Minimum micro-via diameter in millimeters",
                },
            },
        },
    },
    {
        "name": "get_design_rules",
        "title": "Get Current Design Rules",
        "description": "Retrieves the currently configured design rules from the board.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_drc",
        "title": "Run Design Rule Check",
        "description": "Executes a design rule check (DRC) on the current board and reports violations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "includeWarnings": {
                    "type": "boolean",
                    "description": "Include warnings in addition to errors",
                    "default": True,
                }
            },
        },
    },
    {
        "name": "get_drc_violations",
        "title": "Get DRC Violations",
        "description": "Returns a list of design rule violations from the most recent DRC run.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "assign_net_to_class",
        "title": "Assign Net to Class",
        "description": "Assigns an existing net to an existing net class to apply its design rules.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "net": {"type": "string", "description": "Name of the net"},
                "netClass": {"type": "string", "description": "Name of the net class"},
            },
            "required": ["net", "netClass"],
        },
    },
    {
        "name": "check_clearance",
        "title": "Check Clearance",
        "description": "Checks the measured clearance between two PCB items against the board's minimum clearance design rule.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item1": {
                    "type": "object",
                    "description": "First item: {type, id?, reference?}",
                },
                "item2": {
                    "type": "object",
                    "description": "Second item: {type, id?, reference?}",
                },
            },
            "required": ["item1", "item2"],
        },
    },
    {
        "name": "set_layer_constraints",
        "title": "Set Layer Constraints",
        "description": "Sets per-layer minimum track width, clearance, and via dimensions via a .kicad_dru custom rule.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "layer": {"type": "string", "description": "Layer name (e.g. 'F.Cu')"},
                "minTrackWidth": {
                    "type": "number",
                    "description": "Minimum track width for this layer (mm)",
                },
                "minClearance": {
                    "type": "number",
                    "description": "Minimum clearance for this layer (mm)",
                },
                "minViaDiameter": {
                    "type": "number",
                    "description": "Minimum via diameter for this layer (mm)",
                },
                "minViaDrill": {
                    "type": "number",
                    "description": "Minimum via drill size for this layer (mm)",
                },
            },
            "required": ["layer"],
        },
    },
]

# =============================================================================
# EXPORT TOOLS
# =============================================================================

EXPORT_TOOLS = [
    {
        "name": "export_gerber",
        "title": "Export Gerber Files",
        "description": "Generates Gerber files for PCB fabrication (industry standard format).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "outputDir": {
                    "type": "string",
                    "description": "Directory path for output files",
                },
                "layers": {
                    "type": "array",
                    "description": "List of layers to export (if not provided, exports all copper and mask layers)",
                    "items": {"type": "string"},
                },
                "includeDrillFiles": {
                    "type": "boolean",
                    "description": "Include drill files (Excellon format)",
                    "default": True,
                },
            },
            "required": ["outputDir"],
        },
    },
    {
        "name": "export_pdf",
        "title": "Export PDF",
        "description": "Exports the board layout as a PDF document for documentation or review.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "outputPath": {
                    "type": "string",
                    "description": "Path for output PDF file",
                },
                "layers": {
                    "type": "array",
                    "description": "Layers to include in PDF",
                    "items": {"type": "string"},
                },
                "colorMode": {
                    "type": "string",
                    "enum": ["color", "black_white"],
                    "description": "Color mode for output",
                    "default": "color",
                },
            },
            "required": ["outputPath"],
        },
    },
    {
        "name": "export_svg",
        "title": "Export SVG",
        "description": "Exports the board as Scalable Vector Graphics for documentation or web display.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "outputPath": {
                    "type": "string",
                    "description": "Path for output SVG file",
                },
                "layers": {
                    "type": "array",
                    "description": "Layers to include in SVG",
                    "items": {"type": "string"},
                },
            },
            "required": ["outputPath"],
        },
    },
    {
        "name": "export_3d",
        "title": "Export 3D Model",
        "description": "Exports a 3D model of the board in STEP or VRML format for mechanical CAD integration.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "outputPath": {
                    "type": "string",
                    "description": "Path for output 3D file",
                },
                "format": {
                    "type": "string",
                    "enum": ["step", "vrml"],
                    "description": "3D model format",
                    "default": "step",
                },
                "includeComponents": {
                    "type": "boolean",
                    "description": "Include 3D component models",
                    "default": True,
                },
            },
            "required": ["outputPath"],
        },
    },
    {
        "name": "export_bom",
        "title": "Export Bill of Materials",
        "description": "Generates a bill of materials (BOM) listing all components with references, values, and footprints.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "outputPath": {
                    "type": "string",
                    "description": "Path for output BOM file",
                },
                "format": {
                    "type": "string",
                    "enum": ["csv", "xml", "html"],
                    "description": "BOM output format",
                    "default": "csv",
                },
                "groupByValue": {
                    "type": "boolean",
                    "description": "Group components with same value together",
                    "default": True,
                },
            },
            "required": ["outputPath"],
        },
    },
]

# =============================================================================
# SCHEMATIC TOOLS
# =============================================================================

SCHEMATIC_TOOLS = [
    {
        "name": "create_schematic",
        "title": "Create New Schematic",
        "description": "Creates a new KiCAD schematic file for circuit design.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Path for the new schematic file (.kicad_sch)",
                },
                "title": {"type": "string", "description": "Schematic title"},
            },
            "required": ["filename"],
        },
    },
    {
        "name": "load_schematic",
        "title": "Load Existing Schematic",
        "description": "Opens an existing KiCAD schematic file for editing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Path to schematic file (.kicad_sch)",
                }
            },
            "required": ["filename"],
        },
    },
    {
        "name": "add_schematic_component",
        "title": "Add Component to Schematic",
        "description": "Places a symbol (resistor, capacitor, IC, etc.) on the schematic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Reference designator (e.g., R1, C2, U3)",
                },
                "symbol": {
                    "type": "string",
                    "description": "Symbol library:name (e.g., Device:R, Device:C)",
                },
                "value": {
                    "type": "string",
                    "description": "Component value (e.g., 10k, 0.1uF)",
                },
                "x": {"type": "number", "description": "X coordinate on schematic"},
                "y": {"type": "number", "description": "Y coordinate on schematic"},
            },
            "required": ["reference", "symbol", "x", "y"],
        },
    },
    {
        "name": "add_schematic_wire",
        "title": "Draw Wire Between Pins",
        "description": "Draws a wire on the schematic between two or more coordinate points. Always call get_schematic_pin_locations first to get the approximate pin coordinates, then pass them as the first and last waypoints. snapToPins (on by default) will correct any float imprecision by snapping endpoints to the exact nearest pin coordinate. To route around components, add intermediate waypoints between the start and end: e.g. [[x1,y1], [xMid,y1], [xMid,y2], [x2,y2]] routes horizontally then vertically. Intermediate waypoints are never snapped.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to schematic file",
                },
                "waypoints": {
                    "type": "array",
                    "description": "Array of [x, y] coordinates defining the wire path. First and last points are the pin locations (from get_schematic_pin_locations). Add intermediate points to route around obstacles.",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "minItems": 2,
                },
                "snapToPins": {
                    "type": "boolean",
                    "description": "When true, the first and last waypoints are snapped to the nearest schematic pin within snapTolerance mm. Intermediate waypoints are left unchanged. Enabled by default to correct float coordinate imprecision.",
                    "default": True,
                },
                "snapTolerance": {
                    "type": "number",
                    "description": "Maximum distance in mm to search for a nearby pin when snapToPins is enabled.",
                    "default": 1.0,
                },
            },
            "required": ["schematicPath", "waypoints"],
        },
    },
    {
        "name": "add_schematic_net_label",
        "title": "Add Net Label",
        "description": (
            "Add a net label to a schematic. "
            "PREFERRED: supply componentRef + pinNumber to snap the label to the exact pin endpoint — "
            "this guarantees an electrical connection. "
            "Alternatively supply position [x, y], but the coordinates must match the pin endpoint exactly "
            "(even a 0.01 mm offset breaks the connection). "
            "The response includes actual_position (coordinates actually used) and snapped_to_pin "
            "(present when a pin reference was resolved)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to schematic file",
                },
                "netName": {
                    "type": "string",
                    "description": "Name of the net (e.g., VCC, GND, SDA)",
                },
                "position": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Position [x, y] for the label. Required when componentRef/pinNumber are not given.",
                },
                "componentRef": {
                    "type": "string",
                    "description": "Component reference to snap label to (e.g. U1, R1). Use with pinNumber.",
                },
                "pinNumber": {
                    "type": "string",
                    "description": "Pin number or name on componentRef (e.g. '1', 'GND'). Use with componentRef.",
                },
                "labelType": {
                    "type": "string",
                    "enum": ["label", "global_label", "hierarchical_label"],
                    "description": "Label type (default: label)",
                    "default": "label",
                },
                "orientation": {
                    "type": "number",
                    "description": "Rotation angle in degrees (0, 90, 180, 270)",
                    "default": 0,
                },
            },
            "required": ["schematicPath", "netName"],
        },
    },
    {
        "name": "connect_to_net",
        "title": "Connect Pin to Net",
        "description": (
            "Connect a component pin to a named net by adding a wire stub and net label at the exact "
            "pin endpoint. The response includes pin_location (exact pin coords), label_location "
            "(where the label was placed), and wire_stub (the wire segment added) so you can confirm "
            "the placement without a separate verification call."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to schematic file",
                },
                "componentRef": {
                    "type": "string",
                    "description": "Component reference designator (e.g., R1, U3)",
                },
                "pinName": {
                    "type": "string",
                    "description": "Pin number or name on the component",
                },
                "netName": {
                    "type": "string",
                    "description": "Name of the net to connect to",
                },
            },
            "required": ["schematicPath", "componentRef", "pinName", "netName"],
        },
    },
    {
        "name": "get_net_connections",
        "title": "Get Net Connections",
        "description": "Returns all components and pins connected to a specified net.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to schematic file",
                },
                "netName": {
                    "type": "string",
                    "description": "Name of the net to query",
                },
            },
            "required": ["schematicPath", "netName"],
        },
    },
    {
        "name": "get_wire_connections",
        "title": "Get Wire Connections",
        "description": (
            "Returns the net name and all wires and component pins connected at a given point. "
            "Accepts either a component reference + pin number (e.g. reference='U1', pin='3') "
            "or a schematic coordinate (x, y in mm). "
            "The response includes: 'net' (label name or null for unnamed nets), "
            "'pins' (all component pins on the net), 'wires' (all wire segments on the net), "
            "and 'query_point' (the resolved coordinate used). "
            "The query point must be at a wire endpoint or junction — wire midpoints are not matched. "
            "Use get_schematic_pin_locations or list_schematic_wires to obtain exact endpoint coordinates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the schematic file (.kicad_sch)",
                },
                "reference": {
                    "type": "string",
                    "description": "Component reference (e.g. U1, R1). Pair with pin.",
                },
                "pin": {
                    "type": "string",
                    "description": "Pin number or name (e.g. '3', 'SDA'). Pair with reference.",
                },
                "x": {
                    "type": "number",
                    "description": "X coordinate of a wire endpoint in mm. Pair with y.",
                },
                "y": {
                    "type": "number",
                    "description": "Y coordinate of a wire endpoint in mm. Pair with x.",
                },
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "get_net_at_point",
        "title": "Get Net At Point",
        "description": (
            "Returns the net name at a given (x, y) coordinate in a schematic, "
            "or null if no net label or wire endpoint is present at that position. "
            "Checks net label positions first, then wire endpoints. "
            "Useful for quickly identifying what net occupies a specific coordinate "
            "without traversing the full wire graph."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the schematic file (.kicad_sch)",
                },
                "x": {
                    "type": "number",
                    "description": "X coordinate in mm",
                },
                "y": {
                    "type": "number",
                    "description": "Y coordinate in mm",
                },
            },
            "required": ["schematicPath", "x", "y"],
        },
    },
    {
        "name": "get_schematic_pin_locations",
        "title": "Get Schematic Pin Locations",
        "description": "Returns the exact absolute coordinates of all pins on a schematic component. Use this BEFORE placing net labels with add_schematic_net_label to get the correct x/y position for each pin endpoint.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the schematic file",
                },
                "reference": {
                    "type": "string",
                    "description": "Component reference designator (e.g., U1, R1, J2)",
                },
            },
            "required": ["schematicPath", "reference"],
        },
    },
    {
        "name": "connect_passthrough",
        "title": "Connect Passthrough (Pin-to-Pin)",
        "description": "Connects all pins of a source connector to the matching pins of a target connector using shared net labels. Ideal for passthrough adapters where J1 pin N connects directly to J2 pin N. Each pair gets a net label '{netPrefix}_{pinNumber}'. Use this instead of calling connect_to_net 15 times for FFC/ribbon cable passthroughs. NOTE: KiCAD Connector_Generic symbols always have pin 1 at the TOP of the symbol and pin N at the BOTTOM. When assigning named nets (e.g. GND, CAM_SCL) to specific pin numbers, always use the physical pin number as shown in the connector datasheet — pin 1 = top of symbol.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the schematic file",
                },
                "sourceRef": {
                    "type": "string",
                    "description": "Reference of the source connector (e.g., J1)",
                },
                "targetRef": {
                    "type": "string",
                    "description": "Reference of the target connector (e.g., J2)",
                },
                "netPrefix": {
                    "type": "string",
                    "description": "Prefix for generated net names, e.g. 'CSI' produces CSI_1, CSI_2, ... (default: PIN)",
                },
                "pinOffset": {
                    "type": "integer",
                    "description": "Add this value to the pin number when building net names (default: 0)",
                },
            },
            "required": ["schematicPath", "sourceRef", "targetRef"],
        },
    },
    {
        "name": "run_erc",
        "title": "Run Electrical Rules Check (ERC)",
        "description": "Runs the KiCAD Electrical Rules Check (ERC) on a schematic via kicad-cli and returns all violations with type, severity, and location. Use this to verify the schematic is electrically correct before generating a netlist or exporting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file",
                }
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "sync_schematic_to_board",
        "title": "Sync Schematic to PCB (F8)",
        "description": "Reads net connections from the schematic and assigns them to matching component pads in the PCB board file. Equivalent to KiCAD Pcbnew F8 'Update PCB from Schematic'. Must be called after placing components and before routing traces, so that pad-to-net assignments are correct.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to .kicad_sch file. If omitted, auto-detected from current board path.",
                },
                "boardPath": {
                    "type": "string",
                    "description": "Path to .kicad_pcb file. If omitted, uses currently loaded board.",
                },
            },
        },
    },
    {
        "name": "backannotate_footprints",
        "title": "Back-annotate Footprints (PCB to Schematic)",
        "description": (
            "Copy footprint assignments from a .kicad_pcb back into the schematic's "
            "Footprint fields -- the reverse of sync_schematic_to_board. After a layout "
            "pass the board is the side that is right: footprints get swapped in pcbnew, "
            "and imported projects land with schematic-side fields that never matched the "
            "placed parts. Matching is by reference designator, taken from each symbol's "
            "(instances ...) block so a sheet placed more than once contributes all of its "
            "designators; virtual references starting with '#' (power, ground) are skipped, "
            "and every unit of a multi-unit symbol is updated. Only the quoted value is "
            "rewritten, so field visibility, font and position survive. Nothing is written "
            "for a reference the board uses twice, or for instances that share one Footprint "
            "field but disagree on the board -- those are listed under 'conflicts'. "
            "Footprints on the board with no matching symbol are listed under "
            "'notInSchematic'. Instances missing a Footprint field get one added unless "
            "addMissing is false. Use dryRun to see the diff first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "boardPath": {"type": "string", "description": "Path to the .kicad_pcb file"},
                "schematicPath": {
                    "type": "string",
                    "description": (
                        "Single sheet to update. Omit to walk the sheet tree from the root "
                        "schematic named after the board, which is what a hierarchical "
                        "design needs; local history, backup copies and other projects "
                        "under the same directory are left alone."
                    ),
                },
                "references": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Limit the update to these reference designators",
                },
                "addMissing": {
                    "type": "boolean",
                    "default": True,
                    "description": "Add a Footprint field to instances that have none",
                },
                "dryRun": {
                    "type": "boolean",
                    "default": False,
                    "description": "Report the changes without writing them",
                },
            },
            "required": ["boardPath"],
        },
    },
    {
        "name": "create_board_from_schematic",
        "title": "Create Board From Schematic",
        "description": "Creates a fresh .kicad_pcb file, then updates it from the schematic so footprints and nets are present.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {"type": "string"},
                "boardPath": {"type": "string"},
                "overwrite": {"type": "boolean", "default": False},
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "generate_netlist",
        "title": "Generate Netlist (JSON)",
        "description": (
            "Returns a structured JSON netlist from the schematic: component list "
            "(reference, value, footprint) and net list (net name + all connected "
            "component/pin pairs). Uses kicad-cli internally — requires a saved "
            ".kicad_sch file. For writing to a file or exporting SPICE/Cadstar/OrcadPCB2 "
            "format, use export_netlist instead."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Absolute path to the .kicad_sch schematic file",
                },
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "list_schematic_libraries",
        "title": "List Symbol Libraries",
        "description": "Lists all available symbol libraries for schematic design.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "searchPaths": {
                    "type": "array",
                    "description": "Optional additional paths to search for libraries",
                    "items": {"type": "string"},
                }
            },
        },
    },
    {
        "name": "export_schematic_pdf",
        "title": "Export Schematic to PDF",
        "description": "Exports the schematic as a PDF document for printing or documentation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to schematic file",
                },
                "outputPath": {"type": "string", "description": "Path for output PDF"},
            },
            "required": ["schematicPath", "outputPath"],
        },
    },
    # --- Schematic Analysis Tools (read-only) ---
    {
        "name": "get_schematic_view_region",
        "title": "Get Schematic View Region",
        "description": "Exports a cropped region of the schematic as an image (PNG or SVG). Specify a bounding box in schematic mm coordinates to zoom into a specific area.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file",
                },
                "x1": {
                    "type": "number",
                    "description": "Left X coordinate of the region in mm",
                },
                "y1": {
                    "type": "number",
                    "description": "Top Y coordinate of the region in mm",
                },
                "x2": {
                    "type": "number",
                    "description": "Right X coordinate of the region in mm",
                },
                "y2": {
                    "type": "number",
                    "description": "Bottom Y coordinate of the region in mm",
                },
                "format": {
                    "type": "string",
                    "enum": ["png", "svg"],
                    "description": "Output image format (default: png)",
                },
                "width": {
                    "type": "integer",
                    "description": "Output image width in pixels (default: 800)",
                },
                "height": {
                    "type": "integer",
                    "description": "Output image height in pixels (default: 600)",
                },
            },
            "required": ["schematicPath", "x1", "y1", "x2", "y2"],
        },
    },
    {
        "name": "find_overlapping_elements",
        "title": "Find Overlapping Elements",
        "description": "Detects spatially overlapping symbols, wires, and labels in the schematic. Finds: duplicate power symbols at the same position, collinear overlapping wire segments, and labels stacked on top of each other.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file",
                },
                "tolerance": {
                    "type": "number",
                    "description": "Distance threshold in mm for label proximity and wire collinearity checks. Symbol overlap uses bounding-box intersection. (default: 0.5)",
                },
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "get_elements_in_region",
        "title": "Get Elements in Region",
        "description": "Lists all symbols, wires, and labels within a rectangular region of the schematic. Useful for understanding what is in a specific area before modifying it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file",
                },
                "x1": {
                    "type": "number",
                    "description": "Left X coordinate of the region in mm",
                },
                "y1": {
                    "type": "number",
                    "description": "Top Y coordinate of the region in mm",
                },
                "x2": {
                    "type": "number",
                    "description": "Right X coordinate of the region in mm",
                },
                "y2": {
                    "type": "number",
                    "description": "Bottom Y coordinate of the region in mm",
                },
            },
            "required": ["schematicPath", "x1", "y1", "x2", "y2"],
        },
    },
    {
        "name": "find_wires_crossing_symbols",
        "title": "Find Wires Crossing Symbols",
        "description": "Find all wires that cross over component symbol bodies. Wires passing over symbols are unacceptable in schematics — they indicate routing mistakes where a wire was drawn across a component instead of around it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file",
                }
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "find_orphaned_wires",
        "title": "Find Orphaned Wires",
        "description": (
            "Find wire segments with at least one dangling endpoint — an endpoint not connected "
            "to a component pin, net label, or another wire. "
            "Orphaned wires cause ERC 'wire end unconnected' errors and indicate routing mistakes. "
            "Does not require the KiCad UI to be running."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file",
                }
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "list_floating_labels",
        "title": "List Floating Net Labels",
        "description": (
            "Returns all net labels in the schematic that are not connected to any component pin. "
            "A label is 'floating' when no component pin's coordinate falls on the wire-network "
            "reachable from the label's anchor position. "
            "Floating labels indicate misplaced or off-grid labels that will cause ERC errors. "
            "Does not require the KiCad UI to be running."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file",
                }
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "snap_to_grid",
        "title": "Snap Schematic Elements to Grid",
        "description": (
            "Snap schematic element coordinates to the nearest grid point. "
            "KiCAD eeschema uses exact integer matching (10 000 IU/mm) for connectivity, "
            "so even a sub-pixel coordinate offset will make wires appear connected visually "
            "but fail ERC checks. Running this tool before ERC eliminates that class of error. "
            "Modifies the .kicad_sch file in place. "
            "Does not require the KiCAD UI to be running."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file",
                },
                "gridSize": {
                    "type": "number",
                    "description": (
                        "Grid spacing in mm (default: 1.27 — standard KiCAD schematic grid). "
                        "Do NOT use 2.54: half of all valid KiCAD pin positions are at odd "
                        "multiples of 1.27 mm and would be displaced 1.27 mm, breaking "
                        "connectivity."
                    ),
                    "default": 1.27,
                },
                "elements": {
                    "type": "array",
                    "description": (
                        "Element types to snap. "
                        'Valid values: "wires", "junctions", "labels", "components". '
                        'Defaults to ["wires", "junctions", "labels"] when omitted. '
                        '"components" is opt-in because moving a component without re-routing '
                        "its wires will create new mismatches."
                    ),
                    "items": {
                        "type": "string",
                        "enum": ["wires", "junctions", "labels", "components"],
                    },
                },
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "lint_offgrid",
        "title": "Lint Off-Grid Schematic Geometry",
        "description": (
            "Report every off-grid connection-relevant coordinate in a schematic — "
            "wire/bus endpoints, symbol origins, label/junction/no_connect anchors — "
            "and optionally snap them to the nearest grid point (fix=true). "
            "KiCad's connection grid is fixed at 50 mil (1.27 mm) and junction "
            "placement uses exact matching, so a single off-grid endpoint can poison "
            "junction placement for a whole sheet. Fixes are byte-exact text splices "
            "that preserve file formatting; (lib_symbols) content and property field "
            "positions are never touched. Offenders more than 0.5 mm off-grid are "
            "reported as needsHuman and never auto-snapped."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch schematic file",
                },
                "fix": {
                    "type": "boolean",
                    "description": "Snap offenders in place (default false: report only)",
                    "default": False,
                },
                "gridSize": {
                    "type": "number",
                    "description": (
                        "Grid spacing in mm (default: 1.27 = 50 mil, the KiCad " "connection grid)"
                    ),
                    "default": 1.27,
                },
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "suggest_schematic_declutter",
        "title": "Suggest Schematic Declutter",
        "description": (
            "Re-orient overlapping net/global labels so their text lands in free "
            "space and becomes readable. Each label's (at x,y) anchor is its "
            "electrical connection point, so it is held FIXED — only the "
            "orientation (0/90/180/270) and justification change, throwing the "
            "text away from component bodies and other labels. Connectivity is "
            "never altered. DRY RUN by default: returns proposals "
            "[{name, at, from_angle, to_angle}] plus an overlap score "
            "(before/after) WITHOUT modifying the schematic. Set apply=true to "
            "rewrite the label orientations. Phase 1: labels only; symbol "
            "spreading + wire reroute is a separate future capability."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch file.",
                },
                "margin": {
                    "type": "number",
                    "description": (
                        "Extra clearance in mm when testing label overlap " "(default 0.3)."
                    ),
                    "default": 0.3,
                },
                "references": {
                    "type": "array",
                    "description": (
                        "Limit which component bodies count as obstacles "
                        "(default: every component on the sheet)."
                    ),
                    "items": {"type": "string"},
                },
                "apply": {
                    "type": "boolean",
                    "description": (
                        "If true, rewrite the label orientations. Default false "
                        "(dry run — schematic untouched, proposals only)."
                    ),
                    "default": False,
                },
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "update_symbol_from_library",
        "title": "Update Symbol from Library",
        "description": (
            "Refresh embedded lib_symbols cache entries from a KiCad symbol library "
            "(equivalent to KiCad's Update Symbol from Library). Skips mirror-cache "
            "entries (__m0, __m90, …). Flattens (power) symbols for schematic format. "
            "Pass projectsDir to update all schematics in a folder, or schematicPath "
            "for one file."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectsDir": {
                    "type": "string",
                    "description": "Directory containing project subfolders with .kicad_sch files",
                },
                "schematicPath": {
                    "type": "string",
                    "description": "Single .kicad_sch file to update",
                },
                "schematicPaths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Multiple .kicad_sch files",
                },
                "libraryName": {
                    "type": "string",
                    "description": "Symbol library nickname from sym-lib-table (e.g. Device, project_lib)",
                },
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: update only these symbol names (without Library: prefix)",
                },
                "repairMirrorFromBackup": {
                    "type": "boolean",
                    "default": False,
                    "description": "Restore __m* mirror-cache lib_symbols blocks from backupDir first",
                },
                "backupDir": {
                    "type": "string",
                    "description": "Backup folder with matching .kicad_sch filenames (for repairMirrorFromBackup)",
                },
            },
            "required": ["libraryName"],
        },
    },
    {
        "name": "add_library_symbol_property",
        "title": "Add Property to Schematic Lib Symbol",
        "description": (
            "Add or update a custom property (Manufacturer, MPN, LCSC, etc.) on a "
            "symbol definition in the schematic's lib_symbols section (.kicad_sch). "
            "Note: changes live in the schematic cache only — they are overwritten by "
            "update_symbol_from_library. For permanent library-wide changes, use "
            "add_symbol_property on the .kicad_sym file first, then refresh."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {"type": "string", "description": "Path to .kicad_sch file"},
                "libraryName": {"type": "string", "description": "Symbol library nickname"},
                "symbolName": {"type": "string", "description": "Symbol name"},
                "propertyName": {"type": "string", "description": "Property name"},
                "propertyValue": {"type": "string", "description": "Property value"},
                "position": {
                    "type": "object",
                    "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                },
                "hide": {"type": "boolean", "default": False},
            },
            "required": [
                "schematicPath",
                "libraryName",
                "symbolName",
                "propertyName",
                "propertyValue",
            ],
        },
    },
    {
        "name": "add_symbol_property",
        "title": "Add Property to Library Symbol",
        "description": (
            "Add or update a custom property on a symbol in a .kicad_sym library file. "
            "The property is written on the symbol itself, not on one of its units, so "
            "multi-unit symbols are handled correctly. This makes permanent library-wide "
            "changes. After adding properties, use update_symbol_from_library to refresh "
            "schematics that reference the updated symbol."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "libraryPath": {"type": "string", "description": "Path to .kicad_sym file"},
                "symbolName": {"type": "string", "description": "Symbol name"},
                "propertyName": {"type": "string", "description": "Property name"},
                "propertyValue": {"type": "string", "description": "Property value"},
                "position": {
                    "type": "object",
                    "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                    "description": (
                        "Placement in mm. Omit to keep an existing property where it is "
                        "(new properties default to 0, 0)."
                    ),
                },
                "hide": {
                    "type": "boolean",
                    "description": (
                        "Hide the property. Omit to keep an existing property's current "
                        "visibility (new properties default to visible)."
                    ),
                },
            },
            "required": ["libraryPath", "symbolName", "propertyName", "propertyValue"],
        },
    },
    {
        "name": "set_symbol_pin_type",
        "title": "Set Pin Electrical Type in Symbol Library",
        "description": (
            "Set the electrical type (and optionally the graphic style) of pins in a "
            ".kicad_sym library, filtered by symbol, pin number, pin name, or current type. "
            "Use instead of a sed/regex pass over the library: a blind substitution also "
            "rewrites matching words inside symbol names, Descriptions and (alternate ...) "
            "pin functions, and cannot tell which symbol it is standing on. The replacement "
            "token is validated first -- KiCAD refuses to load a library containing a pin "
            "type it does not know. Typical use: imported or SnapEDA symbols arrive with "
            "every pin 'unspecified' or 'bidirectional', flooding ERC with conflicts on nets "
            "that are electrically fine. The library is replaced atomically, keeps its "
            "existing line endings, and is copied to a sibling '.mcp-backups/' first "
            "(path returned in 'backupPath'). 'changes' lists at most 200 per-pin records "
            "with 'changesTruncated' saying when it was cut; 'changeCount' always carries "
            "the true total."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "libraryPath": {"type": "string", "description": "Path to the .kicad_sym file"},
                "type": {
                    "type": "string",
                    "enum": list(PIN_TYPES),
                    "description": "New electrical type",
                },
                "style": {
                    "type": "string",
                    "enum": list(PIN_STYLES),
                    "description": "New graphic style",
                },
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Top-level symbol names to change (not unit names like "
                        "'R_0402_1_1'). Omit to change every symbol in the library."
                    ),
                },
                "pinNumbers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only pins with these numbers",
                },
                "pinNames": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only pins with these names",
                },
                "fromType": {
                    "type": "string",
                    "enum": list(PIN_TYPES),
                    "description": (
                        "Only pins currently of this type -- the safe way to do a bulk fix"
                    ),
                },
                "dryRun": {
                    "type": "boolean",
                    "default": False,
                    "description": "Report what would change without writing",
                },
            },
            "required": ["libraryPath"],
        },
    },
    {
        "name": "find_duplicate_symbols",
        "title": "Find Duplicate Symbols in a Library",
        "description": (
            "Group symbols in a .kicad_sym that are the same part stored twice under "
            "different names -- the residue of Eagle imports, SnapEDA downloads and parts "
            "re-added because search did not find the existing name. KiCad reports nothing "
            "here, because the names differ, which is also why grepping does not find it. "
            "Matches on manufacturer part number (tolerating the inconsistent property "
            "naming real libraries have: MPN, MP, 'MANUFACTURER PART NUMBER', 'PART "
            "NUMBER'), on distributor part number, on Value+Footprint, on an identical "
            "drawn body, or on near-identical names. Pass schematicPaths to count how many "
            "instances each duplicate actually has, which turns the report into a decision: "
            "the one nothing places is the one to retire."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "libraryPath": {"type": "string", "description": "Path to the .kicad_sym file"},
                "matchBy": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(DUPLICATE_STRATEGIES)},
                    "default": list(DEFAULT_DUPLICATE_STRATEGIES),
                    "description": (
                        "How to decide two symbols are the same part. 'graphics' is off by "
                        "default: every resistor in a library shares one body, so on "
                        "passives it groups the whole family. 'name' is off by default "
                        "because matching names that differ only in separators is the "
                        "weakest signal here. Values that only mark a field as unfilled "
                        "(N/A, TBD, -, ~) are never used as a key."
                    ),
                },
                "schematicPaths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        ".kicad_sch files or directories to scan for usage counts. "
                        "Directories are searched recursively, skipping autosave sheets "
                        "and backup/history folders, which are copies of sheets already "
                        "being counted. Only placements of THIS library are counted (see "
                        "libraryNicknames), and a sub-sheet instantiated more than once "
                        "counts once per instantiation. Paths that do not exist come back "
                        "in missingPaths rather than being silently ignored."
                    ),
                },
                "libraryNicknames": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "The nickname(s) this library is registered under in a lib_id, if "
                        "the file stem and the sym-lib-table entries beside the scanned "
                        "sheets do not cover it. Placements naming another library are not "
                        "counted: a bare 'R' here is not Device:R. The result reports the "
                        "nicknames used (libraryNicknames) and the ones actually found in "
                        "the sheets (nicknamesSeen)."
                    ),
                },
                "minGroupSize": {
                    "type": "integer",
                    "default": 2,
                    "description": "Only report groups with at least this many symbols",
                },
                "ignoreCase": {
                    "type": "boolean",
                    "default": True,
                    "description": "Compare part numbers and values case-insensitively",
                },
            },
            "required": ["libraryPath"],
        },
    },
    {
        "name": "replace_instance_lib_ids",
        "title": "Replace Instance lib_ids (Library Migration)",
        "description": (
            "Replace lib_id references in schematic symbol instances per an explicit "
            "old-to-new mapping — the mechanical layer of a library migration (e.g. "
            "eagle_import symbols to curated library symbols). Mirror-variant "
            "suffixes (__m0/__m90/__m180/__m270) get automatic angle correction; "
            "each needs its own mapping entry. Only instances are rewritten; the "
            "lib_symbols section is preserved (use update_symbol_from_library to "
            "refresh definitions afterwards)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {
                    "type": "string",
                    "description": "Path to the .kicad_sch file",
                },
                "mapping": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": (
                        "Map of old full lib_id to new full lib_id, e.g. "
                        '{"eagle_import:C_100n": "Device:C"}. Values are used verbatim.'
                    ),
                },
                "sourceLibrary": {
                    "type": "string",
                    "description": "Library prefix whose instances are candidates",
                    "default": "eagle_import",
                },
            },
            "required": ["schematicPath", "mapping"],
        },
    },
]

# =============================================================================
# UI/PROCESS TOOLS
# =============================================================================

UI_TOOLS = [
    {
        "name": "get_backend_state",
        "title": "Get Backend State",
        "description": ("Returns backend, realtime, loaded project/board paths, and dirty state."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_kicad_ui",
        "title": "Check KiCAD UI Status",
        "description": "Checks if KiCAD user interface is currently running and returns process information.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "launch_kicad_ui",
        "title": "Launch KiCAD Application",
        "description": "Opens the KiCAD graphical user interface, optionally with a specific project loaded.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectPath": {
                    "type": "string",
                    "description": "Optional path to project file to open in UI",
                },
                "autoLaunch": {
                    "type": "boolean",
                    "description": "Whether to automatically launch if not running",
                    "default": True,
                },
            },
        },
    },
]

# =============================================================================
# VALIDATION TOOLS
# =============================================================================

VALIDATION_TOOLS = [
    {
        "name": "validate_schematic",
        "title": "Validate Schematic File",
        "description": (
            "Check that a .kicad_sch file is structurally sound, reporting the line and "
            "column of every fault. kicad-cli only says whether a file loads; this says "
            "where it broke. Catches unbalanced parens, unterminated strings, trailing "
            "content, and property/effects fragments orphaned directly under (kicad_sch), "
            "which is what a truncated property rewrite leaves behind. A paren fault that "
            "nets to zero is caught too, by the first line whose indentation stops "
            "agreeing with its nesting depth. kicad-cli is then run on a throwaway copy "
            "as the authoritative answer, so the file being validated is never modified. "
            "'column' counts characters, so a tab counts once and the number will be "
            "lower than an editor's ruler shows on indented lines. Run this after any "
            "tool that edits a schematic."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematicPath": {"type": "string", "description": "Path to the .kicad_sch file"},
                "runKicadCli": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "Confirm with kicad-cli on a copy. Set false for a fast "
                        "structure-only check, or when KiCad is not installed."
                    ),
                },
            },
            "required": ["schematicPath"],
        },
    },
    {
        "name": "validate_symbol_library",
        "title": "Validate Symbol Library File",
        "description": (
            "Check that a .kicad_sym file is structurally sound and will load, reporting "
            "the line and column of every fault instead of a bare 'Unable to load "
            "library'. Beyond paren/string structure it reports units whose names no "
            "longer match their symbol (a rename that missed the NAME_0_1 sub-symbols "
            "makes the whole library unloadable), (effects ...)/(at ...) fragments a "
            "truncated property rewrite left inside a (symbol ...), units that escaped "
            "their parent to the top level, and duplicate symbol names. kicad-cli is "
            "run on a throwaway copy, so the library is never modified. 'column' counts "
            "characters, so a tab counts once and the number will be lower than an "
            "editor's ruler shows on indented lines. Run this after any tool that edits "
            "a library."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "libraryPath": {"type": "string", "description": "Path to the .kicad_sym file"},
                "runKicadCli": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "Confirm with kicad-cli on a copy. Set false for a fast "
                        "structure-only check, or when KiCad is not installed."
                    ),
                },
            },
            "required": ["libraryPath"],
        },
    },
]

# =============================================================================
# DIGI-KEY TOOLS
# =============================================================================

# Credentials are read from DIGIKEY_CLIENT_ID / DIGIKEY_CLIENT_SECRET in the
# server environment and are deliberately absent from these schemas, matching
# src/tools/digikey-api.ts: an argument is recorded in the caller's transcript,
# in the MCP log, and in anything that replays the call. Keep it that way when
# extending these — tests/test_digikey.py asserts no credential-shaped property
# appears here.

_DIGIKEY_LOCALE_SCHEMA = {
    "type": "object",
    "description": (
        "Override the locale for this call. Digi-Key requires locale headers on every "
        "request -- without them a search returns 404 -- but the values are yours to "
        "pick. Defaults come from DIGIKEY_LOCALE_* or US/en/USD. The response is "
        "localized too, so lifecycle status and packaging names come back in the "
        "language requested; the tools compare ids rather than those strings."
    ),
    "properties": {
        "site": {"type": "string", "description": "Digi-Key site, e.g. US, DE, UK"},
        "language": {"type": "string", "description": "Language code, e.g. en, de"},
        "currency": {"type": "string", "description": "Currency code, e.g. USD, EUR"},
    },
}

_DIGIKEY_PACKAGING_SCHEMA = {
    "type": "string",
    "enum": ["TR", "CT", "DKR"],
    "description": (
        "Which packaging variation to quote as the headline part number: TR (tape & "
        "reel, production), CT (cut tape, prototypes), DKR (Digi-Reel). Matching "
        "handles localized packaging names."
    ),
}

DIGIKEY_TOOLS = [
    {
        "name": "digikey_test_connection",
        "title": "Test Digi-Key API Connection",
        "description": (
            "Verify that the server's Digi-Key credentials work: fetch a token and run "
            "one search. Use this first when a Digi-Key tool reports an authentication "
            "problem, since it distinguishes missing credentials from rejected ones from "
            "a locale misconfiguration. Credentials come from DIGIKEY_CLIENT_ID and "
            "DIGIKEY_CLIENT_SECRET in the server environment; they are never accepted as "
            "arguments and never appear in a response."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"locale": _DIGIKEY_LOCALE_SCHEMA},
        },
    },
    {
        "name": "digikey_search_parts",
        "title": "Search Digi-Key Parts",
        "description": (
            "Search Digi-Key by part number, manufacturer part number, or a parametric "
            "phrase ('0402 100nF 50V X7R'), returning stock, price, lifecycle status, "
            "packaging variations and the parametric table. Two details the raw API "
            "makes easy to get wrong are handled here: the Digi-Key part number lives on "
            "each packaging variation rather than on the product, so reel and cut tape "
            "have different numbers; and lifecycle is read from ProductStatus.Id rather "
            "than the status string, which is localized. Use preferPackaging to pick "
            "which variation is quoted as the headline part number."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": (
                        "Part number, MPN, or a parametric phrase such as " "'0402 100nF 50V X7R'"
                    ),
                },
                "limit": {
                    "type": "number",
                    "description": "Results to return, 1-50 (default 10)",
                },
                "offset": {
                    "type": "number",
                    "description": "Result offset for paging (default 0)",
                },
                "preferPackaging": _DIGIKEY_PACKAGING_SCHEMA,
                "locale": _DIGIKEY_LOCALE_SCHEMA,
            },
            "required": ["keywords"],
        },
    },
    {
        "name": "digikey_check_library_availability",
        "title": "Check Symbol Library Availability on Digi-Key",
        "description": (
            "Look up every symbol in a .kicad_sym on Digi-Key and report which parts are "
            "obsolete, out of stock, unfindable, or missing a part number altogether -- "
            "the check to run before a board goes to purchasing, and after inheriting a "
            "library from an import. Each symbol is searched by its distributor part "
            "number first and its manufacturer part number second, because retired "
            "Digi-Key numbers are the common failure and the MPN usually still resolves; "
            "searchByMpnFirst reverses that. Part numbers are read under any of the "
            "property spellings real libraries use (MPN, MP, 'MANUFACTURER PART NUMBER', "
            "'PART NUMBER', 'SUPPLIER PART NUMBER 1'). Budget up to two rate-limited "
            "requests per symbol -- the fallback costs a second one whenever the first "
            "term misses -- plus one token request, so raise maxSymbols deliberately."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "libraryPath": {
                    "type": "string",
                    "description": "Absolute path to the .kicad_sym library file",
                },
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Only check these symbol names (default: every symbol in the " "library)"
                    ),
                },
                "maxSymbols": {
                    "type": "number",
                    "default": 25,
                    "description": (
                        "Stop after this many symbols (default 25). Each symbol costs one "
                        "or two rate-limited API requests and the client throttles itself "
                        "between them, so a larger sweep takes minutes; raising this past "
                        "a few hundred will exhaust even the extended timeout this tool "
                        "runs under."
                    ),
                },
                "searchByMpnFirst": {
                    "type": "boolean",
                    "description": (
                        "Search by manufacturer part number before the distributor number"
                    ),
                },
                "preferPackaging": _DIGIKEY_PACKAGING_SCHEMA,
                "locale": _DIGIKEY_LOCALE_SCHEMA,
            },
            "required": ["libraryPath"],
        },
    },
]

# =============================================================================
# COMBINED TOOL SCHEMAS
# =============================================================================

TOOL_SCHEMAS: Dict[str, Any] = {}

# Combine all tool categories
for tool in (
    PROJECT_TOOLS
    + BOARD_TOOLS
    + COMPONENT_TOOLS
    + ROUTING_TOOLS
    + LIBRARY_TOOLS
    + DESIGN_RULE_TOOLS
    + EXPORT_TOOLS
    + SCHEMATIC_TOOLS
    + UI_TOOLS
    + VALIDATION_TOOLS
    + DIGIKEY_TOOLS
):
    TOOL_SCHEMAS[tool["name"]] = tool

# Total: 46 tools with comprehensive schemas
