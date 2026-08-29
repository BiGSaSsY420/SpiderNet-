"""TaskManager is a process-wide singleton that background threads write to."""

from datetime import datetime, timedelta

import pytest

from app.models.task import Task, TaskManager, TaskStatus


@pytest.fixture
def manager():
    """A TaskManager with an empty table.

    The class is a singleton, so every test would otherwise see the tasks left
    behind by the previous one.
    """
    m = TaskManager()
    with m._task_lock:
        m._tasks.clear()
    return m


def test_manager_is_a_singleton():
    assert TaskManager() is TaskManager()


def test_created_task_starts_pending(manager):
    task_id = manager.create_task("graph_build", metadata={"project_id": "proj_abc"})

    task = manager.get_task(task_id)
    assert task.status is TaskStatus.PENDING
    assert task.progress == 0
    assert task.metadata == {"project_id": "proj_abc"}


def test_task_ids_are_unique(manager):
    ids = {manager.create_task("t") for _ in range(50)}
    assert len(ids) == 50


def test_unknown_task_id_returns_none(manager):
    assert manager.get_task("no-such-task") is None


def test_update_only_touches_the_fields_it_is_given(manager):
    task_id = manager.create_task("graph_build")
    manager.update_task(task_id, progress=40, message="halfway")

    task = manager.get_task(task_id)
    assert task.progress == 40
    assert task.message == "halfway"
    # untouched fields keep their defaults rather than being reset to None
    assert task.status is TaskStatus.PENDING
    assert task.result is None


def test_updating_an_unknown_task_is_a_no_op(manager):
    manager.update_task("no-such-task", progress=100)  # must not raise
    assert manager.get_task("no-such-task") is None


def test_complete_task_sets_progress_to_100(manager):
    task_id = manager.create_task("graph_build")
    manager.complete_task(task_id, {"graph_id": "graph_1"})

    task = manager.get_task(task_id)
    assert task.status is TaskStatus.COMPLETED
    assert task.progress == 100
    assert task.result == {"graph_id": "graph_1"}


def test_fail_task_records_the_error(manager):
    task_id = manager.create_task("graph_build")
    manager.fail_task(task_id, "upstream refused the connection")

    task = manager.get_task(task_id)
    assert task.status is TaskStatus.FAILED
    assert task.error == "upstream refused the connection"


def test_list_tasks_is_newest_first(manager):
    ids = [manager.create_task("graph_build") for _ in range(3)]
    # created_at has sub-second resolution but can tie; order them explicitly
    for offset, task_id in enumerate(ids):
        manager.get_task(task_id).created_at = datetime(2026, 1, 1 + offset)

    listed = [t["task_id"] for t in manager.list_tasks()]
    assert listed == list(reversed(ids))


def test_list_tasks_filters_by_type(manager):
    build = manager.create_task("graph_build")
    manager.create_task("report")

    listed = manager.list_tasks(task_type="graph_build")
    assert [t["task_id"] for t in listed] == [build]


def test_cleanup_removes_only_old_finished_tasks(manager):
    old_done = manager.create_task("graph_build")
    old_running = manager.create_task("graph_build")
    fresh_done = manager.create_task("graph_build")

    stale = datetime.now() - timedelta(hours=48)
    manager.get_task(old_done).created_at = stale
    manager.get_task(old_running).created_at = stale
    manager.complete_task(old_done, {})
    manager.complete_task(fresh_done, {})
    manager.update_task(old_running, status=TaskStatus.PROCESSING)

    manager.cleanup_old_tasks(max_age_hours=24)

    assert manager.get_task(old_done) is None
    # still running, so it is kept however old it is
    assert manager.get_task(old_running) is not None
    assert manager.get_task(fresh_done) is not None


def test_to_dict_is_json_safe(manager):
    """The dict goes straight through jsonify, so no enums or datetimes."""
    import json

    task_id = manager.create_task("graph_build", metadata={"n": 1})
    manager.update_task(task_id, status=TaskStatus.PROCESSING, progress_detail={"stage": "chunking"})

    payload = manager.get_task(task_id).to_dict()
    assert payload["status"] == "processing"
    assert json.loads(json.dumps(payload))["task_id"] == task_id


def test_task_dataclass_defaults_are_not_shared():
    """A mutable default on a dataclass field would be shared across instances."""
    now = datetime.now()
    a = Task("a", "t", TaskStatus.PENDING, now, now)
    b = Task("b", "t", TaskStatus.PENDING, now, now)

    a.metadata["only_on_a"] = True
    assert b.metadata == {}
