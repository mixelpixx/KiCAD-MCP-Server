"""Exercise Linux setup with real isolated interpreters and small fake modules."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux setup script")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def setup_repo(tmp_path):
    repo = tmp_path / "repo with spaces"
    repo.mkdir()
    shutil.copy2(ROOT / "setup-linux.sh", repo)
    (repo / "package.json").write_text("{}")
    (repo / "dist").mkdir()
    (repo / "dist/index.js").touch()
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(repo / "venv")],
        check=True,
        capture_output=True,
    )
    python = repo / "venv/bin/python"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH", None)
    env.pop("KICAD_PYTHON", None)
    site = Path(
        subprocess.check_output(
            [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            env=env,
            text=True,
        ).strip()
    )
    system = tmp_path / "system packages"
    system.mkdir()
    (site / "system.pth").write_text(str(system) + "\n")
    (system / "pcbnew.py").write_text("def GetBuildVersion(): return '10.0-test'\n")
    # Model the real CFFI failure: a venv package must load its own extension,
    # even when pcbnew lives in a system site-packages directory.
    (system / "_cffi_backend.py").write_text("VERSION = 'system'\n")
    (site / "_cffi_backend.py").write_text("VERSION = 'venv'\n")
    (site / "cairosvg.py").write_text(
        "import _cffi_backend\n"
        "if _cffi_backend.VERSION != 'venv':\n"
        "    raise RuntimeError('CFFI version mismatch')\n"
    )
    for module in (
        "kipy",
        "sexpdata",
        "skip",
        "PIL",
        "fitz",
        "colorlog",
        "pydantic",
        "requests",
        "dotenv",
    ):
        (site / f"{module}.py").touch()
    return repo, site, system, env


def run_setup(setup_repo, *args):
    repo, _, _, env = setup_repo
    return subprocess.run(
        ["bash", str(repo / "setup-linux.sh"), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_generated_environment_keeps_venv_packages_first(setup_repo):
    repo, site, system, env = setup_repo
    # Match the server: a repo venv wins over an explicit interpreter override.
    env["KICAD_PYTHON"] = "/nonexistent/python"
    result = run_setup(setup_repo, "--verify")
    assert result.returncode == 0, result.stdout + result.stderr
    fragment, _ = json.JSONDecoder().raw_decode(result.stdout[result.stdout.index("{") :])
    pythonpaths = fragment["env"]["PYTHONPATH"].split(os.pathsep)
    assert pythonpaths.index(str(site)) < pythonpaths.index(str(system))
    assert fragment["env"]["KICAD_PYTHON"] == str(repo / "venv/bin/python")
    # Check actual runtime imports using the generated environment, not just
    # the detection subprocess or the text of the configuration.
    subprocess.run(
        [fragment["env"]["KICAD_PYTHON"], "-c", "import pcbnew, cairosvg"],
        env={**env, **fragment["env"]},
        check=True,
        capture_output=True,
    )


@pytest.mark.parametrize("module", ["sexpdata", "fitz", "cairosvg"])
def test_verify_and_apply_reject_missing_or_broken_dependencies(setup_repo, module):
    repo, site, _, _ = setup_repo
    if module == "cairosvg":
        (site / "cairosvg.py").write_text("raise RuntimeError('broken native dependency')\n")
    else:
        (site / f"{module}.py").unlink()
    config = repo / "client.json"
    original = '{"mcpServers": {"other": {"command": "keep-me"}}}'
    config.write_text(original)
    for args in (("--verify",), ("--apply", "--yes", "--claude-config", str(config))):
        result = run_setup(setup_repo, *args)
        assert result.returncode == 1, result.stdout + result.stderr
        assert module in result.stdout
        assert "-m pip install -r" in result.stdout
    assert config.read_text() == original
    assert not list(repo.glob("client.json.*"))


def test_dry_run_reports_missing_dependencies_without_writing(setup_repo):
    repo, site, _, _ = setup_repo
    (site / "fitz.py").unlink()
    config = repo / "new-config/client.json"
    result = run_setup(setup_repo, "--dry-run", "--claude-config", str(config))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "pymupdf (fitz)" in result.stdout
    assert not config.parent.exists()


def test_apply_preserves_other_settings_permissions_and_backup(setup_repo):
    repo, _, _, _ = setup_repo
    config = repo / "client.json"
    existing = {
        "preferences": {"theme": "dark"},
        "mcpServers": {"other": {"command": "keep-me"}, "kicad": {"command": "old"}},
    }
    original = json.dumps(existing)
    config.write_text(original)
    config.chmod(0o640)
    result = run_setup(setup_repo, "--apply", "--yes", "--claude-config", str(config))
    assert result.returncode == 0, result.stdout + result.stderr
    updated = json.loads(config.read_text())
    assert updated["preferences"] == existing["preferences"]
    assert updated["mcpServers"]["other"] == existing["mcpServers"]["other"]
    assert updated["mcpServers"]["kicad"]["args"] == [str(repo / "dist/index.js")]
    assert config.stat().st_mode & 0o777 == 0o640
    backups = list(repo.glob("client.json.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text() == original


@pytest.mark.parametrize("original", ["{invalid JSON", "[]", '{"mcpServers": []}'])
def test_apply_rejects_invalid_config_without_writing(setup_repo, original):
    repo, _, _, _ = setup_repo
    config = repo / "client.json"
    config.write_text(original)
    result = run_setup(setup_repo, "--apply", "--yes", "--claude-config", str(config))
    assert result.returncode == 1
    assert config.read_text() == original
    assert not list(repo.glob("client.json.*"))
