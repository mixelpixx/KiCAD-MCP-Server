"""
Resource definitions for exposing KiCAD project state via MCP

Resources follow the MCP 2025-06-18 specification, providing
read-only access to project data for LLM context.
"""

import json
import base64
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger('kicad_interface')

# =============================================================================
# RESOURCE DEFINITIONS
# =============================================================================

RESOURCE_DEFINITIONS = [
    {
        "uri": "kicad://project/current/info",
        "name": "Current Project Information",
        "description": "Metadata about the currently open KiCAD project including paths, name, and status",
        "mimeType": "application/json"
    },
    {
        "uri": "kicad://project/current/board",
        "name": "Board Properties",
        "description": "Comprehensive board information including dimensions, layer count, and design rules",
        "mimeType": "application/json"
    },
    {
        "uri": "kicad://project/current/components",
        "name": "Component List",
        "description": "List of all components on the board with references, footprints, values, and positions",
        "mimeType": "application/json"
    },
    {
        "uri": "kicad://project/current/nets",
        "name": "Electrical Nets",
        "description": "List of all electrical nets and their connections",
        "mimeType": "application/json"
    },
    {
        "uri": "kicad://project/current/layers",
        "name": "Layer Stack",
        "description": "Board layer configuration and properties",
        "mimeType": "application/json"
    },
    {
        "uri": "kicad://project/current/design-rules",
        "name": "Design Rules",
        "description": "Current design rule settings for clearances, track widths, and constraints",
        "mimeType": "application/json"
    },
    {
        "uri": "kicad://project/current/drc-report",
        "name": "DRC Violations",
        "description": "Design Rule Check violations and warnings from last DRC run",
        "mimeType": "application/json"
    },
    {
        "uri": "kicad://board/preview.png",
        "name": "Board Preview Image",
        "description": "2D rendering of the current board state",
        "mimeType": "image/png"
    }
]

# =============================================================================
# RESOURCE READ HANDLERS
# =============================================================================

def handle_resource_read(uri: str, interface) -> Dict[str, Any]:
    """
    Handle reading a resource by URI

    Args:
        uri: Resource URI to read
        interface: KiCADInterface instance with access to board state

    Returns:
        Dict with resource contents following MCP spec
    """
    logger.info(f"Reading resource: {uri}")

    handlers = {
        "kicad://project/current/info": _get_project_info,
        "kicad://project/current/board": _get_board_info,
        "kicad://project/current/components": _get_components,
        "kicad://project/current/nets": _get_nets,
        "kicad://project/current/layers": _get_layers,
        "kicad://project/current/design-rules": _get_design_rules,
        "kicad://project/current/drc-report": _get_drc_report,
        "kicad://board/preview.png": _get_board_preview
    }

    handler = handlers.get(uri)
    if handler:
        try:
            return handler(interface)
        except Exception as e:
            logger.error(f"Error reading resource {uri}: {str(e)}")
            return {
                "contents": [{
                    "uri": uri,
                    "mimeType": "text/plain",
                    "text": f"Error: {str(e)}"
                }]
            }
    else:
        return {
            "contents": [{
                "uri": uri,
                "mimeType": "text/plain",
                "text": f"Unknown resource: {uri}"
            }]
        }

# =============================================================================
# INDIVIDUAL RESOURCE HANDLERS
# =============================================================================

def _get_project_info(interface) -> Dict[str, Any]:
    """Get current project information"""
    result = interface.project_commands.get_project_info({})

    if result.get("success"):
        return {
            "contents": [{
                "uri": "kicad://project/current/info",
                "mimeType": "application/json",
                "text": json.dumps(result.get("project", {}), indent=2)
            }]
        }
    else:
        return {
            "contents": [{
                "uri": "kicad://project/current/info",
                "mimeType": "text/plain",
                "text": "No project currently open"
            }]
        }

def _get_board_info(interface) -> Dict[str, Any]:
    """Get board properties and metadata"""
    result = interface.board_commands.get_board_info({})

    if result.get("success"):
        return {
            "contents": [{
                "uri": "kicad://project/current/board",
                "mimeType": "application/json",
                "text": json.dumps(result.get("board", {}), indent=2)
            }]
        }
    else:
        return {
            "contents": [{
                "uri": "kicad://project/current/board",
                "mimeType": "text/plain",
                "text": "No board currently loaded"
            }]
        }

