import Link from "next/link";
import { SecureBookingClient } from "@/components/secure/SecureBookingClient";

type Props = { params: Promise<{ bookingCode: string }> };

export default async function SecureBookingPage({ params }: Props) {
  const { bookingCode } = await params;
  const code = decodeURIComponent(bookingCode);

  return (
    <div className="mx-auto max-w-lg px-4 py-12">
      <p className="text-sm text-slate-500">
        <Link href="/" className="text-indigo-700 hover:underline">
          Home
        </Link>
        <span className="mx-2">/</span>
        <span>Secure</span>
      </p>
      <h1 className="mt-4 text-2xl font-bold text-slate-900">
        Secure booking details
      </h1>
      <p className="mt-2 text-slate-600">
        Enter secure contact details for booking code:{" "}
        <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-sm">
          {code}
        </span>
      </p>
      <SecureBookingClient bookingCode={code} />
    </div>
  );
}
