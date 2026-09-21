"""The model-facing tasks, with the provider stubbed out."""

import base64
import threading
import time

from backend.services import analysis, llm


def test_ocr_reads_pages_concurrently_and_keeps_page_order(monkeypatch):
    active = peak = 0
    lock = threading.Lock()

    def fake_complete(messages, **_kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        data_url = messages[-1]["content"][1]["image_url"]["url"]
        return base64.b64decode(data_url.split(",", 1)[1]).decode()

    monkeypatch.setattr(llm, "complete", fake_complete)
    pages = [f"page-{number}".encode() for number in range(6)]

    assert analysis.ocr_pages(pages) == [f"page-{number}" for number in range(6)]
    assert peak > 1  # pages overlapped instead of queueing behind each other


def test_ocr_of_no_pages_makes_no_calls(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError))
    assert analysis.ocr_pages([]) == []
