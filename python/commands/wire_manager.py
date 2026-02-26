"""
Wire Manager for KiCad Schematics

Handles wire creation using S-expression manipulation, similar to dynamic symbol loading.
kicad-skip's wire API doesn't support creating wires with standard parameters, so we
manipulate the .kicad_sch file directly.
"""

import uuid
import logging
import math
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import sexpdata
from sexpdata import Symbol

logger = logging.getLogger('kicad_interface')


class WireManager:
    """Manage wires in KiCad schematics using S-expression manipulation"""

    @staticmethod
    def add_wire(schematic_path: Path, start_point: List[float], end_point: List[float],
                 stroke_width: float = 0, stroke_type: str = 'default') -> bool:
        """
        Add a wire to the schematic using S-expression manipulation

        Args:
            schematic_path: Path to .kicad_sch file
            start_point: [x, y] coordinates for wire start
            end_point: [x, y] coordinates for wire end
            stroke_width: Wire width (default 0 for standard)
            stroke_type: Stroke type (default, solid, dashed, etc.)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Read schematic
            with open(schematic_path, 'r', encoding='utf-8') as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Create wire S-expression
            # Format: (wire (pts (xy x1 y1) (xy x2 y2)) (stroke (width N) (type default)) (uuid ...))
            wire_sexp = [
                Symbol('wire'),
                [Symbol('pts'),
                    [Symbol('xy'), start_point[0], start_point[1]],
                    [Symbol('xy'), end_point[0], end_point[1]]
                ],
                [Symbol('stroke'),
                    [Symbol('width'), stroke_width],
                    [Symbol('type'), Symbol(stroke_type)]
                ],
                [Symbol('uuid'), str(uuid.uuid4())]
            ]

            # Find insertion point (before sheet_instances)
            sheet_instances_index = None
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and len(item) > 0 and item[0] == Symbol('sheet_instances'):
                    sheet_instances_index = i
                    break

            if sheet_instances_index is None:
                logger.error("No sheet_instances section found in schematic")
                return False

            # Insert wire before sheet_instances
            sch_data.insert(sheet_instances_index, wire_sexp)
            logger.info(f"Injected wire from {start_point} to {end_point}")

            # Write back
            with open(schematic_path, 'w', encoding='utf-8') as f:
                output = sexpdata.dumps(sch_data)
                f.write(output)

            logger.info(f"Successfully added wire to {schematic_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error adding wire: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_polyline_wire(schematic_path: Path, points: List[List[float]],
                         stroke_width: float = 0, stroke_type: str = 'default') -> bool:
        """
        Add a multi-segment wire (polyline) to the schematic

        Args:
            schematic_path: Path to .kicad_sch file
            points: List of [x, y] coordinates for each point in the path
            stroke_width: Wire width
            stroke_type: Stroke type

        Returns:
            True if successful, False otherwise
        """
        try:
            if len(points) < 2:
                logger.error("Polyline requires at least 2 points")
                return False

            # Read schematic
            with open(schematic_path, 'r', encoding='utf-8') as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Create pts list
            pts_list = [Symbol('pts')]
            for point in points:
                pts_list.append([Symbol('xy'), point[0], point[1]])

            # Create wire S-expression with multiple points
            wire_sexp = [
                Symbol('wire'),
                pts_list,
                [Symbol('stroke'),
                    [Symbol('width'), stroke_width],
                    [Symbol('type'), Symbol(stroke_type)]
                ],
                [Symbol('uuid'), str(uuid.uuid4())]
            ]

            # Find insertion point
            sheet_instances_index = None
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and len(item) > 0 and item[0] == Symbol('sheet_instances'):
                    sheet_instances_index = i
                    break

            if sheet_instances_index is None:
                logger.error("No sheet_instances section found in schematic")
                return False

            # Insert wire
            sch_data.insert(sheet_instances_index, wire_sexp)
            logger.info(f"Injected polyline wire with {len(points)} points")

            # Write back
            with open(schematic_path, 'w', encoding='utf-8') as f:
                output = sexpdata.dumps(sch_data)
                f.write(output)

            logger.info(f"Successfully added polyline wire to {schematic_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error adding polyline wire: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_label(schematic_path: Path, text: str, position: List[float],
                  label_type: str = 'label', orientation: int = 0) -> bool:
        """
        Add a net label to the schematic

        Args:
            schematic_path: Path to .kicad_sch file
            text: Label text (net name)
            position: [x, y] coordinates for label
            label_type: Type of label ('label', 'global_label', 'hierarchical_label')
            orientation: Rotation angle (0, 90, 180, 270)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Read schematic
            with open(schematic_path, 'r', encoding='utf-8') as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Create label S-expression
            # Format: (label "TEXT" (at x y angle) (effects (font (size 1.27 1.27))))
            label_sexp = [
                Symbol(label_type),
                text,
                [Symbol('at'), position[0], position[1], orientation],
                [Symbol('fields_autoplaced'), Symbol('yes')],
                [Symbol('effects'),
                    [Symbol('font'), [Symbol('size'), 1.27, 1.27]],
                    [Symbol('justify'), Symbol('left'), Symbol('bottom')]
                ],
                [Symbol('uuid'), str(uuid.uuid4())]
            ]

            # Find insertion point
            sheet_instances_index = None
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and len(item) > 0 and item[0] == Symbol('sheet_instances'):
                    sheet_instances_index = i
                    break

            if sheet_instances_index is None:
                logger.error("No sheet_instances section found in schematic")
                return False

            # Insert label
            sch_data.insert(sheet_instances_index, label_sexp)
            logger.info(f"Injected label '{text}' at {position}")

            # Write back
            with open(schematic_path, 'w', encoding='utf-8') as f:
                output = sexpdata.dumps(sch_data)
                f.write(output)

            logger.info(f"Successfully added label to {schematic_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error adding label: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_junction(schematic_path: Path, position: List[float], diameter: float = 0) -> bool:
        """
        Add a junction (connection dot) to the schematic

        Args:
            schematic_path: Path to .kicad_sch file
            position: [x, y] coordinates for junction
            diameter: Junction diameter (0 for default)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Read schematic
            with open(schematic_path, 'r', encoding='utf-8') as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Create junction S-expression
            # Format: (junction (at x y) (diameter 0) (color 0 0 0 0) (uuid ...))
            junction_sexp = [
                Symbol('junction'),
                [Symbol('at'), position[0], position[1]],
                [Symbol('diameter'), diameter],
                [Symbol('color'), 0, 0, 0, 0],
                [Symbol('uuid'), str(uuid.uuid4())]
            ]

            # Find insertion point
            sheet_instances_index = None
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and len(item) > 0 and item[0] == Symbol('sheet_instances'):
                    sheet_instances_index = i
                    break

            if sheet_instances_index is None:
                logger.error("No sheet_instances section found in schematic")
                return False

            # Insert junction
            sch_data.insert(sheet_instances_index, junction_sexp)
            logger.info(f"Injected junction at {position}")

            # Write back
            with open(schematic_path, 'w', encoding='utf-8') as f:
                output = sexpdata.dumps(sch_data)
                f.write(output)

            logger.info(f"Successfully added junction to {schematic_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error adding junction: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_no_connect(schematic_path: Path, position: List[float]) -> bool:
        """
        Add a no-connect flag to the schematic

        Args:
            schematic_path: Path to .kicad_sch file
            position: [x, y] coordinates for no-connect flag

        Returns:
            True if successful, False otherwise
        """
        try:
            # Read schematic
            with open(schematic_path, 'r', encoding='utf-8') as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Create no_connect S-expression
            # Format: (no_connect (at x y) (uuid ...))
            no_connect_sexp = [
                Symbol('no_connect'),
                [Symbol('at'), position[0], position[1]],
                [Symbol('uuid'), str(uuid.uuid4())]
            ]

            # Find insertion point
            sheet_instances_index = None
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and len(item) > 0 and item[0] == Symbol('sheet_instances'):
                    sheet_instances_index = i
                    break

            if sheet_instances_index is None:
                logger.error("No sheet_instances section found in schematic")
                return False

            # Insert no_connect
            sch_data.insert(sheet_instances_index, no_connect_sexp)
            logger.info(f"Injected no-connect at {position}")

            # Write back
            with open(schematic_path, 'w', encoding='utf-8') as f:
                output = sexpdata.dumps(sch_data)
                f.write(output)

            logger.info(f"Successfully added no-connect to {schematic_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error adding no-connect: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def create_orthogonal_path(start: List[float], end: List[float],
                              prefer_horizontal_first: bool = True) -> List[List[float]]:
        """
        Create an orthogonal (right-angle) path between two points

        Args:
            start: [x, y] start coordinates
            end: [x, y] end coordinates
            prefer_horizontal_first: If True, route horizontally first, else vertically first

        Returns:
            List of points defining the path: [start, corner, end]
        """
        x1, y1 = start
        x2, y2 = end

        if prefer_horizontal_first:
            # Route: start → (x2, y1) → end
            corner = [x2, y1]
        else:
            # Route: start → (x1, y2) → end
            corner = [x1, y2]

        # If start and end are already aligned, return direct path
        if x1 == x2 or y1 == y2:
            return [start, end]

        return [start, corner, end]


if __name__ == '__main__':
    # Test wire creation
    import sys
    sys.path.insert(0, '/home/chris/MCP/KiCAD-MCP-Server/python')

    from pathlib import Path
    import shutil

    print("=" * 80)
    print("WIRE MANAGER TEST")
    print("=" * 80)

    # Create test schematic (cross-platform temp directory)
    test_path = Path(tempfile.gettempdir()) / 'test_wire_manager.kicad_sch'
    template_path = Path('/home/chris/MCP/KiCAD-MCP-Server/python/templates/empty.kicad_sch')

    shutil.copy(template_path, test_path)
    print(f"\n✓ Created test schematic: {test_path}")

    # Test 1: Add simple wire
    print("\n[1/5] Testing simple wire creation...")
    success = WireManager.add_wire(test_path, [50.8, 50.8], [101.6, 50.8])
    print(f"  {'✓' if success else '✗'} Simple wire: {success}")

    # Test 2: Add orthogonal wire
    print("\n[2/5] Testing orthogonal wire...")
    path = WireManager.create_orthogonal_path([50.8, 60.96], [101.6, 88.9])
    print(f"  Orthogonal path: {path}")
    success = WireManager.add_polyline_wire(test_path, path)
    print(f"  {'✓' if success else '✗'} Polyline wire: {success}")

    # Test 3: Add label
    print("\n[3/5] Testing label creation...")
    success = WireManager.add_label(test_path, "VCC", [76.2, 50.8])
    print(f"  {'✓' if success else '✗'} Label: {success}")

    # Test 4: Add junction
    print("\n[4/5] Testing junction creation...")
    success = WireManager.add_junction(test_path, [76.2, 50.8])
    print(f"  {'✓' if success else '✗'} Junction: {success}")

    # Test 5: Add no-connect
    print("\n[5/5] Testing no-connect creation...")
    success = WireManager.add_no_connect(test_path, [127, 50.8])
    print(f"  {'✓' if success else '✗'} No-connect: {success}")

    # Verify with kicad-skip
    print("\n[Verification] Loading with kicad-skip...")
    try:
        from skip import Schematic
        sch = Schematic(str(test_path))
        wire_count = len(list(sch.wire)) if hasattr(sch, 'wire') else 0
        print(f"  ✓ Loaded successfully")
        print(f"  ✓ Wire count: {wire_count}")
    except Exception as e:
        print(f"  ✗ Failed: {e}")

    print("\n" + "=" * 80)
    print(f"Test schematic saved: {test_path}")
    print("Open in KiCad to verify visual appearance!")
    print("=" * 80)
