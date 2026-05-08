"""Phase 3: lightweight ML theme detection and pulse generation."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import logging
import math
import re
from typing import Any

import numpy as np
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.models import PulseRun, PulseTheme, Review
from app.llm.client import chat_completion_safe, llm_available, parse_json_object
from app.rag.embed import get_embedder

STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "to",
    "of",
    "for",
    "and",
    "or",
    "in",
    "on",
    "with",
    "this",
    "that",
    "it",
    "app",
    "groww",
    "very",
    "but",
    "from",
    "my",
    "your",
    "you",
    "they",
    "them",
    "their",
    "theirs",
    "we",
    "our",
    "ours",
    "he",
    "she",
    "his",
    "her",
    "hers",
    "its",
    "me",
    "mine",
    "myself",
    "yourself",
    "themselves",
    "ourselves",
    "himself",
    "herself",
    "not",
    "no",
    "yes",
    "will",
    "would",
    "could",
    "should",
    "can",
    "did",
    "does",
    "do",
    "done",
    "have",
    "has",
    "had",
    "being",
    "been",
    "am",
    "be",
    "these",
    "those",
    "very",
    "much",
    "also",
    "just",
    "like",
    "really",
    "even",
    "still",
    "best",
    "good",
    "bad",
    "please",
    "thanks",
    "thank",
    "nahi",
    "nahin",
    "bahut",
    "accha",
    "acha",
    "achha",
    "bekar",
    "bekaar",
    "kya",
    "hai",
    "ka",
    "ki",
    "ke",
    "ho",
    "hota",
    "hoti",
    "kar",
    "kara",
    "karo",
    "kr",
    "krna",
    "krne",
    "wala",
    "wali",
    "waale",
    "waali",
}

TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9\-]{2,}")
NON_WORD_RE = re.compile(r"[^A-Za-z0-9\s]")
DOMAIN_TERMS = {
    "login",
    "kyc",
    "sip",
    "upi",
    "portfolio",
    "order",
    "orders",
    "withdrawal",
    "withdraw",
    "mandate",
    "otp",
    "crash",
    "lag",
    "slow",
    "payment",
    "fund",
    "nav",
    "expense",
    "ratio",
    "statement",
    "verification",
    "bank",
}
SPAM_PATTERNS = (
    "referral code",
    "use my code",
    "promo code",
    "coupon",
    "http://",
    "https://",
    "t.me/",
)
MIN_REVIEW_CHARS = 8
MIN_REVIEW_WORDS = 3
MAX_SYMBOL_RATIO = 0.5
MIN_THEME_REVIEWS = 5
MIN_THEME_KEYWORDS = 2
MAX_REPEAT_PER_NORMALIZED_REVIEW = 3
LLM_CLUSTER_LABEL_PROMPT = (
    'Return JSON only: {"label":"2-6 word neutral product theme for these app reviews"}. '
    "No PII or person names."
)
logger = logging.getLogger(__name__)


@dataclass
class QualityEvaluation:
    bucket: str  # usable_high | usable_medium | weak_signal | junk
    score: int
    reasons: list[str]


def _normalize_for_dedupe(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _symbol_ratio(text: str) -> float:
    if not text:
        return 1.0
    symbols = len(NON_WORD_RE.findall(text))
    return symbols / max(len(text), 1)


def _looks_like_star_only(text: str) -> bool:
    t = text.strip().lower()
    return t in {"1 star", "2 star", "3 star", "4 star", "5 star", "one star", "five star"}


def _quality_eval(text: str) -> QualityEvaluation:
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return QualityEvaluation(bucket="junk", score=0, reasons=["empty"])
    if len(cleaned) < MIN_REVIEW_CHARS:
        return QualityEvaluation(bucket="junk", score=0, reasons=["too_short_chars"])
    words = re.findall(r"[A-Za-z0-9]+", cleaned)
    if len(words) < MIN_REVIEW_WORDS:
        return QualityEvaluation(bucket="junk", score=0, reasons=["too_short_words"])
    if _symbol_ratio(cleaned) > MAX_SYMBOL_RATIO:
        return QualityEvaluation(bucket="junk", score=0, reasons=["symbol_heavy"])
    low = cleaned.lower()
    if any(p in low for p in SPAM_PATTERNS):
        return QualityEvaluation(bucket="junk", score=0, reasons=["spam_pattern"])
    if _looks_like_star_only(low):
        return QualityEvaluation(bucket="junk", score=0, reasons=["rating_only"])

    score = 0
    reasons: list[str] = []
    toks = _tokenize(cleaned)
    has_domain = any(t in DOMAIN_TERMS for t in toks)
    if has_domain:
        score += 2
        reasons.append("specific_domain_context")
    elif len(toks) >= 5:
        score += 1
        reasons.append("some_context")

    if any(k in low for k in ("because", "after", "during", "when", "failed", "error", "issue", "stuck", "pending", "not ")):
        score += 2
        reasons.append("actionable_detail")
    elif len(toks) >= 7:
        score += 1
        reasons.append("actionability_partial")

    # Basic legibility gate: enough word-like tokens in the sentence.
    word_ratio = len("".join(ch for ch in cleaned if ch.isalnum() or ch.isspace()).split()) / max(len(words), 1)
    if word_ratio >= 0.8:
        score += 1
        reasons.append("legible")

    if score >= 4:
        bucket = "usable_high"
    elif score >= 2:
        bucket = "usable_medium"
    elif score == 1:
        bucket = "weak_signal"
    else:
        bucket = "junk"
    return QualityEvaluation(bucket=bucket, score=score, reasons=reasons)


def _filter_reviews_for_pulse(texts: list[str]) -> tuple[list[str], dict[str, Any]]:
    seen_counts: dict[str, int] = {}
    usable: list[str] = []
    counters = {
        "fetched": len(texts),
        "used_for_themes": 0,
        "junk_filtered": 0,
        "duplicate_filtered": 0,
        "weak_signal_excluded_from_theming": 0,
        "usable_high": 0,
        "usable_medium": 0,
    }
    for raw in texts:
        norm = _normalize_for_dedupe(raw)
        if not norm:
            counters["junk_filtered"] += 1
            continue
        count = seen_counts.get(norm, 0)
        if count >= MAX_REPEAT_PER_NORMALIZED_REVIEW:
            counters["duplicate_filtered"] += 1
            continue
        seen_counts[norm] = count + 1
        q = _quality_eval(raw)
        if q.bucket == "junk":
            counters["junk_filtered"] += 1
            continue
        if q.bucket == "weak_signal":
            counters["weak_signal_excluded_from_theming"] += 1
            continue
        usable.append(raw.strip())
        counters[q.bucket] += 1
    counters["used_for_themes"] = len(usable)
    return usable, counters


@dataclass
class ClusterResult:
    labels: np.ndarray
    centroids: np.ndarray
    silhouette: float


def _tokenize(text: str) -> list[str]:
    toks = [m.group(0).lower() for m in TOKEN_RE.finditer(text)]
    return [t for t in toks if t not in STOPWORDS]


def _kmeans(x: np.ndarray, k: int, max_iter: int = 25, seed: int = 42) -> ClusterResult:
    n, d = x.shape
    if k <= 1 or k > n:
        labels = np.zeros(n, dtype=int)
        centroid = x.mean(axis=0, keepdims=True)
        return ClusterResult(labels=labels, centroids=centroid, silhouette=0.0)

    rng = np.random.default_rng(seed)
    init_idx = rng.choice(n, size=k, replace=False)
    centroids = x[init_idx].copy()
    labels = np.zeros(n, dtype=int)

    for _ in range(max_iter):
        distances = np.linalg.norm(x[:, None, :] - centroids[None, :, :], axis=2)
        new_labels = np.argmin(distances, axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for i in range(k):
            mask = labels == i
            if mask.any():
                centroids[i] = x[mask].mean(axis=0)
            else:
                centroids[i] = x[rng.integers(0, n)]

    sil = _silhouette_score(x, labels)
    return ClusterResult(labels=labels, centroids=centroids, silhouette=sil)


def _silhouette_score(x: np.ndarray, labels: np.ndarray) -> float:
    n = len(labels)
    if n < 3:
        return 0.0
    clusters = sorted(set(labels.tolist()))
    if len(clusters) <= 1:
        return 0.0
    distances = np.linalg.norm(x[:, None, :] - x[None, :, :], axis=2)
    s_vals: list[float] = []
    for i in range(n):
        c = labels[i]
        same = labels == c
        a = distances[i, same].mean() if same.sum() > 1 else 0.0
        b = math.inf
        for oc in clusters:
            if oc == c:
                continue
            mask = labels == oc
            if mask.any():
                b = min(b, float(distances[i, mask].mean()))
        if not math.isfinite(b):
            s_vals.append(0.0)
            continue
        denom = max(a, b, 1e-6)
        s_vals.append((b - a) / denom)
    return float(np.mean(s_vals))


def _choose_k(x: np.ndarray, k_min: int = 3, k_max: int = 8) -> ClusterResult:
    n = x.shape[0]
    if n < 3:
        return _kmeans(x, 1)
    lo = max(2, k_min)
    hi = min(k_max, max(2, n - 1))
    best: ClusterResult | None = None
    for k in range(lo, hi + 1):
        r = _kmeans(x, k)
        if best is None or r.silhouette > best.silhouette:
            best = r
    return best if best is not None else _kmeans(x, 1)


def _label_cluster(texts: list[str]) -> str:
    c = Counter()
    for t in texts:
        c.update(_tokenize(t))
    top = [w for w, _ in c.most_common(2)]
    if not top:
        return "General feedback"
    if len(top) == 1:
        return top[0].title()
    return f"{top[0].title()} & {top[1].title()}"


def _quote_for_cluster(texts: list[str]) -> str:
    if not texts:
        return ""
    # Prefer medium-length quote for readability.
    texts_sorted = sorted(texts, key=lambda t: abs(len(t) - 120))
    return texts_sorted[0][:220]


def _build_actions(themes: list[dict]) -> list[str]:
    base = [
        "Triage the top complaint theme with severity and owner assignment this week.",
        "Publish a customer-facing status note for recurring operational pain points.",
        "Track daily trend deltas and review improvements in the weekly product sync.",
    ]
    if not themes:
        return base
    t0 = themes[0]["label"]
    t1 = themes[1]["label"] if len(themes) > 1 else "secondary issues"
    t2 = themes[2]["label"] if len(themes) > 2 else "long-tail concerns"
    return [
        f"Launch a focused fix sprint for '{t0}' with measurable SLA impact.",
        f"Instrument funnel checkpoints tied to '{t1}' to identify exact breakpoints.",
        f"Create proactive in-app guidance addressing '{t2}' before users contact support.",
    ]


def _build_analysis(themes: list[dict], review_count: int) -> str:
    if not themes:
        return "No significant patterns were found in the sampled reviews for this period."
    parts = [
        f"This pulse is based on {review_count} recent reviews and highlights three recurring themes.",
        f"The most prominent issue is '{themes[0]['label']}' with {themes[0]['volume']} mentions, indicating concentrated friction.",
    ]
    if len(themes) > 1:
        parts.append(
            f"'{themes[1]['label']}' is the second-largest theme ({themes[1]['volume']} mentions), suggesting adjacent workflow pain."
        )
    if len(themes) > 2:
        parts.append(
            f"A third pattern, '{themes[2]['label']}', appears in {themes[2]['volume']} reviews and should be monitored for escalation."
        )
    parts.append("The action plan prioritizes high-volume issues first while improving communication and instrumentation.")
    txt = " ".join(parts)
    # Keep under 250 words by truncation safety.
    words = txt.split()
    if len(words) > 245:
        txt = " ".join(words[:245])
    return txt


def _deterministic_token_baseline_labels(texts: list[str]) -> list[str]:
    """Token-frequency baseline for eval comparison (not an LLM)."""
    c = Counter()
    for t in texts:
        c.update(_tokenize(t))
    return [w.title() for w, _ in c.most_common(3)]


def _llm_cluster_short_label(cluster_texts: list[str]) -> str | None:
    """Optional LLM theme title for a cluster (Groq/Gemini when configured)."""
    if not llm_available() or not cluster_texts:
        logger.warning("Pulse LLM labeling skipped: unavailable_or_empty_cluster")
        return None
    messages = _build_llm_cluster_label_messages(cluster_texts)
    res = chat_completion_safe(messages, temperature=0.2)
    if res.provider == "none" or not res.text.strip():
        logger.warning("Pulse LLM labeling failed: provider=%s error=%s", res.provider, res.error)
        return None
    label = _parse_llm_cluster_label(res.text)
    if not label:
        snippet = re.sub(r"\s+", " ", res.text).strip()[:240]
        logger.warning(
            "Pulse LLM labeling parse failure: provider=%s error=%s response_snippet=%s",
            res.provider,
            res.error,
            snippet,
        )
        return None
    return label


def _build_llm_cluster_label_messages(cluster_texts: list[str]) -> list[dict[str, str]]:
    sample = "\n---\n".join(t[:400] for t in cluster_texts[:6])
    return [
        {"role": "system", "content": LLM_CLUSTER_LABEL_PROMPT},
        {"role": "user", "content": sample[:4000]},
    ]


def _parse_llm_cluster_label(raw_text: str) -> str | None:
    obj = parse_json_object(raw_text)
    if isinstance(obj, dict):
        lab = obj.get("label")
        if isinstance(lab, str):
            s = re.sub(r"\s+", " ", lab).strip().strip(" .,:;\"'")
            if 3 <= len(s) <= 120:
                return s
    # Fallback: accept plain-text short title if model ignored JSON format.
    one = re.sub(r"\s+", " ", (raw_text or "")).strip().strip("`")
    if not one:
        return None
    if one.startswith("{") and one.endswith("}"):
        return None
    if len(one) <= 120:
        return one
    first = one.split(".", 1)[0].strip()
    return first if 3 <= len(first) <= 120 else None


def generate_pulse(session: Session, sample_size: int = 500) -> dict[str, Any]:
    """Generate pulse from stored reviews and persist run + theme history."""
    reviews = list(session.scalars(select(Review).order_by(desc(Review.review_at)).limit(sample_size)))
    if not reviews:
        raise ValueError("No reviews available. Run /api/reviews/refresh first.")

    raw_texts = [r.content for r in reviews if r.content and r.content.strip()]
    if not raw_texts:
        raise ValueError("No non-empty reviews available for pulse generation.")
    texts, quality = _filter_reviews_for_pulse(raw_texts)
    if not texts:
        raise ValueError("No usable reviews available after quality filtering.")

    embedder = get_embedder()
    x = embedder.encode(texts)
    clustering = _choose_k(x, 3, 8)
    labels = clustering.labels.tolist()

    grouped: dict[int, list[str]] = defaultdict(list)
    for t, lbl in zip(texts, labels, strict=False):
        grouped[int(lbl)].append(t)

    cluster_rows: list[dict[str, Any]] = []
    for _, cluster_texts in grouped.items():
        keyword_count = len(set(_tokenize(" ".join(cluster_texts))))
        cluster_rows.append(
            {
                "texts": cluster_texts,
                "label": _label_cluster(cluster_texts),
                "volume": len(cluster_texts),
                "quote": _quote_for_cluster(cluster_texts),
                "keyword_count": keyword_count,
            }
        )
    cluster_rows.sort(key=lambda x: x["volume"], reverse=True)
    if not cluster_rows:
        raise ValueError("No themes found after quality filtering.")
    robust_rows = [
        row for row in cluster_rows if row["volume"] >= MIN_THEME_REVIEWS and row["keyword_count"] >= MIN_THEME_KEYWORDS
    ]
    selected_rows = (robust_rows or cluster_rows)[:3]
    quality["theme_threshold_relaxed"] = len(robust_rows) == 0
    quality["theme_min_reviews"] = MIN_THEME_REVIEWS
    quality["theme_min_keywords"] = MIN_THEME_KEYWORDS

    themes: list[dict[str, Any]] = []
    used_llm_labels = False
    for row in selected_rows:
        label = row["label"]
        alt = _llm_cluster_short_label(row["texts"])
        if alt:
            label = alt
            used_llm_labels = True
        themes.append({"label": label, "volume": row["volume"], "quote": row["quote"]})

    actions = _build_actions(themes)
    analysis = _build_analysis(themes, len(texts))
    baseline = _deterministic_token_baseline_labels(texts)
    cost_hint = (
        "Embeddings + k-means clustering; top-3 cluster titles refined with LLM when API keys are set; "
        "deterministic_token_baseline is token-frequency only (not LLM)."
        if used_llm_labels
        else "Embeddings + k-means clustering; cluster titles use keyword extraction unless LLM keys are set for optional short labels."
    )
    comparison = {
        "ml_themes": [t["label"] for t in themes],
        "deterministic_token_baseline": baseline,
        "reproducibility_ml_clustering": True,
        "reproducibility_token_baseline": True,
        "token_cost_hint": cost_hint,
        "quality_gate": quality,
    }
    metrics = {
        "algorithm": "custom_kmeans_numpy",
        "sample_size": len(texts),
        "raw_sample_size": len(raw_texts),
        "cluster_count": len(set(labels)),
        "silhouette": round(float(clustering.silhouette), 4),
        "quality_threshold_used": "usable_medium_or_high_only",
    }

    date_from = min((r.review_at for r in reviews if r.review_at), default=None)
    date_to = max((r.review_at for r in reviews if r.review_at), default=None)
    run = PulseRun(
        mode="ml",
        review_count=len(texts),
        date_from=date_from,
        date_to=date_to,
        analysis=analysis,
        actions_json=actions,
        metrics_json=metrics,
        comparison_json=comparison,
    )
    session.add(run)
    session.flush()
    for rank, theme in enumerate(themes, start=1):
        session.add(
            PulseTheme(
                pulse_run_id=run.id,
                rank=rank,
                label=theme["label"],
                volume=theme["volume"],
                quote=theme["quote"],
            )
        )
    session.commit()
    return get_pulse_by_id(session, run.id)


def get_pulse_by_id(session: Session, pulse_run_id: int) -> dict[str, Any]:
    run = session.scalar(select(PulseRun).where(PulseRun.id == pulse_run_id))
    if run is None:
        raise ValueError("Pulse run not found.")
    themes = list(session.scalars(select(PulseTheme).where(PulseTheme.pulse_run_id == pulse_run_id).order_by(PulseTheme.rank)))
    return {
        "pulse_id": run.id,
        "generated_at": run.generated_at.isoformat(timespec="seconds"),
        "mode": run.mode,
        "review_count": run.review_count,
        "date_from": run.date_from.isoformat(timespec="seconds") if run.date_from else None,
        "date_to": run.date_to.isoformat(timespec="seconds") if run.date_to else None,
        "top_themes": [
            {"rank": t.rank, "label": t.label, "volume": t.volume, "quote": t.quote}
            for t in themes
        ],
        "analysis": run.analysis,
        "actions": run.actions_json,
        "metrics": run.metrics_json,
        "comparison": run.comparison_json,
    }


def get_latest_pulse(session: Session) -> dict[str, Any] | None:
    run = session.scalar(select(PulseRun).order_by(desc(PulseRun.generated_at)).limit(1))
    if run is None:
        return None
    return get_pulse_by_id(session, run.id)


def list_pulse_history(session: Session, limit: int = 20) -> list[dict[str, Any]]:
    runs = list(session.scalars(select(PulseRun).order_by(desc(PulseRun.generated_at)).limit(limit)))
    out: list[dict[str, Any]] = []
    for r in runs:
        out.append(
            {
                "pulse_id": r.id,
                "generated_at": r.generated_at.isoformat(timespec="seconds"),
                "review_count": r.review_count,
                "mode": r.mode,
                "silhouette": (r.metrics_json or {}).get("silhouette"),
            }
        )
    return out
