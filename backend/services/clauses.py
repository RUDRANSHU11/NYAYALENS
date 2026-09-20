"""Feature 3: important clause detection.

Deliberately rule-based: it is instant, free, deterministic and testable, and it
works with no LLM configured. The language model is used afterwards to *explain*
a flagged clause, not to find it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.document_processing.chunking import Chunk


@dataclass(frozen=True)
class Category:
    name: str
    pattern: re.Pattern[str]
    why: str


def _category(name: str, pattern: str, why: str) -> Category:
    return Category(name, re.compile(pattern, re.IGNORECASE), why)


CATEGORIES: tuple[Category, ...] = (
    _category(
        "Termination",
        r"terminat\w*|end this agreement|cease to (?:be in force|operate)|expiry of this",
        "Says how and when the agreement can be ended, and by whom.",
    ),
    _category(
        "Notice period",
        r"notice period|\d+\s*(?:days?|weeks?|months?)[’']?s?\s+(?:prior\s+)?(?:written\s+)?notice"
        r"|serving\s+notice|upon\s+\w*\s*notice",
        "Sets how much warning you must give - or will get - before something changes.",
    ),
    _category(
        "Penalties",
        r"penalt\w+|liquidated damages|late fee|forfeit\w*|fine of",
        "Money you may have to pay if you break a term.",
    ),
    _category(
        "Payment obligations",
        r"shall pay|payable|payment (?:of|shall|terms)|invoice|remuneration|salary|rent of"
        r"|monthly rent|fees? (?:of|payable)|due date|consideration of",
        "What you owe, how much and by when.",
    ),
    _category(
        "Confidentiality",
        r"confidential\w*|non-?disclosure|proprietary information|trade secret",
        "Limits what you may say or share, often long after the agreement ends.",
    ),
    _category(
        "Intellectual Property",
        r"intellectual property|copyright|patent\w*|trade ?mark|work product|moral rights",
        "Decides who owns what is created - often your employer, not you.",
    ),
    _category(
        "Indemnification",
        r"indemnif\w+|hold harmless|defend and hold",
        "Makes one side cover the other's losses, which can be open-ended.",
    ),
    _category(
        "Liability",
        r"liab\w+|not be responsible for|limitation of liability|consequential damages",
        "Caps or shifts who pays when something goes wrong.",
    ),
    _category(
        "Non-compete",
        r"non-?compet\w*|shall not (?:engage|work|be employed)|restraint of trade|non-?solicit\w*",
        "Restricts who you can work for or approach after leaving.",
    ),
    _category(
        "Renewal",
        r"renew\w*|auto(?:matically)?[- ]renew|extended? for (?:a )?(?:further|additional)",
        "Can roll the agreement over automatically unless you act in time.",
    ),
    _category(
        "Dispute resolution",
        r"dispute\w*|arbitrat\w+|mediation|conciliation",
        "Sets how disagreements are settled, sometimes instead of a court.",
    ),
    _category(
        "Jurisdiction",
        r"jurisdiction|governing law|courts? (?:at|of|in)\b|subject to the laws",
        "Decides whose law applies and where you would have to fight a case.",
    ),
    _category(
        "Security deposit",
        r"security deposit|refundable deposit|deposit of",
        "Money held by the other side, and the conditions for getting it back.",
    ),
    _category(
        "Data & privacy",
        r"personal (?:data|information)|data (?:collect\w*|shar\w*|process\w*|retention)"
        r"|cookies|third part(?:y|ies)",
        "What is collected about you, and who else it is shared with.",
    ),
)

CATEGORY_NOTES: dict[str, str] = {category.name: category.why for category in CATEGORIES}


def detect(text: str) -> list[str]:
    """Return the important-clause categories present in ``text``."""
    return [category.name for category in CATEGORIES if category.pattern.search(text)]


def flag(chunks: list[Chunk]) -> dict[str, list[str]]:
    """Map chunk id -> categories, for every chunk that matched at least one."""
    flags = {chunk.id: detect(chunk.text) for chunk in chunks}
    return {chunk_id: names for chunk_id, names in flags.items() if names}
