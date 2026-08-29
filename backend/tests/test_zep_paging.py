"""Cursor pagination over the Zep graph API, with a stand-in client.

Every loop here has a termination condition that depends on data the remote
returns; a wrong one means an unbounded loop against a paid API.
"""

from types import SimpleNamespace

import pytest
from zep_cloud import InternalServerError

from app.utils.zep_paging import _fetch_page_with_retry, fetch_all_edges, fetch_all_nodes


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    slept = []
    monkeypatch.setattr("app.utils.zep_paging.time.sleep", slept.append)
    return slept


def _node(index):
    return SimpleNamespace(uuid_=f"uuid-{index}", name=f"node-{index}")


class FakeGraphAPI:
    """Serves a fixed list of items through the uuid_cursor protocol."""

    def __init__(self, items):
        self.items = items
        self.calls = []

    def get_by_graph_id(self, graph_id, limit=None, uuid_cursor=None):
        self.calls.append({"graph_id": graph_id, "limit": limit, "uuid_cursor": uuid_cursor})
        start = 0
        if uuid_cursor is not None:
            uuids = [getattr(i, "uuid_", None) for i in self.items]
            start = uuids.index(uuid_cursor) + 1
        return self.items[start:start + limit]


def _client(node_items=(), edge_items=()):
    return SimpleNamespace(
        graph=SimpleNamespace(
            node=FakeGraphAPI(list(node_items)),
            edge=FakeGraphAPI(list(edge_items)),
        )
    )


# --- happy paths ---------------------------------------------------------

def test_a_single_short_page_stops_after_one_call():
    client = _client(node_items=[_node(i) for i in range(7)])

    nodes = fetch_all_nodes(client, "graph_1", page_size=100)

    assert len(nodes) == 7
    assert len(client.graph.node.calls) == 1
    assert client.graph.node.calls[0]["uuid_cursor"] is None


def test_pages_are_followed_by_cursor_until_exhausted():
    client = _client(node_items=[_node(i) for i in range(25)])

    nodes = fetch_all_nodes(client, "graph_1", page_size=10)

    assert [n.name for n in nodes] == [f"node-{i}" for i in range(25)]
    # 10, 10, then a short page of 5
    assert [c["uuid_cursor"] for c in client.graph.node.calls] == [None, "uuid-9", "uuid-19"]


def test_an_exactly_full_last_page_needs_one_more_call_to_confirm_the_end():
    client = _client(node_items=[_node(i) for i in range(20)])

    nodes = fetch_all_nodes(client, "graph_1", page_size=10)

    assert len(nodes) == 20
    # the third call returns nothing and ends the loop
    assert len(client.graph.node.calls) == 3


def test_an_empty_graph_returns_an_empty_list():
    client = _client()
    assert fetch_all_nodes(client, "graph_1") == []
    assert fetch_all_edges(client, "graph_1") == []


def test_the_graph_id_is_passed_through():
    client = _client(node_items=[_node(0)])
    fetch_all_nodes(client, "graph_abc")
    assert client.graph.node.calls[0]["graph_id"] == "graph_abc"


# --- the bounds that keep the loop finite --------------------------------

def test_node_pagination_stops_at_max_items():
    client = _client(node_items=[_node(i) for i in range(500)])

    nodes = fetch_all_nodes(client, "graph_1", page_size=100, max_items=250)

    assert len(nodes) == 250
    assert len(client.graph.node.calls) == 3


def test_pagination_stops_when_an_item_has_no_uuid_to_page_from():
    """Without a cursor the next call repeats the same page forever."""
    items = [_node(i) for i in range(9)] + [SimpleNamespace(name="no-uuid")]
    client = _client(node_items=items + [_node(i) for i in range(10, 30)])

    nodes = fetch_all_nodes(client, "graph_1", page_size=10)

    assert len(nodes) == 10
    assert len(client.graph.node.calls) == 1


def test_a_legacy_uuid_attribute_is_still_usable_as_a_cursor():
    items = [SimpleNamespace(uuid=f"uuid-{i}", name=f"node-{i}") for i in range(15)]

    class LegacyAPI(FakeGraphAPI):
        def get_by_graph_id(self, graph_id, limit=None, uuid_cursor=None):
            self.calls.append({"graph_id": graph_id, "limit": limit, "uuid_cursor": uuid_cursor})
            start = 0
            if uuid_cursor is not None:
                start = [i.uuid for i in self.items].index(uuid_cursor) + 1
            return self.items[start:start + limit]

    client = SimpleNamespace(graph=SimpleNamespace(node=LegacyAPI(items)))

    assert len(fetch_all_nodes(client, "graph_1", page_size=10)) == 15


def test_edges_are_not_capped_at_the_node_limit():
    """Edges outnumber nodes; only fetch_all_nodes takes a max_items bound."""
    client = _client(edge_items=[_node(i) for i in range(2500)])

    assert len(fetch_all_edges(client, "graph_1", page_size=500)) == 2500


# --- transient failures --------------------------------------------------

class FlakyAPI(FakeGraphAPI):
    def __init__(self, items, failures, error):
        super().__init__(items)
        self.failures = failures
        self.error = error

    def get_by_graph_id(self, graph_id, limit=None, uuid_cursor=None):
        if self.failures > 0:
            self.failures -= 1
            raise self.error
        return super().get_by_graph_id(graph_id, limit=limit, uuid_cursor=uuid_cursor)


@pytest.mark.parametrize("error", [
    ConnectionError("reset"),
    TimeoutError("timed out"),
    OSError("socket closed"),
    InternalServerError(body="upstream exploded"),
])
def test_transient_errors_are_retried(error, no_sleeping):
    api = FlakyAPI([_node(0)], failures=2, error=error)
    client = SimpleNamespace(graph=SimpleNamespace(node=api))

    assert len(fetch_all_nodes(client, "graph_1")) == 1
    assert len(no_sleeping) == 2


def test_retry_delay_doubles(no_sleeping):
    api = FlakyAPI([_node(0)], failures=2, error=ConnectionError("reset"))
    client = SimpleNamespace(graph=SimpleNamespace(node=api))

    fetch_all_nodes(client, "graph_1", max_retries=3, retry_delay=1.5)

    assert no_sleeping == [1.5, 3.0]


def test_the_error_is_raised_once_retries_run_out(no_sleeping):
    api = FlakyAPI([_node(0)], failures=99, error=ConnectionError("still down"))
    client = SimpleNamespace(graph=SimpleNamespace(node=api))

    with pytest.raises(ConnectionError, match="still down"):
        fetch_all_nodes(client, "graph_1", max_retries=3)

    assert len(no_sleeping) == 2  # no sleep after the final attempt


def test_programming_errors_are_not_retried(no_sleeping):
    api = FlakyAPI([_node(0)], failures=99, error=ValueError("bad argument"))
    client = SimpleNamespace(graph=SimpleNamespace(node=api))

    with pytest.raises(ValueError):
        fetch_all_nodes(client, "graph_1")

    assert no_sleeping == []


def test_a_retry_budget_below_one_is_rejected():
    with pytest.raises(ValueError, match="max_retries"):
        _fetch_page_with_retry(lambda: [], max_retries=0)
