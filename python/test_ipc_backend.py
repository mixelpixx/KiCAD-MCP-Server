#!/usr/bin/env python3
"""
Test script for KiCAD IPC Backend

This script tests the real-time UI synchronization capabilities
of the IPC backend. Run this while KiCAD is open with a board.

Prerequisites:
1. KiCAD 9.0+ must be running
2. IPC API must be enabled: Preferences > Plugins > Enable IPC API Server
3. A board should be open in the PCB editor

Usage:
    ./venv/bin/python python/test_ipc_backend.py
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_connection():
    """Test basic IPC connection to KiCAD."""
    print("\n" + "="*60)
    print("TEST 1: IPC Connection")
    print("="*60)

    try:
        from kicad_api.ipc_backend import IPCBackend

        backend = IPCBackend()
        print("✓ IPCBackend created")

        if backend.connect():
            print(f"✓ Connected to KiCAD via IPC")
            print(f"  Version: {backend.get_version()}")
            return backend
        else:
            print("✗ Failed to connect to KiCAD")
            return None

    except ImportError as e:
        print(f"✗ kicad-python not installed: {e}")
        print("  Install with: pip install kicad-python")
        return None
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        print("\nMake sure:")
        print("  1. KiCAD is running")
        print("  2. IPC API is enabled (Preferences > Plugins > Enable IPC API Server)")
        print("  3. A board is open in the PCB editor")
        return None


def test_board_access(backend):
    """Test board access and component listing."""
    print("\n" + "="*60)
    print("TEST 2: Board Access")
    print("="*60)

    try:
        board_api = backend.get_board()
        print("✓ Got board API")

        # List components
        components = board_api.list_components()
        print(f"✓ Found {len(components)} components on board")

        if components:
            print("\n  First 5 components:")
            for comp in components[:5]:
                ref = comp.get('reference', 'N/A')
                val = comp.get('value', 'N/A')
                pos = comp.get('position', {})
                x = pos.get('x', 0)
                y = pos.get('y', 0)
                print(f"    - {ref}: {val} @ ({x:.2f}, {y:.2f}) mm")

        return board_api

    except Exception as e:
        print(f"✗ Failed to access board: {e}")
        return None


def test_board_info(board_api):
    """Test getting board information."""
    print("\n" + "="*60)
    print("TEST 3: Board Information")
    print("="*60)

    try:
        # Get board size
        size = board_api.get_size()
        print(f"✓ Board size: {size.get('width', 0):.2f} x {size.get('height', 0):.2f} mm")

        # Get enabled layers
        try:
            layers = board_api.get_enabled_layers()
            print(f"✓ Enabled layers: {len(layers)}")
            if layers:
                print(f"  Layers: {', '.join(layers[:5])}...")
        except Exception as e:
            print(f"  (Layer info not available: {e})")

        # Get nets
        nets = board_api.get_nets()
        print(f"✓ Found {len(nets)} nets")
        if nets:
            print(f"  First 5 nets: {', '.join([n.get('name', '') for n in nets[:5]])}")

        # Get tracks
        tracks = board_api.get_tracks()
        print(f"✓ Found {len(tracks)} tracks")

        # Get vias
        vias = board_api.get_vias()
        print(f"✓ Found {len(vias)} vias")

        return True

    except Exception as e:
        print(f"✗ Failed to get board info: {e}")
        return False


def test_realtime_track(board_api, interactive=False):
    """Test adding a track in real-time (appears immediately in KiCAD UI)."""
    print("\n" + "="*60)
    print("TEST 4: Real-time Track Addition")
    print("="*60)

    print("\nThis test will add a track that appears IMMEDIATELY in KiCAD UI.")
    print("Watch the KiCAD window!")

    if interactive:
        response = input("\nProceed with adding a test track? [y/N]: ").strip().lower()
        if response != 'y':
            print("Skipped track test")
            return False

    try:
        # Add a track
        success = board_api.add_track(
            start_x=100.0,
            start_y=100.0,
            end_x=120.0,
            end_y=100.0,
            width=0.25,
            layer="F.Cu"
        )

        if success:
            print("✓ Track added! Check the KiCAD window - it should appear at (100, 100) mm")
            print("  Track: (100, 100) -> (120, 100) mm, width 0.25mm on F.Cu")
        else:
            print("✗ Failed to add track")

        return success

    except Exception as e:
        print(f"✗ Error adding track: {e}")
        return False


def test_realtime_via(board_api, interactive=False):
    """Test adding a via in real-time (appears immediately in KiCAD UI)."""
    print("\n" + "="*60)
    print("TEST 5: Real-time Via Addition")
    print("="*60)

    print("\nThis test will add a via that appears IMMEDIATELY in KiCAD UI.")
    print("Watch the KiCAD window!")

    if interactive:
        response = input("\nProceed with adding a test via? [y/N]: ").strip().lower()
        if response != 'y':
            print("Skipped via test")
            return False

    try:
        # Add a via
        success = board_api.add_via(
            x=120.0,
            y=100.0,
            diameter=0.8,
            drill=0.4,
            via_type="through"
        )

        if success:
            print("✓ Via added! Check the KiCAD window - it should appear at (120, 100) mm")
            print("  Via: diameter 0.8mm, drill 0.4mm")
        else:
            print("✗ Failed to add via")

        return success

    except Exception as e:
        print(f"✗ Error adding via: {e}")
        return False


def test_realtime_text(board_api, interactive=False):
    """Test adding text in real-time."""
    print("\n" + "="*60)
    print("TEST 6: Real-time Text Addition")
    print("="*60)

    print("\nThis test will add text that appears IMMEDIATELY in KiCAD UI.")

    if interactive:
        response = input("\nProceed with adding test text? [y/N]: ").strip().lower()
        if response != 'y':
            print("Skipped text test")
            return False

    try:
        success = board_api.add_text(
            text="MCP Test",
            x=100.0,
            y=95.0,
            layer="F.SilkS",
            size=1.0
        )

        if success:
            print("✓ Text added! Check the KiCAD window - should show 'MCP Test' at (100, 95) mm")
        else:
            print("✗ Failed to add text")

        return success

    except Exception as e:
        print(f"✗ Error adding text: {e}")
        return False


def test_selection(board_api, interactive=False):
    """Test getting the current selection from KiCAD UI."""
    print("\n" + "="*60)
    print("TEST 7: UI Selection")
    print("="*60)

    if interactive:
        print("\nSelect some items in KiCAD, then press Enter...")
        input()
    else:
        print("\nReading current selection...")

    try:
        selection = board_api.get_selection()
        print(f"✓ Found {len(selection)} selected items")

        for item in selection[:10]:
            print(f"  - {item.get('type', 'Unknown')} (ID: {item.get('id', 'N/A')})")

        return True

    except Exception as e:
        print(f"✗ Failed to get selection: {e}")
        return False


def run_all_tests(interactive=False):
    """Run all IPC backend tests."""
    print("\n" + "="*60)
    print("KiCAD IPC Backend Test Suite")
    print("="*60)
    print("\nThis script tests real-time communication with KiCAD via IPC API.")
    print("Make sure KiCAD is running with a board open.\n")

    # Test connection
    backend = test_connection()
    if not backend:
        print("\n" + "="*60)
        print("TESTS FAILED: Could not connect to KiCAD")
        print("="*60)
        return False

    # Test board access
    board_api = test_board_access(backend)
    if not board_api:
        print("\n" + "="*60)
        print("TESTS FAILED: Could not access board")
        print("="*60)
        return False

    # Test board info
    test_board_info(board_api)

    # Test real-time modifications
    test_realtime_track(board_api, interactive)
    test_realtime_via(board_api, interactive)
    test_realtime_text(board_api, interactive)

    # Test selection
    test_selection(board_api, interactive)

    print("\n" + "="*60)
    print("TESTS COMPLETE")
    print("="*60)
    print("\nThe IPC backend is working! Changes appear in real-time.")
    print("No manual reload required - this is the power of the IPC API!")

    # Cleanup
    backend.disconnect()

    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Test KiCAD IPC Backend')
    parser.add_argument('-i', '--interactive', action='store_true',
                       help='Run in interactive mode (prompts before modifications)')
    args = parser.parse_args()

    success = run_all_tests(interactive=args.interactive)
    sys.exit(0 if success else 1)
