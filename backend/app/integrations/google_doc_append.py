"""Append plain text to the end of a Google Doc (live integrations only)."""

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


def append_plain_text_to_google_doc(document_id: str, text: str) -> dict[str, Any]:
    """
    Append UTF-8 text to the end of the document body.
    Returns {ok, detail, reference?} — never raises for missing optional deps.
    """
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
        insert_index = max(1, end_index - 1)
        svc.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertText": {"location": {"index": insert_index}, "text": text}}]},
        ).execute()
        return {"ok": True, "detail": "appended", "reference": document_id}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"docs append failed: {exc}"}
