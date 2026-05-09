"use client";

import { useEffect, useMemo, useState } from "react";

type Booking = {
  booking_code: string;
  customer_name: string;
  topic: string;
  date: string;
  time_ist: string;
  advisor: string;
  status: string;
  email_status: string;
  concern_summary: string;
};

type ThemePoint = { theme: string; volume: number };
type SeriesPoint = { date?: string; topic?: string; count: number };
type ChartPoint = { label: string; value: number; pctDisplay: string };

/** Whole % when volume is healthy; one decimal when total counts are small (booking topics, sparse FAQs). */
function formatPctShare(value: number, total: number): string {
  if (total <= 0) return "0";
  const raw = (value / total) * 100;
  if (total < 25) {
    const rounded = Math.round(raw * 10) / 10;
    return Number.isInteger(rounded) ? String(Math.trunc(rounded)) : rounded.toFixed(1);
  }
  return String(Math.round(raw));
}
type AgentLog = {
  timestamp: string;
  user_name: string;
  agent: string;
  reasoning_brief: string;
  outcome: string;
  query_summary: string;
  tools: string[];
};

type PulsePreview = {
  pulse_id: number;
  generated_at: string;
  top_themes: { rank: number; label: string; volume: number; quote: string }[];
  analysis: string;
  actions: string[];
};

function formatTimeIstForDisplay(timeIst: string): string {
  const raw = (timeIst || "").replace(/\s*IST$/i, "").trim();
  const m = raw.match(/^(\d{1,2}):(\d{2})$/);
  if (!m) return timeIst;
  const hh = Number(m[1]);
  const mm = Number(m[2]);
  if (!Number.isFinite(hh) || !Number.isFinite(mm)) return timeIst;
  const suffix = hh < 12 ? "AM" : "PM";
  const h12 = hh % 12 || 12;
  return `${h12}:${String(mm).padStart(2, "0")} ${suffix} IST`;
}

const AGENT_COLORS: Record<string, string> = {
  orchestrator: "bg-indigo-100 text-indigo-800",
  rag_agent: "bg-teal-100 text-teal-800",
  scheduling_agent: "bg-blue-100 text-blue-800",
  review_intelligence_agent: "bg-purple-100 text-purple-800",
  email_drafting_agent: "bg-amber-100 text-amber-800",
  memory_agent: "bg-emerald-100 text-emerald-800",
};

