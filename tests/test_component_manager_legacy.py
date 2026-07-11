"""Legacy ComponentManager.add_component contract (issue #221, part B).

The legacy template-clone path must:
1. keep working on schematics seeded with placed ``_TEMPLATE_*`` donors
   (the template_with_symbols.kicad_sch fixture),
2. raise a clear, actionable error on schematics without donors — pointing
   at the production ``add_schematic_component`` path, and
3. never mutate the on-disk file. The removed dynamic-injection branch used
   to write ``_TEMPLATE_*`` symbols into the file mid-call and clone onto a
   locally reloaded object; callers following the normal add-then-save
   pattern then saved their stale in-memory schematic, silently losing the
   component while the injected template clutter stayed in the file.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.integration  # needs kicad-skip (real 'skip' package)

_TEMPLATE_SCH = (
    Path(__file__).parent.parent / "python" / "templates" / "template_with_symbols.kicad_sch"
)

_BLANK_SCH = """(kicad_sch (version 20260101) (generator "eeschema") (generator_version "10.0")
  (uuid 3c9f2b6e-1a2b-4c3d-8e4f-5a6b7c8d9e0f)
  (paper "A4")
  (lib_symbols)
  (sheet_instances (path "/" (page "1")))
)
"""


def _load(sch_path: Path):
    from kicad_mcp.commands.schematic import SchematicManager

    return SchematicManager.load_schematic(str(sch_path))


class TestTemplateClonePathStillWorks:
    def test_add_component_clones_from_placed_template(self):
        from kicad_mcp.commands.component_schematic import ComponentManager

        with tempfile.TemporaryDirectory() as tmp:
            sch_path = Path(tmp) / "seeded.kicad_sch"
            shutil.copy(_TEMPLATE_SCH, sch_path)
            sch = _load(sch_path)

            new_sym = ComponentManager.add_component(
                sch,
                {"type": "R", "reference": "R1", "value": "10k", "x": 100, "y": 100},
                sch_path,
            )

            assert new_sym.property.Reference.value == "R1"
            assert new_sym.property.Value.value == "10k"


class TestBlankSchematicFailsClearly:
    def test_error_names_the_production_path(self):
        from kicad_mcp.commands.component_schematic import ComponentManager

        with tempfile.TemporaryDirectory() as tmp:
            sch_path = Path(tmp) / "blank.kicad_sch"
            sch_path.write_text(_BLANK_SCH, encoding="utf-8")
            sch = _load(sch_path)

            with pytest.raises(ValueError) as exc:
                ComponentManager.add_component(
                    sch,
                    {"type": "R", "reference": "R1", "value": "10k", "x": 100, "y": 100},
                    sch_path,
                )

            msg = str(exc.value)
            assert "add_schematic_component" in msg, (
                "The template-missing error must point users at the production " f"path; got: {msg}"
            )

    def test_add_component_never_mutates_the_file(self):
        """The removed dynamic branch wrote _TEMPLATE_* symbols into the file
        mid-call. The legacy path must now be read-only with respect to disk."""
        from kicad_mcp.commands.component_schematic import ComponentManager

        with tempfile.TemporaryDirectory() as tmp:
            sch_path = Path(tmp) / "blank.kicad_sch"
            sch_path.write_text(_BLANK_SCH, encoding="utf-8")
            before = sch_path.read_text(encoding="utf-8")
            sch = _load(sch_path)

            with pytest.raises(ValueError):
                ComponentManager.add_component(
                    sch,
                    {"type": "R", "reference": "R1", "value": "10k", "x": 100, "y": 100},
                    sch_path,
                )

            after = sch_path.read_text(encoding="utf-8")
            assert after == before, "add_component must not write to the schematic file"
            assert "_TEMPLATE_" not in after
