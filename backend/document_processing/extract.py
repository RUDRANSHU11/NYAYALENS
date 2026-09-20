"""Pipeline steps 1-2: validate an upload and pull text (plus metadata) out of it.

Everything happens on the in-memory bytes of the request. No uploaded document is
ever written to disk by this module.
"""

from __future__ import annotations

import io
import logging
import os
import zipfile
from dataclasses import dataclass, field

from backend import config

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt")

# A .docx is a zip; refuse one that expands far beyond anything a contract needs.
_MAX_DOCX_UNCOMPRESSED = 200 * 1024 * 1024
# Below this many characters per page we assume the PDF has no text layer (scanned).
_SCANNED_CHARS_PER_PAGE = 40


class DocumentError(ValueError):
    """A problem with the uploaded document that the user can act on."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Line:
    """One physical line of text, with the page it came from (None for DOCX/TXT)."""

    page: int | None
    text: str
    heading: bool = False


@dataclass
class Extracted:
    lines: list[Line]
    pages: int
    needs_ocr: bool = False
    page_images: list[bytes] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(line.text) for line in self.lines)


def extract(filename: str, data: bytes) -> Extracted:
    """Validate ``data`` and return its text. Raises :class:`DocumentError`."""
    extension = _validate(filename, data)
    if extension == ".pdf":
        return _extract_pdf(data)
    if extension == ".docx":
        return _extract_docx(data)
    return _extract_txt(data)


def _validate(filename: str, data: bytes) -> str:
    if not data:
        raise DocumentError("The uploaded file is empty.")
    if len(data) > config.MAX_UPLOAD_BYTES:
        limit = config.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise DocumentError(f"File is larger than the {limit} MB limit.", 413)

    extension = os.path.splitext(filename or "")[1].lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentError("Only PDF, DOCX and TXT documents are supported.", 415)

    # The extension is user-controlled; the bytes are what we actually parse.
    if extension == ".pdf" and not data.lstrip()[:5] == b"%PDF-":
        raise DocumentError("This file is not a valid PDF.", 415)
    if extension == ".docx" and data[:2] != b"PK":
        raise DocumentError("This file is not a valid Word (.docx) document.", 415)
    return extension


def _extract_pdf(data: bytes) -> Extracted:
    import fitz  # PyMuPDF

    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception:  # noqa: BLE001 - library raises several unrelated types
        raise DocumentError("This PDF could not be opened. It may be damaged.") from None

    with document:
        if document.needs_pass:
            raise DocumentError("This PDF is password-protected. Please remove the password first.")
        if document.page_count > config.MAX_PAGES:
            raise DocumentError(
                f"This document has {document.page_count} pages; the limit is {config.MAX_PAGES}.",
                413,
            )

        lines: list[Line] = []
        for number, page in enumerate(document, start=1):
            for block in page.get_text("blocks", sort=True):
                if block[6] != 0:  # 1 = image block
                    continue
                for raw in str(block[4]).splitlines():
                    text = " ".join(raw.split())
                    if text:
                        lines.append(Line(page=number, text=text))

        characters = sum(len(line.text) for line in lines)
        needs_ocr = characters < _SCANNED_CHARS_PER_PAGE * max(document.page_count, 1)

        images: list[bytes] = []
        if needs_ocr:
            for index in range(min(document.page_count, config.OCR_MAX_PAGES)):
                images.append(document[index].get_pixmap(dpi=150).tobytes("png"))

        return Extracted(
            lines=lines, pages=document.page_count, needs_ocr=needs_ocr, page_images=images
        )


def _extract_docx(data: bytes) -> Extracted:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    _guard_zip(data)
    try:
        document = Document(io.BytesIO(data))
    except Exception:  # noqa: BLE001
        raise DocumentError("This Word document could not be read.") from None

    lines: list[Line] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, document)
            text = " ".join(paragraph.text.split())
            if not text:
                continue
            style = getattr(paragraph.style, "name", "") or ""
            lines.append(Line(page=None, text=text, heading=style.startswith("Heading")))
        elif child.tag == qn("w:tbl"):
            for row in Table(child, document).rows:
                cells = [" ".join(cell.text.split()) for cell in row.cells]
                text = " | ".join(cell for cell in cells if cell)
                if text:
                    lines.append(Line(page=None, text=text))

    return Extracted(lines=lines, pages=0)


def _extract_txt(data: bytes) -> Extracted:
    for encoding in ("utf-8", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise DocumentError("This file is not readable text.", 415)

    lines = [Line(page=None, text=" ".join(raw.split())) for raw in text.splitlines() if raw.strip()]
    return Extracted(lines=lines, pages=0)


def _guard_zip(data: bytes) -> None:
    """Reject zip bombs and files that are not really .docx before parsing them."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            uncompressed = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile:
        raise DocumentError("This Word document could not be read.") from None

    if "word/document.xml" not in names:
        raise DocumentError("This file is not a valid Word (.docx) document.", 415)
    if uncompressed > _MAX_DOCX_UNCOMPRESSED:
        raise DocumentError("This document expands to an unreasonable size.", 413)
