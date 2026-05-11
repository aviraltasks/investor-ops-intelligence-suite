# DEVELOPMENT_PLAN.md — Phase-by-Phase Build Plan

**Purpose:** Phase-level checklist. Single source of truth for "what phase are we in?"
**Rule:** Complete one phase → test → deploy → then move to next. Never skip.
**Timeline:** ~3 days (May 5–7, 2026). Submission deadline: May 7, 11:59 PM IST.

---

## Phase Checklist

| Phase | Name | Status | Session Notes |
|-------|------|--------|---------------|
| 0 | Documentation & Architecture | [x] | ARCHITECTURE.md, .env.example, .gitignore, docker-compose for Postgres |
| 1 | Scaffold & Deploy | [x] | Next.js `frontend/` (all routes, header/footer), FastAPI `backend/` + `GET /health`, pytest, render.yaml; Windows path `&` → npm scripts call `node …/next` directly; deploy: connect Vercel/Render per README |
| 2 | Data Pipeline (RAG + Reviews) | [x] | Implemented RAG ingest/search pipeline (`/api/data/ingest`, `/api/data/stats`, `/api/data/search`), review refresh with Play Store + CSV fallback (`/api/reviews/refresh`), source manifest (31+ URLs), and `DATA_PIPELINE.md`; validated via unit tests (step1/2/3) |
| 3 | ML Pipeline (Theme Detection) | [x] | Added lightweight ML clustering pulse pipeline (`backend/app/ml/theme_pipeline.py`) with silhouette metric, top-3 themes + quotes + analysis + 3 actions, persisted run/theme history (`pulse_runs`, `pulse_themes`), comparison payload (ML vs baseline), and APIs (`/api/pulse/generate`, `/api/pulse/latest`, `/api/pulse/history`); validated by unit tests |
| 4 | Agentic Core (Orchestrator + Agents) | [x] | Implemented multi-agent backend orchestration via `POST /api/chat` with traceable steps (orchestrator, RAG, scheduling, review-intel, email drafting, memory agents), local booking lifecycle persistence, memory continuity, and HITL-style advisor draft payload; validated with dedicated Phase 4 unit tests |
| 5 | Chat UI & Agent Panel | [x] | Implemented full `/chat` UI with three-column layout, disclaimer/date/hours, message bubbles, quick topics, backend-wired composer (`/api/chat`), live processing indicators, booking confirmation card rendering, and real agent activity panel traces from backend |
| 6 | Scheduling & Google Integrations | [x] | Wired scheduling lifecycle to integration service (`app/integrations/service.py`) with Calendar hold create/cancel, Sheets row upsert, advisor email draft queue metadata, and graceful fallback (`GOOGLE_INTEGRATIONS_MODE=mock/live`); booking records now store integration refs/status; validated with dedicated Phase 6 tests |
| 7 | Voice Layer | [x] | Implemented Web Speech API voice layer on `/chat` with mic states (idle/listening/processing/speaking), STT input to same `/api/chat` pipeline, TTS response playback, auto text fallback banner on voice errors/unsupported browsers, and stop-on-unload cleanup |
| 8 | Admin Dashboard & Pulse | [x] | Implemented full `/admin` workflow with analytics APIs/UI, pulse refresh+generate+send controls, bookings table with preview/send email actions, subscriber selection, and persisted agent activity log endpoints; validated with dedicated Phase 8 tests |
| 9 | Memory System | [x] | Upgraded memory to session + cross-session user context, added memory-recall intent ("what did we discuss"), returning-user personalized greeting, proactive pending booking reminders, and PII scrubbing before memory persistence; validated via dedicated Phase 9 tests + full regression |
| 10 | Secure Page & Subscriber Page | [x] | Implemented functional `/secure/[bookingCode]` booking verification + secure details form (phone/email/consent validation, invalid-code handling, persisted sheet K/L payload metadata) and `/subscribers` email signup UI wired to backend; validated with dedicated Phase 10 tests + full regression |
| 11 | Edge Cases, Evals & Hardening | [x] | Added hard safety guards (PII block + secure redirect, investment-advice refusal, prompt-injection refusal), input sanitization, and scheduling hardening (invalid/past/weekend/out-of-hours rejection, slot conflict detection, already-cancelled handling); added `test_phase11_hardening.py`; generated `EVAL_REPORT.md`; full regression green |
| 12 | README, Demo & Submission | [x] | README expanded (architecture summary, agents, APIs, full 31+ URL manifest, submission + E2E verification checklists); `screenshots/README.md` capture guide; `EVAL_REPORT.md` linked; demo video deferred per PM (record after prod deploy); run `pytest` + `npm run lint` + `npm run build` green |

