# Finn — Office / Claude upload brief

**Purpose:** One file to upload (e.g. to Claude web) when you cannot use Cursor. It summarizes how the **Investor Ops & Intelligence Suite** actually works in code, especially **agents**, **traces**, and **APIs**.

**Refresh:** Regenerate or edit this file when `orchestrator.py`, trace shapes, or major APIs change. Repo root also has `README.md`, `ARCHITECTURE.md`, `Brain.md`, `PRD.md` for full product context.

---

## 1. Stack & layout

| Layer | Tech | Location |
|-------|------|----------|
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind | `frontend/` |
| Backend | FastAPI, Python | `backend/app/` |
| DB | PostgreSQL in prod; SQLite in many tests | `DATABASE_URL` |
| Deploy | Vercel (frontend), Render (API) | `README.md` |

**Important chat files**

- `backend/app/agents/orchestrator.py` — every turn starts here: `handle_chat_turn`.
- `backend/app/agents/types.py` — trace step schema (`AgentTraceStep`, `AgentResult`).
- `frontend/components/chat/ChatClient.tsx` — UI, sends `POST /api/chat`, renders traces.
- `frontend/components/chat/agentTraceCopy.ts` — maps `outcome` / `tools` to PM-readable strings (same ideas as admin log).

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

**Persistence after each chat turn** (`_log_chat_artifacts` in `main.py`):

- One `InteractionLog` row per intent (for admin analytics FAQ/booking topics).
- One `AgentActivityLog` row **per trace step** (same fields as trace; `outcome` truncated to 120 chars for DB column).

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

Entry: `handle_chat_turn(session, session_id, user_name, message)` in `orchestrator.py`.

Typical **trace order** for a normal turn (simplified):

1. **`memory_agent`** — `load_context`: loads session + user `MemoryFact` rows + latest/pending `Booking` → trace `outcome="context_loaded"`, tools like `db.select(memory_facts)`, `db.select(bookings by session/user)`.
2. **`review_intelligence_agent`** — `get_trending_context`: latest pulse → `pulse_context_loaded` or `no_pulse`.
3. **`orchestrator`** — Early exits (each appends traces and **returns** immediately):
   - Empty message → `input_guard` / `empty_input`.
   - Pending booking confirm + user sends new slot text → may merge with `scheduling.clarify_merge` / `booking_slot_refinement` / `scheduling_context_merge`.
   - PII in message → `pii_guard`, `secure_page_redirect` / `pii_blocked`; payload may include `safe_redirect`.
   - Prompt injection phrases → `prompt_injection_guard` / `injection_refused`.
   - Investment-advice style ask → `investment_advice_guard` / `advice_refused`.
   - “Who are you?” style → `identity_reply` / `identity_answer`.
   - Quick-topic chip match → `quick_topic_clarifier` / `clarification_prompt`.
4. **Intent routing** — `orchestrator`:
   - If forced scheduling confirm/reject path → `confirmation_gate`, `memory.pending_schedule_confirm`, outcome like `intents=[scheduling]_confirm_reply`.
   - Else if LLM keys present (`llm_available()`): `chat_completion_safe` JSON `{"intents":[...],"reasoning":"..."}` with allowed intents: `faq`, `scheduling`, `memory_recall`, `review_context`, `general`. Trace lists `llm.groq` or `llm.gemini` (or fallback) + `outcome=f"intents={intents}"`.
   - If LLM missing or unparsable → keyword `_classify_intents` → `intent_classifier(keyword)` or `intent_fallback(keyword)`.
   - If both `scheduling` and `memory_recall` and user did not explicitly ask for recap → `memory_recall` dropped → `intent.scheduling_priority` / `memory_recall_suppressed`.
5. **Specialists** (for each intent in order):
   - **`faq`** → `rag_agent.answer_faq` — appends **multiple** `rag_agent` traces (retrieval, synthesis, etc.).
   - **`memory_recall`** → orchestrator builds recall text from `mem_ctx` (no separate agent file for the reply).
   - **`scheduling`** → `scheduling_agent.handle_scheduling` — appends `scheduling_agent` traces.
   - **`review_context`** → short text from `trend_ctx` (no extra agent trace block beyond step 2).
   - **`general`** → greeting / pulse teaser / pending booking reminder strings.
6. **Advisor email** — If `booking_code` in payload: `email_agent.draft_advisor_email` → `email_drafting_agent` trace (`draft_ready` or `booking_missing`).
7. **Memory save** — Unless skipped (bot echo heuristics): `memory_agent.save_fact` for `last_user_message` → trace with `fact_saved_safe` etc.
8. **Merge** — If more than one non-empty specialist section and LLM available: second `chat_completion_safe` call merges sections → `orchestrator` trace `response_synthesizer`, `outcome="synthesized"`, tools include `llm.{provider}`. HTTP timeout for this merge is **25s** (see call in code).
9. **Length** — `_compact_reply` or `_compact_reply_loose` (scheduling-critical replies kept looser so confirmations are not cut mid-sentence).

