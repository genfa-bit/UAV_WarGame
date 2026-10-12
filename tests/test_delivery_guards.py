from pathlib import Path

from config import MAX_CONFIGURABLE_STEPS
from core.controller import SimulationController


ROOT = Path(__file__).resolve().parents[1]


def test_complete_journal_step_limit_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))
    controller = SimulationController()
    assert MAX_CONFIGURABLE_STEPS == 10_000
    assert controller.set_timing(0.22, MAX_CONFIGURABLE_STEPS).ok
    result = controller.set_timing(0.22, MAX_CONFIGURABLE_STEPS + 1)
    assert not result.ok
    assert str(MAX_CONFIGURABLE_STEPS) in result.message


def test_pull_requests_run_packaging_and_executable_smoke_test():
    workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
    package_block = workflow.split("  package:", 1)[1]
    assert "github.event_name == 'workflow_dispatch'" not in package_block
    assert "python -m PyInstaller --noconfirm --clean UAV_WarGame.spec" in package_block
    assert "UAV_WarGame.exe" in package_block
    assert "--smoke-test" in package_block
