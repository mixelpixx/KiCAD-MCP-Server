"""
Board-related command implementations for KiCAD interface
"""

import pcbnew
import logging
from typing import Dict, Any, Optional

# Import specialized modules
from .size import BoardSizeCommands
from .layers import BoardLayerCommands
from .outline import BoardOutlineCommands
from .view import BoardViewCommands

logger = logging.getLogger('kicad_interface')

class BoardCommands:
    """Handles board-related KiCAD operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board
        
        # Initialize specialized command classes
        self.size_commands = BoardSizeCommands(board)
        self.layer_commands = BoardLayerCommands(board)
        self.outline_commands = BoardOutlineCommands(board)
        self.view_commands = BoardViewCommands(board)
    
    # Delegate board size commands
    def set_board_size(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Set the size of the PCB board"""
        self.size_commands.board = self.board
        return self.size_commands.set_board_size(params)
    
    # Delegate layer commands
    def add_layer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new layer to the PCB"""
        self.layer_commands.board = self.board
        return self.layer_commands.add_layer(params)
    
    def set_active_layer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Set the active layer for PCB operations"""
        self.layer_commands.board = self.board
        return self.layer_commands.set_active_layer(params)
    
    def get_layer_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a list of all layers in the PCB"""
        self.layer_commands.board = self.board
        return self.layer_commands.get_layer_list(params)
    
    # Delegate board outline commands
    def add_board_outline(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a board outline to the PCB"""
        self.outline_commands.board = self.board
        return self.outline_commands.add_board_outline(params)
    
    def add_mounting_hole(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a mounting hole to the PCB"""
        self.outline_commands.board = self.board
        return self.outline_commands.add_mounting_hole(params)
    
    def add_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add text annotation to the PCB"""
        self.outline_commands.board = self.board
        return self.outline_commands.add_text(params)
    
    # Delegate view commands
    def get_board_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get information about the current board"""
        self.view_commands.board = self.board
        return self.view_commands.get_board_info(params)
    
    def get_board_2d_view(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a 2D image of the PCB"""
        self.view_commands.board = self.board
        return self.view_commands.get_board_2d_view(params)
