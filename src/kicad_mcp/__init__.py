"""KiCAD MCP server — pure-Python MCP server for KiCAD PCB and schematic design.

Package layout:

- ``server``       MCP SDK app + transport selection (the entry point)
- ``registry``     registers every toolset module on the server; tool-count truth
- ``toolsets``     one module per domain; each tool is a typed function
- ``dispatch``     the command router and backend arbitration (session pinning)
- ``backends``     SWIG / IPC / kicad-cli backend implementations
- ``commands``     the command implementations the toolsets dispatch into
- ``legacy_stdio`` transition-era stdin/stdout loop for the TypeScript host
"""

__all__ = ["__version__"]

__version__ = "3.0.0b1"
