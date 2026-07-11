"""Integration tests for autoroute's best-of-N loop.

Mocks subprocess + pcbnew so the test verifies the orchestration without
actually invoking Freerouting or KiCad. Specifically:

  - attempts=1 preserves single-attempt behaviour (no `attempts`/
    `passSchedule` in response, no per-attempt `_best.ses` snapshotting).
  - attempts>1 runs N times and imports the highest-scoring SES.
  - One failing attempt doesn't abort the whole best-of-N run.
  - The pass schedule wraps when attempts > len(schedule).
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

from kicad_mcp.commands import freerouting as fr_mod  # noqa: E402
from kicad_mcp.commands.freerouting import FreeroutingCommands  # noqa: E402


# Synthetic SES text: a `(net ...` section with N (wire ...) inside ->
# scores as N nets, N segments (matching the scorer's expectations).
def _make_ses(num_nets, segs_per_net=2):
    chunks = []
    for i in range(num_nets):
        chunks.append(f'(net "N{i}"\n')
        for _ in range(segs_per_net):
            chunks.append("  (wire (path F.Cu 200 0 0 1 1))\n")
        chunks.append(")\n")
    return "".join(chunks)


def _stub_pcbnew(dsn_to_create=None):
    """A minimal pcbnew stub for autoroute's needs.

    ExportSpecctraDSN normally writes a file as a side effect; tests pass
    a path so the stub creates an empty placeholder file to match the
    real-world contract (the `if not os.path.isfile(dsn_path):` guard
    inside autoroute).
    """
    pcb = MagicMock(name="pcbnew_module")

    def _fake_export(_board, dsn_path, *_args, **_kw):
        # Write a placeholder DSN so the existence check passes
        with open(dsn_path, "w") as f:
            f.write("(pcb \"stub\")\n")
        return True

    pcb.ExportSpecctraDSN.side_effect = _fake_export
    pcb.ImportSpecctraSES.return_value = True
    return pcb


def _make_cmds(board_path, dsn_exists=True):
    """FreeroutingCommands with a mocked board pointing at board_path."""
    cc = FreeroutingCommands.__new__(FreeroutingCommands)
    board = MagicMock(name="board")
    board.GetFileName.return_value = str(board_path)
    board.Save.return_value = None
    tracks = MagicMock()
    tracks.__iter__ = lambda s: iter([])
    board.GetTracks.return_value = tracks
    cc.board = board
    return cc


@pytest.fixture()
def workdir(tmp_path):
    # Pretend we have an existing board file
    (tmp_path / "test.kicad_pcb").write_text("(kicad_pcb)\n")
    return tmp_path


@pytest.fixture()
def fake_jar(tmp_path):
    p = tmp_path / "freerouting.jar"
    p.write_text("not a real jar")
    return p


def _patch_exec_mode(cc):
    """Force direct (non-Docker) mode so we don't go down the docker branch."""
    cc._resolve_execution_mode = MagicMock(return_value={
        "mode": "direct", "use_docker": False,
    })


@pytest.mark.unit
def test_single_attempt_default_keeps_legacy_response_shape(workdir, fake_jar):
    """attempts=1 (or omitted): no `attempts` list in response."""
    cc = _make_cmds(workdir / "test.kicad_pcb")
    _patch_exec_mode(cc)
    ses_path = workdir / "test.ses"

    def fake_run(cmd, **kw):
        # Write a one-net SES on each subprocess call
        ses_path.write_text(_make_ses(num_nets=5))
        proc = types.SimpleNamespace(returncode=0, stdout="ok", stderr="")
        return proc

    fake_pcb = _stub_pcbnew()

    with patch.object(fr_mod, "subprocess") as sp, \
         patch.dict(sys.modules, {"pcbnew": fake_pcb}):
        sp.run.side_effect = fake_run
        sp.TimeoutExpired = TimeoutError
        out = cc.autoroute({
            "boardPath": str(workdir / "test.kicad_pcb"),
            "freeroutingJar": str(fake_jar),
        })

    assert out["success"], out
    assert "attempts" not in out, "single-attempt response must not include attempts list"
    assert "best_attempt" not in out
    assert sp.run.call_count == 1


@pytest.mark.unit
def test_best_of_three_picks_highest_scoring_ses(workdir, fake_jar):
    """attempts=3 with varying SES content: best one wins."""
    cc = _make_cmds(workdir / "test.kicad_pcb")
    _patch_exec_mode(cc)
    ses_path = workdir / "test.ses"
    best_path = workdir / "test_best.ses"

    # Per-attempt SES net counts: 5, 8, 7. Best should be attempt 2 (8 nets).
    counts = iter([5, 8, 7])

    def fake_run(cmd, **kw):
        n = next(counts)
        ses_path.write_text(_make_ses(num_nets=n))
        return types.SimpleNamespace(returncode=0, stdout=f"n={n}", stderr="")

    fake_pcb = _stub_pcbnew()

    with patch.object(fr_mod, "subprocess") as sp, \
         patch.dict(sys.modules, {"pcbnew": fake_pcb}):
        sp.run.side_effect = fake_run
        sp.TimeoutExpired = TimeoutError
        out = cc.autoroute({
            "boardPath": str(workdir / "test.kicad_pcb"),
            "freeroutingJar": str(fake_jar),
            "attempts": 3,
        })

    assert out["success"], out
    assert "attempts" in out
    assert len(out["attempts"]) == 3
    assert out["best_attempt"] == 2, f"attempt 2 has 8 nets, should win; got {out['best_attempt']}"
    assert out["best_score"] == 8 * 1000 + (8 * 2)  # 8 nets, 16 segments
    # The final ses_path content should match the winning attempt (8 nets)
    final_ses = ses_path.read_text()
    assert final_ses.count("(net ") == 8
    # The _best.ses snapshot must also exist
    assert best_path.exists()