### Post–Phase 12 (maintenance)

- **May 2026 — Agent visibility UX:** Chat agent panel uses step badges, shared PM-facing labels (`agentTraceCopy.ts`), and collapsed technical details; admin Agent Activity Log uses the same mapping for consistent reviewer/PM experience.

---

## Phase Details

### Phase 0 — Documentation & Architecture

**Goal:** All planning docs in repo. Cursor reads everything and creates ARCHITECTURE.md.

**Acceptance:**
- All PM-authored MD files in repo (Brain, PRD, UI_UX_SPEC, SCRIPT_FLOW, DEVELOPMENT_PLAN, EDGE_CASES_CHECKLIST, EVAL_CRITERIA, HEALTH)
- `.env.example` with all required variables listed
- `.gitignore` configured
- Cursor reads all docs and creates ARCHITECTURE.md with: tech stack, agent design, ML pipeline design, API design, folder structure, phase mapping
- ARCHITECTURE.md reviewed and approved by PM before any code

**Do not:** Write any application code.

---

### Phase 1 — Scaffold & Deploy

**Goal:** Live URLs on Vercel and Render with skeleton pages.

**Acceptance:**
- Vercel URL shows landing page with both input paths (name + booking code)
- Render health endpoint (`GET /health`) returns structured JSON
- All page routes exist (/, /chat, /admin, /secure/[code], /subscribers) — can be shells
- Navigation works between pages
- Footer on all pages (name, LinkedIn, Built with Cursor, System Design)
- Frontend deployed on Vercel, backend deployed on Render
- Environment variables wired on both platforms

**Do not:** Bot logic, integrations, ML, agents, or chat functionality.

---

### Phase 2 — Data Pipeline (RAG + Reviews)

**Goal:** Knowledge base populated and queryable. Reviews fetched and stored.

**Acceptance:**
- 15 Groww mutual fund pages scraped successfully (all 8 topics per fund)
- 9 SEBI educational pages scraped and processed
- Text cleaned, chunked, and embedded into vector store
- Vector store queryable — sample queries return relevant chunks
- Play Store reviews for Groww fetched and stored (or CSV fallback loaded)
- Data pipeline documented (what was scraped, chunk count, embedding details)
- Fallback: if scraping fails for any source, local data files can be loaded

**Do not:** ML pipeline, agent logic, chat UI. Data pipeline only.

---

### Phase 3 — ML Pipeline (Theme Detection)

**Goal:** Working ML clustering pipeline that identifies themes from reviews.

**Acceptance:**
- Reviews processed through ML pipeline (embeddings → clustering → theme groups)
- LLM labels identified clusters into human-readable themes
- Structured pulse output generated: top 3 themes, quotes, analysis, 3 actions
- ML metrics documented (clustering quality metric appropriate to chosen algorithm)
- Comparison: ML-identified themes vs. LLM-only extraction — documented difference
- Theme history stored for trend tracking
- Fallback: if ML pipeline fails, LLM-based extraction produces themes (lower quality but functional)

**Do not:** Agents, chat UI, scheduling. ML pipeline only.

---

### Phase 4 — Agentic Core (Orchestrator + Agents)

**Goal:** All agents operational with reasoning, tool calling, and evaluation loops. Testable via API.

