"""Reading an uploaded document into text the agents can use: a PDF's text layer (pypdf), a Word file's paragraphs
and tables (.docx, read as the zip of XML it is), or plain text and Markdown. A scanned PDF has no text layer and
is refused with a message saying so; reading page images would need OCR."""
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError

KINDS = (".pdf", ".docx", ".txt", ".md")
MAX_BYTES = 20 * 1024 * 1024
# Characters the fact extractor reads at a time. It gives at most 8 facts a call: from "Attention Is All You Need"
# (15 pages) parts of 20,000 gave 7 facts, 1 per research question; parts of 8,000 gave 12, 2 per question.
PART = 8000
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def pages(name, data):
    """[(page number or None, text)] of the document `name` (its extension says the kind) with bytes `data`: one item
    per PDF page, one for anything else. Raises ValueError, with a message for the user, if there is no text."""
    ext = Path(name).suffix.lower()
    if ext not in KINDS:
        raise ValueError("upload a PDF, a Word file (.docx), or a text or Markdown file")
    if len(data) > MAX_BYTES:
        raise ValueError(f"the document is over {MAX_BYTES // 2**20} MB")
    if ext == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError("this PDF is password-protected; upload an unlocked copy")
            out = [(i, _tidy(p.extract_text() or "")) for i, p in enumerate(reader.pages, 1)]
        except PdfReadError as e:
            raise ValueError(f"could not read this PDF ({e})") from e
    elif ext == ".docx":
        out = [(None, _docx(data))]
    else:
        out = [(None, _tidy(data.decode("utf-8", errors="replace")))]
    if sum(len(t) for _, t in out) < 200:
        raise ValueError("this PDF has no text to read; it looks scanned. Upload a PDF with selectable text, or a "
                         "Word file" if ext == ".pdf" else "the document has almost no text")
    return out


def _tidy(text):
    """Runs of spaces as one, no spaces at line ends, and at most one blank line between paragraphs."""
    text = re.sub(r" ?\n ?", "\n", re.sub(r"[ \t\u00a0]+", " ", text))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _docx(data):
    """A Word file's paragraphs in order, table cells included, one per line."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if z.getinfo("word/document.xml").file_size > 50 * 2**20:  # a zip bomb, not a document
                raise ValueError("the Word file is too large to read")
            root = ElementTree.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
        raise ValueError("could not read this Word file; save it as .docx and try again") from e
    paras = ("".join(t.text or "" for t in p.iter(f"{W}t")) for p in root.iter(f"{W}p"))
    return _tidy("\n".join(p for p in paras if p.strip()))


def parts(doc_pages, size=None):
    """The document in pieces of at most about `size` (default PART) characters, split between paragraphs, for
    reading one at a time: [(label, text)], label like "p. 3" or "pp. 3-7" for a PDF, "" otherwise."""
    size = size or PART
    out, buf, first, last = [], [], None, None

    def flush():
        if buf:
            label = "" if first is None else f"p. {first}" if first == last else f"pp. {first}-{last}"
            out.append((label, "\n\n".join(buf)))
            buf.clear()

    for page, text in doc_pages:
        for para in text.split("\n\n"):
            for k in range(0, len(para), size):  # a paragraph longer than a piece is split
                piece = para[k:k + size]
                if buf and sum(len(b) + 2 for b in buf) + len(piece) > size:
                    flush()
                if not buf:
                    first = page
                buf.append(piece)
                last = page
    flush()
    return out