@pytest.mark.unit
def test_one_failing_attempt_does_not_abort_best_of_n(workdir, fake_jar):
    """Attempt 2 exits nonzero; best-of-N keeps going and picks among the rest."""
    cc = _make_cmds(workdir / "test.kicad_pcb")
    _patch_exec_mode(cc)
    ses_path = workdir / "test.ses"

    call_idx = {"n": 0}

    def fake_run(cmd, **kw):
        call_idx["n"] += 1
        if call_idx["n"] == 2:
            # Fail the middle attempt
            return types.SimpleNamespace(returncode=99, stdout="", stderr="boom")
        # First and third produce 5 and 9 nets respectively
        nets = 5 if call_idx["n"] == 1 else 9
        ses_path.write_text(_make_ses(num_nets=nets))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    fake_pcb = _stub_pcbnew()

    with patch.object(fr_mod, "subprocess") as sp, \
         patch.dict(sys.modules, {"pcbnew": fake_pcb}):
        sp.run.side_effect = fake_run
        sp.TimeoutExpired = TimeoutError
        out = cc.autoroute({
            "boardPath": str(workdir / "test.kicad_pcb"),
            "freeroutingJar": str(fake_jar),
            "attempts": 3,
        })

    assert out["success"], out
    assert sp.run.call_count == 3
    assert out["best_attempt"] == 3, "attempt 3 (9 nets) must win over attempt 1 (5 nets)"
    # The middle attempt is recorded but marked not-ok
    middle = next(a for a in out["attempts"] if a["attempt"] == 2)
    assert middle["ok"] is False
    assert middle["exit_code"] == 99


@pytest.mark.unit
def test_pass_schedule_wraps_when_attempts_exceeds_schedule_length(workdir, fake_jar):
    """Custom 2-entry schedule + 5 attempts → schedule cycles [a, b, a, b, a]."""
    cc = _make_cmds(workdir / "test.kicad_pcb")
    _patch_exec_mode(cc)
    ses_path = workdir / "test.ses"

    seen_mp = []

    def fake_run(cmd, **kw):
        # extract `-mp N` from the command
        mp = int(cmd[cmd.index("-mp") + 1])
        seen_mp.append(mp)
        ses_path.write_text(_make_ses(num_nets=3))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    fake_pcb = _stub_pcbnew()

    with patch.object(fr_mod, "subprocess") as sp, \
         patch.dict(sys.modules, {"pcbnew": fake_pcb}):
        sp.run.side_effect = fake_run
        sp.TimeoutExpired = TimeoutError
        out = cc.autoroute({
            "boardPath": str(workdir / "test.kicad_pcb"),
            "freeroutingJar": str(fake_jar),
            "attempts": 5,
            "passSchedule": [42, 99],
        })

    assert out["success"], out
    assert seen_mp == [42, 99, 42, 99, 42]


@pytest.mark.unit
def test_target_nets_bonus_wins_against_more_nets_without_targets(workdir, fake_jar):
    """Attempt with all targets beats higher-net attempt missing one target."""
    cc = _make_cmds(workdir / "test.kicad_pcb")
    _patch_exec_mode(cc)
    ses_path = workdir / "test.ses"

    # Attempt 1: 8 nets, none named "CRIT" — misses target
    # Attempt 2: 4 nets including "CRIT" — hits target, gets 50k bonus
    def fake_run(cmd, **kw):
        attempt = sum(1 for c in cmd if c == "-mp")  # rough counter — patched below
        ses_path.write_text(fake_run.next_ses)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    sess = [
        _make_ses(num_nets=8),
        # 4 nets but one named CRIT
        '(net "N0"\n  (wire (path F.Cu 200 0 0 1 1))\n)\n'
        '(net "N1"\n  (wire (path F.Cu 200 0 0 1 1))\n)\n'
        '(net "N2"\n  (wire (path F.Cu 200 0 0 1 1))\n)\n'
        '(net "CRIT"\n  (wire (path F.Cu 200 0 0 1 1))\n)\n',
    ]
    seq = iter(sess)

    def fake_run(cmd, **kw):
        fake_run.next_ses = next(seq)
        ses_path.write_text(fake_run.next_ses)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    fake_pcb = _stub_pcbnew()

    with patch.object(fr_mod, "subprocess") as sp, \
         patch.dict(sys.modules, {"pcbnew": fake_pcb}):
        sp.run.side_effect = fake_run
        sp.TimeoutExpired = TimeoutError
        out = cc.autoroute({
            "boardPath": str(workdir / "test.kicad_pcb"),
            "freeroutingJar": str(fake_jar),
            "attempts": 2,
            "targetNets": ["CRIT"],
        })

    assert out["success"], out
    assert out["best_attempt"] == 2, (
        "attempt 2 routed the critical target — its 50k bonus must beat "
        "attempt 1's higher raw net count"
    )


@pytest.mark.unit
def test_invalid_attempts_rejected_cleanly(workdir, fake_jar):
    cc = _make_cmds(workdir / "test.kicad_pcb")
    _patch_exec_mode(cc)
    out = cc.autoroute({
        "boardPath": str(workdir / "test.kicad_pcb"),
        "freeroutingJar": str(fake_jar),
        "attempts": 0,
    })
    assert out["success"] is False
    assert "Invalid attempts" in out["message"]
