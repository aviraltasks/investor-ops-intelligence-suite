# UAT_CHECKLIST.md — Final Polish Runbook

Use this sheet for one full pass after deploy. Mark each item Pass/Fail and add notes.

## Latest Production Notes (May 9, 2026)

- PII chat safety is hardened: Aadhaar/PAN/phone/email inputs are blocked with secure guidance before agent processing.
- Booking confirmation wording is deterministic (no LLM paraphrase): `Please confirm booking: ... Reply yes or no.`
- Cross-fund small-cap expense-ratio comparison remains a known data/retrieval gap on current corpus (backlog item).

## Environment

- App URL:
- Backend URL:
- Browser:
- Date/time:

## A) Voice + Chat UX

- [ ] Landing -> enter name -> Begin -> welcome voice plays
- [ ] After welcome speech, mic auto-listens
- [ ] Voice query -> user message appears -> chat auto-scrolls to latest turn
- [ ] Assistant reply is spoken automatically
- [ ] Mic resumes after assistant speech ends
- [ ] 3 consecutive voice turns complete without stuck states
- [ ] If mic permission denied, clear permission warning is shown

## B) FAQ / RAG quality

- [ ] "what is nav and how is it calculated" returns concept + asks fund name for exact value
- [ ] "what is the NAV for HDFC Flexi Cap" returns concrete value
- [ ] "what is the expense ratio" asks for fund name (no assumption)
- [ ] "compare expense ratio of SBI, Kotak, Quant small cap" returns concise comparison
- [ ] "what all mutual funds do you cover" returns deterministic clean list summary
- [ ] Answers are concise (roughly 1-2 sentences for simple prompts)

## C) Scheduling behavior

- [ ] "book tomorrow for kyc" asks one clarifying time question
- [ ] "book tomorrow at 10 am for kyc" -> asks compact yes/no confirmation
- [ ] yes -> booking code generated and shown
- [ ] cancel flow uses compact yes/no confirmation
- [ ] reschedule flow uses compact yes/no confirmation

## D) Safety checks

- [ ] Investment recommendation prompt is refused safely
- [ ] PII in chat is blocked with secure redirect guidance
- [ ] Prompt injection / override prompt is refused

## E) Admin / Activity visibility

- [ ] Agent Activity panel shows consistent trace flow (orchestrator -> specialist -> memory)
- [ ] No anomalous gibberish outcomes in trace entries
- [ ] Chat payload debug exists (`clarification_prompt_count`, `fallback_answer_count`, `trace_count`)

## Result summary

- Total scenarios:
- Passed:
- Failed:
- Key issues to fix next:
