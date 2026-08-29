"""Project persistence: the round trip through disk must not lose or alter data."""

import io
import json
import os

import pytest

from app.models.project import Project, ProjectManager, ProjectStatus
from app.utils.safe_path import UnsafeIdentifierError


pytestmark = pytest.mark.usefixtures("isolated_storage")


def test_create_project_lays_out_its_directories():
    project = ProjectManager.create_project("My Project")

    assert project.project_id.startswith("proj_")
    assert project.status is ProjectStatus.CREATED
    assert os.path.isdir(ProjectManager._get_project_dir(project.project_id))
    assert os.path.isdir(ProjectManager._get_project_files_dir(project.project_id))


def test_project_survives_a_save_load_round_trip():
    project = ProjectManager.create_project("Round Trip")
    project.status = ProjectStatus.GRAPH_COMPLETED
    project.graph_id = "graph_9f8e"
    project.ontology = {"entities": ["Student", "University"]}
    project.total_text_length = 4096
    project.chunk_size = 800
    ProjectManager.save_project(project)

    loaded = ProjectManager.get_project(project.project_id)
    assert loaded.name == "Round Trip"
    assert loaded.status is ProjectStatus.GRAPH_COMPLETED
    assert loaded.graph_id == "graph_9f8e"
    assert loaded.ontology == {"entities": ["Student", "University"]}
    assert loaded.total_text_length == 4096
    assert loaded.chunk_size == 800


def test_saving_stamps_updated_at():
    project = ProjectManager.create_project("Stamped")
    first = project.updated_at

    project.name = "Renamed"
    ProjectManager.save_project(project)

    assert project.updated_at >= first
    assert ProjectManager.get_project(project.project_id).name == "Renamed"


def test_metadata_is_written_as_readable_utf8():
    """ensure_ascii=False, so Chinese names stay legible in the file on disk."""
    project = ProjectManager.create_project("舆情推演")

    meta_path = ProjectManager._get_project_meta_path(project.project_id)
    raw = open(meta_path, encoding="utf-8").read()
    assert "舆情推演" in raw
    assert json.loads(raw)["name"] == "舆情推演"


def test_unknown_project_is_none_not_an_error():
    assert ProjectManager.get_project("proj_doesnotexist") is None


def test_reading_an_unknown_project_creates_nothing():
    root = ProjectManager.PROJECTS_DIR
    os.makedirs(root, exist_ok=True)
    before = set(os.listdir(root))

    ProjectManager.get_project("proj_doesnotexist")

    assert set(os.listdir(root)) == before


def test_list_projects_is_newest_first():
    a = ProjectManager.create_project("A")
    b = ProjectManager.create_project("B")
    a.created_at = "2020-01-01T00:00:00"
    b.created_at = "2030-01-01T00:00:00"
    ProjectManager.save_project(a)
    ProjectManager.save_project(b)

    listed = [p.project_id for p in ProjectManager.list_projects()]
    assert listed == [b.project_id, a.project_id]


def test_list_projects_honours_the_limit():
    for _ in range(5):
        ProjectManager.create_project("P")

    assert len(ProjectManager.list_projects(limit=2)) == 2


def test_delete_removes_the_project_tree():
    project = ProjectManager.create_project("Doomed")
    ProjectManager.save_extracted_text(project.project_id, "some text")

    assert ProjectManager.delete_project(project.project_id) is True
    assert ProjectManager.get_project(project.project_id) is None
    assert not os.path.exists(ProjectManager._get_project_dir(project.project_id))


def test_deleting_an_unknown_project_reports_false():
    assert ProjectManager.delete_project("proj_doesnotexist") is False


def test_extracted_text_round_trips_unicode():
    project = ProjectManager.create_project("Text")
    text = "第一句话。\nSecond line.\n"

    ProjectManager.save_extracted_text(project.project_id, text)

    assert ProjectManager.get_extracted_text(project.project_id) == text


def test_extracted_text_is_none_before_it_is_written():
    project = ProjectManager.create_project("Empty")
    assert ProjectManager.get_extracted_text(project.project_id) is None


def test_uploaded_files_are_stored_under_a_generated_name():
    """The original filename is attacker-controlled and never becomes a path."""
    project = ProjectManager.create_project("Uploads")

    class _Upload:
        def __init__(self, data):
            self._data = data

        def save(self, path):
            with open(path, "wb") as f:
                f.write(self._data)

    info = ProjectManager.save_file_to_project(
        project.project_id, _Upload(b"hello world"), "../../evil report.txt"
    )

    assert info["original_filename"] == "../../evil report.txt"
    assert "/" not in info["saved_filename"]
    assert info["saved_filename"].endswith(".txt")
    assert info["size"] == len(b"hello world")

    files_dir = ProjectManager._get_project_files_dir(project.project_id)
    assert os.path.abspath(info["path"]).startswith(os.path.abspath(files_dir) + os.sep)
    assert ProjectManager.get_project_files(project.project_id) == [info["path"]]


def test_project_files_is_empty_before_any_upload():
    project = ProjectManager.create_project("No Files")
    assert ProjectManager.get_project_files(project.project_id) == []


@pytest.mark.parametrize("bad", ["../escape", "a/b", "", "proj\x00x"])
def test_every_entry_point_validates_the_project_id(bad):
    for call in (
        lambda: ProjectManager.get_project(bad),
        lambda: ProjectManager.delete_project(bad),
        lambda: ProjectManager.get_extracted_text(bad),
        lambda: ProjectManager.save_extracted_text(bad, "x"),
        lambda: ProjectManager.get_project_files(bad),
    ):
        with pytest.raises(UnsafeIdentifierError):
            call()


def test_from_dict_fills_in_missing_optional_fields():
    project = Project.from_dict({"project_id": "proj_minimal"})

    assert project.name == "Unnamed Project"
    assert project.status is ProjectStatus.CREATED
    assert project.files == []
    assert project.chunk_size == 500
    assert project.chunk_overlap == 50


def test_to_dict_serialises_the_status_enum():
    project = Project.from_dict({"project_id": "proj_x", "status": "graph_building"})
    payload = project.to_dict()

    assert payload["status"] == "graph_building"
    assert json.loads(json.dumps(payload))["project_id"] == "proj_x"


def test_from_dict_rejects_an_unknown_status():
    with pytest.raises(ValueError):
        Project.from_dict({"project_id": "proj_x", "status": "not_a_status"})
