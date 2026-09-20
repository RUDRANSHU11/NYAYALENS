"""Pipeline step 3: split extracted lines into clause-sized chunks.

Chunks keep the metadata the README asks for - page number, section heading,
clause number and (via the store) document id - so every answer can be traced
back to a place in the original document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.document_processing.extract import Line

MAX_CHUNK_CHARS = 1200
MIN_CHUNK_CHARS = 40

# "1.", "2)", "3.4", "10.2.1" at the start of a line.
_NUMBERED = re.compile(r"^(?P<num>\d{1,3}(?:\.\d{1,3}){1,3})(?=[\s.):])")
_NUMBERED_TOP = re.compile(r"^(?P<num>\d{1,3})[.)](?=\s)")
# "Section 4", "Clause 5.2", "Article IV", "Schedule 2".
_LABELLED = re.compile(
    r"^(?P<kind>section|clause|article|schedule|annexure)\s+"
    r"(?P<num>\d{1,3}(?:\.\d{1,3})*|[ivxlcdm]{1,7})\b",
    re.IGNORECASE,
)


@dataclass
class Chunk:
    id: str
    text: str
    page: int | None = None
    section: str | None = None
    clause: str | None = None

    @property
    def reference(self) -> str:
        """Human-readable source reference, e.g. ``Clause 5.2 · Page 3``."""
        parts: list[str] = []
        if self.clause:
            parts.append(f"Clause {self.clause}" if self.clause[0].isdigit() else self.clause)
        elif self.section:
            parts.append(self.section)
        if self.page:
            parts.append(f"Page {self.page}")
        return " · ".join(parts) or "Document"


def clause_number(text: str) -> str | None:
    """Return the clause label a line starts with, or None if it starts mid-prose."""
    labelled = _LABELLED.match(text)
    if labelled:
        number = labelled.group("num")
        number = number if any(character.isdigit() for character in number) else number.upper()
        return f"{labelled.group('kind').capitalize()} {number}"
    for pattern in (_NUMBERED, _NUMBERED_TOP):
        match = pattern.match(text)
        if match:
            return match.group("num")
    return None


def is_heading(text: str) -> bool:
    """True for short standalone titles like ``TERMINATION`` or ``Notice Period``."""
    stripped = text.rstrip(":").strip()
    if not stripped or len(stripped) > 80 or stripped.endswith((".", ";", ",")):
        return False
    words = stripped.split()
    if len(words) > 10:
        return False
    letters = [character for character in stripped if character.isalpha()]
    if not letters:
        return False
    if all(character.isupper() for character in letters):
        return True
    capitalised = sum(1 for word in words if word[:1].isupper())
    return stripped[0].isupper() and capitalised >= max(1, len(words) - 2)


def chunk_document(lines: list[Line], max_chars: int = MAX_CHUNK_CHARS) -> list[Chunk]:
    """Group lines into chunks that start at clause numbers, headings or size limits."""
    raw: list[dict] = []
    section: str | None = None
    current: dict | None = None

    for line in lines:
        number = clause_number(line.text)
        heading = number is None and (line.heading or is_heading(line.text))
        if heading:
            section = line.text.rstrip(":").strip()

        if current is None or number or heading or current["length"] + len(line.text) > max_chars:
            current = {
                "parts": [],
                "length": 0,
                "page": line.page,
                "section": section,
                "clause": number,
            }
            raw.append(current)

        current["parts"].append(line.text)
        current["length"] += len(line.text) + 1

    return _finalise(raw)


def _finalise(raw: list[dict]) -> list[Chunk]:
    """Join the collected lines and fold stray heading-only chunks into their body."""
    merged: list[dict] = []
    for item in raw:
        item["text"] = " ".join(item["parts"]).strip()
        if merged and len(merged[-1]["text"]) < MIN_CHUNK_CHARS:
            previous = merged.pop()
            item = {
                "text": f"{previous['text']} {item['text']}".strip(),
                "page": previous["page"],
                "section": item["section"] or previous["section"],
                "clause": previous["clause"] or item["clause"],
            }
        merged.append(item)

    if len(merged) > 1 and len(merged[-1]["text"]) < MIN_CHUNK_CHARS:
        tail = merged.pop()
        merged[-1]["text"] = f"{merged[-1]['text']} {tail['text']}".strip()

    return [
        Chunk(
            id=f"c{index}",
            text=item["text"],
            page=item["page"],
            section=item["section"],
            clause=item["clause"],
        )
        for index, item in enumerate(merged)
        if item["text"]
    ]
