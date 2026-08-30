"""
Licence disclosure.

AGPL section 13 owes the source to everyone using this over a network. An
endpoint nobody can reach, or one that needs a paid key, does not discharge
that obligation.
"""

import pytest


def test_the_source_offer_is_public(app, client):
    """It is owed to every user, not only to customers."""
    r = client.get('/api/legal/source')
    assert r.status_code == 200
    assert r.get_json()["success"] is True


def test_it_names_the_licence_and_the_upstream(app, client):
    data = client.get('/api/legal/source').get_json()["data"]
    assert data["licence"].startswith("AGPL-3.0")
    assert "MiroFish" in data["upstream_url"]
    assert data["source_url"].startswith("http")


def test_it_points_at_the_running_revision(app, client):
    """
    A link to "latest" is not the source of what you are running. The offer
    has to identify this build.
    """
    data = client.get('/api/legal/source').get_json()["data"]
    if data["revision"] != "unknown":
        assert data["revision"] in data["revision_url"]


def test_source_url_is_configurable(app, client, monkeypatch):
    """A deployment must be able to point the offer at its own fork."""
    monkeypatch.setenv("SOURCE_URL", "https://example.invalid/my-fork")
    data = client.get('/api/legal/source').get_json()["data"]
    assert data["source_url"] == "https://example.invalid/my-fork"


def test_the_notice_explains_the_entitlement(app, client):
    notice = client.get('/api/legal/source').get_json()["data"]["notice"]
    assert "source" in notice.lower()
    assert "no charge" in notice.lower() or "free" in notice.lower()


# --- the files that have to ship ------------------------------------------

@pytest.mark.parametrize("filename", ["LICENSE", "NOTICE"])
def test_licence_files_are_present(filename):
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent.parent
    assert (root / filename).exists(), f"{filename} must ship with the source"


def test_the_notice_marks_the_modifications():
    """AGPL section 5a: modified versions must say so."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent.parent
    notice = (root / "NOTICE").read_text(encoding="utf-8")
    assert "MiroFish" in notice
    assert "modified" in notice.lower()
    assert "AGPL" in notice


def test_the_readme_carries_the_attribution():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent.parent
    for name in ("README.md", "README-EN.md"):
        text = (root / name).read_text(encoding="utf-8")
        assert "666ghj/MiroFish" in text, f"{name} lost the upstream attribution"
