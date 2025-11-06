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

from typing import Dict, Any

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
                    "minLength": 1
                },
                "path": {
                    "type": "string",
                    "description": "Directory path where project will be created (defaults to current working directory)"
                },
                "template": {
                    "type": "string",
                    "description": "Optional path to template board file to copy settings from"
                }
            },
            "required": ["projectName"]
        }
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
                    "description": "Path to .kicad_pro or .kicad_pcb file"
                }
            },
            "required": ["filename"]
        }
    },
    {
        "name": "save_project",
        "title": "Save Current Project",
        "description": "Saves the current board to disk. Can optionally save to a new location.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Optional new path to save the board (if not provided, saves to current location)"
                }
            }
        }
    },
    {
        "name": "get_project_info",
        "title": "Get Project Information",
        "description": "Retrieves metadata and properties of the currently open project including name, paths, and board status.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
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
                    "minimum": 1
                },
                "height": {
                    "type": "number",
                    "description": "Board height in millimeters",
                    "minimum": 1
                }
            },
            "required": ["width", "height"]
        }
    },
    {
        "name": "add_board_outline",
        "title": "Add Board Outline",
        "description": "Adds a board outline shape (rectangle, rounded rectangle, circle, or polygon) on the Edge.Cuts layer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "shape": {
                    "type": "string",
                    "enum": ["rectangle", "rounded_rectangle", "circle", "polygon"],
                    "description": "Shape type for the board outline"
                },
                "width": {
                    "type": "number",
                    "description": "Width in mm (for rectangle/rounded_rectangle)",
                    "minimum": 1
                },
                "height": {
                    "type": "number",
                    "description": "Height in mm (for rectangle/rounded_rectangle)",
                    "minimum": 1
                },
                "radius": {
                    "type": "number",
                    "description": "Radius in mm (for circle) or corner radius (for rounded_rectangle)",
                    "minimum": 0
                },
                "points": {
                    "type": "array",
                    "description": "Array of [x, y] coordinates in mm (for polygon)",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2
                    },
                    "minItems": 3
                }
            },
            "required": ["shape"]
        }
    },
    {
        "name": "add_layer",
        "title": "Add Custom Layer",
        "description": "Adds a new custom layer to the board stack (e.g., User.1, User.Comments).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "layerName": {
                    "type": "string",
                    "description": "Name of the layer to add"
                },
                "layerType": {
                    "type": "string",
                    "enum": ["signal", "power", "mixed", "jumper"],
                    "description": "Type of layer (for copper layers)"
                }
            },
            "required": ["layerName"]
        }
    },
    {
        "name": "set_active_layer",
        "title": "Set Active Layer",
        "description": "Sets the currently active layer for drawing operations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "layerName": {
                    "type": "string",
                    "description": "Name of the layer to make active (e.g., F.Cu, B.Cu, Edge.Cuts)"
                }
            },
            "required": ["layerName"]
        }
    },
    {
        "name": "get_layer_list",
        "title": "List Board Layers",
        "description": "Returns a list of all layers in the board with their properties.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_board_info",
        "title": "Get Board Information",
        "description": "Retrieves comprehensive board information including dimensions, layer count, component count, and design rules.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_board_2d_view",
        "title": "Render Board Preview",
        "description": "Generates a 2D visual representation of the current board state as a PNG image.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "width": {
                    "type": "number",
                    "description": "Image width in pixels (default: 800)",
                    "minimum": 100,
                    "default": 800
                },
                "height": {
                    "type": "number",
                    "description": "Image height in pixels (default: 600)",
                    "minimum": 100,
                    "default": 600
                }
            }
        }
    },
    {
        "name": "add_mounting_hole",
        "title": "Add Mounting Hole",
        "description": "Adds a mounting hole (non-plated through hole) at the specified position with given diameter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {
                    "type": "number",
                    "description": "X coordinate in millimeters"
                },
                "y": {
                    "type": "number",
                    "description": "Y coordinate in millimeters"
                },
                "diameter": {
                    "type": "number",
                    "description": "Hole diameter in millimeters",
                    "minimum": 0.1
                }
            },
            "required": ["x", "y", "diameter"]
        }
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
                    "minLength": 1
                },
                "x": {
                    "type": "number",
                    "description": "X coordinate in millimeters"
                },
                "y": {
                    "type": "number",
                    "description": "Y coordinate in millimeters"
                },
                "layer": {
                    "type": "string",
                    "description": "Layer name (e.g., F.SilkS, B.SilkS, F.Cu)",
                    "default": "F.SilkS"
                },
                "size": {
                    "type": "number",
                    "description": "Text size in millimeters",
                    "minimum": 0.1,
                    "default": 1.0
                },
                "thickness": {
                    "type": "number",
                    "description": "Text thickness in millimeters",
                    "minimum": 0.01,
                    "default": 0.15
                }
            },
            "required": ["text", "x", "y"]
        }
    }
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
                    "description": "Component reference designator (e.g., R1, C2, U3)"
                },
                "footprint": {
                    "type": "string",
                    "description": "Footprint library:name (e.g., Resistor_SMD:R_0805_2012Metric)"
                },
                "x": {
                    "type": "number",
                    "description": "X coordinate in millimeters"
                },
                "y": {
                    "type": "number",
                    "description": "Y coordinate in millimeters"
                },
                "rotation": {
                    "type": "number",
                    "description": "Rotation angle in degrees (0-360)",
                    "minimum": 0,
                    "maximum": 360,
                    "default": 0
                },
                "layer": {
                    "type": "string",
                    "enum": ["F.Cu", "B.Cu"],
                    "description": "Board layer (top or bottom)",
                    "default": "F.Cu"
                }
            },
            "required": ["reference", "footprint", "x", "y"]
        }
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
                    "description": "Component reference designator"
                },
                "x": {
                    "type": "number",
                    "description": "New X coordinate in millimeters"
                },
                "y": {
                    "type": "number",
                    "description": "New Y coordinate in millimeters"
                }
            },
            "required": ["reference", "x", "y"]
        }
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
                    "description": "Component reference designator"
                },
                "angle": {
                    "type": "number",
                    "description": "Rotation angle in degrees (positive = counterclockwise)"
                }
            },
            "required": ["reference", "angle"]
        }
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
                    "description": "Component reference designator"
                }
            },
            "required": ["reference"]
        }
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
                    "description": "Component reference designator"
                },
                "value": {
                    "type": "string",
                    "description": "New component value"
                },
                "footprint": {
                    "type": "string",
                    "description": "New footprint library:name"
                }
            },
            "required": ["reference"]
        }
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
                    "description": "Component reference designator"
                }
            },
            "required": ["reference"]
        }
    },
    {
        "name": "get_component_list",
        "title": "List All Components",
        "description": "Returns a list of all components on the board with their properties.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
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
                    "description": "Reference prefix (e.g., 'R' for R1, R2, R3...)"
                },
                "startNumber": {
                    "type": "integer",
                    "description": "Starting number for references",
                    "minimum": 1,
                    "default": 1
                },
                "footprint": {
                    "type": "string",
                    "description": "Footprint library:name"
                },
                "pattern": {
                    "type": "string",
                    "enum": ["grid", "circular"],
                    "description": "Array pattern type"
                },
                "count": {
                    "type": "integer",
                    "description": "Total number of components to place",
                    "minimum": 1
                },
                "startX": {
                    "type": "number",
                    "description": "Starting X coordinate in millimeters"
                },
                "startY": {
                    "type": "number",
                    "description": "Starting Y coordinate in millimeters"
                },
                "spacingX": {
                    "type": "number",
                    "description": "Horizontal spacing in mm (for grid pattern)"
                },
                "spacingY": {
                    "type": "number",
                    "description": "Vertical spacing in mm (for grid pattern)"
                },
                "radius": {
                    "type": "number",
                    "description": "Circle radius in mm (for circular pattern)"
                },
                "rows": {
                    "type": "integer",
                    "description": "Number of rows (for grid pattern)",
                    "minimum": 1
                },
                "columns": {
                    "type": "integer",
                    "description": "Number of columns (for grid pattern)",
                    "minimum": 1
                }
            },
            "required": ["referencePrefix", "footprint", "pattern", "count", "startX", "startY"]
        }
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
                    "minItems": 2
                },
                "direction": {
                    "type": "string",
                    "enum": ["horizontal", "vertical"],
                    "description": "Alignment direction"
                },
                "spacing": {
                    "type": "number",
                    "description": "Spacing between components in mm (optional, for even distribution)"
                }
            },
            "required": ["references", "direction"]
        }
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
                    "description": "Reference of component to duplicate"
                },
                "newReference": {
                    "type": "string",
                    "description": "Reference designator for the new component"
                },
                "offsetX": {
                    "type": "number",
                    "description": "X offset from original position in mm",
                    "default": 0
                },
                "offsetY": {
                    "type": "number",
                    "description": "Y offset from original position in mm",
                    "default": 0
                }
            },
            "required": ["sourceReference", "newReference"]
        }
    }
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
                "netName": {
                    "type": "string",
                    "description": "Name of the net (e.g., VCC, GND, SDA)",
                    "minLength": 1
                },
                "netClass": {
                    "type": "string",
                    "description": "Optional net class to assign (must exist first)"
                }
            },
            "required": ["netName"]
        }
    },
    {
        "name": "route_trace",
        "title": "Route PCB Trace",
        "description": "Routes a copper trace between two points or pads on a specified layer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "netName": {
                    "type": "string",
                    "description": "Net name for this trace"
                },
                "layer": {
                    "type": "string",
                    "description": "Layer to route on (e.g., F.Cu, B.Cu)",
                    "default": "F.Cu"
                },
                "width": {
                    "type": "number",
                    "description": "Trace width in millimeters",
                    "minimum": 0.1
                },
                "points": {
                    "type": "array",
                    "description": "Array of [x, y] waypoints in millimeters",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2
                    },
                    "minItems": 2
                }
            },
            "required": ["points", "width"]
        }
    },
    {
        "name": "add_via",
        "title": "Add Via",
        "description": "Adds a via (plated through-hole) to connect traces between layers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {
                    "type": "number",
                    "description": "X coordinate in millimeters"
                },
                "y": {
                    "type": "number",
                    "description": "Y coordinate in millimeters"
                },
                "diameter": {
                    "type": "number",
                    "description": "Via diameter in millimeters",
                    "minimum": 0.1
                },
                "drill": {
                    "type": "number",
                    "description": "Drill diameter in millimeters",
                    "minimum": 0.1
                },
                "netName": {
                    "type": "string",
                    "description": "Net name to assign to this via"
                }
            },
            "required": ["x", "y", "diameter", "drill"]
        }
    },
    {
        "name": "delete_trace",
        "title": "Delete Trace",
        "description": "Removes a trace or segment from the board.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "traceId": {
                    "type": "string",
                    "description": "Identifier of the trace to delete"
                }
            },
            "required": ["traceId"]
        }
    },
    {
        "name": "get_nets_list",
        "title": "List All Nets",
        "description": "Returns a list of all electrical nets defined on the board.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
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
                    "minLength": 1
                },
                "traceWidth": {
                    "type": "number",
                    "description": "Default trace width in millimeters",
                    "minimum": 0.1
                },
                "clearance": {
                    "type": "number",
                    "description": "Clearance in millimeters",
                    "minimum": 0.1
                },
                "viaDiameter": {
                    "type": "number",
                    "description": "Via diameter in millimeters"
                },
                "viaDrill": {
                    "type": "number",
                    "description": "Via drill diameter in millimeters"
                }
            },
            "required": ["name", "traceWidth", "clearance"]
        }
    },
    {
        "name": "add_copper_pour",
        "title": "Add Copper Pour",
        "description": "Creates a copper pour/zone (typically for ground or power planes).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "netName": {
                    "type": "string",
                    "description": "Net to connect this copper pour to (e.g., GND, VCC)"
                },
                "layer": {
                    "type": "string",
                    "description": "Layer for the copper pour (e.g., F.Cu, B.Cu)"
                },
                "priority": {
                    "type": "integer",
                    "description": "Pour priority (higher priorities fill first)",
                    "minimum": 0,
                    "default": 0
                },
                "clearance": {
                    "type": "number",
                    "description": "Clearance from other objects in millimeters",
                    "minimum": 0.1
                },
                "outline": {
                    "type": "array",
                    "description": "Array of [x, y] points defining the pour boundary",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2
                    },
                    "minItems": 3
                }
            },
            "required": ["netName", "layer", "outline"]
        }
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
                    "description": "Positive signal net name"
                },
                "negativeName": {
                    "type": "string",
                    "description": "Negative signal net name"
                },
                "layer": {
                    "type": "string",
                    "description": "Layer to route on"
                },
                "width": {
                    "type": "number",
                    "description": "Trace width in millimeters"
                },
                "gap": {
                    "type": "number",
                    "description": "Gap between traces in millimeters"
                },
                "points": {
                    "type": "array",
                    "description": "Waypoints for the pair routing",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2
                    },
                    "minItems": 2
                }
            },
            "required": ["positiveName", "negativeName", "width", "gap", "points"]
        }
    }
]

