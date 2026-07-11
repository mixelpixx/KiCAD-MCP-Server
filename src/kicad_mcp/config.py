"""Server configuration from CLI arguments and environment variables.

Environment variables (all optional):

- ``KICAD_MCP_TRANSPORT``  stdio (default) | streamable-http
- ``KICAD_MCP_HOST``       Streamable HTTP bind host (default 127.0.0.1)
- ``KICAD_MCP_PORT``       Streamable HTTP port (default 8331)
- ``KICAD_MCP_LOG_LEVEL``  Python log level (also honored by dispatch logging)
- ``KICAD_BACKEND``        auto (default) | ipc | swig  (dispatch arbitration)
"""

import argparse
import os
from dataclasses import dataclass


@dataclass
class ServerConfig:
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8331


def load_config(argv: list = None) -> ServerConfig:
    parser = argparse.ArgumentParser(
        prog="kicad-mcp-server",
        description="KiCAD MCP server (stdio or Streamable HTTP)",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=os.environ.get("KICAD_MCP_TRANSPORT", "stdio"),
        help="MCP transport (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("KICAD_MCP_HOST", "127.0.0.1"),
        help="Streamable HTTP bind host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("KICAD_MCP_PORT", "8331")),
        help="Streamable HTTP port (default: 8331)",
    )
    args = parser.parse_args(argv)
    return ServerConfig(transport=args.transport, host=args.host, port=args.port)
