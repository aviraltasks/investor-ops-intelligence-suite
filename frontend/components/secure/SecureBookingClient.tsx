"use client";

import { FormEvent, useMemo, useState } from "react";

type Booking = {
  booking_code: string;
  customer_name: string;
  topic: string;
  date: string;
  time_ist: string;
  advisor: string;
  status: string;
  concern_summary: string;
};

export function SecureBookingClient({ bookingCode }: { bookingCode: string }) {
  const backendBaseUrl = useMemo(
    () => process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000",
    [],
  );
  const [booking, setBooking] = useState<Booking | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  async function lookup() {
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const r = await fetch(`${backendBaseUrl}/api/secure/${encodeURIComponent(bookingCode)}`);
      const d = await r.json();
      if (!d.ok) {
        setBooking(null);
        setError(d.message || "Invalid booking code.");
        return;
      }
      setBooking(d.booking);
      const details = d.secure_details || {};
      if (details.phone) setPhone(details.phone);
      if (details.email) setEmail(details.email);
      if (details.consent) setConsent(true);
    } catch {
      setError("Could not verify booking right now.");
    } finally {
      setLoading(false);
    }
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    setMessage("");
    if (!booking) {
      setError("Lookup booking first.");
      return;
    }
    setLoading(true);
    try {
      const r = await fetch(`${backendBaseUrl}/api/secure/${encodeURIComponent(bookingCode)}/details`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, email, consent }),
      });
      const d = await r.json();
      if (!d.ok) {
        setError(d.message || "Could not save details.");
      } else {
        setSubmitted(true);
        setMessage("Details submitted successfully.");
      }
    } catch {
      setError("Submission failed. Please retry.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mt-6 space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <button
          type="button"
          onClick={() => void lookup()}
          disabled={loading}
          className="rounded-lg bg-indigo-700 px-3 py-2 text-sm text-white disabled:opacity-60"
        >
          {loading ? "Checking..." : "Verify Booking Code"}
        </button>
        <p className="mt-2 text-xs text-slate-500">
          Booking code: <span className="font-mono">{bookingCode}</span>
        </p>
      </div>

      {error && <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}
      {message && (
        <p className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          {message}
        </p>
      )}

      {booking && (
        <>
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="text-sm font-semibold text-slate-900">Booking Summary</h2>
            <dl className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-700">
              <div><dt className="text-slate-500">Code</dt><dd className="font-mono">{booking.booking_code}</dd></div>
              <div><dt className="text-slate-500">Status</dt><dd>{booking.status}</dd></div>
              <div><dt className="text-slate-500">Customer</dt><dd>{booking.customer_name}</dd></div>
              <div><dt className="text-slate-500">Advisor</dt><dd>{booking.advisor}</dd></div>
              <div><dt className="text-slate-500">Date</dt><dd>{booking.date}</dd></div>
              <div><dt className="text-slate-500">Time</dt><dd>{booking.time_ist}</dd></div>
            </dl>
            <p className="mt-2 text-xs text-slate-600">Topic: {booking.topic}</p>
          </div>

          <form onSubmit={onSubmit} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="text-sm font-semibold text-slate-900">Secure Contact Details</h2>
            <p className="mt-1 text-xs text-slate-500">Required to finalize follow-up communication.</p>
            <div className="mt-3 grid gap-3">
              <label className="text-sm text-slate-700">
                Phone (+91 format)
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="+91 9876543210"
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
                />
              </label>
              <label className="text-sm text-slate-700">
                Email
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@example.com"
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
                />
              </label>
              <label className="flex items-start gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                  className="mt-0.5"
                />
                I consent to use these details for booking-related communication.
              </label>
            </div>
            <button
              type="submit"
              disabled={loading || submitted}
              className="mt-4 rounded-lg bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-60"
            >
              {submitted ? "Submitted" : loading ? "Submitting..." : "Submit Secure Details"}
            </button>
          </form>
        </>
      )}
    </div>
  );
}