# =============================================================================
# LIBRARY TOOLS
# =============================================================================

LIBRARY_TOOLS = [
    {
        "name": "list_libraries",
        "title": "List Footprint Libraries",
        "description": "Lists all available footprint libraries accessible to KiCAD.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
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
                    "minLength": 1
                },
                "library": {
                    "type": "string",
                    "description": "Optional library to restrict search to"
                }
            },
            "required": ["query"]
        }
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
                    "minLength": 1
                }
            },
            "required": ["library"]
        }
    },
    {
        "name": "get_footprint_info",
        "title": "Get Footprint Details",
        "description": "Retrieves detailed information about a specific footprint including pad layout, dimensions, and description.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "library": {
                    "type": "string",
                    "description": "Library name"
                },
                "footprint": {
                    "type": "string",
                    "description": "Footprint name"
                }
            },
            "required": ["library", "footprint"]
        }
    }
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
                    "minimum": 0.1
                },
                "trackWidth": {
                    "type": "number",
                    "description": "Minimum track width in millimeters",
                    "minimum": 0.1
                },
                "viaDiameter": {
                    "type": "number",
                    "description": "Minimum via diameter in millimeters"
                },
                "viaDrill": {
                    "type": "number",
                    "description": "Minimum via drill diameter in millimeters"
                },
                "microViaD iameter": {
                    "type": "number",
                    "description": "Minimum micro-via diameter in millimeters"
                }
            }
        }
    },
    {
        "name": "get_design_rules",
        "title": "Get Current Design Rules",
        "description": "Retrieves the currently configured design rules from the board.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
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
                    "default": True
                }
            }
        }
    },
    {
        "name": "get_drc_violations",
        "title": "Get DRC Violations",
        "description": "Returns a list of design rule violations from the most recent DRC run.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
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
                "outputPath": {
                    "type": "string",
                    "description": "Directory path for output files"
                },
                "layers": {
                    "type": "array",
                    "description": "List of layers to export (if not provided, exports all copper and mask layers)",
                    "items": {"type": "string"}
                },
                "includeDrillFiles": {
                    "type": "boolean",
                    "description": "Include drill files (Excellon format)",
                    "default": True
                }
            },
            "required": ["outputPath"]
        }
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
                    "description": "Path for output PDF file"
                },
                "layers": {
                    "type": "array",
                    "description": "Layers to include in PDF",
                    "items": {"type": "string"}
                },
                "colorMode": {
                    "type": "string",
                    "enum": ["color", "black_white"],
                    "description": "Color mode for output",
                    "default": "color"
                }
            },
            "required": ["outputPath"]
        }
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
                    "description": "Path for output SVG file"
                },
                "layers": {
                    "type": "array",
                    "description": "Layers to include in SVG",
                    "items": {"type": "string"}
                }
            },
            "required": ["outputPath"]
        }
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
                    "description": "Path for output 3D file"
                },
                "format": {
                    "type": "string",
                    "enum": ["step", "vrml"],
                    "description": "3D model format",
                    "default": "step"
                },
                "includeComponents": {
                    "type": "boolean",
                    "description": "Include 3D component models",
                    "default": True
                }
            },
            "required": ["outputPath"]
        }
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
                    "description": "Path for output BOM file"
                },
                "format": {
                    "type": "string",
                    "enum": ["csv", "xml", "html"],
                    "description": "BOM output format",
                    "default": "csv"
                },
                "groupByValue": {
                    "type": "boolean",
                    "description": "Group components with same value together",
                    "default": True
                }
            },
            "required": ["outputPath"]
        }
    }
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
                    "description": "Path for the new schematic file (.kicad_sch)"
                },
                "title": {
                    "type": "string",
                    "description": "Schematic title"
                }
            },
            "required": ["filename"]
        }
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
                    "description": "Path to schematic file (.kicad_sch)"
                }
            },
            "required": ["filename"]
        }
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
                    "description": "Reference designator (e.g., R1, C2, U3)"
                },
                "symbol": {
                    "type": "string",
                    "description": "Symbol library:name (e.g., Device:R, Device:C)"
                },
                "value": {
                    "type": "string",
                    "description": "Component value (e.g., 10k, 0.1uF)"
                },
                "x": {
                    "type": "number",
                    "description": "X coordinate on schematic"
                },
                "y": {
                    "type": "number",
                    "description": "Y coordinate on schematic"
                }
            },
            "required": ["reference", "symbol", "x", "y"]
        }
    },
    {
        "name": "add_schematic_wire",
        "title": "Connect Components",
        "description": "Draws a wire connection between component pins on the schematic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "points": {
                    "type": "array",
                    "description": "Array of [x, y] waypoints for the wire",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2
                    },
                    "minItems": 2
                }
            },
            "required": ["points"]
        }
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
                    "items": {"type": "string"}
                }
            }
        }
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
                    "description": "Path to schematic file"
                },
                "outputPath": {
                    "type": "string",
                    "description": "Path for output PDF"
                }
            },
            "required": ["schematicPath", "outputPath"]
        }
    }
]

# =============================================================================
# UI/PROCESS TOOLS
# =============================================================================

UI_TOOLS = [
    {
        "name": "check_kicad_ui",
        "title": "Check KiCAD UI Status",
        "description": "Checks if KiCAD user interface is currently running and returns process information.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
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
                    "description": "Optional path to project file to open in UI"
                },
                "autoLaunch": {
                    "type": "boolean",
                    "description": "Whether to automatically launch if not running",
                    "default": True
                }
            }
        }
    }
]

# =============================================================================
# COMBINED TOOL SCHEMAS
# =============================================================================

TOOL_SCHEMAS: Dict[str, Any] = {}

# Combine all tool categories
for tool in (PROJECT_TOOLS + BOARD_TOOLS + COMPONENT_TOOLS + ROUTING_TOOLS +
             LIBRARY_TOOLS + DESIGN_RULE_TOOLS + EXPORT_TOOLS +
             SCHEMATIC_TOOLS + UI_TOOLS):
    TOOL_SCHEMAS[tool["name"]] = tool

# Total: 46 tools with comprehensive schemas
