import Link from "next/link";
import { SubscriberSignupClient } from "@/components/subscribers/SubscriberSignupClient";

export default function SubscribersPage() {
  return (
    <div className="mx-auto max-w-lg px-4 py-12">
      <p className="text-sm text-slate-500">
        <Link href="/" className="text-indigo-700 hover:underline">
          Home
        </Link>
        <span className="mx-2">/</span>
        <span>Subscribers</span>
      </p>
      <h1 className="mt-4 text-2xl font-bold text-slate-900">
        Pulse subscribers
      </h1>
      <p className="mt-2 text-slate-600">
        Subscribe to receive periodic market pulse updates from Finn.
      </p>
      <SubscriberSignupClient />
    </div>
  );
}
