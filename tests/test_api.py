"""End-to-end API behaviour, including what happens with no AI provider set up."""

from conftest import upload

from backend import config
from backend.api import ratelimit


def test_health_reports_capabilities(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["ai_enabled"] is False  # no key in the test environment
    assert body["embeddings"].startswith(("hash", "fastembed"))


def test_health_does_not_load_the_embedding_model(client, monkeypatch):
    from backend.rag import embeddings

    monkeypatch.setattr(embeddings, "_backend", None)
    body = client.get("/api/health").json()

    assert embeddings._backend is None  # a health probe must never trigger the download
    assert "loads on first upload" in body["embeddings"]


def test_large_responses_are_gzip_compressed(client, contract_v1):
    response = client.post(
        "/api/documents", files={"file": ("contract.txt", contract_v1, "text/plain")}
    )
    assert response.headers.get("content-encoding") == "gzip"


def test_index_carries_the_disclaimer(client):
    body = client.get("/").json()
    assert "qualified lawyer" in body["disclaimer"]


def test_security_headers_are_set(client):
    headers = client.get("/api/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cache-Control"] == "no-store"


def test_upload_returns_clauses_with_references(client, contract_v1):
    body = upload(client, contract_v1)

    assert body["chunk_count"] > 5
    assert body["important_count"] > 0
    assert body["expires_in"] > 0
    assert body["ai_enabled"] is False

    notice = next(c for c in body["clauses"] if "30 days written notice" in c["text"])
    assert notice["clause"] == "4"
    assert "Notice period" in notice["categories"]
    assert notice["reference"].startswith("Clause 4")
    assert body["category_notes"]["Notice period"]


def test_uploaded_document_can_be_fetched_and_deleted(client, contract_v1):
    document_id = upload(client, contract_v1)["id"]

    assert client.get(f"/api/documents/{document_id}").status_code == 200
    assert client.delete(f"/api/documents/{document_id}").status_code == 204
    assert client.get(f"/api/documents/{document_id}").status_code == 404


def test_unknown_document_is_a_clean_404(client):
    response = client.get("/api/documents/does-not-exist")
    assert response.status_code == 404
    assert "upload it again" in response.json()["detail"]


def test_unsupported_file_type_is_rejected(client):
    response = client.post("/api/documents", files={"file": ("x.exe", b"MZ\x90\x00", "application/octet-stream")})
    assert response.status_code == 415


def test_oversized_file_is_rejected(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 128)
    response = client.post("/api/documents", files={"file": ("big.txt", b"x" * 500, "text/plain")})
    assert response.status_code == 413


def test_empty_document_is_rejected(client):
    response = client.post("/api/documents", files={"file": ("empty.txt", b"   \n  ", "text/plain")})
    assert response.status_code in (400, 422)


def test_ask_without_ai_still_returns_sources(client, contract_v1):
    document_id = upload(client, contract_v1)["id"]
    body = client.post(
        f"/api/documents/{document_id}/ask",
        json={"question": "How much notice do I have to give?"},
    ).json()

    assert body["ai_used"] is False
    assert body["notice"]
    assert body["sources"]
    assert any("30 days" in source["text"] for source in body["sources"])


def test_ask_with_ai_returns_answer_and_marks_citations(client, contract_v1, ai):
    document_id = upload(client, contract_v1)["id"]
    body = client.post(
        f"/api/documents/{document_id}/ask",
        json={"question": "How much notice do I have to give?", "language": "en"},
    ).json()

    assert body["ai_used"] is True
    assert body["grounded"] is True
    assert "30 days" in body["answer"]
    assert sum(source["cited"] for source in body["sources"]) == 1
    assert "<document_extract>" in ai[-1]  # context was actually sent


def test_repeated_question_is_served_from_cache(client, contract_v1, ai):
    document_id = upload(client, contract_v1)["id"]
    url = f"/api/documents/{document_id}/ask"

    first = client.post(url, json={"question": "How much notice do I give?"}).json()
    calls = len(ai)
    again = client.post(url, json={"question": "  how much NOTICE do I give? "}).json()

    assert len(ai) == calls  # no second model call for the same question
    assert again == first


def test_failed_answers_are_not_cached(client, contract_v1):
    document_id = upload(client, contract_v1)["id"]
    client.post(f"/api/documents/{document_id}/ask", json={"question": "Notice period?"})

    from backend.rag import store

    assert store.get(document_id).answers == {}  # no AI configured -> nothing cached


def test_ask_validates_the_question(client, contract_v1):
    document_id = upload(client, contract_v1)["id"]
    assert client.post(f"/api/documents/{document_id}/ask", json={"question": "?"}).status_code == 422
    too_long = "a" * (config.MAX_QUESTION_CHARS + 1)
    assert (
        client.post(f"/api/documents/{document_id}/ask", json={"question": too_long}).status_code
        == 422
    )


def test_explain_without_ai_is_unavailable(client, contract_v1):
    body = upload(client, contract_v1)
    response = client.post(
        f"/api/documents/{body['id']}/clauses/{body['clauses'][0]['id']}/explain",
        json={"language": "en"},
    )
    assert response.status_code == 503


def test_explain_returns_plain_language_and_caches_it(client, contract_v1, ai):
    body = upload(client, contract_v1)
    clause = next(c for c in body["clauses"] if c["clause"] == "4")
    url = f"/api/documents/{body['id']}/clauses/{clause['id']}/explain"

    first = client.post(url, json={"language": "en"}).json()
    assert first["obligations"] == ["Give 30 days written notice"]
    assert first["original"].startswith("4. NOTICE PERIOD")

    calls_after_first = len(ai)
    client.post(url, json={"language": "en"})
    assert len(ai) == calls_after_first  # served from the per-document cache


def test_explain_unknown_clause_is_404(client, contract_v1, ai):
    document_id = upload(client, contract_v1)["id"]
    response = client.post(
        f"/api/documents/{document_id}/clauses/c999/explain", json={"language": "en"}
    )
    assert response.status_code == 404


def test_compare_endpoint_reports_changes(client, contract_v1, contract_v2):
    response = client.post(
        "/api/compare",
        files={
            "file_a": ("v1.txt", contract_v1, "text/plain"),
            "file_b": ("v2.txt", contract_v2, "text/plain"),
        },
        data={"language": "en"},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["added"] >= 2 and body["modified"] >= 4
    assert body["ai_used"] is False  # no provider configured
    notice_change = next(
        change
        for change in body["changes"]
        if change["text_after"] and "60 days written notice" in change["text_after"]
    )
    assert {"kind": "duration", "before": "30 days", "after": "60 days"} in notice_change["values"]
    assert notice_change["significant"] is True


def test_compare_with_ai_attaches_impact(client, contract_v1, contract_v2, ai):
    body = client.post(
        "/api/compare",
        files={
            "file_a": ("v1.txt", contract_v1, "text/plain"),
            "file_b": ("v2.txt", contract_v2, "text/plain"),
        },
        data={"language": "hi"},
    ).json()

    assert body["ai_used"] is True
    assert body["changes"][0]["impact"] == "You now need to give twice as much notice."


def test_rate_limit_kicks_in(client, contract_v1, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MINUTE", 2)
    ratelimit.reset()

    files = {"file": ("contract.txt", contract_v1, "text/plain")}
    assert client.post("/api/documents", files=files).status_code == 201
    assert client.post("/api/documents", files=files).status_code == 201
    third = client.post("/api/documents", files=files)
    assert third.status_code == 429
    assert third.headers["Retry-After"] == "60"


def test_scanned_pdf_without_ai_explains_why_it_failed(client):
    from tests.test_extraction import build_pdf

    response = client.post(
        "/api/documents", files={"file": ("scan.pdf", build_pdf("", pages=1), "application/pdf")}
    )
    assert response.status_code == 422
    assert "scanned" in response.json()["detail"]


def test_scanned_pdf_is_read_with_ocr_when_ai_is_available(client, ai):
    from tests.test_extraction import build_pdf

    body = upload(client, build_pdf("", pages=1), name="scan.pdf")
    assert body["ocr_used"] is True
    assert any("30 days written notice" in clause["text"] for clause in body["clauses"])
