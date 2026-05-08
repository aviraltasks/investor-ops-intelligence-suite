import Link from "next/link";
import { ChatClient } from "@/components/chat/ChatClient";

type Props = { searchParams?: Promise<{ name?: string }> };

export default async function ChatPage({ searchParams }: Props) {
  const sp = (await searchParams) ?? {};
  const name = sp.name?.trim() || "there";

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <p className="text-sm text-slate-500">
        <Link href="/" className="text-indigo-700 hover:underline">
          Home
        </Link>
        <span className="mx-2">/</span>
        <span>Customer Chat</span>
      </p>
      <h1 className="mt-3 text-2xl font-bold tracking-tight text-slate-900">
        Chat with Finn
      </h1>
      <p className="mt-1 text-slate-600">
        Hi <span className="font-semibold text-indigo-900">{name}</span> — ask
        a mutual fund question, check trends, or book an advisor session.
      </p>
      <ChatClient initialName={name} />
    </div>
  );
}
