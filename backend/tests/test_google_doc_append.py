"""Unit tests for structured Google Doc pulse insertion."""

from __future__ import annotations

from app.integrations import google_doc_append


class _FakeBatch:
    def __init__(self, sink: dict) -> None:
        self._sink = sink

    def execute(self):
        self._sink["executed"] = True
        return {"ok": True}


class _FakeDocuments:
    def __init__(self, sink: dict, end_index: int) -> None:
        self._sink = sink
        self._end_index = end_index

    def get(self, documentId: str):
        self._sink["get_document_id"] = documentId
        return self

    def batchUpdate(self, documentId: str, body: dict):
        self._sink["batch_document_id"] = documentId
        self._sink["batch_body"] = body
        return _FakeBatch(self._sink)

    def execute(self):
        return {"body": {"content": [{"endIndex": 1}, {"endIndex": self._end_index}]}}


class _FakeService:
    def __init__(self, sink: dict, end_index: int) -> None:
        self._docs = _FakeDocuments(sink, end_index)

    def documents(self):
        return self._docs


def _sample_pulse() -> dict:
    return {
        "pulse_id": 12,
        "generated_at": "2026-05-09T15:40:00",
        "review_count": 143,
        "date_from": "2026-04-25",
        "date_to": "2026-05-07",
        "analysis": "Pulse summary paragraph.",
        "top_themes": [
            {"label": "Stock trading", "volume": 61, "quote": "App freezes in middle of trade."},
            {"label": "Expense ratio", "volume": 20, "quote": "Need better cost visibility."},
        ],
        "actions": ["Improve monitoring.", "Reduce response time."],
    }


def test_append_structured_pulse_inserts_at_top_and_formats(monkeypatch) -> None:
    sink: dict = {}
    monkeypatch.setattr(google_doc_append, "_docs_service", lambda: _FakeService(sink, end_index=220))
    out = google_doc_append.append_structured_pulse_to_google_doc("doc-1", _sample_pulse())
    assert out["ok"] is True
    reqs = sink["batch_body"]["requests"]
    assert reqs[0]["insertText"]["location"]["index"] == 1
    assert "Pulse #12" in reqs[0]["insertText"]["text"]
    assert any("updateParagraphStyle" in r and r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == "HEADING_1" for r in reqs)
    assert any("createParagraphBullets" in r and r["createParagraphBullets"]["bulletPreset"] == "BULLET_DISC_CIRCLE_SQUARE" for r in reqs)
    assert any("createParagraphBullets" in r and r["createParagraphBullets"]["bulletPreset"] == "NUMBERED_DECIMAL_NESTED" for r in reqs)
    assert any("insertPageBreak" in r for r in reqs)


def test_append_structured_pulse_without_existing_content_skips_page_break(monkeypatch) -> None:
    sink: dict = {}
    monkeypatch.setattr(google_doc_append, "_docs_service", lambda: _FakeService(sink, end_index=2))
    out = google_doc_append.append_structured_pulse_to_google_doc("doc-2", _sample_pulse())
    assert out["ok"] is True
    reqs = sink["batch_body"]["requests"]
    assert not any("insertPageBreak" in r for r in reqs)
