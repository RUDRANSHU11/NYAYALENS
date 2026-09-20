"""Test configuration.

The environment is pinned *before* the backend is imported so the suite never
touches the network: hashing embeddings instead of the ONNX model, and no LLM
key, so every "is AI configured?" branch is exercised deliberately.
"""

import os
from pathlib import Path

os.environ["EMBEDDINGS"] = "hash"
os.environ["LLM_API_KEY"] = ""
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.api import ratelimit  # noqa: E402
from backend.main import app  # noqa: E402
from backend.rag import store  # noqa: E402
from backend.services import llm  # noqa: E402

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def _clean_state():
    store.clear()
    ratelimit.reset()
    yield
    store.clear()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def contract_v1() -> bytes:
    return (DATA / "sample_employment_v1.txt").read_bytes()


@pytest.fixture
def contract_v2() -> bytes:
    return (DATA / "sample_employment_v2.txt").read_bytes()


@pytest.fixture
def ai(monkeypatch):
    """Stand in for the model provider. Returns the list of prompts it received."""
    prompts: list[str] = []

    def fake_complete_json(messages, **_kwargs):
        prompt = messages[-1]["content"]
        prompts.append(prompt)
        if '"impacts"' in prompt:
            return {"impacts": [{"id": "ch0", "impact": "You now need to give twice as much notice."}]}
        if '"citations"' in prompt:
            return {"answer": "You must give 30 days written notice.", "citations": [1], "found": True}
        return {
            "explanation": "You have to tell the company a month before you leave.",
            "obligations": ["Give 30 days written notice"],
            "rights": ["Receive the same notice from the company"],
            "watch_out": ["Salary may be paid instead of notice"],
        }

    def fake_complete(messages, **_kwargs):
        prompts.append("ocr")
        return "1. SCANNED CLAUSE\nThe Employee shall give 30 days written notice."

    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "complete_json", fake_complete_json)
    monkeypatch.setattr(llm, "complete", fake_complete)
    return prompts


def upload(client, data: bytes, name: str = "contract.txt") -> dict:
    """Upload a document and return the API payload."""
    response = client.post("/api/documents", files={"file": (name, data, "text/plain")})
    assert response.status_code == 201, response.text
    return response.json()
