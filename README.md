# Investor Ops & Intelligence Suite

Capstone project: **Finn** (smart FAQ + review pulse + advisor scheduling) for a Groww-style fintech. Product and engineering specs live in the repo root (`Brain.md`, `PRD.md`, `ARCHITECTURE.md`, etc.).

## Final submission links

- GitHub repository: https://github.com/aviraltasks/investor-ops-intelligence-suite
- Deployed backend (Render): https://investor-ops-intelligence-suite.onrender.com
- Deployed application (Vercel): https://investor-ops-intelligence-suite.vercel.app
- Evaluation report: [EVAL_REPORT.md](EVAL_REPORT.md)
- Source manifest (official URLs): [Source manifest section](#source-manifest-31-official--product-urls)

## Stack (Phase 1+)

| Area | Technology |
|------|------------|
| Frontend | Next.js (App Router), TypeScript, Tailwind — **Vercel** |
| Backend | FastAPI, Python 3.11 — **Render** |
| Data | PostgreSQL (from Phase 2 onward; see `ARCHITECTURE.md` §3) |

## Prerequisites

- **Node.js** 20+ and npm  
- **Python** 3.11+  
- Optional: **Docker** for local Postgres (`docker compose up -d`)

### Windows: paths containing `&`

If the project lives under a folder whose path contains `&` (e.g. `... Ops & Intelligence ...`), some npm lifecycle scripts may fail when they invoke `cmd.exe`. This repo mitigates that by running Next via `node node_modules/next/dist/bin/next …` in `frontend/package.json` scripts.

Also use:

- `npm install --ignore-scripts` in `frontend/` if a dependency postinstall still fails, or  
- Clone the repo to a path **without** `&`, or use `subst` to map a short drive letter.

## Local development

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- Health: <http://localhost:8000/health>  
- Set `CORS_ORIGINS=http://localhost:3000` in `.env` if you change the frontend port.

### Frontend

```powershell
cd frontend
copy ..\.env.example .env.local
# Set NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
npm install --ignore-scripts
npm run dev
```

Open <http://localhost:3000>. Routes: `/`, `/chat`, `/admin`, `/secure/GRW-TEST`, `/subscribers`.

### Tests (backend)

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest
```

## Deploy

### Render (API)

1. New **Web Service** → connect repo, **Root Directory** `backend`.  
2. **Build:** `pip install -r requirements.txt`  
3. **Start:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`  
4. **Health check path:** `/health`  
5. Set `CORS_ORIGINS` to your Vercel origin (e.g. `https://your-app.vercel.app`).  
6. Optionally use [render.yaml](render.yaml) Blueprint.

### Vercel (frontend)

1. Import repo; **Root Directory** `frontend`.  
2. Environment: `NEXT_PUBLIC_BACKEND_URL=https://<your-render-service>.onrender.com`  
3. Deploy.

## Environment variables

See [.env.example](.env.example) at the repo root. Frontend-only vars are copied into `frontend/.env.local` as needed.

## Phase status

Tracked in [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md).

- **Phase 1 complete:** scaffolded pages, footer/header, and `GET /health`.
- **Phase 2 complete:** RAG + reviews data pipeline primitives.
- **Phase 3 complete:** ML theme detection + pulse generation APIs and persistence.
- **Phase 4 complete:** agentic orchestration core with traceable specialist agents via `POST /api/chat`.
- **Phase 5 complete:** frontend chat UI + backend-connected agent activity panel.
- **Phase 6 complete:** scheduling lifecycle wired to Google integration layer with fallback-safe operation.
- **Phase 7 complete:** voice layer (STT/TTS) on chat with graceful fallback to text.
- **Phase 8 complete:** functional admin dashboard with analytics, pulse controls, bookings/email actions, subscriber selection, and agent activity logs.
- **Phase 9 complete:** memory system upgraded for short-term + long-term continuity, returning-user personalization, and PII-safe persistence.
- **Phase 10 complete:** secure booking details page + subscriber signup page shipped with backend validation and persistence.
- **Phase 11 complete:** hardening + eval phase shipped with safety guardrails, scheduling edge protections, and evaluation report.
- **Phase 12 complete:** submission README polish, full curated source manifest in this file, screenshot capture guide under `screenshots/`, eval report linked; demo video deferred until production deploy (per PM).

### Phase 2 implementation snapshot

- Source manifest with 31+ official URLs in `backend/app/sources/manifest.py`
- RAG ingestion pipeline in `backend/app/rag/ingest_pipeline.py`
  - fetch -> extract -> chunk -> embed -> persist into `rag_chunks`
- Search API over stored embeddings:
  - `GET /api/data/search?q=...`
- Ingestion/stats APIs:
  - `POST /api/data/ingest`
  - `GET /api/data/stats`
- Review ingestion with fallback:
  - `POST /api/reviews/refresh`
  - Play Store (`google-play-scraper`) primary, CSV fallback via `REVIEWS_FALLBACK_CSV`
- Pipeline notes documented in [DATA_PIPELINE.md](DATA_PIPELINE.md)

### Phase 3 implementation snapshot

- ML pulse pipeline in `backend/app/ml/theme_pipeline.py`
  - embeddings -> clustering -> theme labels -> top quotes -> analysis -> 3 actions
  - clustering quality metric: silhouette score
- Pulse persistence for trend tracking:
  - `pulse_runs` and `pulse_themes` tables
- Pulse APIs:
  - `POST /api/pulse/generate`
  - `GET /api/pulse/latest`
  - `GET /api/pulse/history`
- Comparison payload included in pulse output:
  - ML-derived themes vs deterministic baseline extraction

### Phase 4 implementation snapshot

- Agent orchestration package in `backend/app/agents/`
  - `orchestrator.py` (routing/sequencing + final synthesis)
  - `rag_agent.py` (reason -> retrieve -> evaluate -> retry)
  - `scheduling_agent.py` (book/cancel/availability with IST-aware local rules)
  - `review_intel_agent.py` (latest pulse trend context)
  - `email_agent.py` (advisor briefing draft payload)
  - `memory_agent.py` (short/long memory fact load/save)
- Chat API:
  - `POST /api/chat`
  - Returns assistant response + structured trace steps for agent-activity UI
- Added local persistence models for Phase 4:
  - `bookings`, `memory_facts`

### Phase 5 implementation snapshot

- Chat UI implemented in `frontend/components/chat/ChatClient.tsx`
  - three-column desktop layout (schemes/examples, chat center, agent panel)
  - disclaimer banner, date + working-hours strip, message bubbles
  - quick-topic chips and clickable example questions
  - processing indicator text based on intent
- Backend integration:
  - sends user turns to `POST /api/chat`
  - renders booking confirmation card from chat payload
  - renders real per-turn agent trace logs (reasoning/tools/replanned/outcome)
- Validation:
  - frontend `npm run lint` + `npm run build` pass
  - backend regression tests pass after integration

### Phase 6 implementation snapshot

- Integration layer implemented in `backend/app/integrations/service.py`
  - ports for Calendar / Sheets / Gmail draft queue
  - `mock` mode (default) for reliable local/dev execution
  - `live` mode with direct Google API adapters when credentials/IDs are set
- Scheduling agent now triggers integration sync on booking/cancel:
  - creates/cancels calendar hold
  - upserts booking row to sheets format
  - queues advisor draft metadata for HITL flow
- Booking persistence extended with integration metadata:
  - `calendar_event_id`, `sheet_row_ref`, `email_status`, `integration_meta`
- New config:
  - `GOOGLE_INTEGRATIONS_MODE=mock|live` in `.env.example`

### Phase 7 implementation snapshot

- Voice support integrated in `frontend/components/chat/ChatClient.tsx`
  - STT via browser SpeechRecognition / webkitSpeechRecognition
  - TTS via `speechSynthesis`
  - mic state machine: `idle -> listening -> processing -> speaking`
- Same backend endpoint reused:
  - voice transcript is sent to `POST /api/chat` (no separate voice backend)
- Reliability behavior:
  - unsupported browser or recognition errors trigger banner + text-mode fallback
  - speech playback is cancelled on unload/component cleanup

### Phase 8 implementation snapshot

- Admin dashboard shipped in `frontend/app/admin/page.tsx` + `frontend/components/admin/AdminDashboardClient.tsx`
  - tabs: dashboard, pulse management, bookings, agent activity log
  - date range selector and graph cards for review themes, appointments, booking topics, and FAQ topics
- New admin/backend APIs in `backend/app/main.py`:
  - `GET /api/admin/analytics`
  - `GET /api/admin/bookings`
  - `POST /api/admin/bookings/{booking_code}/email/preview`
  - `POST /api/admin/bookings/{booking_code}/email/send`
  - `GET /api/admin/subscribers`
  - `POST /api/admin/pulse/send`
  - `GET /api/admin/agent-activity`
  - `POST /api/subscribers`
- New persistence models in `backend/app/db/models.py`:
  - `interaction_logs` for analytics topic data
  - `agent_activity_logs` for trace visibility in admin
  - `subscribers` for pulse email audience
- Chat API now logs interaction intents/topics + trace steps per turn for admin analytics/activity views.

### Phase 9 implementation snapshot

- Memory upgrades in `backend/app/agents/memory_agent.py`:
  - loads both session memory and cross-session user memory for continuity
  - retrieves pending user booking context for proactive reminders
  - applies PII scrubbing (email/phone/id-like patterns) before saving memory facts
- Orchestrator memory behavior updates in `backend/app/agents/orchestrator.py`:
  - new memory-recall intent for prompts like "what did we discuss?"
  - returning-user personalized greeting in new sessions
  - proactive pending booking reminder in general flows
- Phase 9 tests in `backend/tests/test_phase9_memory.py`:
  - verifies cross-session returning-user continuity
  - verifies memory recall responses
  - verifies chat PII is blocked (no memory persistence for raw PII messages; see Phase 11 orchestrator guard)

### Phase 10 implementation snapshot

- Secure booking flow:
  - new APIs in `backend/app/main.py`
    - `GET /api/secure/{booking_code}` for booking verification + summary
    - `POST /api/secure/{booking_code}/details` for secure form submission
  - validation includes India phone format, email format, and mandatory consent
  - accepted payload is persisted into booking integration metadata with `sheet_columns_updated: ["K", "L"]`
- Subscriber page flow:
  - `/subscribers` now renders a live signup form via `frontend/components/subscribers/SubscriberSignupClient.tsx`
  - form posts to `POST /api/subscribers` and handles success/duplicate/error cases
- Secure page UI:
  - `/secure/[bookingCode]` now renders live lookup + summary + secure details submit flow via `frontend/components/secure/SecureBookingClient.tsx`
  - includes invalid booking handling and success state after submission
- Phase 10 tests in `backend/tests/test_phase10_secure_subscribers.py`:
  - covers secure lookup, invalid code path, validation failures, successful submit
  - covers subscriber create + idempotent re-subscribe + admin listing

### Phase 11 implementation snapshot

- Safety hardening in `backend/app/agents/orchestrator.py`:
  - PII detection in chat (blocks and redirects to secure flow)
  - investment-advice refusal responses
  - prompt-injection refusal handling
  - empty input guard
- Scheduling edge hardening in `backend/app/agents/scheduling_agent.py`:
  - rejects ambiguous/past/weekend/out-of-hours requests
  - duplicate slot conflict detection in-session
  - explicit booking-code cancellation support
  - already-cancelled booking guard
- Input sanitization in API boundary (`backend/app/main.py`) for `message`, `session_id`, and `user_name`.
- New Phase 11 tests in `backend/tests/test_phase11_hardening.py`:
  - adversarial safety prompts
  - scheduling edge cases (time validity/conflicts/double cancel)
  - empty and chaotic input handling
- Evaluation deliverable:
  - `EVAL_REPORT.md` generated with RAG/safety/tone/ML/agentic assessment and known limitations.

### Phase 12 implementation snapshot

- **README** (this file): architecture summary, agent roles, key API surface, full URL manifest, submission checklist, end-to-end verification checklist.
- **Screenshots:** capture guide at [screenshots/README.md](screenshots/README.md) (add images when prod/local demo is ready).
- **Eval report:** [EVAL_REPORT.md](EVAL_REPORT.md).
- **Demo video:** optional; record after Vercel + Render URLs are live (see checklist below).

## LLM integration (Groq primary, Gemini fallback)

When **`GROQ_API_KEY`** and/or **`GEMINI_API_KEY`** are set on the **backend** (Render or local `.env`):

- **Orchestrator** (`app/agents/orchestrator.py`): LLM JSON intent routing from user message + memory/pulse context (falls back to keyword rules if the model returns nothing or invalid JSON). If multiple specialist sections are produced, an LLM **merges** them into one reply; traces show `llm.groq` / `llm.gemini` / `response_synthesizer`.
- **RAG agent** (`app/agents/rag_agent.py`): LLM **retrieval plan** (search queries) then vector search, then LLM **grounded synthesis** with source URLs. If no keys are set, behavior is the previous deterministic snippet path.
- **Scheduling agent** (`app/agents/scheduling_agent.py`): **Rules still enforce** slots, conflicts, and cancellations; on success paths the **user-facing wording** is optionally rewritten by an LLM for natural tone.

Implementation: `backend/app/llm/client.py` (httpx → Groq OpenAI-compatible API, then Gemini `generateContent`). Models: `GROQ_MODEL` (default `llama-3.3-70b-versatile`), `GEMINI_MODEL` (default `gemini-2.5-flash-lite`).

## Architecture summary

Authoritative design: [ARCHITECTURE.md](ARCHITECTURE.md). At a glance:

- **Frontend (Next.js):** landing, chat (voice + traces), admin (analytics + pulse + bookings), secure booking page, subscribers.
- **Backend (FastAPI):** health, RAG ingest/search, reviews refresh, pulse generate/history, chat orchestration, admin APIs, secure APIs, Google integration ports (mock default, live when configured).
- **Persistence:** PostgreSQL (or SQLite for local tests); bookings, reviews, pulses, RAG chunks, memory, subscribers, interaction and agent logs.

## Agents (Finn stack)

| Agent | Role |
|-------|------|
| Orchestrator | Intent + safety routing, multi-step sequencing, synthesis |
| RAG | Retrieval, sufficiency check, cited FAQ answers |
| Scheduling | IST weekday slots, booking codes, cancel/conflict handling |
| Review intelligence | Latest pulse / trending context for greetings |
| Email drafting | Advisor briefing draft payload (HITL send) |
| Memory | Session + cross-session context; PII-safe persistence |

## Key API endpoints (local defaults)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Structured health JSON |
| POST | `/api/data/ingest` | Full RAG corpus ingest |
| GET | `/api/data/stats` | Chunk counts |
| GET | `/api/data/search` | Semantic search over chunks |
| POST | `/api/reviews/refresh` | Play Store + CSV fallback |
| POST | `/api/pulse/generate` | ML pulse run |
| GET | `/api/pulse/latest` | Latest pulse JSON |
| POST | `/api/chat` | Main conversational + traces |
| GET | `/api/secure/{code}` | Booking lookup |
| POST | `/api/secure/{code}/details` | Secure phone/email/consent |
| POST | `/api/subscribers` | Pulse email signup |
| GET | `/api/admin/*` | Analytics, bookings, subscribers, agent log |

## Source manifest (31 official / product URLs)

Canonical list in code: `backend/app/sources/manifest.py` via `all_manifest_urls()`.  
Curated reviewer copy (same 31 URLs) is listed below.

**Groww mutual fund pages (15)**

1. https://groww.in/mutual-funds/sbi-nifty-index-fund-direct-growth  
2. https://groww.in/mutual-funds/parag-parikh-long-term-value-fund-direct-growth  
3. https://groww.in/mutual-funds/hdfc-mid-cap-opportunities-fund-direct-growth  
4. https://groww.in/mutual-funds/sbi-small-midcap-fund-direct-growth  
5. https://groww.in/mutual-funds/mirae-asset-elss-tax-saver-fund-direct-growth  
6. https://groww.in/mutual-funds/nippon-india-large-cap-fund-direct-growth  
7. https://groww.in/mutual-funds/kotak-midcap-fund-direct-growth  
8. https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth  
9. https://groww.in/mutual-funds/motilal-oswal-most-focused-midcap-30-fund-direct-growth  
10. https://groww.in/mutual-funds/uti-nifty-fund-direct-growth  
11. https://groww.in/mutual-funds/axis-midcap-fund-direct-growth  
12. https://groww.in/mutual-funds/icici-prudential-long-term-equity-fund-tax-saving-direct-growth  
13. https://groww.in/mutual-funds/sbi-magnum-children-benefit-plan-direct  
14. https://groww.in/mutual-funds/quant-small-cap-fund-direct-plan-growth  
15. https://groww.in/mutual-funds/canara-robeco-large-cap-fund-direct-growth  

**SEBI investor education (9)**

16. https://investor.sebi.gov.in/securities-mf-investments.html  
17. https://investor.sebi.gov.in/exit_load.html  
18. https://investor.sebi.gov.in/regular_and_direct_mutual_funds.html  
19. https://investor.sebi.gov.in/index_mutual_fund.html  
20. https://investor.sebi.gov.in/understanding_mf.html  
21. https://investor.sebi.gov.in/open_ended_fund.html  
22. https://investor.sebi.gov.in/closed_ended_fund.html  
23. https://investor.sebi.gov.in/interval_fund.html  
24. https://investor.sebi.gov.in/pdf/reference-material/ppt/PPT-8-Introduction_to_Mutual_Funds_Investing_Jan24.pdf  

**Groww category hubs (6)**

25. https://groww.in/mutual-funds/equity-funds/large-cap-funds  
26. https://groww.in/mutual-funds/equity-funds/mid-cap-funds  
27. https://groww.in/mutual-funds/equity-funds/small-cap-funds  
28. https://groww.in/mutual-funds/equity-funds/elss-funds  
29. https://groww.in/mutual-funds/index-funds  
30. https://groww.in/mutual-funds/equity-funds/flexi-cap-funds  

**Play Store (reference app page, 1)**

31. https://play.google.com/store/apps/details?id=com.nextbillion.groww  

## Submission checklist (before grading / demo)

- [ ] Copy `.env.example` → backend `.env` and `frontend/.env.local`; set `NEXT_PUBLIC_BACKEND_URL` to Render URL after deploy.
- [ ] Deploy backend (Render) and frontend (Vercel); confirm `GET /health` and `CORS_ORIGINS`.
- [ ] Run `pytest` in `backend/` and `npm run lint` + `npm run build` in `frontend/` on the machine you submit from.
- [ ] Optional: add screenshots per [screenshots/README.md](screenshots/README.md).
- [ ] Optional: record demo when prod URLs are stable (script ideas in [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) Phase 12).

## End-to-end verification (all phases, architecture-aligned)

Run with **backend** and **frontend** dev servers and a real or Docker Postgres URL if you want parity with prod.

1. **Health & CORS:** open `http://localhost:8000/health`; from `http://localhost:3000`, chat should POST without CORS errors.
2. **RAG (Phase 2):** `POST /api/data/ingest` (may take minutes); `GET /api/data/search?q=exit+load` returns hits.
3. **Reviews + pulse (Phase 2–3):** `POST /api/reviews/refresh`; `POST /api/pulse/generate`; `GET /api/pulse/latest` shows themes and actions.
4. **Chat + agents (Phase 4–5):** `/chat` — FAQ question, booking request, confirm traces and booking card.
5. **Integrations (Phase 6):** with `GOOGLE_INTEGRATIONS_MODE=mock`, book and cancel; booking rows show integration metadata in DB/admin.
6. **Voice (Phase 7):** Chrome/Edge — mic on `/chat`; if unsupported, banner appears.
7. **Admin (Phase 8):** `/admin` — analytics load, pulse refresh/generate, subscriber checkbox + mock send, bookings preview.
8. **Memory (Phase 9):** same `user_name`, new `session_id` — returning greeting; “what did we discuss?” recall.
9. **Secure + subscribers (Phase 10):** create booking in chat → `/secure/{code}` verify + submit; `/subscribers` subscribe → admin list shows email.
10. **Hardening (Phase 11):** try PII in chat (blocked), guaranteed-return prompt (refused), invalid booking time (rejected), `EVAL_REPORT.md` matches expectations.

## License / attribution

Built for the AI Bootcamp capstone — see footer on the site for credits.
