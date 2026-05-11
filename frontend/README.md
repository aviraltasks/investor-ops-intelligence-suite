# Frontend (Next.js)

This folder is the **Investor Ops & Intelligence Suite** web app (App Router, TypeScript, Tailwind).

For setup, env vars, deploy (Vercel), and full project context, use the **[repository root README](../README.md)**.

Quick start (after backend is on port 8000):

```bash
cp ../.env.example .env.local
# Set NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
npm install --ignore-scripts
npm run dev
```

Scripts use `node node_modules/next/dist/bin/next …` so paths containing `&` on Windows stay reliable.
