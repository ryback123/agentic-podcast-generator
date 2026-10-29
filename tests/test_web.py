"""Cover images (web/app.py): only a real PNG, JPEG or WebP under the size limit is kept, and the episode list
points at it."""
from fastapi.testclient import TestClient

from podcast_agent.web import app as web
from podcast_agent.web import jobs

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
