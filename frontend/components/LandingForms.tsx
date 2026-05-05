"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

export function LandingForms() {
  const router = useRouter();
  const [firstName, setFirstName] = useState("");
  const [bookingCode, setBookingCode] = useState("");

  function onStartChat(e: FormEvent) {
    e.preventDefault();
    const name = firstName.trim();
    if (!name) return;
    router.push(`/chat?name=${encodeURIComponent(name)}`);
  }

  function onBookingSubmit(e: FormEvent) {
    e.preventDefault();
    const code = bookingCode.trim().toUpperCase();
    if (!code) return;
    router.push(`/secure/${encodeURIComponent(code)}`);
  }

  return (
    <div className="mx-auto grid max-w-4xl gap-6 md:grid-cols-2">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">
          Start a conversation
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          New here? Enter your first name — no account needed. Finn will greet
          you on the chat page (Phase 5+).
        </p>
        <form onSubmit={onStartChat} className="mt-4 flex flex-col gap-3">
          <label className="text-sm font-medium text-slate-700" htmlFor="fn">
            First name
          </label>
          <input
            id="fn"
            name="firstName"
            autoComplete="given-name"
            placeholder="e.g. Aviral"
            value={firstName}
            onChange={(e) => setFirstName(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-slate-900 shadow-inner outline-none ring-indigo-500 focus:border-indigo-500 focus:ring-2"
          />
          <button
            type="submit"
            className="mt-2 rounded-lg bg-indigo-700 px-4 py-2.5 text-sm font-semibold text-white shadow hover:bg-indigo-800 disabled:opacity-50"
            disabled={!firstName.trim()}
          >
            Begin
          </button>
        </form>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">
          Have a booking code?
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Enter your code (e.g. GRW-A7K2) to open the secure details page.
        </p>
        <form onSubmit={onBookingSubmit} className="mt-4 flex flex-col gap-3">
          <label className="text-sm font-medium text-slate-700" htmlFor="bc">
            Booking code
          </label>
          <input
            id="bc"
            name="bookingCode"
            placeholder="GRW-XXXX"
            value={bookingCode}
            onChange={(e) => setBookingCode(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm uppercase text-slate-900 shadow-inner outline-none ring-indigo-500 focus:border-indigo-500 focus:ring-2"
          />
          <button
            type="submit"
            className="mt-2 rounded-lg border border-indigo-200 bg-white px-4 py-2.5 text-sm font-semibold text-indigo-800 shadow-sm hover:bg-indigo-50 disabled:opacity-50"
            disabled={!bookingCode.trim()}
          >
            Submit
          </button>
        </form>
      </section>
    </div>
  );
}
