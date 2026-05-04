import { apiFetch } from '@/lib/apiBase'

async function json<T>(response: Response): Promise<T> {
  const raw = (await response.text()).trim()
  if (!response.ok) {
    let message = raw || response.statusText
    try {
      const parsed = JSON.parse(raw) as { detail?: unknown; message?: unknown }
      const detail = parsed.detail ?? parsed.message
      if (typeof detail === 'string' && detail.trim()) message = detail.trim()
    } catch {
      // keep raw response text
    }
    throw new Error(message)
  }
  return raw ? (JSON.parse(raw) as T) : ({} as T)
}

export type Workspace = {
  id: string
  slug: string
  name: string
  role: string
}

export type MeResponse = {
  user: {
    id: string
    email?: string | null
    name?: string | null
    auth_provider: string
  }
  workspace: Workspace
  auth_required: boolean
}

export type DashboardResponse = {
  workspace: Workspace
  stats: {
    skills: number
    packages: number
    workflows: number
    active_jobs: number
    published_packages: number
  }
  recent_workflows: Array<Record<string, unknown>>
  recent_packages: Array<Record<string, unknown>>
  active_jobs: JobRecord[]
  package_health: Array<Record<string, unknown>>
  usage: UsageResponse
}

export type UsageResponse = {
  workspace_id: string
  skills: number
  packages: number
  workflows: number
  jobs: number
  active_jobs: number
  metrics: Record<string, unknown>
  limits: Record<string, number | null>
}

export type SubscriptionResponse = {
  subscription: {
    plan: string
    status: string
    customer_id?: string | null
    subscription_id?: string | null
    current_period_end?: number | null
    stripe_configured: boolean
  }
}

export type JobRecord = {
  job_id: string
  kind: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled'
  resource_id?: string | null
  retry_count: number
  user_error?: string | null
  internal_error_code?: string | null
  result?: Record<string, unknown> | null
  created_at: number
  updated_at: number
}

export type PackageRelease = {
  bundle_slug: string
  workspace_id: string
  state: 'draft' | 'published' | 'archived'
  version: string
  release_notes: string
  published_by?: string | null
  published_at?: number | null
  archived_at?: number | null
  updated_at?: number | null
}

export type AuditEvent = {
  id: string
  workspace_id: string
  user_id: string
  action: string
  resource_type: string
  resource_id?: string | null
  metadata: Record<string, unknown>
  created_at: number
}

export function fetchMe(): Promise<MeResponse> {
  return apiFetch('/me').then((r) => json<MeResponse>(r))
}

export function fetchDashboard(): Promise<DashboardResponse> {
  return apiFetch('/dashboard').then((r) => json<DashboardResponse>(r))
}

export function fetchUsage(): Promise<UsageResponse> {
  return apiFetch('/usage').then((r) => json<UsageResponse>(r))
}

export function fetchSubscription(): Promise<SubscriptionResponse> {
  return apiFetch('/billing/subscription').then((r) => json<SubscriptionResponse>(r))
}

export function createCheckout(): Promise<{ url: string }> {
  return apiFetch('/billing/checkout', { method: 'POST' }).then((r) => json<{ url: string }>(r))
}

export function createPortal(): Promise<{ url: string }> {
  return apiFetch('/billing/portal', { method: 'POST' }).then((r) => json<{ url: string }>(r))
}

export function fetchJobs(): Promise<{ jobs: JobRecord[] }> {
  return apiFetch('/jobs').then((r) => json<{ jobs: JobRecord[] }>(r))
}

export function cancelJob(jobId: string): Promise<JobRecord> {
  return apiFetch(`/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' }).then((r) => json<JobRecord>(r))
}

export function fetchRelease(bundleSlug: string): Promise<{ release: PackageRelease }> {
  return apiFetch(`/packages/bundles/${encodeURIComponent(bundleSlug)}/release`).then((r) =>
    json<{ release: PackageRelease }>(r),
  )
}

export function publishBundle(
  bundleSlug: string,
  body: { version?: string; release_notes: string },
): Promise<{ release: PackageRelease }> {
  return apiFetch(`/packages/bundles/${encodeURIComponent(bundleSlug)}/publish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => json<{ release: PackageRelease }>(r))
}

export function patchRelease(
  bundleSlug: string,
  body: Partial<Pick<PackageRelease, 'state' | 'version' | 'release_notes'>>,
): Promise<{ release: PackageRelease }> {
  return apiFetch(`/packages/bundles/${encodeURIComponent(bundleSlug)}/release`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => json<{ release: PackageRelease }>(r))
}

export function fetchAuditEvents(limit = 100): Promise<{ audit_events: AuditEvent[] }> {
  return apiFetch(`/audit-events?limit=${limit}`).then((r) => json<{ audit_events: AuditEvent[] }>(r))
}
