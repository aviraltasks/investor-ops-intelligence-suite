# Codebase & technical functionality — Finn (Investor Ops & Intelligence Suite)

**What this is:** A single-document explanation of how the repo **actually works in code**: stack layout, main APIs, **agent orchestration**, **trace schema**, LLM and integrations, and where to look in the source. Use it for onboarding, reviews, or pasting into another LLM when Cursor is not available.

**Keep in sync:** Update when `orchestrator.py`, trace shapes, or major APIs change. Deeper product intent lives in `README.md`, `ARCHITECTURE.md`, `Brain.md`, and `PRD.md`.

---

## 1. Stack & layout

| Layer | Tech | Location |
|-------|------|----------|
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind | `frontend/` |
| Backend | FastAPI, Python | `backend/app/` (ASGI app: `app.main:app`) |
| DB | PostgreSQL in prod; SQLite in many tests | `DATABASE_URL` |
| Deploy | Vercel (frontend), Render (API) | `README.md`, `render.yaml` |

**Important chat / agent files**

- `backend/app/agents/orchestrator.py` — every successful orchestrated turn: `handle_chat_turn`.
- `backend/app/agents/types.py` — trace step schema (`AgentTraceStep`, `AgentResult`).
- `backend/app/main.py` — HTTP routes, **`POST /api/chat`** wrapper (sanitization, PII pre-flight, logging, fallbacks).
- `frontend/components/chat/ChatClient.tsx` — chat UI, `POST /api/chat`, trace sidebar (`?debugAgents=1` shows last payload JSON).
- `frontend/components/chat/agentTraceCopy.ts` — maps `outcome` / `tools` to PM-readable strings (also imported by `frontend/components/admin/AdminDashboardClient.tsx`).

**Supporting modules (orchestrator-related)**

- `backend/app/agents/topic_routing.py` — quick-support topic labels + `message_suggests_support_faq` (used with keyword intents and orchestrator clarifications).
- `backend/app/pii_guard.py` — `contains_pii` (API + orchestrator) and `scrub_pii` (memory saves).
- `backend/app/scheduling/slot_resolution.py` — helpers such as `message_looks_like_slot_refinement` for pending-booking UX.
- `backend/app/ml/theme_pipeline.py` — `get_latest_pulse` (used by review intel + email draft + analytics).

---

## 2. Chat API contract

**Endpoint:** `POST /api/chat`  
**Request body** (`ChatRequest` in `main.py`):

- `message` (string)
- `session_id` (string, default `"default-session"`)
- `user_name` (string, default `"User"`)

**Response** (`ChatResponse`):

- `response` — final assistant markdown/text.
- `traces` — `list[dict]`; each dict matches `AgentTraceStep` (see §3).
- `payload` — arbitrary JSON: often includes `intents`, `booking_code`, `sources`, `advisor_email_draft`, `safe_redirect`, `debug`, etc.

### 2.1 FastAPI boundary (before `handle_chat_turn`)

Implemented in the `chat()` handler in `main.py` (not inside `orchestrator.py`):

| Step | Behavior |
|------|-----------|
| **Sanitization** | `message` stripped then max **2000** chars; `user_name` / `session_id` trimmed and max **128** chars each. |
| **PII pre-flight** | If `contains_pii(req.message)` here, returns **immediately** with `outcome="pii_blocked_pre_agent"`, tools `chat.pii_precheck`, `secure_page_redirect`, payload `intents: ["safety"]` and `safe_redirect`. **`handle_chat_turn` is not called**; **`_log_chat_artifacts` does not run** (no DB row for that request). |
| **Happy path** | `with _db()` → `handle_chat_turn(...)` → `_log_chat_artifacts(session, req, result)` → return traces from `result.traces` as `model_dump()` dicts. |
| **Exception path** | Any uncaught exception: generic apology + synthetic trace `outcome="runtime_fallback"`, `tools=["chat.fallback_guard"]`, payload `{"status":"runtime_fallback"}`. **Does not** call `_log_chat_artifacts`. |

*Note:* The orchestrator can still block PII **inside** `handle_chat_turn` (`outcome="pii_blocked"`, tools `pii_guard`, etc.) if the message reaches orchestration. That path **does** run `_log_chat_artifacts` like other successful handler completions.

### 2.2 Persistence after a successful orchestrated turn (`_log_chat_artifacts`)

Only runs when `handle_chat_turn` completes without raising:

