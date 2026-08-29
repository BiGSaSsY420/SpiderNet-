"""
Contract tests over the whole route table.

These are deliberately generic: they assert properties every endpoint must
hold, so new routes are covered the day they are added.
"""

import json
import pytest


def _routes(app, method):
    for rule in app.url_map.iter_rules():
        if method in rule.methods and rule.endpoint != 'static':
            yield rule


def test_health_endpoint(client):
    r = client.get('/health')
    assert r.status_code == 200
    assert r.get_json()['status'] == 'ok'


# --- envelope shape -------------------------------------------------------

def _concrete_get_paths(app):
    """Every GET route, with a well-formed but nonexistent id in each path param."""
    for rule in _routes(app, 'GET'):
        path = rule.rule
        for arg in rule.arguments:
            path = path.replace(f'<{arg}>', 'zz_missing_0001')
            path = path.replace(f'<int:{arg}>', '999')
            path = path.replace(f'<string:{arg}>', 'zz_missing_0001')
        # /health is a container liveness probe, not part of the API envelope
        if '<' not in path and path != '/health':
            yield path


def test_every_response_uses_the_standard_envelope(app, client):
    """
    Success or failure, the body must be {success: bool, ...} - the frontend's
    response interceptor branches on that key and treats a missing one as success.
    """
    app.config['DEBUG'] = False
    checked = 0
    for path in _concrete_get_paths(app):
        r = client.get(path)
        checked += 1
        body = r.get_json()
        assert body is not None, f"{path} returned non-JSON ({r.status_code})"
        assert 'success' in body, f"{path} has no success key: {body}"
        if body['success'] is False:
            assert isinstance(body.get('error'), str), f"{path} error is not a string"
    assert checked > 10, "route sweep did not cover enough endpoints"


def test_unknown_ids_are_reported_as_not_found(app, client):
    """
    A lookup miss is a 404, not a crash. Routes that reach an external service
    (Zep, the LLM) are excluded - those legitimately fail differently when the
    upstream is unreachable.
    """
    app.config['DEBUG'] = False
    external = ('/api/graph/data/', '/api/simulation/entities/')
    for path in _concrete_get_paths(app):
        if path.startswith(external):
            continue
        r = client.get(path)
        assert r.status_code != 500, f"{path} returned 500 for an unknown id"


def test_no_endpoint_leaks_a_traceback_when_debug_is_off(app, client):
    """53 handlers used to return traceback.format_exc() to the caller."""
    app.config['DEBUG'] = False
    for path in _concrete_get_paths(app):
        body = client.get(path).get_json() or {}
        assert 'traceback' not in body, f"{path} leaked a traceback"


# --- malformed input ------------------------------------------------------

POST_ROUTES = [
    '/api/graph/build',
    '/api/graph/ontology/generate',
    '/api/simulation/create',
    '/api/simulation/prepare',
    '/api/simulation/prepare/status',
    '/api/simulation/start',
    '/api/simulation/stop',
    '/api/simulation/interview',
    '/api/simulation/env-status',
    '/api/report/generate',
    '/api/report/generate/status',
]


@pytest.mark.parametrize("path", POST_ROUTES)
def test_empty_post_body_is_a_client_error_not_a_crash(app, client, path):
    app.config['DEBUG'] = False
    r = client.post(path, json={})
    assert r.status_code < 500, f"{path} returned {r.status_code} for an empty body"
    body = r.get_json()
    assert body is not None and body.get('success') is False


@pytest.mark.parametrize("path", POST_ROUTES)
def test_wrong_types_are_a_client_error_not_a_crash(app, client, path):
    app.config['DEBUG'] = False
    r = client.post(path, json={"project_id": 12345, "simulation_id": [], "task_id": {}})
    assert r.status_code < 500, f"{path} returned {r.status_code}"


# --- path traversal -------------------------------------------------------

TRAVERSAL_IDS = ["../../etc", "..%2f..%2fetc", "....//....//etc", "%2e%2e%2f%2e%2e%2f"]


@pytest.mark.parametrize("bad", TRAVERSAL_IDS)
def test_traversal_ids_never_500(app, client, bad):
    app.config['DEBUG'] = False
    for path in [f'/api/graph/project/{bad}',
                 f'/api/simulation/{bad}',
                 f'/api/report/{bad}']:
        r = client.get(path)
        assert r.status_code in (301, 308, 400, 404), f"{path} -> {r.status_code}"


def test_delete_project_with_traversal_id_does_not_delete(app, client, isolated_storage):
    app.config['DEBUG'] = False
    victim = isolated_storage / "victim.txt"
    victim.write_text("keep me")
    r = client.delete('/api/graph/project/../../victim.txt')
    assert r.status_code in (301, 308, 400, 404)
    assert victim.exists()


# --- the chunker parameters that could hang a worker ----------------------

@pytest.mark.parametrize("params,reason", [
    ({"chunk_size": 500, "chunk_overlap": 500}, "overlap == size"),
    ({"chunk_size": 100, "chunk_overlap": 900}, "overlap > size"),
    ({"chunk_size": 0, "chunk_overlap": 0}, "zero size"),
    ({"chunk_size": -5, "chunk_overlap": 1}, "negative size"),
    ({"chunk_size": 500, "chunk_overlap": -10}, "negative overlap"),
    ({"chunk_size": "abc", "chunk_overlap": 10}, "non-numeric"),
    ({"chunk_size": 10 ** 9, "chunk_overlap": 10}, "absurd size"),
])
def test_dangerous_chunk_params_are_rejected(app, client, auth_headers, params, reason):
    """These used to reach a background thread and spin a core forever."""
    app.config['DEBUG'] = False
    body = {"project_id": "proj_000000000001", **params}
    r = client.post('/api/graph/build', json=body, headers=auth_headers)
    assert r.status_code == 400, f"{reason} was not rejected: {r.status_code}"
    assert r.get_json()['success'] is False
