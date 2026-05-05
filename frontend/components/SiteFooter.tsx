const LINKEDIN = "https://www.linkedin.com/in/aviralrawat/";

export function SiteFooter() {
  return (
    <footer className="mt-auto border-t border-slate-200 bg-white">
      <div className="mx-auto max-w-5xl px-4 py-8 text-sm text-slate-600">
        <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
          <p className="font-medium text-slate-900">
            Investor Ops & Intelligence Suite
          </p>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            <span>Created by Aviral Rawat</span>
            <a
              href={LINKEDIN}
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-700 underline-offset-4 hover:underline"
            >
              LinkedIn
            </a>
            <span className="text-slate-500">Built with Cursor</span>
          </div>
        </div>

        <details className="mt-6 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <summary className="cursor-pointer font-medium text-indigo-900">
            System Design (Architecture)
          </summary>
          <p className="mt-3 text-slate-700">
            Next.js (Vercel) talks to FastAPI (Render). Finn uses an agentic
            backend: RAG over Groww + SEBI sources, ML theme detection on Play
            Store reviews, IST scheduling with Google Calendar and Sheets, and
            Gmail for advisor briefing emails. Durable state lives in
            PostgreSQL; Google integrations use a swappable port layer. Full
            diagrams, API contracts, and phase mapping:{" "}
            <code className="rounded bg-white px-1 py-0.5 text-xs text-slate-800 ring-1 ring-slate-200">
              ARCHITECTURE.md
            </code>{" "}
            in the repository root.
          </p>
        </details>
      </div>
    </footer>
  );
}
