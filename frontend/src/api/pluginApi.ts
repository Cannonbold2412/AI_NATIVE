import { apiFetch, apiUrl } from '@/lib/apiBase'

async function json<T>(response: Response): Promise<T> {
  const raw = (await response.text()).trim()
  if (!response.ok) {
    let message = raw || response.statusText
    try {
      const parsed = JSON.parse(raw) as { detail?: unknown; message?: unknown }
      const detail = parsed.detail ?? parsed.message
      if (typeof detail === 'string' && detail.trim()) message = detail.trim()
    } catch {
      // keep raw
    }
    throw new Error(message)
  }
  return raw ? (JSON.parse(raw) as T) : ({} as T)
}

export type PluginWorkflow = {
  id: string
  slug: string
  name: string
  session_id: string
  recorded_at: number
  status: 'recorded' | 'compiled' | 'error'
  skill_id: string | null
}

export type PluginAuth = {
  session_id: string
  captured_at: number
  storage_state_path: string
}

export type PluginBuild = {
  last_built_at: number
  output_path: string
  version: string
}

export type PluginInstaller = {
  built_at: number
  installer_path: string
  filename: string
  version: string
  runtime_version: string
}

export type Plugin = {
  id: string
  slug: string
  name: string
  owner_user_id: string
  target_url: string
  protected_url: string
  protected_url_marker_text: string
  status: 'needs_auth' | 'ready' | 'building' | 'error'
  auth: PluginAuth | null
  workflows: PluginWorkflow[]
  build: PluginBuild | null
  installer: PluginInstaller | null
  created_at: number
  updated_at: number
  repository_url: string | null
  repository_private: boolean
  last_published_version: string | null
  last_published_at: number | null
  last_commit_sha: string | null
}

export type PluginsResponse = { plugins: Plugin[] }

export function normalizePluginList(data: unknown): Plugin[] {
  if (Array.isArray(data)) return data as Plugin[]
  if (data && typeof data === 'object') {
    const plugins = (data as { plugins?: unknown }).plugins
    if (Array.isArray(plugins)) return plugins as Plugin[]
  }
  return []
}

export function fetchPlugins(): Promise<PluginsResponse> {
  return apiFetch('/plugins').then((r) => json<PluginsResponse>(r))
}

export function fetchPlugin(id: string): Promise<{ plugin: Plugin }> {
  return apiFetch(`/plugins/${encodeURIComponent(id)}`).then((r) => json<{ plugin: Plugin }>(r))
}

export function createPlugin(body: {
  name: string
  target_url: string
  protected_url: string
  protected_url_marker_text?: string
}): Promise<{ plugin: Plugin }> {
  return apiFetch('/plugins', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => json<{ plugin: Plugin }>(r))
}

export function deletePlugin(id: string): Promise<{ deleted: boolean }> {
  return apiFetch(`/plugins/${encodeURIComponent(id)}`, { method: 'DELETE' }).then((r) =>
    json<{ deleted: boolean }>(r),
  )
}

export function startAuthRecord(
  pluginId: string,
  body: { start_url?: string } = {},
): Promise<{ session_id: string; start_url: string }> {
  return apiFetch(`/plugins/${encodeURIComponent(pluginId)}/auth/record`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => json<{ session_id: string; start_url: string }>(r))
}

