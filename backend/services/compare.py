"""Feature 2: contract comparison.

Two versions of a contract are aligned clause by clause with difflib, then each
pair is diffed at word level and scanned for changed amounts, dates, durations
and obligations. All of it is deterministic - the LLM is only asked afterwards to
explain what the significant changes mean in practice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from backend.document_processing.chunking import Chunk
from backend.services import clauses

# Two clauses are "the same clause, edited" above this similarity, else one was
# removed and another added.
PAIR_THRESHOLD = 0.55
# ponytail: pairing inside a replace block is O(n*m); past this we align by
# position instead. Raise it only if real contracts start losing pairs.
MAX_PAIRING_BLOCK = 40

_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "amount",
        re.compile(
            r"(?:₹|rs\.?|inr|usd|eur|\$|€)\s?\d[\d,]*(?:\.\d+)?"
            r"(?:\s?(?:lakhs?|crores?|million|thousand|k))?",
            re.IGNORECASE,
        ),
    ),
    (
        "duration",
        re.compile(
            r"\b\d{1,4}\s*(?:calendar |business |working )?(?:day|week|month|year)s?\b",
            re.IGNORECASE,
        ),
    ),
    ("percentage", re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%")),
    (
        "date",
        re.compile(
            r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
            r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
            r"[a-z]*\.?,?\s+\d{4}"
            r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b",
            re.IGNORECASE,
        ),
    ),
)

# Modal verbs carry the normative weight in a contract: "shall"/"must" create
# duties, "may" grants discretion. Losing either side of that is a real change,
# so permissions count here too.
_OBLIGATION = re.compile(
    r"\b(?:shall|must|will|may|agrees? to|required to|oblig\w+|entitled to)\b",
    re.IGNORECASE,
)


@dataclass
class ValueChange:
    kind: str  # amount | duration | percentage | date
    before: str | None
    after: str | None


@dataclass
class Segment:
    op: str  # equal | added | removed
    text: str


@dataclass
class Change:
    id: str
    kind: str  # added | removed | modified
    label: str
    reference_before: str | None = None
    reference_after: str | None = None
    text_before: str | None = None
    text_after: str | None = None
    categories: list[str] = field(default_factory=list)
    values: list[ValueChange] = field(default_factory=list)
    diff: list[Segment] = field(default_factory=list)
    obligation_changed: bool = False

    @property
    def significant(self) -> bool:
        return bool(
            self.kind != "modified" or self.categories or self.values or self.obligation_changed
        )


@dataclass
class Comparison:
    added: int
    removed: int
    modified: int
    unchanged: int
    changes: list[Change]


def compare(before: list[Chunk], after: list[Chunk]) -> Comparison:
    """Align two versions of a contract and describe what changed."""
    matcher = SequenceMatcher(
        None, [_key(chunk) for chunk in before], [_key(chunk) for chunk in after], autojunk=False
    )

    changes: list[Change] = []
    unchanged = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            unchanged += i2 - i1
        elif tag == "delete":
            changes.extend(_removed(chunk) for chunk in before[i1:i2])
        elif tag == "insert":
            changes.extend(_added(chunk) for chunk in after[j1:j2])
        else:
            changes.extend(_pair(before[i1:i2], after[j1:j2]))

    changes.sort(key=lambda change: not change.significant)  # stable: keeps document order
    for index, change in enumerate(changes):
        change.id = f"ch{index}"

    return Comparison(
        added=sum(1 for change in changes if change.kind == "added"),
        removed=sum(1 for change in changes if change.kind == "removed"),
        modified=sum(1 for change in changes if change.kind == "modified"),
        unchanged=unchanged,
        changes=changes,
    )


def word_diff(before: str, after: str) -> list[Segment]:
    """Word-level diff, as ordered equal/removed/added segments."""
    old, new = before.split(), after.split()
    segments: list[Segment] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ("delete", "replace"):
            segments.append(Segment("removed", " ".join(old[i1:i2])))
        if tag in ("insert", "replace"):
            segments.append(Segment("added", " ".join(new[j1:j2])))
        if tag == "equal":
            segments.append(Segment("equal", " ".join(old[i1:i2])))
    return segments


def value_changes(before: str, after: str) -> list[ValueChange]:
    """Amounts, durations, percentages and dates that differ between two clauses."""
    found: list[ValueChange] = []
    for kind, pattern in _VALUE_PATTERNS:
        old = [match.group(0).strip() for match in pattern.finditer(before)]
        new = [match.group(0).strip() for match in pattern.finditer(after)]
        dropped, introduced = _difference(old, new), _difference(new, old)
        for index in range(max(len(dropped), len(introduced))):
            found.append(
                ValueChange(
                    kind=kind,
                    before=dropped[index] if index < len(dropped) else None,
                    after=introduced[index] if index < len(introduced) else None,
                )
            )
    return found


def _pair(olds: list[Chunk], news: list[Chunk]) -> list[Change]:
    if len(olds) * len(news) > MAX_PAIRING_BLOCK**2:
        paired = [_modified(old, new) for old, new in zip(olds, news)]
        paired.extend(_removed(chunk) for chunk in olds[len(news) :])
        paired.extend(_added(chunk) for chunk in news[len(olds) :])
        return paired

    matched: set[int] = set()
    changes: list[Change] = []
    for old in olds:
        best_index, best_ratio = -1, 0.0
        for index, new in enumerate(news):
            if index in matched:
                continue
            matcher = SequenceMatcher(None, old.text, new.text)
            if matcher.quick_ratio() < PAIR_THRESHOLD:
                continue
            ratio = matcher.ratio()
            if ratio > best_ratio:
                best_index, best_ratio = index, ratio
        if best_ratio >= PAIR_THRESHOLD:
            matched.add(best_index)
            changes.append(_modified(old, news[best_index]))
        else:
            changes.append(_removed(old))

    changes.extend(_added(new) for index, new in enumerate(news) if index not in matched)
    return changes


def _modified(old: Chunk, new: Chunk) -> Change:
    diff = word_diff(old.text, new.text)
    edited = " ".join(segment.text for segment in diff if segment.op != "equal")
    return Change(
        id="",
        kind="modified",
        label=new.reference,
        reference_before=old.reference,
        reference_after=new.reference,
        text_before=old.text,
        text_after=new.text,
        categories=sorted(set(clauses.detect(old.text)) | set(clauses.detect(new.text))),
        values=value_changes(old.text, new.text),
        diff=diff,
        obligation_changed=bool(_OBLIGATION.search(edited)),
    )


def _added(chunk: Chunk) -> Change:
    return Change(
        id="",
        kind="added",
        label=chunk.reference,
        reference_after=chunk.reference,
        text_after=chunk.text,
        categories=clauses.detect(chunk.text),
        diff=[Segment("added", chunk.text)],
    )


def _removed(chunk: Chunk) -> Change:
    return Change(
        id="",
        kind="removed",
        label=chunk.reference,
        reference_before=chunk.reference,
        text_before=chunk.text,
        categories=clauses.detect(chunk.text),
        diff=[Segment("removed", chunk.text)],
    )


def _key(chunk: Chunk) -> str:
    return " ".join(chunk.text.lower().split())


def _difference(source: list[str], other: list[str]) -> list[str]:
    """Values in ``source`` that ``other`` does not also contain (multiset aware)."""
    remaining = [value.lower() for value in other]
    missing: list[str] = []
    for value in source:
        key = value.lower()
        if key in remaining:
            remaining.remove(key)
        else:
            missing.append(value)
    return missing
