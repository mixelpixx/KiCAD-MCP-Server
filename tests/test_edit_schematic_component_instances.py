"""
Regression tests for edit_schematic_component newReference: must also update
the (reference "...") leaves inside the symbol's (instances) → (project) →
(path) subtree, not just the (property "Reference" "...") field.

Background
----------
A KiCad schematic stores a placed symbol's reference designator in two places:

    (symbol
        (lib_id "Device:R")
        (uuid "abcd-1234-…")
        ...
        (property "Reference" "R5"       ← visible-in-eeschema field
            (at … …)
            (effects …)
        )
        ...
        (instances
            (project "MyProject"
                (path "/sheet-uuid/symbol-uuid"
                    (reference "R5")     ← used by netlist + PCB sync
                    (unit 1)
                )
            )
        )
    )

Before the fix, `edit_schematic_component` with `newReference` updated only the
(property "Reference" ...) field. The (reference "...") inside (instances) stayed
on the old value. eeschema rendered the new ref correctly and ERC passed, but
netlist export and "Update PCB from Schematic" both read from (instances) and
silently used the OLD reference — producing destructive PCB diffs on what users
thought was a clean rename.

The fix walks the (instances) subtree after updating the property field and
replaces every (reference "OLD") leaf with (reference "NEW").
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


PLACED_RESISTOR_WITH_INSTANCES = """\
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    (property "Reference" "R1" (at 51.27 47.46 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "10k" (at 51.27 52.54 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "Resistor_SMD:R_0603_1608Metric" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Datasheet" "~" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (instances
      (project "MyProject"
        (path "/abcdef12-3456-7890-abcd-ef1234567890/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
          (reference "R1")
          (unit 1)
        )
      )
    )
  )
"""

PLACED_RESISTOR_HIERARCHICAL = """\
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    (property "Reference" "R1" (at 51.27 47.46 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "10k" (at 51.27 52.54 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "Resistor_SMD:R_0603_1608Metric" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Datasheet" "~" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (instances
      (project "MyProject"
        (path "/sheet-a-uuid/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
          (reference "R1")
          (unit 1)
        )
        (path "/sheet-b-uuid/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
          (reference "R1")
          (unit 1)
        )
      )
    )
  )
"""

PLACED_RESISTOR_NO_INSTANCES = """\
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    (property "Reference" "R1" (at 51.27 47.46 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "10k" (at 51.27 52.54 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "Resistor_SMD:R_0603_1608Metric" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Datasheet" "~" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
  )
"""


def _write_schematic(tmp_path: Path, placed_block: str) -> Path:
    """Build a minimal kicad_sch wrapper around one placed-symbol block."""
    sch = tmp_path / "test.kicad_sch"
    sch.write_text(
        "(kicad_sch\n"
        '  (version 20260101)\n'
        '  (generator "eeschema")\n'
        '  (uuid "abcdef12-3456-7890-abcd-ef1234567890")\n'
        '  (paper "A4")\n'
        '  (lib_symbols)\n'
        f"{placed_block}"
        ")\n",
        encoding="utf-8",
    )
    return sch


def _interface() -> Any:
    from kicad_interface import KiCADInterface

    iface = KiCADInterface.__new__(KiCADInterface)
    # _handle_edit_schematic_component does not require backend setup since it
    # operates on the .kicad_sch file directly via text-based editing.
    iface._update_command_handlers = MagicMock()
    return iface


@pytest.mark.unit
class TestEditSchematicComponentInstancesReference:
    """The fix: newReference must update (reference "...") inside (instances) too."""

    def test_instances_reference_updated_on_rename(self, tmp_path: Any) -> None:
        """End-to-end: rename R1→R5, both property and instances must reflect R5."""
        sch = _write_schematic(tmp_path, PLACED_RESISTOR_WITH_INSTANCES)

        result = _interface()._handle_edit_schematic_component(
            {
                "schematicPath": str(sch),
                "reference": "R1",
                "newReference": "R5",
            }
        )

        assert result["success"] is True, result
        content = sch.read_text(encoding="utf-8")

        # The visible property is updated (existing behaviour).
        assert '(property "Reference" "R5"' in content
        assert '(property "Reference" "R1"' not in content

        # The fix: the (instances) leaf is updated too. The PCB sync /
        # netlist export path reads this entry.
        assert '(reference "R5")' in content
        assert '(reference "R1")' not in content

    def test_hierarchical_multiple_paths_all_updated(self, tmp_path: Any) -> None:
        """A symbol reused across hierarchical sub-sheets has one (path) per
        instance, each with its own (reference "X"). All must be updated
        atomically — leaving any stale produces the same mismatch bug on
        only-some-of-the-instances."""
        sch = _write_schematic(tmp_path, PLACED_RESISTOR_HIERARCHICAL)

        result = _interface()._handle_edit_schematic_component(
            {
                "schematicPath": str(sch),
                "reference": "R1",
                "newReference": "R5",
            }
        )

        assert result["success"] is True, result
        content = sch.read_text(encoding="utf-8")

        # Both (path) entries inside (instances) must now show R5.
        assert content.count('(reference "R5")') == 2
        assert '(reference "R1")' not in content

    def test_no_instances_block_does_not_crash(self, tmp_path: Any) -> None:
        """Symbols saved by older KiCad versions (or partial schematics
        constructed by external tools) may not have an (instances) block.
        The rename must still succeed — the instances walk is a no-op."""
        sch = _write_schematic(tmp_path, PLACED_RESISTOR_NO_INSTANCES)

        result = _interface()._handle_edit_schematic_component(
            {
                "schematicPath": str(sch),
                "reference": "R1",
                "newReference": "R5",
            }
        )

        assert result["success"] is True, result
        content = sch.read_text(encoding="utf-8")
        assert '(property "Reference" "R5"' in content
        # No (instances) entry → no (reference …) leaves to update; the
        # property update alone is sufficient.
        assert "(instances" not in content

    def test_property_reference_not_clobbered_by_instances_pass(self, tmp_path: Any) -> None:
        """The instances-update regex must match (reference "X") specifically,
        not (property "Reference" "X"). If the regex were too loose it would
        double-substitute or, worse, leave the property field untouched after
        a separate over-eager edit. Pin the shape."""
        sch = _write_schematic(tmp_path, PLACED_RESISTOR_WITH_INSTANCES)

        _interface()._handle_edit_schematic_component(
            {
                "schematicPath": str(sch),
                "reference": "R1",
                "newReference": "R42",
            }
        )

        content = sch.read_text(encoding="utf-8")
        # property line uses (property "Reference" "X") — visible-in-eeschema
        # form, with a leading "(property" not "(reference".
        assert '(property "Reference" "R42"' in content
        # instances leaf uses (reference "X") form.
        assert '(reference "R42")' in content

    def test_other_edits_still_work_when_only_newReference_provided(
        self, tmp_path: Any
    ) -> None:
        """Verify the rename leaves other field values intact."""
        sch = _write_schematic(tmp_path, PLACED_RESISTOR_WITH_INSTANCES)

        _interface()._handle_edit_schematic_component(
            {
                "schematicPath": str(sch),
                "reference": "R1",
                "newReference": "R5",
            }
        )

        content = sch.read_text(encoding="utf-8")
        assert '(property "Value" "10k"' in content
        assert '(property "Footprint" "Resistor_SMD:R_0603_1608Metric"' in content

    def test_response_payload_reports_reference_change(self, tmp_path: Any) -> None:
        """The response payload's `updated.reference` should reflect the new
        reference, preserving the existing handler contract."""
        sch = _write_schematic(tmp_path, PLACED_RESISTOR_WITH_INSTANCES)

        result = _interface()._handle_edit_schematic_component(
            {
                "schematicPath": str(sch),
                "reference": "R1",
                "newReference": "R5",
            }
        )

        assert result["updated"]["reference"] == "R5"
