# AI_NATIVE

## Production Deployment

Frontend:
- Vercel project root: `frontend`
- Build command: `npm run build`
- Framework/runtime: Next.js App Router
- The built-in `/api/v1/*` Next route handler proxies to the Render API. Set `API_ORIGIN` to the backend origin.

Backend and worker:
- `render.yaml` defines `ai-native-api` and `ai-native-worker`.
- The API exposes legacy local routes plus `/api/v1/*`.
- Set `SKILL_AUTH_REQUIRED=true`, Clerk issuer/JWKS values, allowed origins, DB, Redis, Blob, Stripe, app URL, and LLM secrets in Render/Vercel environment settings.
- Product endpoints include `/api/v1/me`, `/workspaces/current`, `/dashboard`, `/usage`, `/jobs`, `/billing/*`, `/packages/bundles/{bundle}/publish`, `/packages/bundles/{bundle}/release`, and `/audit-events`.

Frontend product shell:
- `/` is the dashboard.
- `/recordings/new` preserves the record -> compile -> edit flow.
- Backward-compatible redirects remain for `/pakage`, `/package`, `/packages`, `/skill-pack-builder`, `/skills`, and `/edit`.
- Set `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` to enable Clerk sign-in/sign-up pages, protected routes, and the user menu.

Local verification:
- Backend: `pytest -q tests`
- Frontend: `cd frontend && npm run build`
