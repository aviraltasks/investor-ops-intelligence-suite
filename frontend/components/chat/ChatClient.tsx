"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

type Role = "assistant" | "user";

type ChatMessage = {
  role: Role;
  text: string;
};

type AgentTrace = {
  agent: string;
  reasoning_brief: string;
  tools: string[];
  replanned: boolean;
  outcome: string;
};

type ChatPayload = {
  booking_code?: string;
  date?: string;
  time_ist?: string;
  topic?: string;
  advisor?: string;
  [k: string]: unknown;
};

type ChatApiResponse = {
  response: string;
  traces: AgentTrace[];
  payload: ChatPayload;
};

type SpeechRecognitionResultLike = { transcript?: string };
type SpeechRecognitionEventLike = {
  results?: ArrayLike<ArrayLike<SpeechRecognitionResultLike>>;
};
type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onstart: (() => void) | null;
  onresult: ((evt: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;
type VoicePick = {
  name: string;
  lang: string;
};
type TtsState = "idle" | "queued" | "started" | "ended" | "error";

const COVERED_FUNDS = [
  "SBI Nifty Index Fund",
  "Parag Parikh Flexi Cap",
  "HDFC Mid Cap Opportunities",
  "SBI Small Cap",
  "Mirae Asset ELSS Tax Saver",
  "Nippon India Large Cap",
  "Kotak Small Cap",
  "HDFC Flexi Cap",
  "Motilal Oswal Midcap",
  "UTI Nifty 50 Index",
  "Axis Midcap",
  "ICICI Prudential ELSS",
  "SBI Magnum Children's Benefit",
  "Quant Small Cap",
  "Canara Robeco Large Cap",
] as const;

const EXAMPLE_QUESTIONS = [
  "What is the exit load for Mirae ELSS and why is it charged?",
  "Compare expense ratios of small cap funds in your database",
  "What is NAV and how is it calculated?",
  "Book an appointment for KYC tomorrow at 10 am",
  "Show available advisor slots this week",
] as const;

const QUICK_TOPICS = [
  "KYC & Onboarding",
  "SIP & Mandates",
  "Statements & Tax Documents",
  "Withdrawals & Timelines",
  "Account Changes & Nominee Updates",
] as const;

const AGENT_COLORS: Record<string, string> = {
  orchestrator: "bg-indigo-100 text-indigo-800",
  rag_agent: "bg-teal-100 text-teal-800",
  scheduling_agent: "bg-blue-100 text-blue-800",
  review_intelligence_agent: "bg-purple-100 text-purple-800",
  email_drafting_agent: "bg-amber-100 text-amber-800",
  memory_agent: "bg-emerald-100 text-emerald-800",
};

function voiceTtsText(data: ChatApiResponse): string {
  const raw = data.response.split("\n").slice(0, 2).join(" ").slice(0, 260);
  const codeRaw = data.payload?.booking_code;
  const code = typeof codeRaw === "string" ? codeRaw.trim().toUpperCase() : "";
  if (/^GRW-W-[A-Z0-9]{4}$/.test(code) || /^GRW-[A-Z0-9]{4}$/.test(code)) {
    const spelled = code.split("").join(" ");
    return `Your booking code is ${spelled}. ${raw}`.slice(0, 420);
  }
  return raw;
}

function inferProcessingText(input: string): string {
  const t = input.toLowerCase();
  if (
    t.includes("book") ||
    t.includes("appointment") ||
    t.includes("availability") ||
    t.includes("cancel") ||
    t.includes("reschedule") ||
    t.includes("waitlist") ||
    t.includes("prepare")
  ) {
    return "Checking available slots...";
  }
  if (t.includes("theme") || t.includes("pulse") || t.includes("review")) {
    return "Analyzing current trends...";
  }
  return "Searching knowledge base...";
}

export function ChatClient({ initialName }: { initialName: string }) {
  const welcomeText = `Hi ${initialName}! I provide factual mutual fund information and help schedule advisor appointments. I do not provide investment advice or handle personal account details in this chat.`;
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      text: welcomeText,
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [showDisclaimer, setShowDisclaimer] = useState(true);
  const [showAgentPanel, setShowAgentPanel] = useState(true);
  const [traces, setTraces] = useState<AgentTrace[]>([]);
  const [lastPayload, setLastPayload] = useState<ChatPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sttSupported, setSttSupported] = useState(false);
  const [ttsSupported, setTtsSupported] = useState(false);
  const [voiceBanner, setVoiceBanner] = useState<string | null>(null);
  const [micState, setMicState] = useState<"idle" | "listening" | "processing" | "speaking">("idle");
  const [ttsState, setTtsState] = useState<TtsState>("idle");
  const [ttsErrorDetail, setTtsErrorDetail] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const synthesisUtteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const preferredVoiceRef = useRef<VoicePick | null>(null);
  const voiceTurnPendingRef = useRef(false);
  const hasUserInteractedRef = useRef(false);
  const welcomeSpeechPendingRef = useRef(false);
  const lastAssistantTextRef = useRef(welcomeText);
  const ttsRetryRef = useRef(false);

  const backendBaseUrl = useMemo(
    () => process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000",
    [],
  );

  const today = useMemo(
    () =>
      new Intl.DateTimeFormat("en-IN", {
        weekday: "long",
        day: "2-digit",
        month: "short",
        year: "numeric",
      }).format(new Date()),
    [],
  );

  useEffect(() => {
    const SpeechRecognitionCtor = (() => {
      if (typeof window === "undefined") return undefined;
      const w = window as Window & {
        SpeechRecognition?: SpeechRecognitionCtor;
        webkitSpeechRecognition?: SpeechRecognitionCtor;
      };
      return w.SpeechRecognition || w.webkitSpeechRecognition;
    })();
    const hasSynthesis =
      typeof window !== "undefined" && "speechSynthesis" in window;

    setSttSupported(Boolean(SpeechRecognitionCtor));
    setTtsSupported(Boolean(hasSynthesis));
    if (!hasSynthesis) {
      setVoiceBanner("Text-to-speech is not supported in this browser.");
    } else if (!SpeechRecognitionCtor) {
      setVoiceBanner("Voice input is unavailable in this browser. Text input still works.");
    }

    if (SpeechRecognitionCtor) {
      const recognition = new SpeechRecognitionCtor();
      recognition.lang = "en-IN";
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.maxAlternatives = 1;

      recognition.onstart = () => setMicState("listening");
      recognition.onresult = (evt: SpeechRecognitionEventLike) => {
        const transcript = evt.results?.[0]?.[0]?.transcript?.trim();
        if (!transcript) {
          setMicState("idle");
          return;
        }
        voiceTurnPendingRef.current = true;
        setMicState("processing");
        void sendMessage(transcript);
      };
      recognition.onerror = () => {
        setMicState("idle");
        setVoiceBanner("Voice input failed. Switched to text mode.");
      };
      recognition.onend = () => {
        setMicState((cur) => (cur === "listening" ? "idle" : cur));
      };
      recognitionRef.current = recognition;
    }

    const choosePreferredVoice = () => {
      if (typeof window === "undefined" || !window.speechSynthesis) return;
      const voices = window.speechSynthesis.getVoices();
      if (!voices.length) return;
      const normalized = voices.map((v) => ({
        voice: v,
        lang: (v.lang || "").toLowerCase(),
        name: (v.name || "").toLowerCase(),
      }));
      const ranked =
        normalized.find((v) => v.lang.startsWith("en-in") && /neural|natural|wavenet|samantha|zira|aria|google|microsoft/.test(v.name)) ||
        normalized.find((v) => v.lang.startsWith("en-in")) ||
        normalized.find((v) => v.lang.startsWith("en") && /neural|natural|wavenet|samantha|zira|aria|google|microsoft/.test(v.name)) ||
        normalized.find((v) => v.lang.startsWith("en")) ||
        normalized[0];
      preferredVoiceRef.current = ranked
        ? { name: ranked.voice.name, lang: ranked.voice.lang }
        : null;
    };
    choosePreferredVoice();
    window.speechSynthesis.onvoiceschanged = choosePreferredVoice;

    const stopSpeech = () => {
      window.speechSynthesis.cancel();
      synthesisUtteranceRef.current = null;
      setMicState((cur) => (cur === "speaking" ? "idle" : cur));
      setTtsState("idle");
    };
    const unlockTts = () => {
      if (typeof window === "undefined" || !window.speechSynthesis) return;
      try {
        window.speechSynthesis.resume();
      } catch {
        // noop
      }
    };
    const markInteractedAndSpeakWelcome = () => {
      if (hasUserInteractedRef.current) return;
      hasUserInteractedRef.current = true;
      unlockTts();
    };
    window.addEventListener("pointerdown", markInteractedAndSpeakWelcome, {
      once: true,
    });
    window.addEventListener("keydown", markInteractedAndSpeakWelcome, {
      once: true,
    });
    window.addEventListener("beforeunload", stopSpeech);
    return () => {
      try {
        recognitionRef.current?.stop();
      } catch {
        // noop
      }
      recognitionRef.current = null;
      stopSpeech();
      window.removeEventListener("beforeunload", stopSpeech);
      window.removeEventListener("pointerdown", markInteractedAndSpeakWelcome);
      window.removeEventListener("keydown", markInteractedAndSpeakWelcome);
      if (window.speechSynthesis) {
        window.speechSynthesis.onvoiceschanged = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function speak(text: string) {
    if (!ttsSupported || typeof window === "undefined") return;
    ttsRetryRef.current = false;
    setTtsErrorDetail(null);
    setTtsState("queued");
    try {
      window.speechSynthesis.resume();
    } catch {
      // noop
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    const preferred = preferredVoiceRef.current;
    utterance.lang = preferred?.lang || "en-IN";
    const selectedVoice =
      window.speechSynthesis
        .getVoices()
        .find((v) => preferred && v.name === preferred.name && v.lang === preferred.lang) || null;
    if (selectedVoice) utterance.voice = selectedVoice;
    utterance.rate = 1;
    utterance.pitch = 1;
    utterance.volume = 1;
    utterance.onstart = () => {
      setMicState("speaking");
      setTtsState("started");
      setVoiceBanner(null);
    };
    utterance.onend = () => {
      setMicState("idle");
      setTtsState("ended");
    };
    utterance.onerror = (evt) => {
      setMicState("idle");
      const detail = typeof evt.error === "string" ? evt.error : "unknown";
      // Browsers often emit interrupted/canceled when replacing active speech.
      // Treat these as benign so users can tap Speak repeatedly without false errors.
      if (detail === "interrupted" || detail === "canceled") {
        setTtsState("ended");
        setTtsErrorDetail(null);
        return;
      }
      if (!ttsRetryRef.current) {
        ttsRetryRef.current = true;
        const fallback = new SpeechSynthesisUtterance(text);
        fallback.lang = "en-US";
        fallback.rate = 1;
        fallback.pitch = 1;
        fallback.volume = 1;
        fallback.onstart = () => {
          setMicState("speaking");
          setTtsState("started");
          setVoiceBanner(null);
        };
        fallback.onend = () => {
          setMicState("idle");
          setTtsState("ended");
        };
        fallback.onerror = () => {
          setMicState("idle");
          setTtsState("error");
          setTtsErrorDetail(detail);
          setVoiceBanner("Text-to-speech failed. You can continue in text mode.");
        };
        window.setTimeout(() => {
          try {
            window.speechSynthesis.resume();
          } catch {
            // noop
          }
          window.speechSynthesis.speak(fallback);
        }, 60);
        return;
      }
      setTtsState("error");
      setTtsErrorDetail(detail);
      setVoiceBanner("Text-to-speech failed. You can continue in text mode.");
    };
    synthesisUtteranceRef.current = utterance;
    // Some browsers drop immediate speak calls; tiny delay makes TTS more reliable.
    window.setTimeout(() => {
      window.speechSynthesis.speak(utterance);
    }, 40);
  }

  async function sendMessage(text: string) {
    const msg = text.trim();
    if (!msg || isLoading) return;
    hasUserInteractedRef.current = true;
    if (welcomeSpeechPendingRef.current) {
      welcomeSpeechPendingRef.current = false;
    }
    const shouldSpeakForThisTurn = voiceTurnPendingRef.current;
    setError(null);
    setMessages((prev) => [...prev, { role: "user", text: msg }]);
    setInput("");
    setIsLoading(true);
    try {
      const res = await fetch(`${backendBaseUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: msg,
          session_id: `web-${initialName.toLowerCase().replace(/\s+/g, "-")}`,
          user_name: initialName,
        }),
      });
      if (!res.ok) throw new Error(`Chat API failed (${res.status})`);
      const data = (await res.json()) as ChatApiResponse;
      setMessages((prev) => [...prev, { role: "assistant", text: data.response }]);
      lastAssistantTextRef.current = data.response;
      setTraces(data.traces || []);
      setLastPayload(data.payload || null);
      // Auto-voice only for mic-originated turns; text turns use Speak button.
      if (shouldSpeakForThisTurn) {
        speak(voiceTtsText(data));
      }
    } catch (e) {
      const msgText =
        e instanceof Error ? e.message : "Could not reach backend API.";
      setError(msgText);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: "I’m having trouble reaching the backend right now. Please try again in a moment.",
        },
      ]);
      if (shouldSpeakForThisTurn) {
        speak("I am having trouble reaching the backend right now. Please try again.");
      }
    } finally {
      setIsLoading(false);
      voiceTurnPendingRef.current = false;
      setMicState((cur) => (cur === "processing" ? "idle" : cur));
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void sendMessage(input);
  }

  function onMicClick() {
    if (!sttSupported) {
      setVoiceBanner(
        "Voice is unavailable in this browser. Please continue with text.",
      );
      return;
    }
    if (!recognitionRef.current) {
      setVoiceBanner("Voice recognizer is not initialized. Please use text.");
      return;
    }
    if (micState === "listening") {
      recognitionRef.current.stop();
      setMicState("idle");
      return;
    }
    try {
      setVoiceBanner(null);
      setMicState("listening");
      recognitionRef.current.start();
    } catch {
      setMicState("idle");
      setVoiceBanner("Could not start voice input. Please use text.");
    }
  }

  function onSpeakClick() {
    if (!ttsSupported) {
      setVoiceBanner("Text-to-speech is unavailable in this browser.");
      return;
    }
    hasUserInteractedRef.current = true;
    welcomeSpeechPendingRef.current = false;
    const text = (lastAssistantTextRef.current || "").trim();
    if (!text) return;
    speak(text.slice(0, 420));
  }

  const processingText = inferProcessingText(input || messages.at(-1)?.text || "");
  const bookingCode = typeof lastPayload?.booking_code === "string" ? lastPayload.booking_code : null;

  return (
    <section className="mt-6 grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)_320px]">
      <aside className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-900">Covered Schemes</h2>
        <ul className="mt-3 max-h-52 space-y-1 overflow-auto text-xs text-slate-600">
          {COVERED_FUNDS.map((fund) => (
            <li key={fund} className="flex items-start gap-2">
              <span className="mt-1 h-1.5 w-1.5 rounded-full bg-indigo-500" />
              <span>{fund}</span>
            </li>
          ))}
        </ul>

        <h3 className="mt-4 text-sm font-semibold text-slate-900">Example Questions</h3>
        <div className="mt-2 flex flex-col gap-2">
          {EXAMPLE_QUESTIONS.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => void sendMessage(q)}
              className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-left text-xs text-indigo-900 hover:bg-indigo-100"
            >
              {q}
            </button>
          ))}
        </div>
      </aside>

      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        {showDisclaimer && (
          <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
            <div className="flex items-start justify-between gap-4">
              <p>
                Disclaimer: Finn provides factual information from public sources and helps with advisor scheduling.
                Finn does not provide investment advice or handle personal account details in chat.
              </p>
              <button
                type="button"
                className="rounded bg-white px-2 py-1 text-[11px] font-medium text-amber-700 ring-1 ring-amber-300"
                onClick={() => setShowDisclaimer(false)}
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
          <span>Today: {today}</span>
          <span>Advisor hours: Mon–Fri, 9:00 AM–6:00 PM IST</span>
        </div>

        <div className="max-h-[420px] min-h-[420px] space-y-3 overflow-auto rounded-xl border border-slate-100 bg-slate-50 p-3">
          {messages.map((m, idx) => (
            <div
              key={`${m.role}-${idx}`}
              className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm shadow-sm ${
                  m.role === "user"
                    ? "bg-indigo-700 text-white"
                    : "border border-slate-200 bg-white text-slate-800"
                }`}
              >
                {m.role === "assistant" && (
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                    Finn
                  </p>
                )}
                <p className="whitespace-pre-wrap">{m.text}</p>
              </div>
            </div>
          ))}

          {isLoading && (
            <div className="flex justify-start">
              <div className="rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 shadow-sm">
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                  Finn
                </p>
                <p className="animate-pulse">Thinking...</p>
                <p className="text-xs text-slate-500">{processingText}</p>
              </div>
            </div>
          )}
        </div>

        {bookingCode && (
          <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-emerald-800">
              Booking Confirmation
            </p>
            <p className="mt-1 font-mono text-base font-bold text-emerald-900">{bookingCode}</p>
            <p className="mt-1 text-emerald-900">
              {String(lastPayload?.date || "—")} at {String(lastPayload?.time_ist || "—")}
            </p>
            <p className="text-emerald-900">
              {String(lastPayload?.topic || "—")} · {String(lastPayload?.advisor || "—")}
            </p>
          </div>
        )}

        {error && (
          <p className="mt-2 text-xs text-rose-700">
            Backend error: {error}
          </p>
        )}
        {voiceBanner && (
          <p className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800">
            {voiceBanner}
          </p>
        )}
        {ttsSupported && (
          <p className="mt-2 text-[11px] text-slate-500">
            Voice debug: {ttsState}
            {ttsErrorDetail ? ` (${ttsErrorDetail})` : ""}
          </p>
        )}

        <div className="mt-3 flex flex-wrap gap-2">
          {QUICK_TOPICS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => void sendMessage(`I want help with ${t}`)}
              className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-700 hover:bg-slate-100"
            >
              {t}
            </button>
          ))}
        </div>

        <form onSubmit={onSubmit} className="mt-3 flex items-center gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about funds, trends, or booking..."
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none ring-indigo-500 focus:border-indigo-500 focus:ring-2"
          />
          <button
            type="button"
            onClick={onMicClick}
            className={`rounded-lg border px-3 py-2 text-sm ${
              micState === "listening"
                ? "border-emerald-400 bg-emerald-50 text-emerald-800"
                : micState === "processing"
                  ? "border-indigo-300 bg-indigo-50 text-indigo-800"
                  : micState === "speaking"
                    ? "border-purple-300 bg-purple-50 text-purple-800"
                    : "border-slate-300 bg-white text-slate-700"
            }`}
            title="Voice input toggle"
          >
            {micState === "listening"
              ? "Listening"
              : micState === "processing"
                ? "Processing"
                : micState === "speaking"
                  ? "Speaking"
                  : "Mic"}
          </button>
          <button
            type="button"
            onClick={onSpeakClick}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700"
            title="Read latest reply aloud"
          >
            Speak
          </button>
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="rounded-lg bg-indigo-700 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-800 disabled:opacity-50"
          >
            Send
          </button>
        </form>
      </div>

      <aside className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">Agent Activity</h2>
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700"
            onClick={() => setShowAgentPanel((v) => !v)}
          >
            {showAgentPanel ? "Hide" : "Show"}
          </button>
        </div>

        {showAgentPanel ? (
          traces.length ? (
            <div className="space-y-2">
              {traces.map((t, idx) => (
                <div key={`${t.agent}-${idx}`} className="rounded-lg border border-slate-200 p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span
                      className={`rounded px-2 py-0.5 text-[11px] font-semibold ${
                        AGENT_COLORS[t.agent] || "bg-slate-100 text-slate-700"
                      }`}
                    >
                      {t.agent}
                    </span>
                    <span className="text-[11px] text-slate-500">
                      {t.replanned ? "Replanned" : "Single pass"}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-700">{t.reasoning_brief}</p>
                  {t.tools?.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {t.tools.map((tool) => (
                        <span
                          key={tool}
                          className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600"
                        >
                          {tool}
                        </span>
                      ))}
                    </div>
                  )}
                  <p className="mt-1 text-[11px] text-slate-500">Outcome: {t.outcome}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-500">
              Agent traces will appear here after your first message.
            </p>
          )
        ) : (
          <p className="text-xs text-slate-500">Panel collapsed.</p>
        )}
      </aside>
    </section>
  );
}
