"""
Shared pytest fixtures.

Storage roots in this codebase are class attributes evaluated at import time,
so redirecting them at runtime means rebinding the attribute on each class.
`isolated_storage` does that for every manager, pointing them at a tmp dir so
tests never touch backend/uploads.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("ZEP_API_KEY", "test-key")


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    """Point every persistence root at a throwaway directory."""
    from app.models.project import ProjectManager
    from app.services.simulation_manager import SimulationManager
    from app.services.report_agent import ReportManager
    from app.services.simulation_runner import SimulationRunner

    roots = {
        ProjectManager: ("PROJECTS_DIR", "projects"),
        SimulationManager: ("SIMULATION_DATA_DIR", "simulations"),
        ReportManager: ("REPORTS_DIR", "reports"),
        SimulationRunner: ("RUN_STATE_DIR", "run_state"),
    }
    for cls, (attr, name) in roots.items():
        path = str(tmp_path / name)
        os.makedirs(path, exist_ok=True)
        monkeypatch.setattr(cls, attr, path)

    return tmp_path


@pytest.fixture
def app(isolated_storage):
    from app import create_app

    application = create_app()
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()
