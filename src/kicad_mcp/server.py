"""The KiCAD MCP server — pure Python, MCP SDK v2.

A tool call is a function call: SDK -> typed toolset function -> command
router -> KiCAD (SWIG / IPC / kicad-cli / schematic files). No TypeScript, no
subprocess, no JSON-over-stdio plumbing.
"""

import logging
from typing import Optional

from mcp.server import MCPServer

from kicad_mcp import __version__, registry
from kicad_mcp.config import ServerConfig, load_config
from kicad_mcp.stdio_guard import install_stdio_guard

logger = logging.getLogger("kicad_interface")

INSTRUCTIONS = (
    "AI-assisted PCB design with KiCAD. Use tools to create projects, design "
    "boards, place components, route traces, and export manufacturing files. "
    "Schematic tools edit .kicad_sch files directly; board tools use the "
    "running KiCAD (IPC) or the SWIG API; exports and checks use kicad-cli."
)


def build_server() -> MCPServer:
    """Construct the server with every toolset, resource and prompt registered."""
    mcp = MCPServer(
        name="kicad-mcp-server",
        title="KiCAD PCB Design Assistant",
        version=__version__,
        instructions=INSTRUCTIONS,
    )
    count = registry.register_all(mcp)
    logger.info(f"Registered {count} tools")

    from kicad_mcp.resources.mcp_resources import register_resources
    from kicad_mcp.prompts import register_prompts

    register_resources(mcp)
    register_prompts(mcp)
    return mcp


def main(argv: Optional[list] = None) -> None:
    config: ServerConfig = load_config(argv)
    if config.transport == "stdio":
        # Must happen before the transport wraps sys.stdout and before any
        # tool call imports pcbnew: C-level noise goes to stderr, the wire
        # stays clean.
        install_stdio_guard()
        build_server().run()
    else:
        build_server().run(
            transport="streamable-http",
            host=config.host,
            port=config.port,
        )


if __name__ == "__main__":
    main()
