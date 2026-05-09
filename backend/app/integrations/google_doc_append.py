"""Google Docs pulse writer with structured formatting."""

from __future__ import annotations

import base64
import json
import os
from typing import Any


def _docs_service():
    from google.oauth2 import service_account  # type: ignore[import-not-found]
    from googleapiclient.discovery import build  # type: ignore[import-not-found]

    scopes = ["https://www.googleapis.com/auth/documents"]
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_BASE64")
    if raw:
        parsed = json.loads(base64.b64decode(raw).decode("utf-8"))
        creds = service_account.Credentials.from_service_account_info(parsed, scopes=scopes)
        return build("docs", "v1", credentials=creds, cache_discovery=False)
    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not path:
        raise RuntimeError("Google credentials not configured")
    creds = service_account.Credentials.from_service_account_file(path, scopes=scopes)
    return build("docs", "v1", credentials=creds, cache_discovery=False)


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _build_pulse_doc_requests(pulse: dict[str, Any], *, insert_index: int, add_page_break: bool) -> list[dict[str, Any]]:
    generated = _safe_text(pulse.get("generated_at"))
    title = f"Pulse #{pulse.get('pulse_id')} — {generated or 'Unknown date'}"
    reviews = (
        f"Reviews sampled: {pulse.get('review_count')} | "
        f"Date range: {pulse.get('date_from')} → {pulse.get('date_to')}"
    )
    analysis = _safe_text(pulse.get("analysis")) or "No analysis available."
    themes = list(pulse.get("top_themes") or [])
    actions = list(pulse.get("actions") or [])

    lines: list[str] = []
    lines.append(title)
    lines.append(reviews)
    lines.append(analysis)
    lines.append("Top Themes")
    theme_line_ranges: list[dict[str, int]] = []
    theme_quote_ranges: list[dict[str, int]] = []
    for t in themes:
        label = _safe_text(t.get("label")) or "Theme"
        volume = t.get("volume")
        quote = _safe_text(t.get("quote")) or "No quote available."
        prefix = f"{label} (n={volume})"
        line = f"{prefix}: {quote}"
        lines.append(line)
        line_start_rel = sum(len(x) + 1 for x in lines[:-1])
        theme_line_ranges.append({"start": line_start_rel, "end": line_start_rel + len(line)})
        quote_start = line.find(quote)
        if quote_start >= 0:
            theme_quote_ranges.append(
                {"start": line_start_rel + quote_start, "end": line_start_rel + quote_start + len(quote)}
            )
    lines.append("Actions")
    action_line_ranges: list[dict[str, int]] = []
    for a in actions:
        action_text = _safe_text(a)
        if not action_text:
            continue
        lines.append(action_text)
        line_start_rel = sum(len(x) + 1 for x in lines[:-1])
        action_line_ranges.append({"start": line_start_rel, "end": line_start_rel + len(action_text)})
    lines.append("")
    block_text = "\n".join(lines)

    title_start = 0
    reviews_start = len(title) + 1
    analysis_start = reviews_start + len(reviews) + 1
    top_themes_start = analysis_start + len(analysis) + 1
    actions_heading_start = top_themes_start + len("Top Themes") + 1 + sum(len(lines[i]) + 1 for i in range(4, 4 + len(themes)))

    reqs: list[dict[str, Any]] = [
        {"insertText": {"location": {"index": insert_index}, "text": block_text}},
        {
            "updateParagraphStyle": {
                "range": {"startIndex": insert_index + title_start, "endIndex": insert_index + title_start + len(title)},
                "paragraphStyle": {"namedStyleType": "HEADING_1"},
                "fields": "namedStyleType",
            }
        },
        {
            "updateTextStyle": {
                "range": {"startIndex": insert_index + reviews_start, "endIndex": insert_index + reviews_start + len(reviews)},
                "textStyle": {"bold": True},
                "fields": "bold",
            }
        },
        {
            "updateParagraphStyle": {
                "range": {
                    "startIndex": insert_index + top_themes_start,
                    "endIndex": insert_index + top_themes_start + len("Top Themes"),
                },
                "paragraphStyle": {"namedStyleType": "HEADING_2"},
                "fields": "namedStyleType",
            }
        },
        {
            "updateParagraphStyle": {
                "range": {
                    "startIndex": insert_index + actions_heading_start,
                    "endIndex": insert_index + actions_heading_start + len("Actions"),
                },
                "paragraphStyle": {"namedStyleType": "HEADING_2"},
                "fields": "namedStyleType",
            }
        },
    ]

    if theme_line_ranges:
        reqs.append(
            {
                "createParagraphBullets": {
                    "range": {
                        "startIndex": insert_index + theme_line_ranges[0]["start"],
                        "endIndex": insert_index + theme_line_ranges[-1]["end"] + 1,
                    },
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            }
        )
        for rng in theme_line_ranges:
            colon_idx = block_text[rng["start"] : rng["end"]].find(":")
            bold_end = rng["end"] if colon_idx < 0 else rng["start"] + colon_idx
            reqs.append(
                {
                    "updateTextStyle": {
                        "range": {"startIndex": insert_index + rng["start"], "endIndex": insert_index + bold_end},
                        "textStyle": {"bold": True},
                        "fields": "bold",
                    }
                }
            )
        for rng in theme_quote_ranges:
            reqs.append(
                {
                    "updateTextStyle": {
                        "range": {"startIndex": insert_index + rng["start"], "endIndex": insert_index + rng["end"]},
                        "textStyle": {"italic": True},
                        "fields": "italic",
                    }
                }
            )

    if action_line_ranges:
        reqs.append(
            {
                "createParagraphBullets": {
                    "range": {
                        "startIndex": insert_index + action_line_ranges[0]["start"],
                        "endIndex": insert_index + action_line_ranges[-1]["end"] + 1,
                    },
                    "bulletPreset": "NUMBERED_DECIMAL_NESTED",
                }
            }
        )

    if add_page_break:
        reqs.append({"insertPageBreak": {"location": {"index": insert_index + len(block_text)}}})
    return reqs


def append_structured_pulse_to_google_doc(document_id: str, pulse: dict[str, Any]) -> dict[str, Any]:
    """Insert latest pulse at top with Docs-native formatting."""
    if not document_id.strip():
        return {"ok": False, "detail": "missing document id"}
    try:
        svc = _docs_service()
    except ImportError:
        return {"ok": False, "detail": "google-api-python-client not installed"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"credentials error: {exc}"}
    try:
        doc = svc.documents().get(documentId=document_id).execute()
        body = doc.get("body") or {}
        content = body.get("content") or []
        end_index = 1
        for el in content:
            if isinstance(el, dict) and "endIndex" in el:
                end_index = max(end_index, int(el["endIndex"]))
        has_existing_content = end_index > 2
        requests = _build_pulse_doc_requests(pulse, insert_index=1, add_page_break=has_existing_content)
        svc.documents().batchUpdate(documentId=document_id, body={"requests": requests}).execute()
        return {"ok": True, "detail": "pulse inserted at top", "reference": document_id}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"docs append failed: {exc}"}
