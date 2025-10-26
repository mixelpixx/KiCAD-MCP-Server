"""
Board-related command implementations for KiCAD interface

This file is maintained for backward compatibility.
It imports and re-exports the BoardCommands class from the board package.
"""

from commands.board import BoardCommands

# Re-export the BoardCommands class for backward compatibility
__all__ = ['BoardCommands']
