"""Contract comparison: alignment, value changes and significance."""

from backend.document_processing.chunking import Chunk
from backend.services.compare import compare, value_changes, word_diff


def chunks(*texts: str) -> list[Chunk]:
    return [Chunk(id=f"c{index}", text=text, clause=str(index + 1)) for index, text in enumerate(texts)]


NOTICE_V1 = "4. NOTICE PERIOD Either party may terminate this Agreement by giving 30 days written notice."
NOTICE_V2 = "4. NOTICE PERIOD Either party may terminate this Agreement by giving 60 days written notice."


def test_readme_example_thirty_to_sixty_days():
    result = compare(chunks(NOTICE_V1), chunks(NOTICE_V2))

    assert (result.added, result.removed, result.modified) == (0, 0, 1)
    change = result.changes[0]
    assert change.kind == "modified"
    assert change.significant
    assert "Notice period" in change.categories
    assert [(value.before, value.after) for value in change.values if value.kind == "duration"] == [
        ("30 days", "60 days")
    ]


def test_identical_documents_report_no_changes():
    result = compare(chunks(NOTICE_V1), chunks(NOTICE_V1))
    assert result.changes == []
    assert result.unchanged == 1


def test_added_and_removed_clauses():
    before = chunks("1. RENT The Tenant shall pay Rs. 25,000 monthly.", "2. LEAVE Annual leave is 18 days.")
    after = chunks(
        "1. RENT The Tenant shall pay Rs. 25,000 monthly.",
        "3. NON-COMPETE The Tenant shall not sublet the premises to a competitor.",
    )
    result = compare(before, after)

    kinds = {change.kind for change in result.changes}
    assert kinds == {"added", "removed"}
    assert result.added == 1 and result.removed == 1
    assert result.unchanged == 1


def test_renumbered_clause_is_paired_not_reported_as_added_and_removed():
    before = chunks("9. DISPUTE RESOLUTION Any dispute shall be referred to arbitration at Pune.")
    after = chunks("8. DISPUTE RESOLUTION Any dispute shall be referred to arbitration at Pune.")
    result = compare(before, after)

    assert result.modified == 1
    assert result.added == 0 and result.removed == 0


def test_changed_amount_is_extracted():
    before = chunks("2. COMPENSATION The Company shall pay Rs. 9,00,000 per annum.")
    after = chunks("2. COMPENSATION The Company shall pay Rs. 10,80,000 per annum.")
    change = compare(before, after).changes[0]

    amounts = [value for value in change.values if value.kind == "amount"]
    assert (amounts[0].before, amounts[0].after) == ("Rs. 9,00,000", "Rs. 10,80,000")


def test_removed_obligation_is_flagged():
    before = chunks("4. NOTICE The Company may pay salary in lieu of notice. Notice shall be written.")
    after = chunks("4. NOTICE Notice shall be written.")
    change = compare(before, after).changes[0]

    assert change.obligation_changed
    assert "salary in lieu" in " ".join(
        segment.text for segment in change.diff if segment.op == "removed"
    )


def test_significant_changes_are_listed_first():
    before = chunks(
        "1. INTRODUCTION This document sets out the arrangement between the parties here.",
        "2. NOTICE Either party may terminate on 30 days notice.",
    )
    after = chunks(
        "1. INTRODUCTION This document sets out the arrangement between both parties here.",
        "2. NOTICE Either party may terminate on 60 days notice.",
    )
    result = compare(before, after)

    assert result.changes[0].significant
    assert not result.changes[-1].significant


def test_word_diff_marks_both_sides():
    segments = word_diff("give 30 days notice", "give 60 days notice")
    assert [segment.op for segment in segments] == ["equal", "removed", "added", "equal"]
    assert segments[1].text == "30" and segments[2].text == "60"


def test_value_changes_handles_dates_and_percentages():
    changes = value_changes(
        "The rate is 5% and the term starts on 01/04/2026.",
        "The rate is 8% and the term starts on 01/07/2026.",
    )
    kinds = {change.kind: (change.before, change.after) for change in changes}
    assert kinds["percentage"] == ("5%", "8%")
    assert kinds["date"] == ("01/04/2026", "01/07/2026")


def test_comparison_of_the_sample_contracts(contract_v1, contract_v2):
    from backend.document_processing.chunking import chunk_document
    from backend.document_processing.extract import extract

    before = chunk_document(extract("v1.txt", contract_v1).lines)
    after = chunk_document(extract("v2.txt", contract_v2).lines)
    result = compare(before, after)

    assert result.added >= 2  # non-compete and penalty clauses
    assert result.modified >= 4  # salary, probation, notice, termination, confidentiality
    assert result.unchanged >= 3
    durations = [
        (value.before, value.after)
        for change in result.changes
        for value in change.values
        if value.kind == "duration"
    ]
    assert ("30 days", "60 days") in durations