- One **`InteractionLog`** row per intent in `result.payload["intents"]` (FAQ rows skipped when message looks like bot echo — see `_looks_like_bot_generated_text` in `main.py`).
- One **`AgentActivityLog`** row per trace step: `session_id`, `user_name`, `agent`, `reasoning_brief`, `tools_json`, `outcome` (truncated to **120** chars for the DB column), `query_summary` (first **240** chars of user message).

### 2.3 Admin: read logged steps

**`GET /api/admin/agent-activity?limit=…`** returns `{ "count", "items" }`. Each item:

- `timestamp` (ISO from `created_at`), `session_id`, `user_name`, `agent`, `reasoning_brief`, `tools` (array), `outcome`, `query_summary`

---

## 3. Trace step schema (ground truth)

Defined in `backend/app/agents/types.py`:

```python
class AgentTraceStep(BaseModel):
    agent: str              # e.g. "orchestrator", "memory_agent", "rag_agent"
    reasoning_brief: str    # short English explanation (dev-oriented)
    tools: list[str]        # list of tool *names* (strings), not nested objects
    replanned: bool = False # RAG/scheduling can set True when they retry/refine
    outcome: str = ""       # machine-readable outcome / status
```

The UI shows a **friendly summary** derived from `outcome`, `tools`, and sometimes `reasoning_brief`; raw fields stay in **Technical details** (`agentTraceCopy.ts` + `ChatClient.tsx`).

---

## 4. Orchestrator: `handle_chat_turn` pipeline (order matters)

Entry: `handle_chat_turn(session, session_id, user_name, message)` in `orchestrator.py`. *(Assumes the request already passed the API PII pre-flight in `main.py`.)*

Typical **trace order** for a normal turn (simplified):

1. **`memory_agent`** — `load_context`: loads session + user `MemoryFact` rows + latest/pending `Booking` → trace `outcome="context_loaded"`, tools like `db.select(memory_facts)`, `db.select(bookings by session/user)`.
2. **`review_intelligence_agent`** — `get_trending_context`: latest pulse → `pulse_context_loaded` or `no_pulse`.
3. **`orchestrator`** — Early exits (each appends traces and **returns** immediately):
   - Empty message → `input_guard` / `empty_input`.
   - Pending booking confirm + user sends new slot text → may merge with `scheduling.clarify_merge` / `booking_slot_refinement` / `scheduling_context_merge` (then flow **continues**; not always an early return).
   - PII in message → `pii_guard`, `secure_page_redirect` / `pii_blocked`; payload may include `safe_redirect`.
   - Prompt injection phrases → `prompt_injection_guard` / `injection_refused`.
   - Investment-advice style ask → `investment_advice_guard` / `advice_refused`.
   - “Who are you?” style → `identity_reply` / `identity_answer`.
   - Quick-topic chip match → `quick_topic_clarifier` / `clarification_prompt` (from `topic_routing.match_quick_support_topic_label`).
4. **Intent routing** — `orchestrator`:
   - If forced scheduling confirm/reject path → `confirmation_gate`, `memory.pending_schedule_confirm`, outcome like `intents=[scheduling]_confirm_reply`.
   - Else if LLM keys present (`llm_available()`): `chat_completion_safe` JSON `{"intents":[...],"reasoning":"..."}` with allowed intents: `faq`, `scheduling`, `memory_recall`, `review_context`, `general`. Trace lists `llm.groq` or `llm.gemini` (or `llm.none` if call failed) + `outcome=f"intents={intents}"`.
   - If LLM missing or unparsable → keyword `_classify_intents` → `intent_classifier(keyword)` or `intent_fallback(keyword)`.
   - If both `scheduling` and `memory_recall` and user did not explicitly ask for recap → `memory_recall` dropped → `intent.scheduling_priority` / `memory_recall_suppressed`.
5. **Specialists** (for each intent in **list order**):
   - **`faq`** → `rag_agent.answer_faq` — appends **multiple** `rag_agent` traces (retrieval, synthesis, etc.).
   - **`memory_recall`** → orchestrator builds recall text from `mem_ctx` (no separate `memory_agent` trace for the text itself).
   - **`scheduling`** → `scheduling_agent.handle_scheduling` — appends `scheduling_agent` traces; on successful create/cancel may call **`sync_booking_created` / `sync_booking_cancelled`** in `integrations/service.py` (Calendar/Sheets/Gmail queue per mode).
   - **`review_context`** → short text from `trend_ctx` (no extra agent trace block beyond step 2).
   - **`general`** → greeting / pulse teaser / pending booking reminder strings.
