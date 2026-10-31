"""Episodes made from an uploaded document: reading PDF, Word and text files, planning and researching from them, and
the upload itself. The documents are built here, so no binary files live in the repo."""
import base64
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from podcast_agent import document
from podcast_agent.agents import producer, researcher
from podcast_agent.web import app as web
from podcast_agent.web import jobs

SAYS = "The bank checks the PIN before it pays the shop, and the money moves in a few seconds. "


def make_pdf(texts):
    """A small PDF with one page per text (Helvetica); None makes a page with a drawing and no text, like a scan."""
    n, objs = len(texts), ["<< /Type /Catalog /Pages 2 0 R >>"]
    objs.append(f"<< /Type /Pages /Kids [{' '.join(f'{3 + 2 * i} 0 R' for i in range(n))}] /Count {n} >>")
    for i, t in enumerate(texts):
        stream = f"BT /F1 9 Tf 30 760 Td ({t}) Tj ET" if t else "0 0 1 rg 10 10 50 50 re f"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {3 + 2 * n} 0 R >> >> "
                    f"/Contents {4 + 2 * i} 0 R >>")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = b"%PDF-1.4\n", []
    for k, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{k} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def make_docx(paras, cell):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paras)
    body += f"<w:tbl><w:tr><w:tc><w:p><w:r><w:t>{cell}</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                                        f"<w:body>{body}</w:body></w:document>")
    return buf.getvalue()


PDF = make_pdf([SAYS * 2, "Page two: " + SAYS * 2])


def test_reads_pdf_word_and_text():
    pages = document.pages("UPI.pdf", PDF)
    assert [n for n, _ in pages] == [1, 2] and pages[1][1].startswith("Page two: The bank checks the PIN")
    word = document.pages("notes.docx", make_docx([SAYS, SAYS, SAYS], "Limit: one lakh rupees"))
    assert word == [(None, "\n".join([SAYS.strip()] * 3 + ["Limit: one lakh rupees"]))]  # table cells too
    assert document.pages("notes.md", (SAYS * 3).encode())[0][1] == (SAYS * 3).strip()


@pytest.mark.parametrize("name, data, says", [
    ("scan.pdf", make_pdf([None, None]), "looks scanned"),
    ("deck.pptx", b"PK", "upload a PDF"),
    ("broken.docx", b"not a zip", "could not read this Word file"),
    ("short.txt", b"Too short.", "almost no text"),
])
def test_refuses_what_it_cannot_read(name, data, says):
    with pytest.raises(ValueError, match=says):
        document.pages(name, data)


def test_parts_keep_page_ranges():
    pages = [(1, "a" * 300), (2, "b" * 300), (3, "c" * 900)]
    assert [(label, len(t)) for label, t in document.parts(pages, size=700)] == [("pp. 1-2", 602), ("p. 3", 700), ("p. 3", 200)]
    assert [label for label, _ in document.parts([(None, "x" * 50)])] == [""]


def doc_episode(tmp_path, **request):
    (tmp_path / "document.pdf").write_bytes(PDF)
    return {"id": "e1", "dir": str(tmp_path), "log": [], "facts": [], "questions": {"Q1": "How does UPI check a payment?"},
            "plan": {"title": "UPI", "audience": "adults"},
            "request": {"lang": "en", "document": {"file": "document.pdf", "name": "UPI.pdf"}, **request}}


def test_research_reads_the_document_and_searches_only_if_asked(tmp_path, monkeypatch):
    prompts = []

    def ask(ep, prompt, agent, json_reply=False, **kw):
        prompts.append((agent, prompt))
        return {"facts": [{"q": "Q1", "fact": "The bank checks the PIN."}]} if agent == "notes" else \
            {"tool": "done", "args": {"reason": "covered"}}
    monkeypatch.setattr(researcher, "ask", ask)
    monkeypatch.setattr(researcher.search, "web_search", lambda *a: pytest.fail("searched the web"))
    ep = doc_episode(tmp_path)
    researcher.research(ep, 5)
    assert ep["facts"] == [{"q": "Q1", "fact": "The bank checks the PIN.", "source": "UPI.pdf, pp. 1-2",
                            "url": "/api/episodes/e1/files/document.pdf#page=1", "id": "F1"}]
    assert [a for a, _ in prompts] == ["notes"] and "Page two: The bank" in prompts[0][1]  # the whole document read

    prompts.clear()
    researcher.research(doc_episode(tmp_path, doc_web=True), 5)  # then the search loop, told what the document gave
    assert [a for a, _ in prompts] == ["notes", "researcher"] and "read the uploaded document -> 1 facts" in prompts[1][1]


def test_the_producer_reads_a_short_document_whole_and_a_long_one_in_summaries(tmp_path, monkeypatch):
    ep = doc_episode(tmp_path)
    assert "Page two: The bank" in producer.document_brief(ep) and "ask nothing it does not cover" in producer.document_brief(ep)
    monkeypatch.setattr(producer, "PLAN_CHARS", 100)
    monkeypatch.setattr(document, "PART", 200)
    monkeypatch.setattr(producer, "ask", lambda ep, prompt, agent, **kw: f"summary of {prompt.split('(')[1].split(')')[0]}")
    brief = producer.document_brief(ep)
    assert ep["digest"][0] == ["p. 1", "summary of p. 1"] and "[p. 2] summary of p. 2" in brief and "summarised" in brief


def test_upload_makes_an_episode_from_the_document(tmp_path, monkeypatch):
    for module in (web, jobs):
        monkeypatch.setattr(module, "RUNS", tmp_path)
    monkeypatch.setattr(web.producer, "produce", lambda ep: None)  # the planning job, without the model
    c = TestClient(web.app)
    body = {"topic": "", "lang": "en", "speakers": 2, "minutes": 6, "doc_web": True}

    def post(name, data):
        return c.post("/api/episodes", json={**body, "document": {"name": name, "data": base64.b64encode(data).decode()}})
    assert "looks scanned" in post("scan.pdf", make_pdf([None])).json()["detail"]
    assert c.post("/api/episodes", json={**body, "document": {"name": "a.pdf", "data": "%%%"}}).status_code == 400
    assert not [f for f in tmp_path.iterdir() if f.is_dir()]  # nothing made for a file that can't be read

    eid = post("UPI_payments.pdf", PDF).json()["id"]
    ep = json.loads((tmp_path / eid / "episode.json").read_text())
    assert ep["request"]["topic"] == "UPI payments" and ep["request"]["doc_web"] is True
    assert ep["request"]["document"] == {"file": "document.pdf", "name": "UPI_payments.pdf", "pages": 2,
                                           "chars": sum(len(t) for _, t in document.pages("a.pdf", PDF))}
    assert c.get(f"/api/episodes/{eid}/files/document.pdf").content == PDF
    copy = c.post(f"/api/episodes/{eid}/duplicate").json()["id"]
    assert (tmp_path / copy / "document.pdf").read_bytes() == PDF  # a duplicate is made from the same document
