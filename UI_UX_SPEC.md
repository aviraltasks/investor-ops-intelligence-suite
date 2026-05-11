# UI_UX_SPEC.md — Visual Design Specification

**Status:** Final for Cursor review
**Author:** PM (Aviral Rawat)

This document defines the visual identity, layout, component patterns, and page-by-page design for the Investor Ops & Intelligence Suite. Cursor owns all implementation choices (framework, CSS approach, libraries) — this spec defines what the user sees and experiences.

---

## 1. Design Direction

### 1.1 Philosophy

The previous project (M3 — INDMoney Voice Agent) used a dark navy/teal glassmorphism aesthetic. **This project must look visually distinct** so that recruiters and reviewers immediately see it as a separate, new product.

**Target aesthetic:** Clean, modern fintech dashboard. Think Linear, Notion, or Vercel's design language — light-mode-first, generous whitespace, sharp typography, subtle depth through shadows rather than glassmorphism. Professional yet approachable. The UI should feel like an internal ops tool built by a real product team, not a bootcamp demo.

### 1.2 Visual Identity

- **Mode:** Light-mode primary. Dark backgrounds only for accent sections (hero, sidebar nav if used).
- **Feel:** Spacious, structured, confident. Cards with subtle shadows. Clean lines.
- **No glassmorphism, no heavy gradients, no neon accents.**
- **The product should feel like a different product from M3** at first glance — different palette, different layout pattern, different typography.

---

## 2. Design System

### 2.1 Color Palette

**Primary:**
- **Deep Indigo** — primary brand color for buttons, active states, links. A rich, professional blue-purple.
- **White / Off-White** — page backgrounds, card backgrounds.

**Accents:**
- **Emerald/Green** — success states, positive indicators, "active" status pills.
- **Amber/Warm Orange** — warnings, pending states, attention indicators.
- **Red** — errors, cancelled states, destructive actions.
- **Soft Gray** — borders, dividers, muted text, inactive states.

**Neutral:**
- **Near-Black** — primary text.
- **Medium Gray** — secondary/muted text.
- **Light Gray** — backgrounds for sections, input fields, code blocks.

**Agent Activity Panel Colors:**
- Each agent should have a subtle color association so the panel is scannable:
  - Orchestrator: indigo
  - RAG Agent: teal
  - Scheduling Agent: blue
  - Review Intelligence Agent: purple
  - Email Agent: amber
  - Memory Agent: green

### 2.2 Typography