6. **Advisor email** — If `booking_code` in payload after scheduling: `email_agent.draft_advisor_email` → `email_drafting_agent` trace (`draft_ready` or `booking_missing`).
7. **Memory save** — Unless `_should_skip_memory_fact` (bot-echo heuristics): `memory_agent.save_fact` for `last_user_message` → trace with `fact_saved_safe` when persisted safely.
8. **Merge** — Only if **`llm_available()`** and **more than one non-empty specialist string** in `responses`: second `chat_completion_safe` merges sections → `orchestrator` trace `response_synthesizer`, `outcome="synthesized"`, tools include `llm.{provider}`. Uses **`http_timeout=25.0`** on that call (shorter than default 90s) so the chat request fails fast if merge hangs.
9. **Length** — `_compact_reply` or `_compact_reply_loose` (scheduling-critical replies use loose compaction so confirmations are not cut mid-sentence).

**Payload `debug`** (merged into `result.payload`; visible in UI under `?debugAgents=1`):

- `clarification_prompt_count`, `fallback_answer_count`, `trace_count` (computed from traces in orchestrator).

---

## 5. Specialist agents (what each module does)

### `memory_agent.py`

- `load_context` → context dict + trace (`context_loaded`).
- `save_fact` / PII scrub via `pii_guard.scrub_pii` before insert.
- Pending scheduling JSON in `MemoryFact` keys: `pending_schedule_confirm`, `pending_scheduling_clarify`, etc.; helpers `get_*` / `clear_*` / `save_pending_*` used by orchestrator + `scheduling_agent` for two-phase confirm / clarify flows.

### `review_intel_agent.py`

- `get_trending_context` → latest pulse from DB (`get_latest_pulse`) + trace `pulse_context_loaded` or `no_pulse`.

### `rag_agent.py`

- `answer_faq(session, message)` → `AgentResult` with **many** traces: retrieval planning, vector/lexical search, sufficiency, optional LLM synthesis, outcomes like `faq_answer`, `hits=N`, `clarification_prompt`, etc. (Large file — this guide does not list every branch.)

### `scheduling_agent.py`

- `handle_scheduling(session, session_id, user_name, message)` → booking lifecycle: parse time, weekday/hours guards, slots, confirm/cancel/reschedule/waitlist paths.
- **Integrations:** imports `sync_booking_created`, `sync_booking_cancelled` from `app.integrations.service` so successful lifecycle updates Calendar/Sheets/draft metadata according to `GOOGLE_INTEGRATIONS_MODE`.

### `email_agent.py`

- `draft_advisor_email(session, booking_code)` → loads `Booking` + optional pulse theme; template or LLM JSON → `draft_text` in payload; trace `draft_ready` / `booking_missing`.

### `orchestrator.py`

- Routing, safety, intent list, calling specialists, merge, compact reply, `debug` payload.

---

## 6. LLM usage (`backend/app/llm/client.py`)

- **Keys:** `GROQ_API_KEY`, `GEMINI_API_KEY` (either can satisfy `llm_available()`).
- **Provider order:** `chat_completion` tries **Groq first** (`GROQ_MODEL`, default `llama-3.3-70b-versatile`); on failure, **Gemini** if `GEMINI_API_KEY` is set (`GEMINI_MODEL`, default `gemini-2.5-flash-lite`). Endpoints: Groq OpenAI-compatible `/chat/completions`; Gemini `generateContent` v1beta.
- **`chat_completion_safe`:** wraps `chat_completion`, never raises; returns `provider="none"` and empty text on total failure (orchestrator handles that path).
- **Tests:** If `PYTEST_CURRENT_TEST` is set, `llm_available()` is **false** unless `ENABLE_LLM_IN_PYTEST` is `1`/`true`/`yes` — keeps CI deterministic when developers have keys locally.
- **Call sites (non-exhaustive):** orchestrator intent JSON + merge; `rag_agent`, `scheduling_agent` (voice polish), `email_agent` (structured draft), and other agents as implemented in their modules.

---

## 7. Integrations (`backend/app/integrations/service.py`)

- Mode: `GOOGLE_INTEGRATIONS_MODE=mock|live` (see `README` / `.env.example`).
- **Ports:** `CalendarPort` (tentative hold, cancel), `SheetsPort` (booking row upsert), `GmailPort` (queue advisor draft metadata).
- **Named sync helpers** used from scheduling: `sync_booking_created`, `sync_booking_cancelled` (wrap port calls + metadata on `Booking`).
- Mock adapters return deterministic success for dev/tests; live uses Google APIs when IDs + service account are configured.