export function finalizeAuth(
  pluginId: string,
  sessionId: string,
): Promise<{ plugin_status: string; storage_state_saved: boolean }> {
  return apiFetch(`/plugins/${encodeURIComponent(pluginId)}/auth/finalize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  }).then((r) => json<{ plugin_status: string; storage_state_saved: boolean }>(r))
}

export function getPluginRecordingStatus(sessionId: string): Promise<{
  session_id: string
  browser_open: boolean
  event_count: number
  ended_by_user: boolean
  binding_errors: string[]
  reached_wait_url?: boolean
}> {
  return apiFetch(`/record/${encodeURIComponent(sessionId)}/status`).then((r) =>
    json<{
      session_id: string
      browser_open: boolean
      event_count: number
      ended_by_user: boolean
      binding_errors: string[]
      reached_wait_url?: boolean
    }>(r),
  )
}

export function reRecordAuth(pluginId: string): Promise<{ status: string }> {
  return apiFetch(`/plugins/${encodeURIComponent(pluginId)}/auth/re-record`, {
    method: 'POST',
  }).then((r) => json<{ status: string }>(r))
}

export function startWorkflowRecord(
  pluginId: string,
  name: string,
  urlVariables?: Record<string, string>,
): Promise<{ session_id: string; workflow_id: string }> {
  return apiFetch(`/plugins/${encodeURIComponent(pluginId)}/workflows/record`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, url_variables: urlVariables || {} }),
  }).then((r) => json<{ session_id: string; workflow_id: string }>(r))
}

export function finalizeWorkflow(
  pluginId: string,
  workflowId: string,
  sessionId: string,
  forceWorkflowKind?: 'login' | 'workflow',
): Promise<{ status: string; session_id: string; workflow_id: string; workflow_kind: 'login' | 'workflow' }> {
  return apiFetch(`/plugins/${encodeURIComponent(pluginId)}/workflows/${encodeURIComponent(workflowId)}/finalize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      workflow_id: workflowId,
      ...(forceWorkflowKind ? { force_workflow_kind: forceWorkflowKind } : {}),
    }),
  }).then((r) => json<{ status: string; session_id: string; workflow_id: string; workflow_kind: 'login' | 'workflow' }>(r))
}

export function deleteWorkflow(pluginId: string, workflowId: string): Promise<{ deleted: boolean }> {
  return apiFetch(
    `/plugins/${encodeURIComponent(pluginId)}/workflows/${encodeURIComponent(workflowId)}`,
    { method: 'DELETE' },
  ).then((r) => json<{ deleted: boolean }>(r))
}

