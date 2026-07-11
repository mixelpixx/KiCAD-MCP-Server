"""Legacy stdin/stdout JSON-RPC loop for the TypeScript host.

This is the transition-era entry point: the TypeScript server spawns
``python/kicad_interface.py`` (now a shim) which calls :func:`main` here.
The pure-Python MCP server (``kicad_mcp.server``) replaces this path and the
loop dies with the TypeScript layer.
"""

import json
import os
import sys
import traceback
from typing import Any

from kicad_mcp import dispatch
from kicad_mcp.dispatch import KiCADInterface, _annotation_loader, logger
from kicad_mcp.resources.resource_definitions import (
    RESOURCE_DEFINITIONS,
    handle_resource_read,
)
from kicad_mcp.schemas.tool_schemas import TOOL_SCHEMAS


def _write_response(response_fd: Any, response: Any) -> None:
    """Write a JSON response to the original stdout fd.

    All response output goes through this function so that stray C-level
    writes from pcbnew (warnings, diagnostics) never corrupt the JSON
    framing seen by the TypeScript host.
    """
    payload = json.dumps(response) + "\n"
    os.write(response_fd, payload.encode("utf-8"))


def _exit_if_backendless() -> None:
    """Preserve the historical fatal-at-startup behavior for the TS host.

    dispatch no longer exits at import time (the MCP server can run without
    pcbnew), but the TypeScript host expects the old contract: no SWIG and no
    IPC means an error JSON on stdout and exit code 1.
    """
    if dispatch.IPC_REQUIRED_BUT_UNAVAILABLE:
        print(
            json.dumps(
                {
                    "success": False,
                    "message": "IPC backend requested but not available",
                    "errorDetails": (
                        "KiCAD must be running with IPC API enabled. Enable at: "
                        "Preferences > Plugins > Enable IPC API Server"
                    ),
                }
            )
        )
        sys.exit(1)
    if dispatch.PCBNEW_IMPORT_ERROR and not dispatch.USE_IPC_BACKEND:
        print(
            json.dumps(
                {
                    "success": False,
                    "message": "Failed to import pcbnew module - KiCAD Python API not found",
                    "errorDetails": dispatch.PCBNEW_IMPORT_ERROR,
                }
            )
        )
        sys.exit(1)


def main() -> None:
    """Main entry point"""
    _exit_if_backendless()

    # --- Redirect stdout so pcbnew C++ noise never reaches the TS host ---
    # Save the real stdout fd for our exclusive JSON response channel.
    _response_fd = os.dup(1)
    # Point fd 1 (C-level stdout) at stderr so that any printf / std::cout
    # output from pcbnew or other C extensions is visible in logs but does
    # NOT corrupt the JSON stream the TypeScript side is parsing.
    os.dup2(2, 1)
    # Also redirect Python-level stdout to stderr for the same reason.
    sys.stdout = sys.stderr

    logger.info("Starting KiCAD interface...")
    interface = KiCADInterface()
    # Signal to the TypeScript server that the stdin loop is live.
    _write_response(_response_fd, {"type": "ready"})

    try:
        logger.info("Processing commands from stdin...")
        # Process commands from stdin
        for line in sys.stdin:
            try:
                # Parse command
                logger.debug(f"Received input: {line.strip()}")
                command_data = json.loads(line)

                # Check if this is JSON-RPC 2.0 format
                if "jsonrpc" in command_data and command_data["jsonrpc"] == "2.0":
                    logger.info("Detected JSON-RPC 2.0 format message")
                    method = command_data.get("method")
                    params = command_data.get("params", {})
                    request_id = command_data.get("id")

                    # Handle MCP protocol methods
                    if method == "initialize":
                        logger.info("Handling MCP initialize")
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "protocolVersion": "2025-06-18",
                                "capabilities": {
                                    "tools": {"listChanged": True},
                                    "resources": {
                                        "subscribe": False,
                                        "listChanged": True,
                                    },
                                },
                                "serverInfo": {
                                    "name": "kicad-mcp-server",
                                    "title": "KiCAD PCB Design Assistant",
                                    "version": "2.1.0-alpha",
                                },
                                "instructions": "AI-assisted PCB design with KiCAD. Use tools to create projects, design boards, place components, route traces, and export manufacturing files.",
                            },
                        }
                    elif method == "tools/list":
                        logger.info("Handling MCP tools/list")
                        # Return list of available tools with proper schemas
                        tools = []
                        for cmd_name in interface.command_routes.keys():
                            if cmd_name in TOOL_SCHEMAS:
                                # Enrich the existing schema with IPC annotation data
                                # (adds description/blocking hints where the schema lacks them)
                                tool_def = _annotation_loader.enrich_schema(
                                    cmd_name, TOOL_SCHEMAS[cmd_name]
                                )
                                tools.append(tool_def)
                            else:
                                # Build a best-effort schema from IPC annotations
                                ann_desc = _annotation_loader.description(cmd_name)
                                if ann_desc:
                                    logger.debug(f"Using IPC annotation for tool: {cmd_name}")
                                else:
                                    logger.warning(f"No schema or annotation for tool: {cmd_name}")
                                tools.append(
                                    _annotation_loader.enrich_schema(
                                        cmd_name,
                                        {
                                            "name": cmd_name,
                                            "description": ann_desc or f"KiCAD command: {cmd_name}",
                                            "inputSchema": {
                                                "type": "object",
                                                "properties": {},
                                            },
                                        },
                                    )
                                )

                        logger.info(f"Returning {len(tools)} tools")
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"tools": tools},
                        }
                    elif method == "tools/call":
                        logger.info("Handling MCP tools/call")
                        tool_name = params.get("name")
                        tool_params = params.get("arguments", {})

                        # Execute the command
                        result = interface.handle_command(tool_name, tool_params)

                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
                        }
                    elif method == "resources/list":
                        logger.info("Handling MCP resources/list")
                        # Return list of available resources
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"resources": RESOURCE_DEFINITIONS},
                        }
                    elif method == "resources/read":
                        logger.info("Handling MCP resources/read")
                        resource_uri = params.get("uri")

                        if not resource_uri:
                            response = {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "error": {
                                    "code": -32602,
                                    "message": "Missing required parameter: uri",
                                },
                            }
                        else:
                            # Read the resource
                            resource_data = handle_resource_read(resource_uri, interface)

                            response = {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "result": resource_data,
                            }
                    else:
                        logger.error(f"Unknown JSON-RPC method: {method}")
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {
                                "code": -32601,
                                "message": f"Method not found: {method}",
                            },
                        }
                else:
                    # Handle legacy custom format
                    logger.info("Detected custom format message")
                    command = command_data.get("command")
                    params = command_data.get("params", {})

                    if not command:
                        logger.error("Missing command field")
                        response = {
                            "success": False,
                            "message": "Missing command",
                            "errorDetails": "The command field is required",
                        }
                    else:
                        # Handle command
                        response = interface.handle_command(command, params)

                # Send response via the clean fd (immune to pcbnew stdout noise)
                logger.debug(f"Sending response: {response}")
                _write_response(_response_fd, response)

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON input: {str(e)}")
                response = {
                    "success": False,
                    "message": "Invalid JSON input",
                    "errorDetails": str(e),
                }
                _write_response(_response_fd, response)

    except KeyboardInterrupt:
        logger.info("KiCAD interface stopped")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}\n{traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
