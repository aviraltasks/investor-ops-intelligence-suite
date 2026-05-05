"use client";

import { FormEvent, useMemo, useState } from "react";

export function SubscriberSignupClient() {
  const backendBaseUrl = useMemo(
    () => process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000",
    [],
  );
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setStatus("");
    setError("");
    if (!email.trim()) {
      setError("Please enter an email.");
      return;
    }
    setLoading(true);
    try {
      const r = await fetch(`${backendBaseUrl}/api/subscribers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const d = await r.json();
      if (!d.ok) {
        setError(d.message || "Subscription failed.");
        return;
      }
      setStatus(d.message === "already subscribed" ? "You are already subscribed." : "Subscribed successfully.");
      setEmail("");
    } catch {
      setError("Could not subscribe right now.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="mt-8 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <label className="text-sm text-slate-700">
        Work email
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@company.com"
          className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
      </label>
      <button
        type="submit"
        disabled={loading}
        className="mt-3 rounded-lg bg-indigo-700 px-3 py-2 text-sm text-white disabled:opacity-60"
      >
        {loading ? "Subscribing..." : "Subscribe"}
      </button>
      {status && <p className="mt-2 text-sm text-emerald-700">{status}</p>}
      {error && <p className="mt-2 text-sm text-rose-700">{error}</p>}
    </form>
  );
}
