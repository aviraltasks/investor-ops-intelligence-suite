import Link from "next/link";

const nav = [
  { href: "/chat", label: "Chat" },
  { href: "/admin", label: "Admin" },
  { href: "/subscribers", label: "Advisor" },
] as const;

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 shadow-sm backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
        <Link
          href="/"
          className="text-base font-semibold tracking-tight text-indigo-900"
        >
          Investor Ops & Intelligence Suite
        </Link>
        <nav className="flex items-center gap-6 text-sm font-medium text-slate-700">
          {nav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="transition-colors hover:text-indigo-700"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
