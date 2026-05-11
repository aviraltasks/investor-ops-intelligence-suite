# HEALTH.md — Project Health Tracker

**Purpose:** Quick-check system status. Cursor updates after each phase.  
**Last updated:** Agent panel / admin log UX alignment (May 11, 2026)

---

## System Status

| Component | Status | Notes |
|-----------|--------|-------|
| Frontend (Vercel) | 🔧 Ready to deploy | Next.js app in `frontend/`; connect repo root `frontend` on Vercel |
| Backend (Render) | 🔧 Ready to deploy | FastAPI in `backend/`; use `render.yaml` or manual web service |
| `GET /health` | ✅ Implemented | Structured JSON (`components`, `timestamp_ist`); run locally: `uvicorn app.main:app` |
| LLM — Groq (primary) | ⬜ Not configured | Set `GROQ_API_KEY` on Render |
| LLM — Gemini (fallback) | ⬜ Not configured | Set `GEMINI_API_KEY` |
| Vector Store | ✅ Implemented (local DB vectors) | `rag_chunks` with embeddings + `/api/data/search` |
| Google Calendar | ✅ Integrated (mock/live mode) | Calendar hold create/cancel wired via integration service; live mode uses direct Google APIs when configured |
| Google Sheets | ✅ Integrated (mock/live mode) | Booking row upsert wired via integration service; secure-details endpoint now writes K/L payload metadata for follow-up sync |
| Gmail SMTP | ✅ Draft + admin send flow wired | Booking email preview/send endpoints available in admin (mock send status now; live SMTP cutover later) |
| Google Doc | 🔧 Live when configured | `POST /api/admin/pulse/append-doc` appends latest pulse when `GOOGLE_INTEGRATIONS_MODE=live`, `GOOGLE_DOC_ID`, and service account have Docs edit access |
| Voice (STT/TTS) | ✅ Implemented | `/chat` uses Web Speech API for STT/TTS with mic states and text fallback banner |
| Chat safety (PII) | ✅ Hardened | PII now blocked at `/api/chat` boundary before agent routing/memory; Aadhaar/PAN/phone/email blocked with secure redirect guidance |
| FAQ cache controls | ✅ Implemented | `POST /api/admin/cache/faq/clear` clears in-memory FAQ cache per API process |

---

## Agent Status

| Agent | Status | Notes |
|-------|--------|-------|
| Orchestrator | ✅ Working | `app/agents/orchestrator.py`; intent sequencing + multi-agent coordination + safety guards (PII/advice/prompt-injection) |
| RAG Agent | ✅ Working | `app/agents/rag_agent.py`; retrieval, sufficiency check, retry/replan |
| Scheduling Agent | ✅ Working | `app/agents/scheduling_agent.py`; book/cancel/availability + edge guards (weekday/hours/past checks, duplicate-slot conflict, already-cancelled handling) |
| Review Intelligence Agent | ✅ Working | `app/agents/review_intel_agent.py`; latest pulse context |
| Email Drafting Agent | ✅ Working | `app/agents/email_agent.py`; booking + concern + market context draft payload |
| Memory Agent | ✅ Working | `app/agents/memory_agent.py`; session + cross-session memory, returning-user context, pending booking reminders, and PII-safe fact persistence |

---

## Data Pipeline Status

| Component | Status | Notes |
|-----------|--------|-------|
| Groww fund scraping (15 funds) | ✅ Implemented | Manifest + ingest pipeline in `backend/app/rag/` |
| SEBI page scraping (9 pages) | ✅ Implemented | Manifest + ingest pipeline in `backend/app/rag/` |
| Text cleaning + chunking | ✅ Working | `extract.py` + `chunking.py` |
| Embedding generation | ✅ Working | Default `HashEmbedder`; optional sentence-transformers |
| Vector store populated | ✅ Working | Stored in `rag_chunks.embedding`; queryable via `/api/data/search` |
| Play Store review fetching | ✅ Working with fallback | `google-play-scraper` primary + CSV fallback (`backend/sample_data/reviews_fallback.csv`) |
| ML theme detection pipeline | ✅ Working | `backend/app/ml/theme_pipeline.py` (custom kmeans + silhouette + pulse history tables) |

