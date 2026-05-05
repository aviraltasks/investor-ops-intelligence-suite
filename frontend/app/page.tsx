import { LandingForms } from "@/components/LandingForms";

export default function HomePage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-12 sm:py-16">
      <section className="mx-auto max-w-3xl text-center">
        <p className="text-sm font-semibold uppercase tracking-wide text-indigo-700">
          Groww-style fintech ops
        </p>
        <h1 className="mt-3 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
          Smart answers. Real insights. Advisor access.
        </h1>
        <p className="mt-4 text-lg text-slate-600">
          Meet Finn — factual mutual fund help from curated sources, Play Store
          pulse for your team, and IST-aware advisor booking. Phase 1: routes and
          shell UI; chat and agents ship in later phases.
        </p>
      </section>

      <div className="mt-12">
        <LandingForms />
      </div>
    </div>
  );
}
