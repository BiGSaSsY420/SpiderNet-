"""Storage IDs come straight off the URL path - they must not escape their root."""

import os
import pytest

from app.utils.safe_path import UnsafeIdentifierError, safe_join, validate_storage_id


TRAVERSAL = [
    "../etc",
    "../../etc/passwd",
    "..",
    ".",
    "a/../../b",
    "/absolute/path",
    "proj_abc/../../../x",
    "proj\x00abc",
    "proj abc",
    "",
    "sub/dir",
    "\\windows\\path",
]


@pytest.mark.parametrize("bad", TRAVERSAL)
def test_unsafe_ids_are_rejected(bad):
    with pytest.raises(UnsafeIdentifierError):
        validate_storage_id(bad)


@pytest.mark.parametrize("good", [
    "proj_2b7f1a9c4d3e",
    "sim_00112233aabb",
    "report_ffeeddccbbaa",
    "spidernet_0123456789abcdef",
    "legacy-id-1",
])
def test_real_ids_are_accepted(good):
    assert validate_storage_id(good) == good


@pytest.mark.parametrize("bad", TRAVERSAL)
def test_safe_join_refuses_to_escape(tmp_path, bad):
    with pytest.raises(UnsafeIdentifierError):
        safe_join(str(tmp_path), bad)


def test_safe_join_returns_a_contained_path(tmp_path):
    joined = safe_join(str(tmp_path), "proj_abc123", "project.json")
    assert joined.startswith(os.path.abspath(str(tmp_path)) + os.sep)


# --- the managers -------------------------------------------------------

def test_delete_project_cannot_rmtree_outside_its_root(isolated_storage):
    from app.models.project import ProjectManager

    victim = isolated_storage / "victim"
    victim.mkdir()
    (victim / "important.txt").write_text("do not delete")

    for attack in ["../victim", "../../victim", ".."]:
        with pytest.raises(UnsafeIdentifierError):
            ProjectManager.delete_project(attack)

    assert (victim / "important.txt").exists()


def test_loading_an_unknown_simulation_creates_nothing(isolated_storage):
    """A read used to call makedirs, so any GET grew the filesystem."""
    from app.services.simulation_manager import SimulationManager

    manager = SimulationManager()
    root = SimulationManager.SIMULATION_DATA_DIR
    before = set(os.listdir(root))

    assert manager.get_simulation("sim_doesnotexist01") is None

    assert set(os.listdir(root)) == before


def test_unknown_simulation_id_that_is_unsafe_is_rejected(isolated_storage):
    from app.services.simulation_manager import SimulationManager

    manager = SimulationManager()
    with pytest.raises(UnsafeIdentifierError):
        manager.get_simulation("../../escape")