---

## Pages Status

| Page | Status | Notes |
|------|--------|-------|
| Landing (/) | ✅ Shell | Name + booking code paths; footer + nav |
| Chat (/chat) | ✅ Functional | Full conversation UI wired to `/api/chat`; agent panel with PM summaries + expandable technical trace + booking card; Web Speech API voice layer (Phase 7) |
| Admin (/admin) | ✅ Functional | Dashboard graphs, pulse actions, bookings/email actions, subscribers, and agent activity log (aligned copy/UX with chat panel) |
| Secure (/secure/[code]) | ✅ Functional | Booking-code verify, summary, phone/email/consent validation, success/error states, and secure-details submit API |
| Subscribers (/subscribers) | ✅ Functional | Email signup page wired to `POST /api/subscribers` with validation/error/success states |

---

## Eval Status

| Eval | Status | Notes |
|------|--------|-------|
| RAG golden dataset (5 questions) | ✅ Baseline scored | Documented in `EVAL_REPORT.md` with honest limitations |
| Safety adversarial (3 prompts) | ✅ Passed | Automated in `backend/tests/test_phase11_hardening.py` |
| Tone & structure check | ✅ Completed | Pulse and greeting checks documented in `EVAL_REPORT.md` |
| ML metrics + comparison | ✅ Completed | Metrics + ML-vs-LLM comparison documented in `EVAL_REPORT.md` |
| Agentic behavior verification | ✅ Completed | Trace/routing behavior documented in `EVAL_REPORT.md` |

---

## Pre-Demo Checklist

- [ ] `GROQ_API_KEY` on backend
- [ ] `GEMINI_API_KEY` on backend
- [ ] `FRONTEND_URL` matches Vercel URL
- [ ] `NEXT_PUBLIC_BACKEND_URL` on Vercel → Render API
- [ ] Google SA + Calendar + Sheet shared
- [ ] Gmail app password configured
- [ ] All 5 pages accessible via live URLs
- [ ] Agent activity panel: PM summary lines + expand **Technical details** to verify raw tools/outcomes
- [ ] Voice working on /chat
- [ ] Admin dashboard graphs rendering
- [x] Eval report generated (`EVAL_REPORT.md`)

---

## Known Issues

| Date | Issue | Status |
|------|-------|--------|
| 2026-05-04 | Windows: project path contains `&` breaks default `next` / `npm` scripts that invoke `cmd` | Mitigated: `frontend/package.json` uses `node node_modules/next/dist/bin/next …`; use `npm install --ignore-scripts` if postinstall fails |
| 2026-05-04 | Python 3.14 local env triggers heavier deprecation warnings in FastAPI/Starlette and UTC defaults | Non-blocking for Phase 2; tests pass; can clean in hardening phase |
| 2026-05-09 | Database-wide small-cap expense-ratio comparison can return generic category text on production | Known data/retrieval gap: top chunks are category-page prose, not clean per-fund metric rows. Backlog: ingest/add chunk quality for individual fund metric pages. |

---

## Backlog (Next)

- [ ] RAG corpus upgrade for cross-fund comparisons: ingest/refresh per-fund pages with explicit metric rows (expense ratio/NAV/exit load).
- [x] UI safety alignment: replaced unsupported example query with production-validated query to avoid overpromising current corpus.
- [x] Deterministic booking confirmations enforced (no LLM paraphrase) for predictable yes/no scheduling flow.

---

*Legend: ⬜ not started · 🔧 in progress · ✅ working · ⚠️ degraded · ❌ broken*

*Update after each phase completion.*
