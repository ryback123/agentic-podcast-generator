"""The web app's own rules (web/app.py, web/settings.py): cover images, settings, deleting and duplicating."""
import json

import pytest
from fastapi.testclient import TestClient

from podcast_agent.web import app as web
from podcast_agent.web import jobs, settings

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def test_cover_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "RUNS", tmp_path)
    monkeypatch.setattr(jobs, "RUNS", tmp_path)
    (tmp_path / "e1").mkdir()
    (tmp_path / "e1" / "episode.json").write_text('{"id": "e1", "request": {"topic": "t", "lang": "en"}, "log": []}')
    c = TestClient(web.app)

    assert c.put("/api/episodes/e1/cover", content=b"<svg onload='alert(1)'/>").status_code == 400
    assert c.put("/api/episodes/e1/cover", content=PNG + b"\0" * web.COVER_MAX).status_code == 413
    assert c.put("/api/episodes/nope/cover", content=PNG).status_code == 404
    assert not list(tmp_path.glob("e1/cover.*"))

    name = c.put("/api/episodes/e1/cover", content=PNG).json()["cover"]
    assert name.startswith("cover.png?v=")
    assert c.get("/api/episodes").json()[0]["cover"] == name
    assert c.get("/api/episodes/e1/files/cover.png").content == PNG

    jpg = c.put("/api/episodes/e1/cover", content=b"\xff\xd8\xff\xe0" + b"\0" * 16).json()["cover"]
    assert jpg.startswith("cover.jpg?v=") and [f.name for f in tmp_path.glob("e1/cover.*")] == ["cover.jpg"]

    assert c.delete("/api/episodes/e1/cover").json() == {"cover": None}
    assert not list(tmp_path.glob("e1/cover.*")) and c.get("/api/episodes").json()[0]["cover"] is None


def episode(run, eid, **request):
    (run / eid).mkdir()
    req = {"topic": "How UPI works", "description": "", "lang": "hi", "speakers": 3, "minutes": 10.0, "code_mix": "heavy", **request}
    (run / eid / "episode.json").write_text(json.dumps({"id": eid, "request": req, "plan": None, "facts": [], "log": []}))


def test_settings_are_checked_and_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RUNS", tmp_path)
    assert settings.load() == settings.DEFAULTS
    for bad in ({"lang": "xx"}, {"speakers": 9}, {"speakers": True}, {"minutes": 12.5}, {"review_rounds": 5},
                {"research_steps": 2}, {"web_search": "yes"}, {"voice_male": 3}):
        with pytest.raises(ValueError):
            settings.save(bad)
    saved = settings.save({"lang": "ta", "review_rounds": 0, "web_search": False, "api_key": "dropped"})
    assert settings.load() == saved and "api_key" not in saved and saved["speakers"] == 2


def test_delete_moves_to_trash_and_duplicate_copies_the_request(tmp_path, monkeypatch):
    for module in (web, jobs, settings):
        monkeypatch.setattr(module, "RUNS", tmp_path)
    monkeypatch.setattr(web.producer, "produce", lambda ep: None)  # the copy's planning job, without the model
    episode(tmp_path, "e1")
    c = TestClient(web.app)

    monkeypatch.setitem(jobs.jobs, "e1", {"task": "researching", "running": True, "error": None})
    assert c.delete("/api/episodes/e1").status_code == 409 and (tmp_path / "e1").exists()
    jobs.jobs["e1"]["running"] = False

    new = c.post("/api/episodes/e1/duplicate").json()["id"]
    assert new != "e1" and json.loads((tmp_path / new / "episode.json").read_text())["request"] | {"seed": 0} == {
        "topic": "How UPI works", "description": "", "lang": "hi", "speakers": 3, "minutes": 10.0, "code_mix": "heavy", "seed": 0}

    assert c.delete("/api/episodes/e1").json() == {"ok": True}
    assert (tmp_path / ".trash" / "e1" / "episode.json").exists() and not (tmp_path / "e1").exists()
    assert [e["id"] for e in c.get("/api/episodes").json()] == [new]
    assert c.delete("/api/episodes/e1").status_code == 404
