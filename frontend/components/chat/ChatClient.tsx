"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { nextVoiceModeState } from "./voiceModeStateMachine";
import type { VoiceModeState } from "./voiceModeStateMachine";

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
type SpeechRecognitionErrorEventLike = {
  error?: string;
};
type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onstart: (() => void) | null;
  onresult: ((evt: SpeechRecognitionEventLike) => void) | null;
  onerror: ((evt: SpeechRecognitionErrorEventLike) => void) | null;
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
  "What is the exit load of SBI Nifty Index Fund Direct Growth?",
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

type TraceTurnBlock = {
  id: string;
  userQuery: string;
  traces: AgentTrace[];
};

function voiceTtsText(data: ChatApiResponse): string {
  const cleaned = data.response
    .split("\n")
    .filter((line) => {
      const l = line.trim().toLowerCase();
      return !l.startsWith("sources:") && !l.startsWith("- http") && !l.startsWith("http");
    })
    .join(" ");
  const raw = cleaned
    .replace(/https?:\/\/\S+/gi, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 220);
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

function voiceModeHelperText(state: VoiceModeState, processingSlow: boolean): string {
  if (state === "starting") return "Setting up voice session...";
  if (state === "speaking_welcome") return "Finn is speaking...";
  if (state === "listening") return "Listening...";
  if (state === "processing") return processingSlow ? "Still thinking, hang on..." : "Got it - thinking...";
  if (state === "speaking_reply") return "Finn is responding...";
  if (state === "error_fallback") return "Voice unavailable, continuing in text";
  return "";
}

function isVoiceActive(state: VoiceModeState): boolean {
  return state !== "off" && state !== "error_fallback";
}

function isVoiceSpeakingState(state: VoiceModeState): boolean {
  return state === "speaking_welcome" || state === "speaking_reply";
}

function isTtsInFlight(ttsState: TtsState): boolean {
  const queuedOrStarted = ttsState === "queued" || ttsState === "started";
  if (typeof window === "undefined" || !("speechSynthesis" in window)) {
    return queuedOrStarted;
  }
  return queuedOrStarted || window.speechSynthesis.speaking || window.speechSynthesis.pending;
}

function normalizeForEcho(text: string): string {
  return (text || "")
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function isLikelyTtsEcho(transcript: string, assistantTexts: string[]): boolean {
  const t = normalizeForEcho(transcript);
  if (!t || t.length < 12) return false;
  for (const src of assistantTexts) {
    const s = normalizeForEcho(src);
    if (!s) continue;
    if (s.includes(t) || t.includes(s.slice(0, Math.min(80, s.length)))) return true;
  }
  return false;
}

function pickPreferredVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  if (!voices.length) return null;
  const normalized = voices.map((v) => ({
    voice: v,
    lang: (v.lang || "").toLowerCase(),
    name: (v.name || "").toLowerCase(),
  }));
  const femaleHint = /(female|samantha|zira|aria|natasha|heera|veena|alloy|priya|aditi|swara|saanvi)/;
  const premiumHint = /(neural|natural|wavenet|google|microsoft|enhanced|premium)/;
  const indiaFemaleHint = /(heera|priya|aditi|swara|veena|saanvi|india|en-in|english \(india\))/;
  return (
    normalized.find((v) => v.lang.startsWith("en-in") && indiaFemaleHint.test(v.name) && premiumHint.test(v.name))?.voice ||
    normalized.find((v) => v.lang.startsWith("en-in") && indiaFemaleHint.test(v.name))?.voice ||
    normalized.find((v) => v.lang.startsWith("en-in") && femaleHint.test(v.name) && premiumHint.test(v.name))?.voice ||
    normalized.find((v) => v.lang.startsWith("en-in") && femaleHint.test(v.name))?.voice ||
    normalized.find((v) => v.lang.startsWith("en") && femaleHint.test(v.name) && premiumHint.test(v.name))?.voice ||
    normalized.find((v) => v.lang.startsWith("en") && femaleHint.test(v.name))?.voice ||
    normalized.find((v) => v.lang.startsWith("en-in") && premiumHint.test(v.name))?.voice ||
    normalized.find((v) => v.lang.startsWith("en"))?.voice ||
    normalized[0].voice
  );
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
  const [traceTurnHistory, setTraceTurnHistory] = useState<TraceTurnBlock[]>([]);
  const [pendingTraceQuery, setPendingTraceQuery] = useState<string | null>(null);
  const [lastPayload, setLastPayload] = useState<ChatPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sttSupported, setSttSupported] = useState(false);
  const [ttsSupported, setTtsSupported] = useState(false);
  const [voiceBanner, setVoiceBanner] = useState<string | null>(null);
  const [voiceModeState, setVoiceModeState] = useState<VoiceModeState>("off");
  const [showVoiceHint, setShowVoiceHint] = useState(false);
  const [voiceProcessingSlow, setVoiceProcessingSlow] = useState(false);
  const [micState, setMicState] = useState<"idle" | "listening" | "processing" | "speaking">("idle");
  const [ttsState, setTtsState] = useState<TtsState>("idle");
  const [ttsErrorDetail, setTtsErrorDetail] = useState<string | null>(null);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const agentPanelScrollRef = useRef<HTMLDivElement | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const recognitionActiveRef = useRef(false);
  const synthesisUtteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const preferredVoiceRef = useRef<VoicePick | null>(null);
  const hasUserInteractedRef = useRef(false);
  const autoWelcomeAttemptedRef = useRef(false);
  const welcomeSpeechPendingRef = useRef(true);
  const ttsRetryRef = useRef(false);
  const welcomeSpokenRef = useRef(false);
  const speechStartTimeoutRef = useRef<number | null>(null);
  const autoListenWatchdogRef = useRef<number | null>(null);
  const autoListenAfterSpeakRef = useRef(false);
  const autoListenQueuedRef = useRef(false);
  const isLoadingRef = useRef(false);
  const micStateRef = useRef<"idle" | "listening" | "processing" | "speaking">("idle");
  const ttsStateRef = useRef<TtsState>("idle");
  const voiceModeStateRef = useRef<VoiceModeState>("off");
  const voiceRestartAttemptsRef = useRef(0);
  const processingSlowTimerRef = useRef<number | null>(null);

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
    isLoadingRef.current = isLoading;
  }, [isLoading]);

  useEffect(() => {
    micStateRef.current = micState;
  }, [micState]);

  useEffect(() => {
    ttsStateRef.current = ttsState;
  }, [ttsState]);

  useEffect(() => {
    voiceModeStateRef.current = voiceModeState;
  }, [voiceModeState]);

  useEffect(() => {
    return () => {
      if (speechStartTimeoutRef.current !== null) {
        window.clearTimeout(speechStartTimeoutRef.current);
      }
      if (autoListenWatchdogRef.current !== null) {
        window.clearTimeout(autoListenWatchdogRef.current);
      }
      if (processingSlowTimerRef.current !== null) {
        window.clearTimeout(processingSlowTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (processingSlowTimerRef.current !== null) {
      window.clearTimeout(processingSlowTimerRef.current);
      processingSlowTimerRef.current = null;
    }
    if (voiceModeState === "processing") {
      setVoiceProcessingSlow(false);
      processingSlowTimerRef.current = window.setTimeout(() => {
        setVoiceProcessingSlow(true);
      }, 5000);
      return;
    }
    setVoiceProcessingSlow(false);
  }, [voiceModeState]);

  useEffect(() => {
    const el = chatScrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, isLoading]);

  function requestStartListening(delayMs = 0) {
    if (!sttSupported || !recognitionRef.current) return;
    if (typeof document !== "undefined" && document.hidden) return;
    if (isTtsInFlight(ttsStateRef.current)) return;
    if (isLoadingRef.current || micStateRef.current === "processing" || micStateRef.current === "speaking") return;
    const run = () => {
      if (!recognitionRef.current || recognitionActiveRef.current) return;
      if (isTtsInFlight(ttsStateRef.current)) return;
      try {
        voiceRestartAttemptsRef.current += 1;
        setVoiceBanner(null);
        recognitionRef.current.start();
      } catch {
        setMicState("idle");
      }
    };
    if (delayMs > 0) {
      window.setTimeout(run, delayMs);
      return;
    }
    run();
  }

  function transitionVoice(event: Parameters<typeof nextVoiceModeState>[1]) {
    setVoiceModeState((cur) => nextVoiceModeState(cur, event));
  }

  function stopListening() {
    if (!recognitionRef.current) return;
    try {
      recognitionRef.current.stop();
    } catch {
      // noop
    }
  }

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

      recognition.onstart = () => {
        recognitionActiveRef.current = true;
        setMicState("listening");
      };
      recognition.onresult = (evt: SpeechRecognitionEventLike) => {
        const transcript = evt.results?.[0]?.[0]?.transcript?.trim();
        if (!transcript) {
          setMicState("idle");
          return;
        }
        const assistantCandidates = [
          welcomeText,
          messages
            .slice()
            .reverse()
            .find((m) => m.role === "assistant")?.text || "",
        ];
        if (isLikelyTtsEcho(transcript, assistantCandidates)) {
          setVoiceBanner("I caught my own voice. Please speak now.");
          autoListenQueuedRef.current = true;
          setMicState("idle");
          return;
        }
        autoListenQueuedRef.current = false;
        setMicState("processing");
        if (voiceModeStateRef.current === "listening") {
          transitionVoice("USER_SPEECH_CAPTURED");
        }
        void sendMessage(transcript);
      };
      recognition.onerror = (evt: SpeechRecognitionErrorEventLike) => {
        recognitionActiveRef.current = false;
        setMicState("idle");
        const code = (evt?.error || "").toLowerCase();
        if (code === "not-allowed" || code === "service-not-allowed") {
          setVoiceBanner("Mic permission is blocked. Please allow microphone access in browser settings.");
          if (isVoiceActive(voiceModeStateRef.current)) {
            transitionVoice("VOICE_FAILURE");
            setVoiceBanner("Voice unavailable, continuing in text");
          }
          return;
        }
        if (isVoiceActive(voiceModeStateRef.current)) {
          transitionVoice("VOICE_FAILURE");
          setVoiceBanner("Voice unavailable, continuing in text");
          return;
        }
        setVoiceBanner("Voice input failed. Switched to text mode.");
      };
      recognition.onend = () => {
        recognitionActiveRef.current = false;
        if (autoListenQueuedRef.current && isVoiceActive(voiceModeStateRef.current)) {
          autoListenQueuedRef.current = false;
          requestStartListening(140);
          return;
        }
        setMicState((cur) => (cur === "listening" ? "idle" : cur));
      };
      recognitionRef.current = recognition;
    }

    const choosePreferredVoice = () => {
      if (typeof window === "undefined" || !window.speechSynthesis) return;
      const voices = window.speechSynthesis.getVoices();
      if (!voices.length) return;
      const ranked = pickPreferredVoice(voices);
      preferredVoiceRef.current = ranked ? { name: ranked.name, lang: ranked.lang } : null;
    };
    choosePreferredVoice();
    window.speechSynthesis.onvoiceschanged = choosePreferredVoice;

    const stopSpeech = () => {
      transitionVoice("PAGE_CLOSED");
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
      const firstInteraction = !hasUserInteractedRef.current;
      hasUserInteractedRef.current = true;
      unlockTts();
      if (!isVoiceActive(voiceModeStateRef.current)) return;
      if (autoWelcomeAttemptedRef.current && !welcomeSpokenRef.current && typeof window !== "undefined" && !window.speechSynthesis.speaking) {
        autoWelcomeAttemptedRef.current = false;
        speak(welcomeText, { autoListen: true });
        return;
      }
      if (firstInteraction) requestStartListening();
    };
    if (typeof window !== "undefined") {
      const seen = window.sessionStorage.getItem("finn_voice_mode_seen") === "1";
      setShowVoiceHint(!seen);
    }
    const onVisibilityChange = () => {
      if (document.hidden) return;
      if (autoListenQueuedRef.current) {
        requestStartListening(80);
      }
    };
    window.addEventListener("pointerdown", markInteractedAndSpeakWelcome, {
      once: true,
    });
    window.addEventListener("keydown", markInteractedAndSpeakWelcome, {
      once: true,
    });
    window.addEventListener("beforeunload", stopSpeech);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      transitionVoice("PAGE_CLOSED");
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
      document.removeEventListener("visibilitychange", onVisibilityChange);
      if (window.speechSynthesis) {
        window.speechSynthesis.onvoiceschanged = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function speak(text: string, opts?: { autoListen?: boolean }) {
    if (!ttsSupported || typeof window === "undefined") return;
    const cleanText = (text || "").replace(/\s+/g, " ").trim();
    if (!cleanText) return;
    ttsRetryRef.current = false;
    autoListenAfterSpeakRef.current = Boolean(opts?.autoListen);
    setTtsErrorDetail(null);
    setTtsState("queued");
    setMicState("speaking");
    autoListenQueuedRef.current = false;
    try {
      window.speechSynthesis.resume();
    } catch {
      // noop
    }
    if (recognitionActiveRef.current) {
      stopListening();
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(cleanText);
    const preferred = preferredVoiceRef.current;
    utterance.lang = preferred?.lang || "en-IN";
    const selectedVoice =
      window.speechSynthesis
        .getVoices()
        .find((v) => preferred && v.name === preferred.name && v.lang === preferred.lang) ||
      pickPreferredVoice(window.speechSynthesis.getVoices());
    if (selectedVoice) utterance.voice = selectedVoice;
    utterance.rate = 0.95;
    utterance.pitch = 1.02;
    utterance.volume = 1;
    utterance.onstart = () => {
      if (speechStartTimeoutRef.current !== null) {
        window.clearTimeout(speechStartTimeoutRef.current);
        speechStartTimeoutRef.current = null;
      }
      if (cleanText === welcomeText) {
        welcomeSpokenRef.current = true;
        welcomeSpeechPendingRef.current = false;
        autoWelcomeAttemptedRef.current = false;
        if (voiceModeStateRef.current === "starting" || !isVoiceActive(voiceModeStateRef.current)) {
          transitionVoice("WELCOME_SPEECH_STARTED");
        }
      } else if (voiceModeStateRef.current === "processing" || voiceModeStateRef.current === "listening") {
        transitionVoice("ASSISTANT_REPLY_STARTED");
      }
      setMicState("speaking");
      setTtsState("started");
      setVoiceBanner(null);
    };
    utterance.onend = () => {
      setMicState("idle");
      setTtsState("ended");
      if (autoListenAfterSpeakRef.current) {
        autoListenAfterSpeakRef.current = false;
        autoListenQueuedRef.current = true;
        requestStartListening(120);
      }
      if (cleanText === welcomeText && voiceModeStateRef.current === "speaking_welcome") {
        transitionVoice("WELCOME_SPEECH_ENDED");
      } else if (voiceModeStateRef.current === "speaking_reply") {
        transitionVoice("ASSISTANT_REPLY_ENDED");
      }
    };
    utterance.onerror = (evt) => {
      if (speechStartTimeoutRef.current !== null) {
        window.clearTimeout(speechStartTimeoutRef.current);
        speechStartTimeoutRef.current = null;
      }
      setMicState("idle");
      const detail = typeof evt.error === "string" ? evt.error : "unknown";
      // Browsers often emit interrupted/canceled when replacing active speech.
      // Treat these as benign so users can tap Speak repeatedly without false errors.
      if (detail === "interrupted" || detail === "canceled") {
        setTtsState("ended");
        setTtsErrorDetail(null);
        if (autoWelcomeAttemptedRef.current && !hasUserInteractedRef.current) {
          setVoiceBanner("Tap anywhere once to enable voice in this browser.");
        }
        return;
      }
      if (isVoiceActive(voiceModeStateRef.current)) {
        transitionVoice("VOICE_FAILURE");
        setVoiceBanner("Voice unavailable, continuing in text");
      }
      if (!ttsRetryRef.current) {
        ttsRetryRef.current = true;
        const fallback = new SpeechSynthesisUtterance(cleanText);
        fallback.lang = "en-US";
        fallback.rate = 0.95;
        fallback.pitch = 1.02;
        fallback.volume = 1;
        fallback.onstart = () => {
          if (speechStartTimeoutRef.current !== null) {
            window.clearTimeout(speechStartTimeoutRef.current);
            speechStartTimeoutRef.current = null;
          }
          if (cleanText === welcomeText) {
            welcomeSpokenRef.current = true;
            welcomeSpeechPendingRef.current = false;
            autoWelcomeAttemptedRef.current = false;
          }
          setMicState("speaking");
          setTtsState("started");
          setVoiceBanner(null);
        };
        fallback.onend = () => {
          setMicState("idle");
          setTtsState("ended");
          if (autoListenAfterSpeakRef.current) {
            autoListenAfterSpeakRef.current = false;
            autoListenQueuedRef.current = true;
            requestStartListening(120);
          }
          if (cleanText === welcomeText && voiceModeStateRef.current === "speaking_welcome") {
            transitionVoice("WELCOME_SPEECH_ENDED");
          } else if (voiceModeStateRef.current === "speaking_reply") {
            transitionVoice("ASSISTANT_REPLY_ENDED");
          }
        };
        fallback.onerror = () => {
          setMicState("idle");
          setTtsState("error");
          setTtsErrorDetail(detail);
          if (autoWelcomeAttemptedRef.current && !hasUserInteractedRef.current) {
            setVoiceBanner("Tap anywhere once to enable voice in this browser.");
            return;
          }
          if (isVoiceActive(voiceModeStateRef.current)) {
            transitionVoice("VOICE_FAILURE");
            setVoiceBanner("Voice unavailable, continuing in text");
          }
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
      if (autoWelcomeAttemptedRef.current && !hasUserInteractedRef.current) {
        setVoiceBanner("Tap anywhere once to enable voice in this browser.");
        return;
      }
      setVoiceBanner("Text-to-speech failed. You can continue in text mode.");
    };
    synthesisUtteranceRef.current = utterance;
    // Some browsers clip the first phrase when called too quickly after cancel/resume.
    // A slightly longer delay reduces first-words truncation.
    window.setTimeout(() => {
      window.speechSynthesis.speak(utterance);
    }, 140);
    speechStartTimeoutRef.current = window.setTimeout(() => {
      if (ttsStateRef.current !== "started") {
        setTtsState("error");
        if (isVoiceActive(voiceModeStateRef.current)) {
          transitionVoice("VOICE_FAILURE");
          setVoiceBanner("Voice unavailable, continuing in text");
        }
        if (opts?.autoListen) {
          autoListenQueuedRef.current = true;
          requestStartListening(100);
        }
        if (autoWelcomeAttemptedRef.current && !welcomeSpokenRef.current) {
          setVoiceBanner("Tap once to start voice mode.");
        }
      }
    }, 1600);
  }

  async function sendMessage(text: string) {
    const msg = text.trim();
    if (!msg || isLoading) return;
    hasUserInteractedRef.current = true;
    if (welcomeSpeechPendingRef.current) {
      welcomeSpeechPendingRef.current = false;
    }
    setError(null);
    setMessages((prev) => [...prev, { role: "user", text: msg }]);
    setInput("");
    setIsLoading(true);
    setPendingTraceQuery(msg);
    if (voiceModeStateRef.current === "listening") {
      transitionVoice("USER_SPEECH_CAPTURED");
    }
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
      const nextTraces = data.traces || [];
      setTraceTurnHistory((prev) => [
        {
          id:
            typeof crypto !== "undefined" && crypto.randomUUID
              ? crypto.randomUUID()
              : `turn-${Date.now()}`,
          userQuery: msg,
          traces: nextTraces,
        },
        ...prev,
      ]);
      setLastPayload(data.payload || null);
      // Hands-free voice mode: speak every assistant reply, then auto-listen.
      if (isVoiceActive(voiceModeStateRef.current) && ttsSupported) {
        speak(voiceTtsText(data), { autoListen: true });
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
      if (isVoiceActive(voiceModeStateRef.current)) {
        transitionVoice("VOICE_FAILURE");
        setVoiceBanner("Voice unavailable, continuing in text");
      }
    } finally {
      setIsLoading(false);
      setPendingTraceQuery(null);
      setMicState((cur) => (cur === "processing" ? "idle" : cur));
      if (autoListenWatchdogRef.current !== null) {
        window.clearTimeout(autoListenWatchdogRef.current);
      }
      autoListenWatchdogRef.current = window.setTimeout(() => {
        if (
          isVoiceActive(voiceModeStateRef.current) &&
          sttSupported &&
          !recognitionActiveRef.current &&
          micStateRef.current === "idle" &&
          !isTtsInFlight(ttsStateRef.current)
        ) {
          requestStartListening(0);
        }
      }, 2200);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    hasUserInteractedRef.current = true;
    welcomeSpeechPendingRef.current = false;
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
    if (isVoiceSpeakingState(voiceModeStateRef.current)) {
      return;
    }
    if (micState === "listening") {
      autoListenQueuedRef.current = false;
      stopListening();
      setMicState("idle");
      return;
    }
    autoListenQueuedRef.current = false;
    requestStartListening();
  }

  function onEnableVoiceMode() {
    hasUserInteractedRef.current = true;
    if (typeof window !== "undefined") {
      window.sessionStorage.setItem("finn_voice_mode_seen", "1");
    }
    setShowVoiceHint(false);
    transitionVoice("ENABLE_CLICKED");
    if (!ttsSupported || !sttSupported) {
      transitionVoice("VOICE_FAILURE");
      setVoiceBanner("Voice unavailable, continuing in text");
      return;
    }
    autoWelcomeAttemptedRef.current = true;
    speak(welcomeText, { autoListen: true });
  }

  function onStopVoiceMode() {
    transitionVoice("STOP_CLICKED");
    autoListenQueuedRef.current = false;
    autoListenAfterSpeakRef.current = false;
    welcomeSpeechPendingRef.current = false;
    autoWelcomeAttemptedRef.current = false;
    welcomeSpokenRef.current = false;
    if (speechStartTimeoutRef.current !== null) {
      window.clearTimeout(speechStartTimeoutRef.current);
      speechStartTimeoutRef.current = null;
    }
    if (autoListenWatchdogRef.current !== null) {
      window.clearTimeout(autoListenWatchdogRef.current);
      autoListenWatchdogRef.current = null;
    }
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    stopListening();
    setMicState("idle");
  }

  const processingText = inferProcessingText(input || messages.at(-1)?.text || "");
  const bookingCode = typeof lastPayload?.booking_code === "string" ? lastPayload.booking_code : null;
  const debugAgentTrace =
    typeof window !== "undefined" && new URLSearchParams(window.location.search).get("debugAgents") === "1";

  function renderTraceStepCard(t: AgentTrace, stepKey: string) {
    return (
      <div key={stepKey} className="rounded-lg border border-slate-200 bg-slate-50/80 p-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span
            className={`rounded px-2 py-0.5 text-[11px] font-semibold ${
              AGENT_COLORS[t.agent] || "bg-slate-100 text-slate-700"
            }`}
          >
            {t.agent}
          </span>
          <span className="text-[11px] text-slate-500">{t.replanned ? "Replanned" : "Single pass"}</span>
        </div>
        <p className="mt-1.5 text-xs leading-snug text-slate-800">{t.reasoning_brief}</p>
        {t.tools?.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {t.tools.map((tool) => (
              <span key={tool} className="rounded bg-white px-1.5 py-0.5 text-[11px] text-slate-600 ring-1 ring-slate-200">
                {tool}
              </span>
            ))}
          </div>
        )}
        <p className="mt-1.5 font-mono text-[11px] text-slate-600">
          <span className="font-sans text-slate-500">Outcome:</span> {t.outcome || "—"}
        </p>
      </div>
    );
  }

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

        <div className="mb-3 flex items-center justify-between gap-2">
          <div>
            <p className="text-xs font-semibold text-slate-700">Voice Mode</p>
            {showVoiceHint && !isVoiceActive(voiceModeState) && (
              <p className="text-xs text-slate-500">Hands-free conversation with Finn. Tap to start.</p>
            )}
            {voiceModeHelperText(voiceModeState, voiceProcessingSlow) && (
              <p className="text-xs text-slate-600">{voiceModeHelperText(voiceModeState, voiceProcessingSlow)}</p>
            )}
          </div>
          {!isVoiceActive(voiceModeState) ? (
            <button
              type="button"
              onClick={onEnableVoiceMode}
              className="rounded-lg border border-indigo-300 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-800 hover:bg-indigo-100"
            >
              Enable Voice Mode
            </button>
          ) : (
            <button
              type="button"
              onClick={onStopVoiceMode}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100"
            >
              Stop Voice Mode
            </button>
          )}
        </div>

        <div
          ref={chatScrollRef}
          className="h-[420px] space-y-3 overflow-auto rounded-xl border border-slate-100 bg-slate-50 p-3"
        >
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
            {debugAgentTrace && ttsErrorDetail ? ` (${ttsErrorDetail})` : ""}
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
          <h2 className="text-sm font-semibold text-slate-900">How Finn Is Helping</h2>
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700"
            onClick={() => setShowAgentPanel((v) => !v)}
          >
            {showAgentPanel ? "Hide" : "Show"}
          </button>
        </div>

        {showAgentPanel ? (
          <div
            ref={agentPanelScrollRef}
            className="max-h-[min(70vh,520px)] space-y-0 overflow-y-auto overscroll-contain pr-1"
          >
            {isLoading && pendingTraceQuery && (
              <div className="mb-4 border-b border-slate-200 pb-3">
                <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Latest</p>
                <p className="mt-1 line-clamp-3 text-xs text-slate-800">&ldquo;{pendingTraceQuery}&rdquo;</p>
                <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50/80 px-2 py-2">
                  <p className="text-xs font-semibold text-amber-900">Working…</p>
                  <p className="text-[11px] text-amber-800">{processingText}</p>
                </div>
              </div>
            )}

            {!isLoading && !traceTurnHistory.length && (
              <p className="text-xs text-slate-500">
                Ask a question to see the real agent trace from the API (reasoning, tools, outcomes).
              </p>
            )}

            {traceTurnHistory.map((block, blockIdx) => (
              <div key={block.id} className={blockIdx > 0 ? "mt-4 border-t border-slate-200 pt-4" : ""}>
                <div className="mb-2 flex items-baseline justify-between gap-2">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                    {blockIdx === 0 ? "Latest turn" : "Earlier turn"}
                  </p>
                </div>
                <p className="mb-2 line-clamp-4 text-xs font-medium text-slate-800">&ldquo;{block.userQuery}&rdquo;</p>
                <div className="space-y-2">
                  {block.traces.length ? (
                    block.traces.map((t, idx) => renderTraceStepCard(t, `${block.id}-s${idx}`))
                  ) : (
                    <p className="text-xs text-slate-500">No trace steps returned for this message.</p>
                  )}
                </div>
                {debugAgentTrace && blockIdx === 0 && lastPayload && Object.keys(lastPayload).length > 0 && (
                  <details className="mt-2 rounded border border-slate-200 bg-slate-50 p-2 text-[11px]">
                    <summary className="cursor-pointer font-medium text-slate-700">Payload (debug)</summary>
                    <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-all text-slate-600">
                      {JSON.stringify(lastPayload, null, 2)}
                    </pre>
                  </details>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-500">Panel collapsed.</p>
        )}
      </aside>
    </section>
  );
}