export function AdminDashboardClient() {
  const backendBaseUrl = useMemo(
    () => process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000",
    [],
  );
  const googleSheetId = (process.env.NEXT_PUBLIC_GOOGLE_SHEET_ID || "").trim();
  const googleDocId = (process.env.NEXT_PUBLIC_GOOGLE_DOC_ID || "").trim();
  const googleCalendarId = (process.env.NEXT_PUBLIC_GOOGLE_CALENDAR_ID || "").trim();
  const googleCalendarEmbedUrl = (process.env.NEXT_PUBLIC_GOOGLE_CALENDAR_EMBED_URL || "").trim();
  const [tab, setTab] = useState<"dashboard" | "pulse" | "bookings" | "agentlog">("dashboard");
  const [range, setRange] = useState<"day" | "week" | "month">("week");

  const [analytics, setAnalytics] = useState<{
    review_themes: ThemePoint[];
    appointments_booked: SeriesPoint[];
    booking_topics: SeriesPoint[];
    faq_topics: SeriesPoint[];
  } | null>(null);
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [agentLogs, setAgentLogs] = useState<AgentLog[]>([]);
  const [pulsePreview, setPulsePreview] = useState<PulsePreview | null>(null);
  const [subscribers, setSubscribers] = useState<{ id: number; email: string }[]>([]);
  const [selectedSubs, setSelectedSubs] = useState<Record<string, boolean>>({});
  const [reviewMeta, setReviewMeta] = useState<{ source?: string; total?: number } | null>(null);
  const [emailDraft, setEmailDraft] = useState<string>("");
  const [status, setStatus] = useState<string>("");

  async function loadAnalytics() {
    const r = await fetch(`${backendBaseUrl}/api/admin/analytics?range=${range}`);
    if (!r.ok) return;
    const d = await r.json();
    setAnalytics(d);
  }

  async function loadBookings() {
    const r = await fetch(`${backendBaseUrl}/api/admin/bookings`);
    if (!r.ok) return;
    const d = await r.json();
    setBookings(d.items || []);
  }

  async function loadAgentLogs() {
    const r = await fetch(`${backendBaseUrl}/api/admin/agent-activity?limit=100`);
    if (!r.ok) return;
    const d = await r.json();
    setAgentLogs(d.items || []);
  }

  async function loadPulse() {
    const r = await fetch(`${backendBaseUrl}/api/pulse/latest`);
    if (!r.ok) return;
    const d = await r.json();
    if (d.pulse_id) setPulsePreview(d);
  }

  async function loadSubscribers() {
    const r = await fetch(`${backendBaseUrl}/api/admin/subscribers`);
    if (!r.ok) return;
    const d = await r.json();
    const items = d.items || [];
    setSubscribers(items);
    const init: Record<string, boolean> = {};
    for (const s of items) init[s.email] = true;
    setSelectedSubs(init);
  }

  useEffect(() => {
    void loadAnalytics();
    void loadBookings();
    void loadAgentLogs();
    void loadPulse();
    void loadSubscribers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range, backendBaseUrl]);

  async function onRefreshReviews() {
    setStatus("Refreshing reviews...");
    const r = await fetch(`${backendBaseUrl}/api/reviews/refresh?limit=250`, { method: "POST" });
    const d = await r.json();
    setReviewMeta({ source: d.source, total: d.total });
    setStatus(`Reviews refreshed (${d.total || 0}, source=${d.source || "unknown"}).`);
  }

  async function onGeneratePulse() {
    setStatus("Generating pulse...");
    const r = await fetch(`${backendBaseUrl}/api/pulse/generate?sample_size=500`, { method: "POST" });
    const d = (await r.json()) as { pulse_id?: number; detail?: string; message?: string };
    if (r.ok && d.pulse_id) {
      setPulsePreview(d as PulsePreview);
      void loadAnalytics();
      setStatus(`Pulse #${d.pulse_id} generated.`);
    } else {
      const err =
        typeof d.detail === "string"
          ? d.detail
          : typeof d.message === "string"
            ? d.message
            : `Pulse generation failed (HTTP ${r.status}).`;
      setStatus(err);
    }
  }

  async function onPreviewBookingEmail(code: string) {
    setStatus("Preparing email preview...");
    const r = await fetch(`${backendBaseUrl}/api/admin/bookings/${encodeURIComponent(code)}/email/preview`, { method: "POST" });
    const d = await r.json();
    setEmailDraft(d.draft || "");
    setStatus(`Preview ready for ${code}.`);
  }

  async function onSendBookingEmail(code: string) {
    const to = "advisor@example.com";
    const r = await fetch(`${backendBaseUrl}/api/admin/bookings/${encodeURIComponent(code)}/email/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to_email: to }),
    });
    const d = await r.json();
    if (d.ok) {
      setStatus(`Email marked sent for ${code} -> ${to}`);
      void loadBookings();
    } else {
      setStatus(`Email send failed for ${code}`);
    }
  }

  async function onSendPulseEmail() {
    const emails = Object.entries(selectedSubs)
      .filter(([, checked]) => checked)
      .map(([email]) => email);
    const r = await fetch(`${backendBaseUrl}/api/admin/pulse/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ emails }),
    });
    const d = await r.json();
    setStatus(d.ok ? `Pulse sent to ${d.sent_count} subscriber(s).` : `Pulse send failed: ${d.message}`);
  }

  async function onExportAnalyticsCsv() {
    setStatus("Preparing CSV…");
    const r = await fetch(`${backendBaseUrl}/api/admin/export/analytics.csv?range=${range}`);
    if (!r.ok) {
      setStatus("CSV export failed.");
      return;
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `analytics-${range}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    setStatus("Analytics CSV downloaded.");
  }

  async function onAppendPulseToDoc() {
    setStatus("Appending pulse to Google Doc…");
    const r = await fetch(`${backendBaseUrl}/api/admin/pulse/append-doc`, { method: "POST" });
    const d = (await r.json()) as { ok?: boolean; message?: string; detail?: string };
    if (d.ok) {
      setStatus("Pulse appended to Google Doc.");
    } else {
      setStatus(typeof d.message === "string" ? d.message : d.detail || "Doc append failed.");
    }
  }

  function buildChartPoints(raw: Array<{ label: string; value: number }>): { points: ChartPoint[]; total: number } {
    const cleaned = raw
      .filter((x) => x.label && Number.isFinite(x.value) && x.value > 0)
      .map((x) => ({ label: x.label.trim(), value: x.value }));
    const sorted = cleaned.sort((a, b) => (b.value !== a.value ? b.value - a.value : a.label.localeCompare(b.label)));
    const total = sorted.reduce((acc, x) => acc + x.value, 0);
    if (!sorted.length || total <= 0) return { points: [], total: 0 };

    const top = sorted.slice(0, 7);
    const remainder = sorted.slice(7);
    const otherValue = remainder.reduce((acc, x) => acc + x.value, 0);
    const merged = otherValue > 0 ? [...top, { label: "Other", value: otherValue }] : top;
    return {
      points: merged.map((x) => ({
        label: x.label,
        value: x.value,
        pctDisplay: formatPctShare(x.value, total),
      })),
      total,
    };
  }

  function card(title: string, points: ChartPoint[], total: number) {
    const max = Math.max(1, ...points.map((p) => p.value));
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
          <span className="text-[11px] text-slate-500">Total: {total}</span>
        </div>
        <div className="mt-3 space-y-2">
          {points.length ? (
            points.map((p, idx) => (
              <div key={`${p.label}-${idx}`} className="text-xs">
                <div className="mb-1 flex justify-between text-slate-600">
                  <span className="truncate">{p.label}</span>
                  <span>
                    {p.value} ({p.pctDisplay}%)
                  </span>
                </div>
                <div className="h-2 rounded bg-slate-100">
                  <div
                    className="h-2 rounded bg-indigo-500"
                    style={{ width: `${(p.value / max) * 100}%` }}
                  />
                </div>
              </div>
            ))
          ) : (
            <p className="text-xs text-slate-500">No data yet.</p>
          )}
        </div>
      </div>
    );
  }

  const reviewThemeChart = useMemo(
    () => buildChartPoints((analytics?.review_themes || []).map((x) => ({ label: x.theme, value: x.volume }))),
    [analytics],
  );
  const appointmentsChart = useMemo(
    () => buildChartPoints((analytics?.appointments_booked || []).map((x) => ({ label: x.date || "-", value: x.count }))),
    [analytics],
  );
  const bookingTopicsChart = useMemo(
    () => buildChartPoints((analytics?.booking_topics || []).map((x) => ({ label: x.topic || "-", value: x.count }))),
    [analytics],
  );
  const faqTopicsChart = useMemo(
    () => buildChartPoints((analytics?.faq_topics || []).map((x) => ({ label: x.topic || "-", value: x.count }))),
    [analytics],
  );

  const topTheme = reviewThemeChart.points[0];
  const topBookingTopic = bookingTopicsChart.points[0];
  const topFaqTopic = faqTopicsChart.points[0];
  const agentLogGroups = useMemo(() => {
    const grouped: Record<string, AgentLog[]> = {};
    for (const row of agentLogs) {
      const key = row.agent || "unknown";
      if (!grouped[key]) grouped[key] = [];
      grouped[key].push(row);
    }
    return Object.entries(grouped).sort((a, b) => b[1].length - a[1].length);
  }, [agentLogs]);

  const verificationLinks = [
    {
      label: "Google Sheet (booking log)",
      url: googleSheetId ? `https://docs.google.com/spreadsheets/d/${encodeURIComponent(googleSheetId)}/view?usp=sharing` : "",
      configured: Boolean(googleSheetId),
    },
    {
      label: "Google Doc (weekly pulse archive)",
      url: googleDocId ? `https://docs.google.com/document/d/${encodeURIComponent(googleDocId)}/view?usp=sharing` : "",
      configured: Boolean(googleDocId),
    },
    {
      label: "Google Calendar",
      url:
        googleCalendarEmbedUrl ||
        (googleCalendarId
          ? `https://calendar.google.com/calendar/u/0/embed?src=${encodeURIComponent(googleCalendarId)}`
          : ""),
      configured: Boolean(googleCalendarEmbedUrl || googleCalendarId),
    },
  ];

  return (
    <div className="mt-6 grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
      <aside className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        <div className="space-y-2">
          {[
            ["dashboard", "Dashboard"],
            ["pulse", "Pulse Management"],
            ["bookings", "Bookings"],
            ["agentlog", "Agent Activity Log"],
          ].map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id as typeof tab)}
              className={`w-full rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                tab === id
                  ? "bg-indigo-600 font-semibold text-white shadow-md shadow-indigo-600/25"
                  : "text-slate-700 hover:bg-slate-100"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </aside>

      <section className="space-y-4">
        {status && (
          <div className="rounded-md border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm text-indigo-900">
            {status}
          </div>
        )}

        {tab === "dashboard" && (
          <div className="space-y-4">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h3 className="text-sm font-semibold text-slate-900">Integration Verification — Reviewer Links</h3>
              <p className="mt-1 text-xs text-slate-500">
                Read-only links for reviewers to verify live Google integrations.
              </p>
              <div className="mt-3 space-y-2">
                {verificationLinks.map((item) => (
                  <div key={item.label} className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-100 p-2">
                    <span className="text-xs text-slate-700">{item.label}</span>
                    {item.configured ? (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded bg-indigo-50 px-2 py-1 text-xs text-indigo-800 hover:bg-indigo-100"
                      >
                        Open
                      </a>
                    ) : (
                      <span className="rounded bg-amber-100 px-2 py-1 text-xs text-amber-800">Not configured</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void onExportAnalyticsCsv()}
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800"
              >
                Export analytics CSV
              </button>
              <p className="self-center text-xs text-slate-500">
                CSV reflects the selected range ({range}) and current database aggregates.
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-3">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-indigo-700">Top Theme</p>
                <p className="mt-1 text-sm text-indigo-900">
                  {topTheme ? `${topTheme.label} (${topTheme.value}, ${topTheme.pctDisplay}%)` : "No data"}
                </p>
              </div>
              <div className="rounded-xl border border-teal-100 bg-teal-50 p-3">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-teal-700">Top Booking Topic</p>
                <p className="mt-1 text-sm text-teal-900">
                  {topBookingTopic
                    ? `${topBookingTopic.label} (${topBookingTopic.value}, ${topBookingTopic.pctDisplay}%)`
                    : "No data"}
                </p>
              </div>
              <div className="rounded-xl border border-violet-100 bg-violet-50 p-3">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-violet-700">Top FAQ Topic</p>
                <p className="mt-1 text-sm text-violet-900">
                  {topFaqTopic ? `${topFaqTopic.label} (${topFaqTopic.value}, ${topFaqTopic.pctDisplay}%)` : "No data"}
                </p>
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <p className="text-xs font-semibold text-slate-800">Date range</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {(["day", "week", "month"] as const).map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => setRange(r)}
                    className={`rounded px-2 py-1 text-xs capitalize ${range === r ? "bg-indigo-600 text-white" : "bg-white text-slate-700 ring-1 ring-slate-200"}`}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
            {card(
              "Play Store Review Themes · latest pulse in range",
              reviewThemeChart.points,
              reviewThemeChart.total,
            )}
            {card("Appointments Booked", appointmentsChart.points, appointmentsChart.total)}
            {card("Chat Booking Topics", bookingTopicsChart.points, bookingTopicsChart.total)}
            {card("FAQ Question Topics", faqTopicsChart.points, faqTopicsChart.total)}
            </div>
          </div>
        )}

        {tab === "pulse" && (
          <div className="space-y-4">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={onRefreshReviews}
                  className="rounded-lg bg-slate-900 px-3 py-2 text-sm text-white"
                >
                  Refresh Reviews
                </button>
                <button
                  type="button"
                  onClick={onGeneratePulse}
                  className="rounded-lg bg-indigo-700 px-3 py-2 text-sm text-white"
                >
                  Generate Pulse
                </button>
                <button
                  type="button"
                  onClick={onSendPulseEmail}
                  className="rounded-lg border border-indigo-300 bg-white px-3 py-2 text-sm text-indigo-800"
                >
                  Send Pulse Email
                </button>
                <button
                  type="button"
                  onClick={() => void onAppendPulseToDoc()}
                  className="rounded-lg border border-emerald-400 bg-emerald-50 px-3 py-2 text-sm text-emerald-900"
                >
                  Append pulse to Google Doc
                </button>
              </div>
              <p className="mt-2 text-xs text-slate-500">
                Reviews source: {reviewMeta?.source || "unknown"} · Count: {reviewMeta?.total ?? 0}
              </p>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h3 className="text-sm font-semibold text-slate-900">Subscribers</h3>
              <div className="mt-2 grid gap-1 sm:grid-cols-2">
                {subscribers.length ? (
                  subscribers.map((s) => (
                    <label key={s.id} className="flex items-center gap-2 text-xs text-slate-700">
                      <input
                        type="checkbox"
                        checked={!!selectedSubs[s.email]}
                        onChange={(e) =>
                          setSelectedSubs((prev) => ({ ...prev, [s.email]: e.target.checked }))
                        }
                      />
                      {s.email}
                    </label>
                  ))
                ) : (
                  <p className="text-xs text-slate-500">No subscribers yet.</p>
                )}
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h3 className="text-sm font-semibold text-slate-900">Pulse Preview</h3>
              {pulsePreview ? (
                <div className="mt-2 space-y-2 text-sm">
                  <p className="text-xs text-slate-500">
                    Pulse #{pulsePreview.pulse_id} · {pulsePreview.generated_at}
                  </p>
                  <ul className="space-y-1 text-slate-700">
                    {pulsePreview.top_themes?.map((t) => (
                      <li key={t.rank}>
                        <strong>{t.rank}. {t.label}</strong> ({t.volume}) — &quot;{t.quote}&quot;
                      </li>
                    ))}
                  </ul>
                  <p className="text-slate-700">{pulsePreview.analysis}</p>
                  <ul className="list-disc pl-5 text-slate-700">
                    {pulsePreview.actions?.map((a) => <li key={a}>{a}</li>)}
                  </ul>
                </div>
              ) : (
                <p className="mt-2 text-xs text-slate-500">No pulse generated yet.</p>
              )}
            </div>
          </div>
        )}

        {tab === "bookings" && (
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h3 className="text-sm font-semibold text-slate-900">Bookings</h3>
            <div className="mt-3 overflow-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-slate-500">
                  <tr>
                    <th className="py-1">Code</th>
                    <th className="py-1">Name</th>
                    <th className="py-1">Topic</th>
                    <th className="py-1">Date/Time</th>
                    <th className="py-1">Advisor</th>
                    <th className="py-1">Status</th>
                    <th className="py-1">Email</th>
                    <th className="py-1">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {bookings.map((b) => (
                    <tr key={b.booking_code} className="border-t border-slate-100">
                      <td className="py-1 font-mono">{b.booking_code}</td>
                      <td className="py-1">{b.customer_name}</td>
                      <td className="py-1">{b.topic}</td>
                      <td className="py-1">{b.date} {formatTimeIstForDisplay(b.time_ist)}</td>
                      <td className="py-1">{b.advisor}</td>
                      <td className="py-1">
                        <span className="rounded-full bg-slate-100 px-2 py-0.5">{b.status}</span>
                      </td>
                      <td className="py-1">{b.email_status}</td>
                      <td className="py-1">
                        <div className="flex gap-1">
                          <button
                            type="button"
                            onClick={() => void onPreviewBookingEmail(b.booking_code)}
                            className="rounded border border-slate-300 px-2 py-0.5"
                          >
                            Preview
                          </button>
                          <button
                            type="button"
                            onClick={() => void onSendBookingEmail(b.booking_code)}
                            className="rounded border border-indigo-300 px-2 py-0.5 text-indigo-800"
                          >
                            Send
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {emailDraft && (
              <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs whitespace-pre-wrap">
                {emailDraft}
              </div>
            )}
          </div>
        )}

        {tab === "agentlog" && (
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h3 className="text-sm font-semibold text-slate-900">Agent Activity Log</h3>
            <div className="mt-3">
              {agentLogGroups.length ? (
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {agentLogGroups.map(([agent, rows]) => (
                    <section key={agent} className="rounded-lg border border-slate-200 bg-slate-50/50 p-2">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <span
                          className={`rounded px-2 py-0.5 text-[11px] font-semibold ${AGENT_COLORS[agent] || "bg-slate-100 text-slate-700"}`}
                        >
                          {agent}
                        </span>
                        <span className="text-[11px] text-slate-500">{rows.length}</span>
                      </div>
                      <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
                        {rows.map((a, idx) => (
                          <div key={`${agent}-${a.timestamp}-${idx}`} className="rounded-lg border border-slate-200 bg-white p-2">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-[11px] text-slate-500">{a.timestamp}</span>
                            </div>
                            <p className="mt-1 text-xs text-slate-700">{a.reasoning_brief}</p>
                            <p className="mt-1 text-[11px] text-slate-500">User: {a.user_name} · Outcome: {a.outcome}</p>
                            <p className="mt-1 text-[11px] text-slate-500">Query: {a.query_summary}</p>
                          </div>
                        ))}
                      </div>
                    </section>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-slate-500">No activity logs yet.</p>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