export function buildPlugin(pluginId: string, version = '0.1.0'): Promise<Response> {
  return apiFetch(`/plugins/${encodeURIComponent(pluginId)}/build/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version }),
  })
}

export function updateWorkflow(
  pluginId: string,
  workflowId: string,
  body: { skill_id?: string | null },
): Promise<{ plugin_id: string; workflow_id: string; skill_id: string | null }> {
  return apiFetch(`/plugins/${encodeURIComponent(pluginId)}/workflows/${encodeURIComponent(workflowId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => json<{ plugin_id: string; workflow_id: string; skill_id: string | null }>(r))
}

export function downloadPlugin(pluginId: string): string {
  return `/api/v1/plugins/${encodeURIComponent(pluginId)}/download`
}

// ─────────────────────────────────────────────────
// Runs / tracker
// ─────────────────────────────────────────────────

export type RunEvent = {
  event: 'step_failure' | 'recovery_attempt' | 'run_outcome'
  run_id: string
  plugin_id: string
  skill_slug: string
  step_id: string | null
  data: Record<string, unknown>
  ts: string
}

export type RunOutcome = {
  status: 'success' | 'failure' | 'aborted'
  duration_ms: number
  total_steps: number
  recovered_steps: number
  failed_step_id: string | null
}

export type Run = {
  run_id: string
  plugin_id: string
  skill_slug: string
  events: RunEvent[]
  outcome: RunOutcome | null
}

export type RunsResponse = { runs: Run[] }

// ─────────────────────────────────────────────────
// Compiled skill inspect + url_state editing
// ─────────────────────────────────────────────────

export type CompiledSkillFiles = {
  'execution.json': Record<string, unknown> | unknown[] | null
  'recovery.json': Record<string, unknown> | unknown[] | null
  'input.json': Record<string, unknown> | unknown[] | null
}

export function getCompiledSkill(
  pluginId: string,
  skillSlug: string,
): Promise<{ plugin_id: string; skill_slug: string; files: CompiledSkillFiles }> {
  return apiFetch(`/plugins/${encodeURIComponent(pluginId)}/skills/${encodeURIComponent(skillSlug)}/compiled`).then(
    (r) => json<{ plugin_id: string; skill_slug: string; files: CompiledSkillFiles }>(r),
  )
}

export function updateStepUrlState(
  pluginId: string,
  skillSlug: string,
  stepId: string,
  body: { before?: Record<string, unknown>; after?: Record<string, unknown> },
): Promise<{ plugin_id: string; skill_slug: string; step_id: string; updated: boolean }> {
  return apiFetch(
    `/plugins/${encodeURIComponent(pluginId)}/skills/${encodeURIComponent(skillSlug)}/steps/${encodeURIComponent(stepId)}/url_state`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  ).then((r) => json<{ plugin_id: string; skill_slug: string; step_id: string; updated: boolean }>(r))
}

export function fetchRuns(pluginId?: string, since?: number): Promise<RunsResponse> {
  const params = new URLSearchParams()
  if (pluginId) params.set('plugin_id', pluginId)
  if (since != null) params.set('since', String(since))
  const qs = params.toString()
  return apiFetch(`/runs${qs ? '?' + qs : ''}`).then((r) => json<RunsResponse>(r))
}

export function fetchRun(runId: string): Promise<{ run: Run }> {
  return apiFetch(`/runs/${encodeURIComponent(runId)}`).then((r) => json<{ run: Run }>(r))
}

// ─────────────────────────────────────────────────────────────────────────────
// GitHub publish
// ─────────────────────────────────────────────────────────────────────────────

export type GithubStatus = {
  connected: boolean
  login: string | null
  scopes: string[] | null
}

export type PublishPreview = {
  plugin_id: string
  current_version: string
  next_versions: { patch: string; minor: string; major: string }
  repo_status: 'linked' | 'unlinked'
  repo_url: string | null
  last_published_version: string | null
  last_commit_sha: string | null
  bundle_files: string[]
  has_build: boolean
}

export type PublishResult = {
  repo_url: string
  version: string
  commit_sha: string
  install_snippet: string
}

export type PublishPayload = {
  version_bump?: 'patch' | 'minor' | 'major' | null
  manual_version?: string | null
  changelog?: string
  create_repo?: boolean
  repo_name?: string | null
  private?: boolean
}

export function getGithubStatus(): Promise<GithubStatus> {
  return apiFetch('/integrations/github/status').then((r) => json<GithubStatus>(r))
}

export function disconnectGithub(): Promise<{ disconnected: boolean }> {
  return apiFetch('/integrations/github/disconnect', { method: 'POST' }).then((r) =>
    json<{ disconnected: boolean }>(r),
  )
}

export function previewPublish(pluginId: string): Promise<PublishPreview> {
  return apiFetch(`/plugins/${encodeURIComponent(pluginId)}/publish/preview`).then((r) =>
    json<PublishPreview>(r),
  )
}

export function publishPlugin(pluginId: string, payload: PublishPayload): Promise<PublishResult> {
  return apiFetch(`/plugins/${encodeURIComponent(pluginId)}/publish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => json<PublishResult>(r))
}

// ─────────────────────────────────────────────────────────────────────────────
// Installer build + download
// ─────────────────────────────────────────────────────────────────────────────

export type InstallerBuildResult = {
  installer_path: string
  filename: string
  company: string
  plugin_id: string
  version: string
  runtime_version: string
}

/** Returns a raw Response for SSE streaming — same pattern as buildPlugin(). */
export function buildInstaller(pluginId: string): Promise<Response> {
  return apiFetch(`/plugins/${encodeURIComponent(pluginId)}/build-installer/stream`, { method: 'POST' })
}

/** Returns the URL to download the compiled installer EXE. */
export function installerDownloadUrl(pluginId: string): string {
  return apiUrl(`/plugins/${encodeURIComponent(pluginId)}/installer/download`)
}