**Acceptance:**
- **Orchestrator Agent:** Receives user messages, reasons about intent, routes to specialist agents, evaluates combined output. Can handle multi-intent queries.
- **RAG Agent:** Plans retrieval strategy, executes search, evaluates sufficiency, re-retrieves if needed, generates cited answers. Handles all three query types (single, cross-source, cross-fund).
- **Scheduling Agent:** Handles all 5 intents (book, reschedule, cancel, prepare, availability). Validates IST, working hours, weekdays. Generates booking codes (GRW-XXXX format). In-memory bookings for now.
- **Review Intelligence Agent:** Returns current themes and trending context on demand. Pulse generation functional.
- **Email Drafting Agent:** Assembles 3-section advisor email (booking + concern + market context). Drafts queued.
- **Memory Agent:** Extracts and stores key facts per turn. Short-term memory functional.
- All agents demonstrate reasoning (visible in logs), tool calling, result evaluation, and re-planning.
- Testable via `POST /api/chat` — full conversational flows work via text API.
- Dual LLM fallback working (Groq primary → Gemini fallback).
- Token optimization: history truncation, lean prompts, caching.

**Do not:** Frontend chat UI (test via API/curl), Google integrations, voice, admin dashboard.

---

### Phase 5 — Chat UI & Agent Panel

**Goal:** Full chat interface connected to agentic backend.

**Acceptance:**
- Chat page (/chat) fully functional with styled message bubbles
- Left sidebar: covered schemes, example questions, quick topics, trending theme badge
- Agent activity panel (right sidebar): shows agent + **what happened** (mapped summary), step order, and **Technical details** with raw reasoning, tools, outcomes, re-plan flag per query
- Transparency indicators during processing ("Searching knowledge base...", etc.)
- Booking confirmation card renders inline with copyable code
- Example questions clickable (auto-send to Finn)
- Topic quick-select cards functional
- Disclaimer banner on first interaction
- Today's date displayed
- Mic button visible but inactive (placeholder for Phase 7)
- Responsive: works on desktop and mobile
- Loading/skeleton states on page load
- Empty state: welcome message + examples before first interaction

**Do not:** Voice, Google integrations, admin page, secure page.

---

### Phase 6 — Scheduling & Google Integrations

**Goal:** Real Google Calendar, Sheets, and email integrations firing on booking actions.

**Acceptance:**
- Booking creates real Google Calendar event (title format per PRD)
- Booking appends row to Google Sheet (all columns per PRD §6.1)
- Reschedule: old row → "rescheduled", new row + new calendar event
- Cancel: row → "cancelled", calendar hold deleted
- Waitlist: row with "waitlisted", waitlist calendar hold
- Secure URL column populated in sheet
- Advisor email draft created and queued (Gmail SMTP configured)
- Email contains all 3 sections (booking details, user concern, market context)
- Changes visible in actual Google Calendar and Sheet
- Booking code format: GRW-XXXX (not the old AV-IND format)

**Do not:** Voice, admin dashboard, memory persistence.

---

### Phase 7 — Voice Layer

**Goal:** Voice input and output working on chat page.

**Acceptance:**
- Can speak to Finn and hear spoken response (Web Speech API, Chrome/Edge HTTPS)
- Full booking flow works entirely via voice
- Mic button shows states: idle → listening → processing → speaking
- Booking code spelled out character by character in voice
- Finn says "visit our website and enter your booking code" (no URL spoken)
- Fallback: if voice fails, auto-switch to text with notification banner
- TTS stops on page navigate
- Same agent pipeline processes voice — no separate voice logic

**Do not:** Over-optimize. Working voice > perfect voice.

---

### Phase 8 — Admin Dashboard & Pulse

**Goal:** Full admin dashboard with analytics, pulse management, email management, bookings.

**Acceptance:**
- Admin page loads without password
- **Analytics:** 4 graphs with date range selectors
  - Graph 1: Review themes (from ML pipeline)
  - Graph 2: Appointments booked over time
  - Graph 3: Booking topics distribution
  - Graph 4: FAQ question topics
- **Pulse management:**
  - "Refresh Reviews" button works
  - "Generate Pulse" creates preview with themes, quotes, analysis, actions
  - "Append to Google Doc" works
  - Download reviews CSV
- **Bookings table:**
  - All bookings with status pills (color-coded)
  - Sortable, filterable
  - CSV export
  - Expandable booking details
- **Email management per booking:**
  - Advisor email editable
  - Preview shows full formatted email
  - Send dispatches via Gmail
  - Status: Draft → Sent
- **Subscriber management:**
  - Subscriber list with checkboxes
  - "Send Pulse Email" sends to selected
