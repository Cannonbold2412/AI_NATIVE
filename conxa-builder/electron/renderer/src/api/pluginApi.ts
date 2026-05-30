import { cmd } from '@/lib/ipc'
import type { BackendEvent } from '@/lib/ipc'

export type PluginWorkflow = {
  id: string
  slug: string
  name: string
  session_id: string
  recorded_at: number
  status: 'recorded' | 'compiled' | 'error'
  skill_id: string | null
  edited_at: number | null
  last_test_at: number | null
  last_test_status: 'passed' | 'failed' | 'never'
  last_test_error: string | null
  last_test_inputs: Record<string, unknown>
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
}

export type PluginsResponse = { plugins: Plugin[] }

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

export type CompiledSkillFiles = {
  'execution.json': Record<string, unknown> | unknown[] | null
  'recovery.json': Record<string, unknown> | unknown[] | null
  'input.json': Record<string, unknown> | unknown[] | null
  'inputs.json'?: Record<string, unknown> | unknown[] | null
}

export type InstallerBuildResult = {
  installer_path: string
  filename: string
  company: string
  plugin_id: string
  version: string
  runtime_version: string
}

export type TrackingEvent = {
  e: string
  ts: number
  si?: number
  l?: number
  sc?: string
  fc?: string
  tier?: string
  dur?: number
  tot?: number
  rec?: number
  fsi?: number | null
}

export type TrackingRunSummary = {
  run_id: string
  plugin_id: string
  plugin_ver: string
  runtime_ver: string
  uid: string
  wid: string
  status: 'ok' | 'fail' | 'running'
  duration_ms: number
  total_steps: number
  recovered_steps: number
  failed_step_id: number | null
  failure_code: string | null
  started_at: number
  server_ts: number
}

export type TrackingRunsResponse = { runs: TrackingRunSummary[]; total: number }

export type TrackingRunDetail = {
  run_id: string
  company: string
  plugin_id: string
  plugin_ver: string
  runtime_ver: string
  uid: string
  wid: string
  timeline: TrackingEvent[]
}

export function normalizePluginList(data: unknown): Plugin[] {
  if (Array.isArray(data)) return data as Plugin[]
  if (data && typeof data === 'object') {
    const plugins = (data as { plugins?: unknown }).plugins
    if (Array.isArray(plugins)) return plugins as Plugin[]
  }
  return []
}

export function fetchPlugins(): Promise<PluginsResponse> {
  return cmd<PluginsResponse>('list_plugins')
}

export function fetchPlugin(id: string): Promise<{ plugin: Plugin }> {
  return cmd<{ plugin: Plugin }>('get_plugin', { plugin_id: id })
}

export function createPlugin(body: {
  name: string
  target_url: string
  protected_url?: string
  protected_url_marker_text?: string
}): Promise<{ plugin: Plugin }> {
  return cmd<{ plugin: Plugin }>('create_plugin', body)
}

export function deletePlugin(id: string): Promise<{ deleted: boolean }> {
  return cmd<{ deleted: boolean }>('delete_plugin', { plugin_id: id })
}

export function startAuthRecord(
  pluginId: string,
  body: { start_url?: string } = {},
): Promise<{ session_id: string; start_url: string }> {
  return cmd<{ session_id: string; start_url: string }>('start_recording', {
    plugin_id: pluginId,
    workflow_name: '__auth__',
    ...body,
  })
}

export function finalizeAuth(
  pluginId: string,
  sessionId: string,
): Promise<{ plugin_status: string; storage_state_saved: boolean; protected_url: string }> {
  return cmd<{ plugin_status: string; storage_state_saved: boolean; protected_url: string }>(
    'stop_recording',
    { plugin_id: pluginId, session_id: sessionId, auth_mode: true },
  )
}

export function getPluginRecordingStatus(sessionId: string): Promise<{
  session_id: string
  browser_open: boolean
  event_count: number
  ended_by_user: boolean
  binding_errors: string[]
  reached_wait_url?: boolean
  capture_hover?: boolean
  current_url?: string
}> {
  return cmd('get_recording_status', { session_id: sessionId })
}

export function reRecordAuth(pluginId: string): Promise<{ status: string }> {
  return cmd<{ status: string }>('re_record_auth', { plugin_id: pluginId })
}

