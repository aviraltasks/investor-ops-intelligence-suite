/**
 * Human-readable labels for agent traces — shared by the chat sidebar and admin Agent Activity Log.
 */

const INTENT_LABEL: Record<string, string> = {
  faq: "FAQ question",
  scheduling: "Booking",
  memory_recall: "Past chat",
  review_context: "Review trends",
  general: "General",
};

const TOOL_LABELS: Record<string, string> = {
  "scheduling.clarify_merge": "Merged your date and time details",
  "scheduling.slot_refinement": "Updated your booking time before confirmation",
  "intent.scheduling_priority": "Prioritised booking over recap",
  "input_guard": "Checked your message was not empty",
  "pii_guard": "Checked for sensitive personal details",
  "secure_page_redirect": "Offered a secure page for sensitive details",
  "prompt_injection_guard": "Blocked an unsafe instruction pattern",
  "investment_advice_guard": "Blocked personalised investment advice",
  "identity_reply": "Answered a name or identity question",
  "quick_topic_clarifier": "Asked how you want help on this topic",
  "confirmation_gate": "Handled a yes/no on booking or cancellation",
  "memory.pending_schedule_confirm": "Checked pending booking confirmation",
  "memory_context": "Used your recent chat context",
  "pulse_context": "Used latest app-review themes",
  "intent_classifier(keyword)": "Matched your message to help areas (rules)",
  "intent_fallback(keyword)": "Matched your message to help areas (fallback)",
  "response_synthesizer": "Combined specialist replies into one answer",
  "db.select(memory_facts)": "Checked conversation history",
  "db.select(bookings by session/user)": "Looked up your bookings",
  "db.select(bookings)": "Looked up bookings",
  "db.select(pulse_runs)": "Loaded latest review insights",
  "db.select(pulse_themes)": "Loaded review theme summaries",
  "pii_scrubber": "Removed sensitive details before saving",
  "db.insert(memory_facts)": "Saved a memory note for next time",
  "slot_generator(local_rules)": "Suggested available time slots",
  "time_parser": "Read the date and time you gave",
  "working_hours_guard": "Checked advisor hours (9am–6pm IST)",
  "weekday_guard": "Checked weekday-only booking rules",
  "gmail.queue_draft": "Queued advisor email draft",
  "calendar.cancel_hold": "Updated calendar hold",
  "sheets.upsert_row": "Updated booking spreadsheet",
};

function toolLabel(tool: string): string | null {
  if (TOOL_LABELS[tool]) return TOOL_LABELS[tool];
  if (tool.startsWith("llm.")) return "Polished wording with AI";
  if (tool.startsWith("db.select(")) {
    const inner = tool.slice("db.select(".length, -1);
    if (inner.includes("memory")) return "Checked conversation history";
    if (inner.includes("pulse_runs")) return "Loaded latest review insights";
    if (inner.includes("pulse_themes")) return "Loaded review theme summaries";
    if (inner.includes("booking")) return "Looked up bookings";
    return "Looked up stored data";
  }
  return null;
}

