"""Chunking keeps clause, section and page metadata - everything downstream
(citations, comparison, retrieval) depends on it being right."""

from backend.document_processing.chunking import (
    chunk_document,
    clause_number,
    is_heading,
)
from backend.document_processing.extract import Line


def lines(*items) -> list[Line]:
    return [Line(page=page, text=text) for page, text in items]


def test_clause_numbers_are_recognised():
    assert clause_number("1. TERMINATION") == "1"
    assert clause_number("5.2 The Employee shall give notice.") == "5.2"
    assert clause_number("2) Payment terms") == "2"
    assert clause_number("Section 4 Confidentiality") == "Section 4"
    assert clause_number("Article IV") == "Article IV"


def test_prose_is_not_mistaken_for_a_clause_number():
    assert clause_number("30 days written notice is required.") is None
    assert clause_number("The Employee shall report to the manager.") is None


def test_headings_are_recognised():
    assert is_heading("TERMINATION")
    assert is_heading("Notice Period:")
    assert not is_heading("The Employee shall not disclose confidential information.")
    assert not is_heading("")


def test_each_numbered_clause_becomes_its_own_chunk():
    chunks = chunk_document(
        lines(
            (1, "1. NOTICE PERIOD"),
            (1, "Either party may terminate by giving 30 days written notice to the other."),
            (1, "2. CONFIDENTIALITY"),
            (1, "The Employee shall not disclose confidential information to any third party."),
        )
    )
    assert [chunk.clause for chunk in chunks] == ["1", "2"]
    assert "30 days" in chunks[0].text
    assert chunks[0].reference == "Clause 1 · Page 1"


def test_heading_only_line_is_folded_into_the_clause_below_it():
    chunks = chunk_document(
        lines(
            (2, "TERMINATION"),
            (2, "The Company may end this agreement at any time for misconduct or absence."),
        )
    )
    assert len(chunks) == 1
    assert chunks[0].section == "TERMINATION"
    assert chunks[0].text.startswith("TERMINATION")


def test_section_heading_carries_to_following_clauses():
    chunks = chunk_document(
        lines(
            (1, "PART B - OBLIGATIONS OF THE TENANT"),
            (1, "3.1 The Tenant shall pay the monthly rent on or before the fifth day."),
            (1, "3.2 The Tenant shall maintain the premises in good condition at all times."),
        )
    )
    assert [chunk.section for chunk in chunks[-2:]] == [
        "PART B - OBLIGATIONS OF THE TENANT"
    ] * 2
    assert chunks[-1].clause == "3.2"


def test_long_unnumbered_text_is_split_by_size():
    sentence = "This privacy policy explains how we collect and use your personal data. "
    chunks = chunk_document(lines(*[(1, sentence) for _ in range(40)]), max_chars=300)
    assert len(chunks) > 1
    assert all(len(chunk.text) <= 400 for chunk in chunks)


def test_pages_are_preserved_across_a_page_break():
    chunks = chunk_document(
        lines(
            (1, "4. PAYMENT"),
            (1, "The Company shall pay the fee within thirty days of the invoice date."),
            (2, "5. LIABILITY"),
            (2, "Neither party shall be liable for indirect or consequential damages."),
        )
    )
    assert [chunk.page for chunk in chunks] == [1, 2]
    assert chunks[1].reference == "Clause 5 · Page 2"


def test_empty_input_produces_no_chunks():
    assert chunk_document([]) == []
