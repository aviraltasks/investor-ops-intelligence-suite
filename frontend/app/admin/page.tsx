import Link from "next/link";
import { AdminDashboardClient } from "@/components/admin/AdminDashboardClient";

export default function AdminPage() {
  return (
    <div className="mx-auto max-w-5xl px-4 py-12">
      <p className="text-sm text-slate-500">
        <Link href="/" className="text-indigo-700 hover:underline">
          Home
        </Link>
        <span className="mx-2">/</span>
        <span>Admin</span>
      </p>
      <h1 className="mt-4 text-2xl font-bold text-slate-900">
        Admin dashboard
      </h1>
      <p className="mt-2 max-w-2xl text-slate-600">
        No password for reviewers per product spec. This panel includes
        analytics graphs, pulse management, bookings actions, and an agent
        activity feed.
      </p>
      <AdminDashboardClient />
    </div>
  );
}
