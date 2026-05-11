const LINKEDIN = "https://www.linkedin.com/in/aviralrawat/";
const GITHUB_REPO = "https://github.com/aviraltasks/investor-ops-intelligence-suite";

export function SiteFooter() {
  return (
    <footer className="mt-auto border-t border-slate-200 bg-white">
      <div className="mx-auto max-w-5xl px-4 py-8 text-center text-sm text-slate-600">
        <div className="flex flex-col items-center justify-center gap-3 sm:flex-row sm:flex-wrap sm:gap-x-6 sm:gap-y-2">
          <p className="font-medium text-slate-900 sm:shrink-0">
            Investor Ops & Intelligence Suite
          </p>
          <span
            className="hidden h-4 w-px shrink-0 bg-slate-200 sm:block"
            aria-hidden
          />
          <p className="flex flex-wrap items-center justify-center gap-x-2 text-slate-600 sm:gap-x-3">
            <span>Created by Aviral Rawat</span>
            <span className="text-slate-300" aria-hidden>
              ·
            </span>
            <a
              href={LINKEDIN}
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-700 underline-offset-4 hover:underline"
            >
              LinkedIn
            </a>
          </p>
        </div>

        <details className="open:[&>summary>span:first-of-type]:rotate-90 mx-auto mt-6 w-full max-w-3xl rounded-lg border border-slate-200 bg-slate-50 p-4 text-center">
          <summary className="flex cursor-pointer list-none items-center justify-center gap-2 font-medium text-indigo-900 [&::-webkit-details-marker]:hidden">
            <span
              aria-hidden
              className="inline-block origin-center text-slate-500 transition-transform duration-200"
            >
              ▸
            </span>
            About This Product
          </summary>
          <div className="mt-3 space-y-3 text-slate-700 [&>p]:text-balance">
            <p>
              An AI-native ops assistant for mutual fund platforms — built on a multi-agent architecture
              where specialized agents (orchestrator, RAG, scheduling, review intelligence, memory) reason
              and collaborate on every user query, with full transparency via the live agent activity panel.
            </p>
            <p>
              <span className="font-medium text-slate-800">Key differentiators:</span> Agentic orchestration
              with real-time reasoning traces. ML-powered theme detection (KMeans clustering + LLM labeling)
              on Play Store reviews — not just LLM-only analysis. RAG over 30+ verified sources (Groww, SEBI)
              with citation grounding. End-to-end Google Workspace integration (Calendar, Sheets, Gmail,
              Docs).
            </p>
            <p className="text-slate-600">
              Built by Aviral Rawat{" "}
              <span className="text-slate-400" aria-hidden>
                ·
              </span>{" "}
              <a
                href={GITHUB_REPO}
                target="_blank"
                rel="noopener noreferrer"
                className="text-indigo-700 underline-offset-4 hover:underline"
              >
                View codebase &amp; architecture on GitHub
              </a>
            </p>
          </div>
        </details>
      </div>
    </footer>
  );
}
