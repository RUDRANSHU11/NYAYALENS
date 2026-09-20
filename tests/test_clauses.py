"""Important-clause detection is rule-based, so it can be asserted exactly."""

import pytest

from backend.document_processing.chunking import Chunk
from backend.services import clauses


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Either party may terminate this Agreement on 30 days written notice.", "Termination"),
        ("Either party may terminate this Agreement on 30 days written notice.", "Notice period"),
        ("The Employee shall pay liquidated damages of Rs. 1,00,000.", "Penalties"),
        ("The Company shall pay a gross salary of Rs. 9,00,000 per annum.", "Payment obligations"),
        ("The Employee shall not disclose confidential information.", "Confidentiality"),
        ("All work product shall be the intellectual property of the Company.", "Intellectual Property"),
        ("The Vendor shall indemnify and hold harmless the Client.", "Indemnification"),
        ("Neither party shall be liable for consequential damages.", "Liability"),
        ("The Employee shall not be employed by any competing business.", "Non-compete"),
        ("This Agreement shall automatically renew for a further 12 months.", "Renewal"),
        ("Any dispute shall be referred to arbitration at Pune.", "Dispute resolution"),
        ("The courts at Pune shall have exclusive jurisdiction.", "Jurisdiction"),
        ("The Tenant shall pay a security deposit of Rs. 50,000.", "Security deposit"),
        ("We share your personal data with third parties for analytics.", "Data & privacy"),
    ],
)
def test_categories_are_detected(text, expected):
    assert expected in clauses.detect(text)


def test_plain_prose_is_not_flagged():
    assert clauses.detect("The Employee will be based at the Pune office.") == []


def test_every_category_has_a_plain_language_note():
    assert set(clauses.CATEGORY_NOTES) == {category.name for category in clauses.CATEGORIES}
    assert all(note and note[0].isupper() for note in clauses.CATEGORY_NOTES.values())


def test_flag_returns_only_matching_chunks():
    chunks = [
        Chunk(id="c0", text="The Employee will be based at the Pune office."),
        Chunk(id="c1", text="Either party may terminate this Agreement."),
    ]
    flags = clauses.flag(chunks)
    assert list(flags) == ["c1"]
    assert "Termination" in flags["c1"]
