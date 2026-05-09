import Link from "next/link";
import { SubscriberSignupClient } from "@/components/subscribers/SubscriberSignupClient";

export default function SubscribersPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-12">
      <p className="text-sm text-slate-500">
        <Link href="/" className="text-indigo-700 hover:underline">
          Home
        </Link>
        <span className="mx-2">/</span>
        <span>Advisor Hub</span>
      </p>
      <h1 className="mt-4 text-2xl font-bold text-slate-900">
        Advisor Hub
      </h1>
      <p className="mt-2 text-slate-600">
        The weekly intelligence brief for Groww&apos;s advisor team
      </p>

      <section className="mt-6 grid gap-4 md:grid-cols-3">
        <article className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-900">What You&apos;ll Receive</h2>
          <p className="mt-2 text-sm text-slate-600">
            A weekly pulse report analyzing 150+ Play Store reviews — top user pain points, trending themes,
            representative quotes, and 3 prioritized action items. Delivered to your inbox every week.
          </p>
        </article>
        <article className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-900">Client Context on Every Booking</h2>
          <p className="mt-2 text-sm text-slate-600">
            When a customer books an appointment, you&apos;ll receive a briefing email with their concern, booking details,
            and current market sentiment — so you&apos;re prepared before the call.
          </p>
        </article>
        <article className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-900">Customer Details Shared Securely</h2>
          <p className="mt-2 text-sm text-slate-600">
            After booking, customers share their phone and email through a secure page. These contact details are included
            in your briefing — never exposed in the chat.
          </p>
        </article>
      </section>

      <section className="mt-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm md:max-w-2xl">
        <h2 className="text-lg font-semibold text-slate-900">Subscribe to Weekly Pulse</h2>
        <p className="mt-1 text-sm text-slate-600">
          Enter your work email to start receiving the weekly product intelligence report.
        </p>
        <SubscriberSignupClient />
        <p className="mt-3 text-xs text-slate-500">
          You can also be added by the admin team via the Admin dashboard.
        </p>
      </section>
    </div>
  );
}