**Payload `debug`** (useful for support; also visible under `?debugAgents=1` in UI for payload JSON):

- `clarification_prompt_count`, `fallback_answer_count`, `trace_count` (computed from traces in orchestrator).

---

## 5. Specialist agents (what each module does)

### `memory_agent.py`

- `load_context` → context dict + trace (`context_loaded`).
- `save_fact` / PII scrub via `pii_guard.scrub_pii` before insert.
- Pending scheduling JSON in `MemoryFact` keys: `pending_schedule_confirm`, `pending_scheduling_clarify`, etc. Used by orchestrator + scheduling for two-phase confirm flows.

### `review_intel_agent.py`

- `get_trending_context` → latest pulse from DB (`get_latest_pulse`) + trace `pulse_context_loaded` or `no_pulse`.

### `rag_agent.py`

- `answer_faq(session, message)` → `AgentResult` with **many** traces: retrieval planning, vector/lexical search, sufficiency, optional LLM synthesis, outcomes like `faq_answer`, `hits=N`, `clarification_prompt`, etc. (Large file — this brief does not list every branch.)

### `scheduling_agent.py`

- `handle_scheduling(session, session_id, user_name, message)` → booking lifecycle: parse time, weekday/hours guards, slots, confirm/cancel/reschedule/waitlist paths, integration hooks. Emits `scheduling_agent` traces with outcomes such as `booked_tentative`, `slots_returned`, `cancelled`, `llm_voice`, etc.

### `email_agent.py`

- `draft_advisor_email(session, booking_code)` → loads `Booking` + optional pulse theme; template or LLM JSON → `draft_text` in payload; trace `draft_ready` / `booking_missing`.

### `orchestrator.py`

- Routing, safety, intent list, calling specialists, merge, compact reply, `debug` payload.

---

## 6. LLM usage (`backend/app/llm/client.py`)

- **Groq** primary (`GROQ_API_KEY`), OpenAI-compatible chat API.
- **Gemini** fallback (`GEMINI_API_KEY`); default model env `GEMINI_MODEL` defaulting to `gemini-2.5-flash-lite` in code.
- `chat_completion_safe(...)` returns provider + text; used for intent JSON, RAG steps, scheduling voice polish, email draft, **merge** step.
- `llm_available()` is true if either key is set (see `client.py` / health).

---

## 7. Integrations (`backend/app/integrations/service.py`)

- Mode: `GOOGLE_INTEGRATIONS_MODE=mock|live` (see `README` / `.env.example`).
- **Ports:** `CalendarPort` (tentative hold, cancel), `SheetsPort` (booking row upsert), `GmailPort` (queue advisor draft metadata).
- Mock adapters return deterministic success for dev/tests; live uses Google APIs when IDs + service account are configured.

---

## 8. Other notable HTTP routes (`main.py`)

| Area | Examples |
|------|-----------|
| Health | `GET /health` |
| RAG / data | `POST /api/data/ingest`, `GET /api/data/stats`, `GET /api/data/search` |
| Reviews / pulse | `POST /api/reviews/refresh`, `POST /api/pulse/generate`, `GET /api/pulse/latest`, `GET /api/pulse/history` |
| Admin | `GET /api/admin/analytics`, `GET /api/admin/bookings`, `GET /api/admin/subscribers`, `GET /api/admin/agent-activity`, booking email preview/send, pulse send, FAQ cache clear, maintenance |
| Secure / subs | `GET/POST /api/secure/{booking_code}`, `POST /api/subscribers` |

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
| `backend/tests/test_phase4_agents.py` | Orchestration / chat |
| `backend/tests/test_phase8_admin.py` | Admin + agent activity API |
| `backend/tests/test_phase9_memory.py` | Memory / recall |
| `backend/tests/test_phase11_hardening.py` | Safety + scheduling edges |
| `backend/tests/test_llm_client.py` | LLM client defaults |

Run: `cd backend && pytest`

---

## 11. Questions this brief is meant to answer

- “What runs first on every chat message?” → Memory load + pulse context, then orchestrator guards + intents + specialists + optional merge.
- “Why do I see two `orchestrator` steps?” → e.g. intent routing + later `synthesized` merge, or guard steps vs routing.
- “Where is booking code set?” → `scheduling_agent` payload consumed by orchestrator; email draft uses it.
- “What’s the difference between `traces` and admin Agent Activity Log?” → Same steps: API returns traces live; `_log_chat_artifacts` copies each step to `agent_activity_logs` for `/api/admin/agent-activity`.

If something disagrees with this file, **the Python source wins** — treat this document as a map, not a second codebase.
