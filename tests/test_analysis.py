"""The model-facing tasks, with the provider stubbed out."""

import asyncio
import base64

from backend.services import analysis, llm


def test_ocr_reads_pages_concurrently_and_keeps_page_order(monkeypatch):
    active = peak = 0

    async def fake_complete(messages, **_kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        active -= 1
        data_url = messages[-1]["content"][1]["image_url"]["url"]
        return base64.b64decode(data_url.split(",", 1)[1]).decode()

    monkeypatch.setattr(llm, "complete", fake_complete)
    pages = [f"page-{number}".encode() for number in range(6)]

    assert asyncio.run(analysis.ocr_pages(pages)) == [f"page-{number}" for number in range(6)]
    assert peak > 1  # pages overlapped instead of queueing behind each other


def test_ocr_concurrency_is_bounded(monkeypatch):
    active = peak = 0

    async def fake_complete(_messages, **_kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return "text"

    monkeypatch.setattr(llm, "complete", fake_complete)
    asyncio.run(analysis.ocr_pages([b"page"] * 20))

    assert peak <= analysis._OCR_CONCURRENCY  # never stampedes the provider


def test_ocr_of_no_pages_makes_no_calls(monkeypatch):
    async def fail(*_args, **_kwargs):
        raise AssertionError("the model should not be called for zero pages")

    monkeypatch.setattr(llm, "complete", fail)
    assert asyncio.run(analysis.ocr_pages([])) == []