def _get_components(interface) -> Dict[str, Any]:
    """Get list of all components"""
    result = interface.component_commands.get_component_list({})

    if result.get("success"):
        components = result.get("components", [])
        return {
            "contents": [{
                "uri": "kicad://project/current/components",
                "mimeType": "application/json",
                "text": json.dumps({
                    "count": len(components),
                    "components": components
                }, indent=2)
            }]
        }
    else:
        return {
            "contents": [{
                "uri": "kicad://project/current/components",
                "mimeType": "application/json",
                "text": json.dumps({"count": 0, "components": []}, indent=2)
            }]
        }

def _get_nets(interface) -> Dict[str, Any]:
    """Get list of electrical nets"""
    result = interface.routing_commands.get_nets_list({})

    if result.get("success"):
        nets = result.get("nets", [])
        return {
            "contents": [{
                "uri": "kicad://project/current/nets",
                "mimeType": "application/json",
                "text": json.dumps({
                    "count": len(nets),
                    "nets": nets
                }, indent=2)
            }]
        }
    else:
        return {
            "contents": [{
                "uri": "kicad://project/current/nets",
                "mimeType": "application/json",
                "text": json.dumps({"count": 0, "nets": []}, indent=2)
            }]
        }

def _get_layers(interface) -> Dict[str, Any]:
    """Get layer stack information"""
    result = interface.board_commands.get_layer_list({})

    if result.get("success"):
        layers = result.get("layers", [])
        return {
            "contents": [{
                "uri": "kicad://project/current/layers",
                "mimeType": "application/json",
                "text": json.dumps({
                    "count": len(layers),
                    "layers": layers
                }, indent=2)
            }]
        }
    else:
        return {
            "contents": [{
                "uri": "kicad://project/current/layers",
                "mimeType": "application/json",
                "text": json.dumps({"count": 0, "layers": []}, indent=2)
            }]
        }

def _get_design_rules(interface) -> Dict[str, Any]:
    """Get design rule settings"""
    result = interface.design_rule_commands.get_design_rules({})

    if result.get("success"):
        return {
            "contents": [{
                "uri": "kicad://project/current/design-rules",
                "mimeType": "application/json",
                "text": json.dumps(result.get("rules", {}), indent=2)
            }]
        }
    else:
        return {
            "contents": [{
                "uri": "kicad://project/current/design-rules",
                "mimeType": "text/plain",
                "text": "Design rules not available"
            }]
        }

def _get_drc_report(interface) -> Dict[str, Any]:
    """Get DRC violations"""
    result = interface.design_rule_commands.get_drc_violations({})

    if result.get("success"):
        violations = result.get("violations", [])
        return {
            "contents": [{
                "uri": "kicad://project/current/drc-report",
                "mimeType": "application/json",
                "text": json.dumps({
                    "count": len(violations),
                    "violations": violations
                }, indent=2)
            }]
        }
    else:
        return {
            "contents": [{
                "uri": "kicad://project/current/drc-report",
                "mimeType": "application/json",
                "text": json.dumps({
                    "count": 0,
                    "violations": [],
                    "message": "Run DRC first to get violations"
                }, indent=2)
            }]
        }

def _get_board_preview(interface) -> Dict[str, Any]:
    """Get board preview as PNG image"""
    result = interface.board_commands.get_board_2d_view({"width": 800, "height": 600})

    if result.get("success") and "imageData" in result:
        # Image data should already be base64 encoded
        image_data = result.get("imageData", "")
        return {
            "contents": [{
                "uri": "kicad://board/preview.png",
                "mimeType": "image/png",
                "blob": image_data  # Base64 encoded PNG
            }]
        }
    else:
        # Return a placeholder message
        return {
            "contents": [{
                "uri": "kicad://board/preview.png",
                "mimeType": "text/plain",
                "text": "Board preview not available"
            }]
        }