- **Agent activity log:**
  - Recent agent decisions visible
  - Reasoning traces, tool calls, routing decisions

**Do not:** Over-polish. Functional admin > beautiful admin.

---

### Phase 9 — Memory System

**Goal:** Full memory system — short-term, long-term, cross-channel.

**Acceptance:**
- Short-term: session context maintained. "What did we discuss?" works.
- Long-term: returning user recognized. Past bookings and topics surfaced.
- Cross-channel: voice session memory carries to text session and vice versa.
- Returning user greeting personalized with past context.
- Pending booking mentioned proactively.
- Graceful degradation: if memory unavailable, system works as if new user.
- Memory does not store PII.

**Do not:** Sacrifice stability for memory features. Memory is important but system must work without it.

---

### Phase 10 — Secure Page & Subscriber Page

**Goal:** Secure details and subscriber pages fully functional.

**Acceptance:**
- `/secure/[bookingCode]` shows booking summary
- Form validates phone (+91 format), email, consent checkbox
- Submit updates Google Sheet (columns K, L)
- Invalid booking code shows error
- Success state after submission
- `/subscribers` page: email input + subscribe button
- Subscription stored for admin to select when sending pulse
- Both pages: responsive, clean, footer present

---

### Phase 11 — Edge Cases, Evals & Hardening

**Goal:** System handles edge cases gracefully. Eval suite completed.

**Acceptance:**
- **Edge cases tested** (from EDGE_CASES_CHECKLIST.md):
  - Date/time validation (past dates, weekends, out-of-hours)
  - PII blocking
  - Investment advice refusal
  - Prompt injection resistance
  - Intent switching mid-flow
  - Invalid/duplicate booking codes
  - Slot exhaustion → waitlist
  - Cancel already-cancelled booking
  - Reschedule cancelled booking
- **Evals completed** (from EVAL_CRITERIA.md):
  - RAG golden dataset: 5 questions scored for faithfulness + relevance
  - Safety: 3 adversarial prompts — 100% pass
  - Tone/structure: pulse format check, trending theme mention
  - ML metrics: clustering quality, comparison with LLM-only
- **Evals report generated:** Markdown file with all results, scores, honest assessment
- **Fallbacks verified:** LLM failover, RAG degradation, Google API failure, voice failure
- **Mobile responsive verified**
- **Session timeout handling** (idle sessions cleared after configurable period)
- **Input sanitization** on all user inputs

---

### Phase 12 — README, Demo & Submission

**Goal:** All submission deliverables complete.

**Acceptance:**
- **README.md** complete: project overview, setup instructions, architecture summary, fund coverage, data pipeline description, agent descriptions, how to run locally, how to deploy
- **Source manifest:** 30+ official URLs listed in README
- **Screenshots:** Key screens captured (chat, admin, booking, pulse, agent panel)
- **Demo video:** ≤5 minutes showing:
  1. Review CSV → Pulse generation (admin)
  2. Voice call booking using pulse context (customer)
  3. Smart FAQ answering a complex cross-source question (customer)
  4. Agent activity panel showing real reasoning
- **DEVELOPMENT_PLAN.md:** All phases checked off
- **HEALTH.md:** Final status updated
- **EVAL report:** Submitted as markdown file
- **Live URLs verified:** Vercel + Render accessible
- **Git:** Clean commits, meaningful messages

---

## Time Allocation Guidance

With ~3 days, rough time allocation:

| Priority | Phases | Estimated Effort |
|----------|--------|-----------------|
| Critical | 0, 1, 2, 4, 5 | ~40% (Architecture, data, agents, chat UI) |
| High | 3, 6, 8 | ~30% (ML, Google integrations, admin) |
| Medium | 7, 9, 10 | ~15% (Voice, memory, secure/subscriber pages) |
| Final | 11, 12 | ~15% (Hardening, evals, submission) |

**If running behind:** Cut voice polish (keep text working), simplify admin graphs (fewer filters), reduce memory to short-term only. Protect: agentic core, RAG, ML pipeline, eval suite.

---

*Check off phases as they complete. Add session notes for learnings. Update HEALTH.md and IMPROVEMENT.md alongside.*
