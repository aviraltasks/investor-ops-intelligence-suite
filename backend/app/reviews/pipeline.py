"""Play Store review ingestion with CSV fallback."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_play_store_app_id, get_reviews_fallback_csv
from app.db.models import Review


@dataclass
class ReviewRecord:
    external_id: str
    content: str
    score: float | None
    review_at: datetime | None
    source: str


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def fetch_reviews_from_play_store(app_id: str, limit: int = 200) -> list[ReviewRecord]:
    """Fetch reviews from Google Play using google-play-scraper."""
    from google_play_scraper import Sort, reviews  # type: ignore[import-not-found]

    rows, _ = reviews(
        app_id,
        lang="en",
        country="in",
        sort=Sort.NEWEST,
        count=limit,
    )
    out: list[ReviewRecord] = []
    for row in rows:
        review_id = str(row.get("reviewId") or row.get("userName") or "")
        content = (row.get("content") or "").strip()
        if not review_id or not content:
            continue
        score_raw = row.get("score")
        score = float(score_raw) if score_raw is not None else None
        out.append(
            ReviewRecord(
                external_id=review_id,
                content=content,
                score=score,
                review_at=row.get("at"),
                source="play_store",
            )
        )
    return out


def load_reviews_from_csv(path: str) -> list[ReviewRecord]:
    """Load fallback reviews from CSV with permissive column names."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[ReviewRecord] = []
    with p.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            external_id = (
                row.get("external_id")
                or row.get("review_id")
                or row.get("id")
                or ""
            ).strip()
            content = (row.get("content") or row.get("review") or "").strip()
            score_raw = (row.get("score") or row.get("rating") or "").strip()
            score = float(score_raw) if score_raw else None
            review_at = _parse_dt(row.get("review_at") or row.get("at") or row.get("date"))
            if not external_id or not content:
                continue
            out.append(
                ReviewRecord(
                    external_id=external_id,
                    content=content,
                    score=score,
                    review_at=review_at,
                    source="csv_fallback",
                )
            )
    return out


def fetch_reviews_with_fallback(
    *,
    app_id: str | None = None,
    limit: int = 200,
    fallback_csv: str | None = None,
    play_fetcher: Callable[[str, int], list[ReviewRecord]] = fetch_reviews_from_play_store,
) -> tuple[list[ReviewRecord], str]:
    """Return (reviews, source_used) where source_used is play_store or csv_fallback."""
    app = app_id or get_play_store_app_id()
    try:
        rows = play_fetcher(app, limit)
        if rows:
            return rows, "play_store"
    except Exception:
        pass

    csv_path = fallback_csv or get_reviews_fallback_csv()
    if not csv_path:
        return [], "csv_fallback"
    return load_reviews_from_csv(csv_path), "csv_fallback"


def persist_reviews(session: Session, rows: list[ReviewRecord]) -> dict[str, int]:
    """Upsert reviews by external_id."""
    inserted = 0
    updated = 0
    if not rows:
        return {"inserted": 0, "updated": 0, "total": 0}

    ids = [r.external_id for r in rows]
    existing = {
        r.external_id: r
        for r in session.scalars(select(Review).where(Review.external_id.in_(ids)))
    }

    for row in rows:
        cur = existing.get(row.external_id)
        if cur is None:
            session.add(
                Review(
                    external_id=row.external_id,
                    content=row.content,
                    score=row.score,
                    review_at=row.review_at,
                    source=row.source,
                )
            )
            inserted += 1
        else:
            cur.content = row.content
            cur.score = row.score
            cur.review_at = row.review_at
            cur.source = row.source
            updated += 1

    session.commit()
    return {"inserted": inserted, "updated": updated, "total": len(rows)}


def refresh_reviews(session: Session, limit: int = 200) -> dict[str, int | str]:
    rows, src = fetch_reviews_with_fallback(limit=limit)
    stats = persist_reviews(session, rows)
    return {"source": src, **stats}
