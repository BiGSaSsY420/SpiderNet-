# Testing Guide

English | [中文文档](./TESTING.md)

MiroFish has two test suites: pytest for the backend and Vitest for the frontend.
Both run **without any API keys and without starting any service**.

## One minute to green

From the project root:

```bash
npm test
```

This runs both suites back to back, in about 30 seconds. The `passed` count at
the end of the output is the number of tests that ran; as long as there is no
`failed`, everything is working.

For coverage:

```bash
npm run test:coverage
```

### Prerequisites

| Tool | Needed for | Check |
|------|-----------|-------|
| **uv** | backend tests | `uv --version` |
| **Node.js 18+** | frontend tests | `node -v` |

The backend tests do **not** require `npm run setup:backend` first.
`npm run test:backend` builds a throwaway environment from
`backend/requirements-test.txt` containing only the lightweight dependencies the
tests actually import (about 20 seconds the first time, cached by uv afterwards).
This is deliberate: the full backend environment includes `camel-oasis` /
`camel-ai`, which pull in torch, transformers and several gigabytes of packages
that only the simulation subprocess ever needs.

The frontend tests need dependencies installed first (`npm run setup`, or
`cd frontend && npm install`).

## All commands

| Command | What it does |
|---------|-------------|
| `npm test` | Both suites, back to back |
| `npm run test:backend` | Backend only (pytest) |
| `npm run test:frontend` | Frontend only (Vitest) |
| `npm run test:frontend:watch` | Frontend in watch mode, reruns on save |
| `npm run test:coverage` | Both suites with coverage reports |
| `npm run test:backend:coverage` | Backend coverage only |
| `npm run test:frontend:coverage` | Frontend coverage only |

You can also call each runner directly, which is how you run a single file:

```bash
# Backend: one file, or one group of tests by name
cd backend
uv run --no-project --with-requirements requirements-test.txt pytest tests/test_retry.py
uv run --no-project --with-requirements requirements-test.txt pytest -k "traversal"

# Frontend: one file
cd frontend
npx vitest run tests/api-retry.test.js
```

## Where the coverage reports land

After `npm run test:coverage`:

- **Backend**: a per-file breakdown in the terminal; HTML report at
  `backend/htmlcov/index.html`
- **Frontend**: a summary in the terminal; HTML report at
  `frontend/coverage/index.html` (plus `lcov.info` for IDE plugins or services
  like Codecov)

Open the HTML report in a browser to see, line by line, what is not covered.

## What is covered, and what is not

Worth stating plainly, because the headline number is easy to misread.

**Well covered (90%+)** — the pure logic that needs no external service:

| Module | What is tested |
|--------|---------------|
| `app/utils/safe_path.py` | Path traversal: a `../` identifier must not escape the storage root |
| `app/utils/json_repair.py` | Repairing malformed LLM JSON (`<think>` tags, markdown fences) |
| `app/utils/retry.py` | Exponential backoff, sync and async, including the jitter ceiling |
| `app/utils/zep_paging.py` | Every termination condition of the Zep cursor pagination loop |
| `app/utils/file_parser.py` | Text chunking, and the encoding fallback chain (UTF-8 → GBK → replace) |
| `app/models/project.py` | The project save/load round trip through disk |
| `app/models/task.py` | The task state machine and its thread-safe singleton |
| Frontend `src/api/`, `src/store/` | Every endpoint's URL, method and query params; the retry policy; envelope unwrapping |

On top of that, `backend/tests/test_api_contract.py` sweeps **the entire route
table**: every endpoint must return a `{success: ...}` envelope, must not leak a
traceback with DEBUG off, and must not return 500 for an unknown id or a
malformed body. New routes are covered by these tests the day they are added,
with no extra work.

**Not covered** — the code that needs a live external service to execute:

- `app/services/report_agent.py`, `ontology_generator.py`, `graph_builder.py`:
  need a working LLM API
- `app/services/zep_*.py`: need a Zep Cloud account and graph data
- `app/services/simulation_runner.py`, `oasis_profile_generator.py`: need the
  OASIS simulation environment (and a great many LLM calls)
- Frontend `.vue` views: verified by hand today

Those modules are most of the codebase, so **overall coverage sits around 30%,
but that 30% covers nearly all of the logic that can be checked offline**.
Bringing the rest under test means first introducing a substitutable adapter
layer in front of the external services — a separate piece of refactoring.

## Coverage thresholds

Both suites enforce a **regression floor**, not a target: dropping below it fails
the run, which is what catches a test being deleted or silently skipped.

| Where | Floor | Actual |
|-------|-------|--------|
| `backend/pyproject.toml` → `[tool.coverage.report] fail_under` | 29% | ~30% (with branch coverage) |
| `frontend/vite.config.js` → `test.coverage.thresholds` | 90% statements/functions/lines, 85% branches | ~99% |

When new tests raise coverage, **raise these floors to match** so they stay just
under the current level.

## Writing new tests

### Backend

Tests live in `backend/tests/`, in files named `test_*.py`. `conftest.py`
provides three fixtures:

| Fixture | What it gives you |
|---------|------------------|
| `isolated_storage` | Every persistence root redirected to a tmp dir, so tests never write to `backend/uploads/` |
| `app` | A Flask app with `TESTING=True` (pulls in `isolated_storage` automatically) |
| `client` | That app's test client — call `client.get('/api/...')` directly |

```python
def test_creating_a_project_returns_its_id(client):
    response = client.post('/api/graph/ontology/generate', json={})
    assert response.status_code < 500
    assert response.get_json()['success'] is False
```

Async tests take `@pytest.mark.asyncio` (`asyncio_mode` is set to `strict`).

**Never actually sleep in a test.** Use `monkeypatch` to replace `time.sleep` /
`asyncio.sleep` with a recorder: you get to assert on the backoff delays *and*
the whole suite stays under 20 seconds. `test_retry.py` and `test_zep_paging.py`
both do this.

### Frontend

Tests live in `frontend/tests/`, in files ending `.test.js` (colocated
`src/**/*.test.js` files are picked up too). `tests/setup.js`
replaces `console.error` / `console.warn` with spies before each test, so the
tests that deliberately drive failure paths don't print a screenful of stack
traces on a passing run. To assert on what was logged, read
`console.error.mock.calls`.

## Continuous integration

`.github/workflows/test.yml` runs on every pull request and on pushes to `main`:

- **Backend (pytest)** — the same dependencies and the same command as
  `npm run test:backend` locally, plus a coverage report
- **Frontend (vitest + build)** — tests, the coverage thresholds, then a
  production build

Both jobs upload their HTML coverage report as an artifact, downloadable from the
Actions page.

## Troubleshooting

**`uv: command not found`**
The backend tests need uv. See the [uv docs](https://docs.astral.sh/uv/), or run
`curl -LsSf https://astral.sh/uv/install.sh | sh`.

**Frontend fails with `Cannot find module 'vitest'`**
Frontend dependencies aren't installed. Run `npm run setup`, or
`cd frontend && npm install`.

**Backend fails with a pile of `ModuleNotFoundError`**
Most likely pytest was run against the system Python instead of through
`npm run test:backend`. Use the
`uv run --no-project --with-requirements requirements-test.txt pytest` command
shown above.

**Will the tests touch my real data?**
No. The `isolated_storage` fixture redirects every storage root to a temp
directory that is destroyed afterwards, and `conftest.py` fills in placeholder
values for `LLM_API_KEY` / `ZEP_API_KEY`, so no real external API call is ever
made.