export function startWorkflowRecord(
  pluginId: string,
  name: string,
  urlVariables?: Record<string, string>,
  captureHover = false,
): Promise<{ session_id: string; workflow_id: string }> {
  return cmd<{ session_id: string; workflow_id: string }>('start_recording', {
    plugin_id: pluginId,
    workflow_name: name,
    url_variables: urlVariables ?? {},
    capture_hover: captureHover,
  })
}

export function finalizeWorkflow(
  pluginId: string,
  workflowId: string,
  sessionId: string,
  forceWorkflowKind?: 'login' | 'workflow',
): Promise<{ status: string; session_id: string; workflow_id: string; workflow_kind: 'login' | 'workflow' }> {
  return cmd<{ status: string; session_id: string; workflow_id: string; workflow_kind: 'login' | 'workflow' }>(
    'stop_recording',
    {
      plugin_id: pluginId,
      workflow_id: workflowId,
      session_id: sessionId,
      ...(forceWorkflowKind ? { force_workflow_kind: forceWorkflowKind } : {}),
    },
  )
}

export function deleteWorkflow(pluginId: string, workflowId: string): Promise<{ deleted: boolean }> {
  return cmd<{ deleted: boolean }>('delete_workflow', { plugin_id: pluginId, workflow_id: workflowId })
}

export function updateWorkflow(
  pluginId: string,
  workflowId: string,
  body: { skill_id?: string | null },
): Promise<{ plugin_id: string; workflow_id: string; skill_id: string | null; status: PluginWorkflow['status'] }> {
  return cmd('update_workflow', { plugin_id: pluginId, workflow_id: workflowId, ...body })
}

export async function buildPlugin(
  pluginId: string,
  version = '0.1.0',
  onLog: (message: string) => void = () => {},
): Promise<PluginBuild> {
  const unsub = window.conxa.onEvent((ev: BackendEvent) => {
    if (ev.kind === 'plugin_build' && ev.message) onLog(String(ev.message))
  })
  try {
    return await cmd<PluginBuild>('build_plugin', { plugin_id: pluginId, version })
  } finally {
    unsub()
  }
}

export async function buildInstaller(
  pluginId: string,
  onLog: (message: string) => void = () => {},
): Promise<InstallerBuildResult> {
  const unsub = window.conxa.onEvent((ev: BackendEvent) => {
    if (ev.kind === 'installer_build' && ev.message) onLog(String(ev.message))
  })
  try {
    return await cmd<InstallerBuildResult>('build_installer', { plugin_id: pluginId })
  } finally {
    unsub()
  }
}

export function installerDownloadUrl(pluginId: string): string {
  return pluginId
}

export function downloadPlugin(pluginId: string): string {
  return pluginId
}

export function getCompiledSkill(
  pluginId: string,
  skillSlug: string,
): Promise<{ plugin_id: string; skill_slug: string; files: CompiledSkillFiles }> {
  return cmd('get_compiled_skill', { plugin_id: pluginId, skill_slug: skillSlug })
}

export function fetchRuns(pluginId?: string, since?: number): Promise<RunsResponse> {
  return cmd<RunsResponse>('list_runs', { plugin_id: pluginId, since })
}

export function fetchRun(runId: string): Promise<{ run: Run }> {
  return cmd<{ run: Run }>('get_run', { run_id: runId })
}

export async function testWorkflow(
  pluginId: string,
  workflowId: string,
  inputs: Record<string, unknown> = {},
  headless = false,
  onLog: (message: string) => void = () => {},
): Promise<unknown> {
  const unsub = window.conxa.onEvent((ev: BackendEvent) => {
    if (ev.kind === 'workflow_test' && ev.message) onLog(String(ev.message))
  })
  try {
    return await cmd('test_workflow', {
      plugin_id: pluginId,
      workflow_id: workflowId,
      inputs,
      headless,
    })
  } finally {
    unsub()
  }
}

export function fetchTrackingRuns(
  _company: string,
  _limit = 50,
  _offset = 0,
): Promise<TrackingRunsResponse> {
  return Promise.reject(new Error('Tracking runs not available in Build Studio'))
}

export function fetchTrackingRun(_company: string, _runId: string): Promise<TrackingRunDetail> {
  return Promise.reject(new Error('Tracking detail not available in Build Studio'))
}