---

## 8. Other notable HTTP routes (`main.py`)

| Area | Routes |
|------|--------|
| Health / root | `GET /health`, `GET /` |
| RAG / data | `POST /api/data/ingest`, `GET /api/data/stats`, `GET /api/data/search` |
| Reviews / pulse | `POST /api/reviews/refresh`, `POST /api/pulse/generate`, `GET /api/pulse/latest`, `GET /api/pulse/history` |
| Chat | `POST /api/chat` |
| Admin analytics | `GET /api/admin/analytics`, `GET /api/admin/export/analytics.csv` |
| Admin ops | `POST /api/admin/pulse/append-doc`, `POST /api/admin/pulse/send`, `POST /api/admin/cache/faq/clear`, `POST /api/admin/maintenance/normalize-faq-topics` |
| Admin bookings / email | `GET /api/admin/bookings`, `POST /api/admin/bookings/{code}/email/preview`, `POST /api/admin/bookings/{code}/email/send` |
| Admin audience / logs | `GET /api/admin/subscribers`, `GET /api/admin/agent-activity` |
| Public subscribers | `POST /api/subscribers` |
| Secure booking | `GET /api/secure/{booking_code}`, `POST /api/secure/{booking_code}/details` |

---

## 9. How to interpret a trace in practice

1. Read **`agent`** — who produced the step.
2. Read **`outcome`** — primary machine label (orchestrator uses `intents=[...]` strings; specialists use their own vocab).
3. Read **`tools`** — parallel list of string labels (`llm.groq`, `db.select(...)`, guards, etc.).
4. Use **`reasoning_brief`** for the author’s short narrative (may duplicate outcome semantics).

For **plain-language labels** aligned with the product UI, see the mapping tables and functions in `frontend/components/chat/agentTraceCopy.ts` (`traceWhatHappenedLine`, `OUTCOME_LABELS`, `TOOL_LABELS`, intent parsing).

---

## 10. Tests as executable spec

| File | Focus |
|------|--------|
| `backend/tests/test_phase2_step*.py` | RAG ingest / data pipeline steps |
| `backend/tests/test_phase3_ml_pipeline.py` | Pulse / ML themes |
| `backend/tests/test_phase4_agents.py` | Orchestration / chat |
| `backend/tests/test_phase6_integrations.py` | Google integration layer |
| `backend/tests/test_phase8_admin.py` | Admin + agent activity API |
| `backend/tests/test_phase9_memory.py` | Memory / recall |
| `backend/tests/test_phase10_secure_subscribers.py` | Secure page + subscribers |
| `backend/tests/test_phase11_hardening.py` | Safety + scheduling edges |
| `backend/tests/test_phase12_reschedule_waitlist.py` | Reschedule / waitlist flows |
| `backend/tests/test_phase13_prepare.py` | “What to prepare” / prepare flows |
| `backend/tests/test_phase14_rag_reliability.py` | RAG reliability |
| `backend/tests/test_phase15_slot_resolution.py` | Slot-resolution helpers |
| `backend/tests/test_llm_client.py` | LLM client defaults + pytest gating |

Run: `cd backend && pytest`

---

## 11. FAQ (quick answers)

- “What runs first on every chat message?” → **API** sanitization + optional PII block; if allowed, DB session + **memory** `load_context` + **review intel** pulse context, then orchestrator guards + intents + specialists + optional merge.
- “Why do I see two `orchestrator` steps?” → e.g. intent routing + later `synthesized` merge, or guard steps vs routing, or `memory_recall_suppressed` after intents.
- “Where is booking code set?” → `scheduling_agent` puts `booking_code` in its `AgentResult.payload`; orchestrator merges into top-level `payload`; email draft reads it.
- “What’s the difference between `traces` and admin Agent Activity Log?” → Same step content for successful turns: API returns live `traces`; `_log_chat_artifacts` copies each step to `agent_activity_logs` for `GET /api/admin/agent-activity`. **API-level PII block and runtime fallback do not write activity rows.**
- “When is LLM merge skipped?” → Single non-empty specialist response, or `llm_available()` false, or merge returns empty text (then prior joined text is used before compaction).

If something disagrees with this file, **the Python source wins** — treat this document as a map, not a second codebase.