- **Headings:** A modern sans-serif with character — not Inter, not Arial, not Roboto. Something distinctive but readable (examples of the feel: Geist, Satoshi, General Sans, Cabinet Grotesk — Cursor picks what's available and fits).
- **Body text:** Clean sans-serif, optimized for readability at small sizes.
- **Monospace:** For booking codes, technical details in the agent panel, data values.
- **Sizes:** Clear hierarchy — page titles large and bold, section headers medium, body text comfortable reading size, captions/labels small.

### 2.3 Spacing & Layout

- **Generous whitespace.** Don't cram elements together. Sections breathe.
- **Card-based UI.** Major content blocks (chat, booking confirmation, pulse preview, analytics graphs) live in cards with subtle shadows and rounded corners.
- **Consistent padding/margins** across all pages.
- **Max content width** — content doesn't stretch to full screen on wide monitors. Centered container with comfortable reading width.

### 2.4 Interactive Elements

- **Buttons:** Solid fill for primary actions (deep indigo background, white text). Outlined/ghost for secondary actions. Rounded corners.
- **Input fields:** Clean borders, subtle focus states (border color change or shadow), clear placeholder text.
- **Status pills:** Small rounded badges with color-coded backgrounds — green for active/tentative, amber for pending/waitlisted, red for cancelled, gray for draft.
- **Hover states:** Subtle — slight shadow lift on cards, color darken on buttons. No jarring transitions.
- **Loading states:** Skeleton loaders for page loads. Animated dots or spinner for processing states. Never show a blank page.
- **Toast/notification:** For success messages (booking confirmed, email sent) — brief, auto-dismiss.

### 2.5 Animations & Transitions

- **Minimal and purposeful.** No animation for animation's sake.
- **Page transitions:** Smooth, fast.
- **Chat messages:** Messages appear with a subtle fade or slide-in.
- **Agent activity panel:** Steps appear sequentially as agents process — gives the feel of watching the system think.
- **Graphs:** Animate on first render (bars grow, lines draw).
- **Processing indicators:** Subtle pulsing or animated dots when Finn is thinking.

---

## 3. Page Specifications

### 3.1 Landing Page (/)

**Layout:** Centered single-column hero section.

**Elements:**
- **Header/Nav bar:** Product name ("Investor Ops & Intelligence Suite" or a shorter brand name) on the left. Navigation links on the right: "Chat", "Admin", "Subscribers".
- **Hero section:**
  - Headline: Clear, bold, communicates value (e.g., "Smart answers. Real insights. Advisor access." or similar — Cursor can refine the copy).
  - Subtext: One line explaining what the product does.
  - Subtle illustration or icon graphic (not a stock photo — could be a minimal line illustration or abstract shapes).
- **Two action cards (side by side on desktop, stacked on mobile):**
  - **Card 1 — New User:** "Start a conversation" — first name input field + "Begin" button. Brief helper text.
  - **Card 2 — Existing Booking:** "Have a booking code?" — booking code input (placeholder: GRW-XXXX) + "Submit" button. Brief helper text.
- **Footer:** (see §3.7)

**Mobile:** Cards stack vertically. Hero text scales down. Full-width inputs.

### 3.2 Chat Page (/chat)

**Layout:** Three-column on desktop (left sidebar + center chat + right panel). On mobile, center chat takes full width, sidebar and panel accessible via toggles/drawers.

**Left Sidebar:**
- **Covered Schemes section:** List of the 15 mutual fund names with category color dots. Shows the user what Finn knows about.
- **Example Questions section:** 4-5 clickable example questions that auto-send to Finn when clicked. Styled as teal/indigo cards or chips.
- **Collapsible on mobile** — hamburger or slide-out.

**Center Chat Area:**
- **Disclaimer banner** at top on first interaction (dismissible for returning users).
- **Today's date** and **working hours** displayed subtly.
- **Message bubbles:** Finn on the left (with a small Finn avatar/icon), user on the right. Clear visual distinction.
- **Booking confirmation card:** When a booking is confirmed, display a styled card inside the chat with: booking code (large, monospace, copyable), date, time, topic, advisor. Visually distinct from regular messages.
- **Processing indicators:** When Finn is thinking, show animated dots and a transparency line like "Searching knowledge base..." or "Checking available slots..." — this text should reflect which agent is actually working.
- **Text input bar** at bottom — always visible. Send button. Mic button (for voice toggle).
- **Mic button states:** Idle (mic icon, muted color) → Listening (animated, active color like red/green pulse) → Processing (spinner) → Speaking (speaker icon animation).

**Right Panel — Agent Activity Panel (shipped as "How Finn AI Agents Are Helping"):**
- **Collapsible** — toggle open/close. Default: closed on mobile, open on desktop.
- **Per user turn:** Turn title, caption **Steps run top → bottom**, quoted user message, then one card per agent step in pipeline order.
- **Each step card:** Muted **step number** badge (1…n); **friendly agent label** (color-coded); **one-line PM summary** (mapped from `outcome` / `tools` / short safe `reasoning_brief`); collapsed **Technical details** with raw `reasoning_brief`, tool strings, outcome, single-pass vs replanned, and raw agent id.
- **Entries appear sequentially** as agents process — gives a live "thinking" feel.
- **This panel is the single most important element for reviewer evaluation of agentic behavior.** Summaries must be grounded in real trace data; reviewers expand technical details for proof.

### 3.3 Secure Details Page (/secure/[bookingCode])

**Layout:** Centered single-column, card-based.

**Elements:**
- **Booking summary card:** Shows booking code, topic, date, time, advisor — read-only, styled consistently with the chat confirmation card.
- **Contact form card below:**
  - Phone input (with +91 prefix, Indian format validation)
  - Email input (format validation)
  - Notes textarea (optional)
  - Consent checkbox: "I consent to sharing my contact details with the assigned advisor."
  - Submit button
- **States:**
  - **Loading:** Skeleton while fetching booking details
  - **Not found:** "No booking found with this code. Please check and try again."
  - **Already submitted:** Show submitted details (masked) with "Your details have been shared."
  - **Success:** Confirmation message after submit
  - **Validation errors:** Inline field-level errors (not just a generic error banner)

### 3.4 Admin Dashboard (/admin)

**Layout:** Full-width dashboard layout. Sidebar navigation (vertical, left) + main content area.

**No password required.** Loads directly.

**Sidebar Nav Items:**
- Dashboard (analytics graphs)
- Pulse Management
- Bookings
- Agent Activity Log

**Dashboard Tab (default view):**
- **4 analytics graphs** in a 2x2 grid (or scrollable on mobile):
  - Graph 1: Review themes (bar chart or horizontal bars)
  - Graph 2: Appointments booked (line chart or bar chart over time)
  - Graph 3: Booking topics distribution (pie/donut or bar chart)
  - Graph 4: FAQ question topics (bar chart or treemap)
- Each graph has a date range selector (day/week/month toggle or date picker).
- Cards around each graph with a title, brief description.

**Pulse Management Tab:**
- **Reviews Data panel:** Review count, app ID, last fetch timestamp, last attempt. "Refresh Reviews" button. "Download CSV" link.
- **Generate Pulse section:** "Create Preview" button → on click, runs pipeline → shows pulse preview below.
- **Pulse preview:** Rendered card showing: pulse number, date, themes, quotes, analysis, actions, fee explainer section. Styled like the email briefing. Has "Append to Google Doc" and "Send Email" buttons below.
- **Subscriber selector:** Checkboxes for subscribed emails. "Select all" toggle. "Send pulse email" button.

**Bookings Tab:**
- **Table:** Columns — Code, Name, Topic, Date/Time, Advisor, Status, Email Status.
- **Status pills** color-coded (green: tentative, amber: waitlisted, red: cancelled, blue: rescheduled).
- **Sort/filter** by date, status, topic.
- **CSV export** button.
- **Expandable rows:** Click a booking → shows full details panel below:
  - Booking details
  - User concern (from chat context)
  - Advisor email field (editable)
  - Email preview button → shows formatted email in a modal or inline
  - Send email button → dispatches, status changes to "Sent"

**Agent Activity Log Tab (shipped):**
- Columns **per agent** (not a single flat table): scrollable cards, newest at top.
- Each card: **short timestamp**, **PM summary line** (same mapping module as chat), **Technical details** with user, session id, raw `reasoning_brief`, tools list, outcome, query summary, ISO timestamp.
- Proof of orchestration for reviewers; content **aligned** with chat agent panel.

### 3.5 Subscriber Page (/subscribers)

**Layout:** Simple centered single-column.

**Elements:**
- Brief explanation: "Subscribe to receive the weekly product pulse from the Groww ops team."
- Email input field (placeholder: "your.name@company.com")
- Subscribe button
- Success state: "You're subscribed. The admin will include you when sending the weekly pulse."
- Already subscribed state (if same email entered again)
- Back link to home

### 3.6 Navigation (All Pages)

**Header nav bar:**
- Product name/logo on the left (clickable → home)
- Navigation links on the right: Chat, Admin, Subscribers
- On mobile: hamburger menu or compact nav
- Active page indicated (underline, color change, or bold)

### 3.7 Footer (All Pages)

Every page must have a consistent footer:

- "Investor Ops & Intelligence Suite"
- "Created by Aviral Rawat"
- LinkedIn link: `https://www.linkedin.com/in/aviralrawat/`
- "Built with Cursor"
- "System Design (Architecture)" — expandable accordion or link that shows the architecture overview. Can link to a rendered version of the architecture diagram or show a summary inline.
- Last deployed timestamp (optional but nice to have)

---

## 4. Email Design

### 4.1 Advisor Email

**Format:** Image-based branded briefing card — not a plain HTML table.

**Visual style:**
- Clean card layout with the product's color scheme
- Header with product branding and "Advisor Briefing" title
- Three clearly separated sections with headers:
  1. **Booking Details** — code, topic, date/time, advisor, user first name
  2. **User Concern** — the user's stated problem/question from chat
  3. **Market Context** — trending themes, sentiment data, relevant insights
- Footer with product name and timestamp
- Responsive — readable on both desktop and mobile email clients

### 4.2 Pulse Email

**Format:** Branded briefing card — matches the advisor email styling.

**Content:** Full pulse report — themes, verbatim quotes, weekly analysis, actionable takeaways, fee explainer section (if applicable).

**Attachable:** Admin can optionally attach the verbatim reviews CSV.

---

## 5. Responsive Design

### 5.1 Breakpoints

- **Desktop:** Full layout with sidebars, multi-column grids.
- **Tablet:** Sidebars collapse to drawers/toggles, graphs stack to single column.
- **Mobile:** Single column layout, bottom-fixed chat input, slide-out panels, touch-friendly targets (minimum 44px).

### 5.2 Critical Mobile Considerations

- Chat page must be fully usable on mobile — this is likely where the demo video will be shown
- Booking confirmation card must be readable on small screens
- Agent activity panel must be accessible but not always visible on mobile
- Admin dashboard graphs must be scrollable and readable on mobile
- Touch targets: all buttons and interactive elements minimum 44px

---

## 6. Accessibility Basics

- Sufficient color contrast for all text (WCAG AA minimum)
- Focus states visible on all interactive elements (keyboard navigation)
- Alt text on any images or icons that convey meaning
- Error messages associated with form fields (not just color-based indication)
- Loading states announced (aria-live regions for screen readers, if feasible within timeline)

---

## 7. Key Distinction from Previous Project (M3)

| Aspect | M3 (INDMoney Voice Agent) | This Project |
|--------|--------------------------|-------------|
| Color scheme | Dark navy + teal + glassmorphism | Light mode + deep indigo + clean shadows |
| Layout | Single-purpose pages | Dashboard-style with sidebar nav (admin) |
| Chat layout | Two-column (sidebar + chat) | Three-column (sidebar + chat + agent panel) |
| Admin | Password-protected, basic table | Open access, rich dashboard with 4 graphs |
| Typography | Standard sans-serif | Distinctive heading font + clean body |
| Processing states | Simple "thinking..." | Agent-specific transparency ("Searching knowledge base...") |
| Overall feel | Dark, fintech consumer app | Light, internal ops dashboard/tool |

---

*Cursor should use this spec as the reference for all frontend decisions. The spec defines what the user sees — Cursor decides how to build it.*