/** Parse outcomes like intents=['faq', 'scheduling'] or intents=[scheduling]_confirm_reply */
function parseIntentList(outcome: string): string[] | null {
  const m = outcome.match(/intents=\[([^\]]+)\]/);
  if (!m) return null;
  const inner = m[1];
  return inner
    .split(",")
    .map((s) => s.trim().replace(/^['"]|['"]$/g, ""))
    .filter(Boolean);
}

function formatIntentList(intents: string[]): string {
  const labels = intents.map((i) => INTENT_LABEL[i] || i.replace(/_/g, " "));
  if (labels.length === 1) return `Classified as: ${labels[0]}`;
  return `Classified as: ${labels.join(", ")}`;
}

const OUTCOME_LABELS: Record<string, string> = {
  context_loaded: "Context loaded",
  pulse_context_loaded: "Review insights loaded",
  no_pulse: "No pulse report available yet",
  scheduling_context_merge: "Ready to proceed with booking",
  booking_slot_refinement: "Adjusted your slot before confirming",
  memory_recall_suppressed: "Focused on booking instead of recap",
  synthesized: "Combined specialist replies",
  empty_input: "Asked for a clearer message",
  pii_blocked: "Sensitive details blocked in chat",
  injection_refused: "Unsafe instruction blocked",
  advice_refused: "Investment advice request declined",
  identity_answer: "Introduced Finn",
  clarification_prompt: "Asked what kind of help you want",
  waitlisted: "Added you to a waitlist",
  booked_tentative: "Created a tentative booking",
  book_confirm_conflict: "That time was already taken",
  cancelled: "Cancelled the booking",
  already_cancelled: "Booking was already cancelled",
  cancel_confirm_missing: "Needed a clear yes/no to cancel",
  llm_voice: "Smoothed the reply wording",
  invalid_time_request: "Asked for a valid weekday time",
  post_booking_idle: "Noted you already have this slot booked",
  post_booking_slot_suppressed: "Ignored duplicate slot after booking",
  conflict: "Slot conflict with another booking",
  slots_returned: "Listed available slots",
  faq_answer: "Answered from fund sources",
  fact_saved_safe: "Saved a non-sensitive memory note from this turn",
  draft_ready: "Advisor email draft prepared",
  booking_missing: "Booking details missing for email draft",
  cache_hit: "Answered from cached fund information",
  fast_path_answer: "Answered using a fast fund-information path",
  coverage_fast_path: "Answered from fund coverage summary",
  out_of_scope_fund: "Fund not in covered list — offered guidance",
  rescheduled: "Booking time updated",
  confirmation_declined: "Booking confirmation declined",
  pending_stale: "Stale pending booking cleared",
  reschedule_no_booking: "Reschedule asked but no active booking",
  reschedule_rejected_cancelled: "Cannot reschedule a cancelled booking",
  reschedule_not_for_waitlist: "Reschedule not available for waitlist",
  reschedule_needs_new_slot: "Reschedule needs a new time slot",
  reschedule_noop_same_slot: "Reschedule unchanged (same slot)",
  reschedule_slot_conflict: "Reschedule blocked by a slot conflict",
  awaiting_reschedule_confirm: "Waiting for you to confirm a new time",
  awaiting_cancel_confirm: "Waiting for cancel confirmation",
  awaiting_book_confirm: "Waiting for booking confirmation",
  slot_conflict: "That slot is already yours or held under your name — reschedule if you want to change it",
  slot_unavailable: "That time is booked by someone else — suggested other times or availability",
  prepare_needs_topic: "Asked for a topic before booking",
  prepare_checklist: "Shared pre-call checklist",
  no_booking: "No booking found for that request",
};

function outcomeLabel(outcome: string): string | null {
  if (!outcome) return null;
  if (OUTCOME_LABELS[outcome]) return OUTCOME_LABELS[outcome];
  if (/^hits=\d+$/.test(outcome)) return "Retrieved fund passages for the answer";
  if (/^retry_hits=\d+$/.test(outcome)) return "Retried retrieval and found fund passages";
  const intents = parseIntentList(outcome);
  if (intents?.length) return formatIntentList(intents);
  if (outcome.startsWith("intents=")) return "Classified your message for routing";
  return null;
}

export function friendlyAgentDisplayName(agent: string): string {
  const map: Record<string, string> = {
    orchestrator: "Finn (routing)",
    memory_agent: "Memory",
    review_intelligence_agent: "Review insights",
    scheduling_agent: "Scheduling",
    rag_agent: "Fund answers",
    email_drafting_agent: "Advisor email",
  };
  return map[agent] || agent.replace(/_/g, " ");
}

/**
 * One plain-language line for PMs (agent is shown separately on the card).
 */
export function traceWhatHappenedLine(t: { agent: string; outcome: string; tools: string[]; reasoning_brief: string }): string {
  const byOutcome = outcomeLabel(t.outcome);
  if (byOutcome) return byOutcome;

  for (const tool of t.tools || []) {
    const tl = toolLabel(tool);
    if (tl) return tl;
  }

  const rb = (t.reasoning_brief || "").trim();
  if (rb.length > 0 && rb.length < 100 && !rb.includes("db.")) {
    return rb;
  }

  if (t.agent === "memory_agent") return "Loaded your session context";
  if (t.agent === "review_intelligence_agent") return "Loaded trend context";
  if (t.agent === "scheduling_agent") return "Handled your booking request";
  if (t.agent === "rag_agent") return "Looked up fund information";
  if (t.agent === "orchestrator") return "Coordinated the reply";
  if (t.agent === "email_drafting_agent") return "Prepared advisor email context";
  return "Completed a step";
}

export function toolLabelForDisplay(tool: string): string {
  return toolLabel(tool) || tool;
}
