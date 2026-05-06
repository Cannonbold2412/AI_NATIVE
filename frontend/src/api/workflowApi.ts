import type { WorkflowResponse } from '../types/workflow'
import { apiUrl } from '@/lib/apiBase'
import { z } from 'zod'

export type SkillPackBuildLogEntry = Record<string, unknown>

function skillPackFailFromDetail(detail: unknown): { message: string; buildLog: SkillPackBuildLogEntry[] } | null {
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return null
  const rec = detail as Record<string, unknown>
  const msg = rec.message
  if (typeof msg !== 'string' || !msg.trim()) return null
  let buildLog: SkillPackBuildLogEntry[] = []
  const bl = rec.build_log
  if (Array.isArray(bl)) {
    buildLog = bl.filter((x): x is SkillPackBuildLogEntry => Boolean(x && typeof x === 'object'))
  }
  return { message: msg.trim(), buildLog }
}

export class SkillPackBuildRequestError extends Error {
  readonly buildLog: SkillPackBuildLogEntry[]

  constructor(message: string, buildLog: SkillPackBuildLogEntry[]) {
    super(message)
    this.name = 'SkillPackBuildRequestError'
    this.buildLog = buildLog
    Object.setPrototypeOf(this, new.target.prototype)
  }
}

const json = <T = unknown>(r: Response): Promise<T> => {
  if (!r.ok) {
    return r.text().then((t) => {
      const raw = t.trim()
      if (!raw) {
        throw new Error(r.statusText)
      }
      let message: string | null = null
      try {
        const payload = JSON.parse(raw) as { detail?: unknown; message?: unknown }
        const detail = payload.detail ?? payload.message
        const enriched = skillPackFailFromDetail(detail)
        if (enriched) throw new SkillPackBuildRequestError(enriched.message, enriched.buildLog)
        if (typeof detail === 'string' && detail.trim()) {
          message = detail.trim()
        }
      } catch (err) {
        if (err instanceof SkillPackBuildRequestError) throw err
        // Non-JSON error bodies are common (e.g., plain "Internal Server Error").
      }
      if (message) throw new Error(message)
      throw new Error(raw)
    })
  }
  return r.text().then((t) => {
    const raw = t.trim()
    if (!raw) return {} as T

    const contentType = r.headers.get('content-type')?.toLowerCase() ?? ''
    const looksJson =
      contentType.includes('application/json') ||
      contentType.includes('+json') ||
      raw.startsWith('{') ||
      raw.startsWith('[')

    if (!looksJson) return { message: raw } as T

    try {
      return JSON.parse(raw) as T
    } catch {
      throw new Error(`Invalid JSON response (${r.status} ${r.statusText}): ${raw.slice(0, 200)}`)
    }
  })
}

export const errorMessage = (err: unknown, fallback: string) => {
  if (err instanceof Error) {
    const msg = err.message.trim()
    if (msg) return msg
  }
  if (typeof err === 'string' && err.trim()) {
    return err.trim()
  }
  return fallback
}

const recordUnknown = z.record(z.string(), z.unknown())
const recordNumber = z.record(z.string(), z.number())

const stepFlagsSchema = z.object({
  is_destructive: z.boolean(),
  is_scroll: z.boolean(),
  generic_intent: z.boolean(),
})

const stepScreenshotSchema = z.object({
  full_url: z.string().nullable().catch(null),
  element_url: z.string().nullable().catch(null),
  scroll_url: z.string().nullable().catch(null),
  bbox: recordNumber,
  viewport: z.string(),
  scroll_position: z.string(),
})

const stepEditorSchema = z.object({
  id: z.string(),
  step_index: z.number(),
  human_readable_description: z.string(),
  action_type: z.string(),
  intent: z.string(),
  final_intent: z.string(),
  url: z.string().default(''),
  target: recordUnknown,
  selectors: recordUnknown,
  anchors_signals: z.array(recordUnknown),
  anchors_recovery: z.array(recordUnknown),
  validation: z.object({
    wait_for: recordUnknown,
    success_conditions: recordUnknown,
  }),
  recovery: recordUnknown,
  value: z.unknown(),
  scroll_mode: z.string().nullable().default(null),
  scroll_selector: z.string().nullable().default(null),
  scroll_amount: z.number().int().nullable().default(null),
  input_binding: z.string().nullable().default(null),
  screenshot: stepScreenshotSchema,
  editable_fields: z.record(z.string(), z.boolean()),
  flags: stepFlagsSchema,
  parameter_bindings: z.array(recordUnknown),
  check_kind: z.string().nullable().optional(),
  check_pattern: z.string().nullable().optional(),
  check_threshold: z.number().nullable().optional(),
  check_selector: z.string().nullable().optional(),
  check_text: z.string().nullable().optional(),
})

const suggestionSchema = z.object({
  step_index: z.number(),
  severity: z.enum(['info', 'warn', 'error']),
  code: z.string(),
  message: z.string(),
})

const workflowSchema = z.object({
  skill_id: z.string(),
  package_meta: recordUnknown,
  inputs: z.array(recordUnknown),
  steps: z.array(stepEditorSchema),
  suggestions: z.array(suggestionSchema),
  asset_base_url: z.string(),
})

const skillSummarySchema = z.object({
  skill_id: z.string(),
  title: z.string(),
  version: z.number(),
  step_count: z.number(),
  modified_at: z.number(),
})

const skillListSchema = z.object({
  skills: z.array(skillSummarySchema),
})

const deleteSkillSchema = z.object({
  skill_id: z.string(),
  title: z.string(),
  deleted: z.boolean(),
})

const workflowMutationSchema = z.object({
  skill_id: z.string(),
  meta: recordUnknown,
  workflow: workflowSchema,
})

const patchStepSchema = z.object({
  skill_id: z.string(),
  meta: recordUnknown,
  revalidation: recordUnknown,
  workflow: workflowSchema,
})

function parseOrThrow<T>(schema: z.ZodType<T>, payload: unknown, endpoint: string): T {
  const parsed = schema.safeParse(payload)
  if (parsed.success) return parsed.data
  throw new Error(`Invalid API response from ${endpoint}: ${parsed.error.issues[0]?.message ?? 'unknown schema error'}`)
}

/** Custom DataTransfer type for dragging a recording frame onto a workflow step. */
export const RECORDING_SCREENSHOT_DRAG_MIME = 'application/x-ai-native-recording-shot'

/** Drag payload `{ "mode": "clear_visual" }` — removes step screenshot and clears vision anchors. */
export const RECORDING_DRAG_MODE_CLEAR_VISUAL = 'clear_visual' as const

export type SkillSummary = {
  skill_id: string
  title: string
  version: number
  step_count: number
  modified_at: number
}

export type SkillPackageWorkflowSummary = {
  workflow_slug: string
  display_label?: string
  modified_at: number
  files: string[]
}

export type SkillPackageSummary = {
  /** Skill package bundle slug: output/skill_package/<package_name>/ */
  package_name: string
  modified_at: number
  workflows: SkillPackageWorkflowSummary[]
  /** Flattened logical paths across the bundle (for search). */
  files: string[]
}

export type SkillPackageFiles = {
  package_name: string
  bundle_name?: string
  files: Record<string, string>
}

export type RecordingScreenshotItemDTO = {
  event_index: number
  sequence: number
  persisted_full_screenshot: string
  preview_url: string
  viewport: string
  has_element_snapshot: boolean
}

const recordingScreenshotsSchema = z.object({
  skill_id: z.string(),
  session_id: z.string().nullable(),
  items: z.array(
    z.object({
      event_index: z.number(),
      sequence: z.number(),
      persisted_full_screenshot: z.string(),
      preview_url: z.string(),
      viewport: z.string(),
      has_element_snapshot: z.boolean(),
    }),
  ),
})

const applyRecordingVisualResponseSchema = z.object({
  skill_id: z.string(),
  meta: recordUnknown,
  revalidation: recordUnknown,
  workflow: workflowSchema,
})

const skillPackBuildLogEntrySchema = z.record(z.string(), z.unknown())

const skillPackBuildSchema = z.object({
  name: z.string(),
  bundle_slug: z.string().optional(),
  index_json: z.string(),
  skill_md: z.string(),
  execution_json: z.string(),
  recovery_json: z.string(),
  inputs_json: z.string(),
  manifest_json: z.string(),
  input_count: z.number(),
  step_count: z.number(),
  used_llm: z.boolean(),
  warnings: z.array(z.string()),
  workflow_names: z.array(z.string()).optional(),
  build_log: z.array(skillPackBuildLogEntrySchema).optional(),
})

const skillPackageWorkflowSummarySchema = z.object({
  workflow_slug: z.string(),
  display_label: z.string().optional(),
  modified_at: z.number(),
  files: z.array(z.string()),
})

const skillPackageSummarySchema = z.object({
  package_name: z.string(),
  modified_at: z.number(),
  workflows: z.array(skillPackageWorkflowSummarySchema),
  files: z.array(z.string()),
})

const skillPackageListSchema = z.object({
  packages: z.array(skillPackageSummarySchema),
  bundle_root: z.string().default('skill_package'),
})

const skillPackageFilesSchema = z.object({
  package_name: z.string(),
  bundle_name: z.string().optional(),
  files: z.record(z.string(), z.string()),
})

const deleteSkillPackageRecordSchema = z.object({
  package_name: z.string(),
  deleted: z.boolean(),
})

const renameSkillPackageRecordSchema = z.object({
  package_name: z.string(),
  previous_name: z.string(),
})

export function fetchSkillList(): Promise<{ skills: SkillSummary[] }> {
  return fetch(apiUrl('/skills'))
    .then((r) => json<{ skills: SkillSummary[] }>(r))
    .then((payload) => parseOrThrow(skillListSchema, payload, '/skills'))
}

export function deleteSkillPackage(skillId: string): Promise<{ skill_id: string; title: string; deleted: boolean }> {
  const endpoint = `/skills/${encodeURIComponent(skillId)}`
  return fetch(apiUrl(endpoint), { method: 'DELETE' })
    .then(json)
    .then((payload) => parseOrThrow(deleteSkillSchema, payload, endpoint))
}

export function fetchWorkflow(skillId: string): Promise<WorkflowResponse> {
  const endpoint = `/skills/${encodeURIComponent(skillId)}/workflow`
  return fetch(apiUrl(endpoint))
    .then(json)
    .then((payload) => parseOrThrow(workflowSchema, payload, endpoint) as WorkflowResponse)
}

export function fetchRecordingScreenshots(skillId: string): Promise<{
  skill_id: string
  session_id: string | null
  items: RecordingScreenshotItemDTO[]
}> {
  const endpoint = `/skills/${encodeURIComponent(skillId)}/recording-screenshots`
  return fetch(apiUrl(endpoint))
    .then(json)
    .then((payload) => {
      const parsed = parseOrThrow(recordingScreenshotsSchema, payload, endpoint)
      return {
        skill_id: parsed.skill_id,
        session_id: parsed.session_id ?? null,
        items: parsed.items,
      }
    })
}

export function postApplyRecordingVisual(
  skillId: string,
  stepIndex: number,
  body: { event_index: number },
): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  revalidation: Record<string, unknown>
  workflow: WorkflowResponse
}> {
  const endpoint = `/skills/${encodeURIComponent(skillId)}/steps/${stepIndex}/apply-recording-visual`
  return fetch(apiUrl(endpoint), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
    .then(json)
    .then(
      (payload) =>
        parseOrThrow(applyRecordingVisualResponseSchema, payload, endpoint) as {
          skill_id: string
          meta: Record<string, unknown>
          revalidation: Record<string, unknown>
          workflow: WorkflowResponse
        },
    )
}

export function postClearStepVisual(
  skillId: string,
  stepIndex: number,
): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  revalidation: Record<string, unknown>
  workflow: WorkflowResponse
}> {
  const endpoint = `/skills/${encodeURIComponent(skillId)}/steps/${stepIndex}/clear-step-visual`
  return fetch(apiUrl(endpoint), { method: 'POST' })
    .then(json)
    .then(
      (payload) =>
        parseOrThrow(applyRecordingVisualResponseSchema, payload, endpoint) as {
          skill_id: string
          meta: Record<string, unknown>
          revalidation: Record<string, unknown>
          workflow: WorkflowResponse
        },
    )
}

export function postUpdateVisualBbox(
  skillId: string,
  stepIndex: number,
  body: { x: number; y: number; w: number; h: number },
): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  revalidation: Record<string, unknown>
  workflow: WorkflowResponse
}> {
  const endpoint = `/skills/${encodeURIComponent(skillId)}/steps/${stepIndex}/visual-bbox`
  return fetch(apiUrl(endpoint), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
    .then(json)
    .then(
      (payload) =>
        parseOrThrow(applyRecordingVisualResponseSchema, payload, endpoint) as {
          skill_id: string
          meta: Record<string, unknown>
          revalidation: Record<string, unknown>
          workflow: WorkflowResponse
        },
    )
}

export function patchStep(
  skillId: string,
  stepIndex: number,
  patch: Record<string, unknown>,
  assistLlm = false,
): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  revalidation: Record<string, unknown>
  workflow: WorkflowResponse
}> {
  const endpoint = `/skills/${encodeURIComponent(skillId)}/steps/${stepIndex}`
  return fetch(
    apiUrl(`/skills/${encodeURIComponent(skillId)}/steps/${stepIndex}`),
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ patch, assist_llm: assistLlm }),
    },
  )
    .then(json)
    .then(
      (payload) =>
        parseOrThrow(patchStepSchema, payload, endpoint) as {
          skill_id: string
          meta: Record<string, unknown>
          revalidation: Record<string, unknown>
          workflow: WorkflowResponse
        },
    )
}

export function patchSkillInputs(
  skillId: string,
  body: { inputs: Record<string, unknown>[]; title?: string | null },
): Promise<Record<string, unknown>> {
  return fetch(apiUrl(`/skills/${encodeURIComponent(skillId)}`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => json<Record<string, unknown>>(r))
}

export function postWorkflowReplaceLiterals(
  skillId: string,
  body: { find: string; replace_with: string },
): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  workflow: WorkflowResponse
}> {
  const endpoint = `/skills/${encodeURIComponent(skillId)}/workflow:replace-literals`
  return fetch(apiUrl(endpoint), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
    .then(json)
    .then(
      (payload) =>
        parseOrThrow(workflowMutationSchema, payload, endpoint) as {
          skill_id: string
          meta: Record<string, unknown>
          workflow: WorkflowResponse
        },
    )
}

export function renameSkill(skillId: string, title: string): Promise<Record<string, unknown>> {
  return fetch(apiUrl(`/skills/${encodeURIComponent(skillId)}`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  }).then((r) => json<Record<string, unknown>>(r))
}

export function postValidate(skillId: string): Promise<Record<string, unknown>> {
  return fetch(apiUrl(`/skills/${encodeURIComponent(skillId)}/validate`), {
    method: 'POST',
  }).then((r) => json<Record<string, unknown>>(r))
}

export function postReorder(skillId: string, newOrder: number[]): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  workflow: WorkflowResponse
}> {
  const endpoint = `/skills/${encodeURIComponent(skillId)}/steps:reorder`
  return fetch(apiUrl(endpoint), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_order: newOrder }),
  })
    .then(json)
    .then(
      (payload) =>
        parseOrThrow(workflowMutationSchema, payload, endpoint) as {
          skill_id: string
          meta: Record<string, unknown>
          workflow: WorkflowResponse
        },
    )
}

export function postInsertStep(
  skillId: string,
  body: { action_kind: string; insert_after?: number | null },
): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  workflow: WorkflowResponse
}> {
  const endpoint = `/skills/${encodeURIComponent(skillId)}/steps`
  return fetch(apiUrl(endpoint), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
    .then(json)
    .then(
      (payload) =>
        parseOrThrow(workflowMutationSchema, payload, endpoint) as {
          skill_id: string
          meta: Record<string, unknown>
          workflow: WorkflowResponse
        },
    )
}

export function deleteStep(skillId: string, stepIndex: number): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  workflow: WorkflowResponse
}> {
  const endpoint = `/skills/${encodeURIComponent(skillId)}/steps/${stepIndex}`
  return fetch(
    apiUrl(`/skills/${encodeURIComponent(skillId)}/steps/${stepIndex}`),
    { method: 'DELETE' },
  )
    .then(json)
    .then(
      (payload) =>
        parseOrThrow(workflowMutationSchema, payload, endpoint) as {
          skill_id: string
          meta: Record<string, unknown>
          workflow: WorkflowResponse
        },
    )
}

export function postCompileUpdated(
  skillId: string,
  skillTitle?: string,
): Promise<Record<string, unknown>> {
  return fetch(apiUrl(`/skills/${encodeURIComponent(skillId)}/compile-updated`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ skill_title: skillTitle ?? null }),
  }).then((r) => json<Record<string, unknown>>(r))
}

export function postStartRecording(): Promise<{ session_id: string }> {
  return fetch(apiUrl('/record'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  }).then((r) => json<{ session_id: string }>(r))
}

export function getRecordingStatus(sessionId: string): Promise<{
  session_id: string
  browser_open: boolean
  event_count: number
  ended_by_user: boolean
  binding_errors: string[]
}> {
  return fetch(apiUrl(`/record/${encodeURIComponent(sessionId)}/status`)).then((r) =>
    json<{
      session_id: string
      browser_open: boolean
      event_count: number
      ended_by_user: boolean
      binding_errors: string[]
    }>(r),
  )
}

export function postStopRecording(sessionId: string): Promise<{ session_id: string; status: string }> {
  return fetch(apiUrl(`/record/${encodeURIComponent(sessionId)}/stop`), {
    method: 'POST',
  }).then((r) => json<{ session_id: string; status: string }>(r))
}

export function postCompileSession(sessionId: string, skillTitle?: string): Promise<{
  skill_id: string
  version: number
  step_count: number
  audit_status: string
}> {
  return fetch(apiUrl('/compile'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, skill_title: skillTitle ?? '' }),
  }).then((r) =>
    json<{
      skill_id: string
      version: number
      step_count: number
      audit_status: string
    }>(r),
  )
}

export function fetchSkillDocument(skillId: string): Promise<Record<string, unknown>> {
  return fetch(apiUrl(`/skill/${encodeURIComponent(skillId)}`)).then((r) => json<Record<string, unknown>>(r))
}

export function fetchMetrics(): Promise<Record<string, unknown>> {
  return fetch(apiUrl('/metrics')).then((r) => json<Record<string, unknown>>(r))
}

export type SkillPackBuildPayload = {
  json_text: string
  package_name?: string
  bundle_name?: string
}

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled'

export type JobRecord = {
  job_id: string
  kind: string
  status: JobStatus
  resource_id?: string | null
  retry_count: number
  user_error?: string | null
  internal_error_code?: string | null
  result?: Record<string, unknown> | null
  created_at: number
  updated_at: number
}

export type EnqueuedJob = Pick<JobRecord, 'job_id' | 'status' | 'resource_id'>

const jobRecordSchema = z.object({
  job_id: z.string(),
  kind: z.string(),
  status: z.enum(['queued', 'running', 'succeeded', 'failed', 'canceled']),
  resource_id: z.string().nullable().optional(),
  retry_count: z.number(),
  user_error: z.string().nullable().optional(),
  internal_error_code: z.string().nullable().optional(),
  result: recordUnknown.nullable().optional(),
  created_at: z.number(),
  updated_at: z.number(),
})

const enqueuedJobSchema = z.object({
  job_id: z.string(),
  status: z.enum(['queued', 'running', 'succeeded', 'failed', 'canceled']),
  resource_id: z.string().nullable().optional(),
})

export function fetchJob(jobId: string): Promise<JobRecord> {
  const endpoint = `/jobs/${encodeURIComponent(jobId)}`
  return fetch(apiUrl(endpoint))
    .then(json)
    .then((payload) => parseOrThrow(jobRecordSchema, payload, endpoint) as JobRecord)
}

export function enqueueCompileJob(sessionId: string, skillTitle?: string): Promise<EnqueuedJob> {
  const endpoint = '/jobs/compile'
  return fetch(apiUrl(endpoint), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, skill_title: skillTitle ?? '' }),
  })
    .then(json)
    .then((payload) => parseOrThrow(enqueuedJobSchema, payload, endpoint) as EnqueuedJob)
}

export function enqueuePackageBuildJob(body: SkillPackBuildPayload): Promise<EnqueuedJob> {
  const endpoint = '/jobs/packages/build'
  return fetch(apiUrl(endpoint), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
    .then(json)
    .then((payload) => parseOrThrow(enqueuedJobSchema, payload, endpoint) as EnqueuedJob)
}

export function postBuildSkillPack(body: SkillPackBuildPayload): Promise<{
  name: string
  bundle_slug?: string
  index_json: string
  skill_md: string
  execution_json: string
  recovery_json: string
  inputs_json: string
  manifest_json: string
  input_count: number
  step_count: number
  used_llm: boolean
  warnings: string[]
  workflow_names?: string[]
  build_log?: SkillPackBuildLogEntry[]
}> {
  const endpoint = '/skill-pack/build'
  return fetch(apiUrl(endpoint), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
    .then(json)
    .then(
      (payload) =>
        parseOrThrow(skillPackBuildSchema, payload, endpoint) as {
          name: string
          bundle_slug?: string
          index_json: string
          skill_md: string
          execution_json: string
          recovery_json: string
          inputs_json: string
          manifest_json: string
          input_count: number
          step_count: number
          used_llm: boolean
          warnings: string[]
          workflow_names?: string[]
          build_log?: SkillPackBuildLogEntry[]
        },
    )
}

export type SkillPackBuildApiResult = {
  name: string
  bundle_slug?: string
  index_json: string
  skill_md: string
  execution_json: string
  recovery_json: string
  inputs_json: string
  manifest_json: string
  input_count: number
  step_count: number
  used_llm: boolean
  warnings: string[]
  workflow_names?: string[]
  build_log?: SkillPackBuildLogEntry[]
}

/** POST /skill-pack/build/stream — SSE ``data:`` JSON events: ``log``, ``done``, ``error``. */
export async function postBuildSkillPackStream(
  body: SkillPackBuildPayload,
  onLog?: (entry: SkillPackBuildLogEntry) => void,
): Promise<SkillPackBuildApiResult> {
  const endpoint = '/skill-pack/build/stream'
  const res = await fetch(apiUrl(endpoint), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const raw = (await res.text()).trim()
    let message: string | null = null
    try {
      const payload = JSON.parse(raw) as { detail?: unknown; message?: unknown }
      const detail = payload.detail ?? payload.message
      const enriched = skillPackFailFromDetail(detail)
      if (enriched) throw new SkillPackBuildRequestError(enriched.message, enriched.buildLog)
      if (typeof detail === 'string' && detail.trim()) message = detail.trim()
    } catch (err) {
      if (err instanceof SkillPackBuildRequestError) throw err
    }
    if (message) throw new Error(message)
    throw new Error(raw || res.statusText)
  }
  const reader = res.body?.getReader()
  if (!reader) {
    throw new Error('Streaming skill pack build is not supported in this browser (no response body).')
  }
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
    for (;;) {
      const sep = buffer.indexOf('\n\n')
      if (sep === -1) break
      const block = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const dataLines = block
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
      if (dataLines.length === 0) continue
      const dataPayload = dataLines.join('\n')
      let evt: unknown
      try {
        evt = JSON.parse(dataPayload) as unknown
      } catch {
        continue
      }
      if (!evt || typeof evt !== 'object' || !('event' in evt)) continue
      const row = evt as {
        event: string
        entry?: unknown
        result?: unknown
        message?: unknown
        build_log?: unknown
      }
      if (row.event === 'log' && row.entry && typeof row.entry === 'object' && onLog) {
        onLog(row.entry as SkillPackBuildLogEntry)
      }
      if (row.event === 'done' && row.result && typeof row.result === 'object') {
        return parseOrThrow(skillPackBuildSchema, row.result, endpoint) as SkillPackBuildApiResult
      }
      if (row.event === 'error') {
        const msg = typeof row.message === 'string' && row.message.trim() ? row.message.trim() : 'Skill pack build failed.'
        let bl: SkillPackBuildLogEntry[] = []
        if (Array.isArray(row.build_log)) {
          bl = row.build_log.filter((x): x is SkillPackBuildLogEntry => Boolean(x && typeof x === 'object'))
        }
        throw new SkillPackBuildRequestError(msg, bl)
      }
    }
    if (done) break
  }
  throw new Error('Skill pack stream ended before a completion event.')
}

/** POST /skill-pack/bundles/:bundle/append/stream — same SSE shape as build/stream. */
export async function postAppendSkillPackStream(
  bundleName: string,
  body: { json_text: string; package_name?: string },
  onLog?: (entry: SkillPackBuildLogEntry) => void,
): Promise<SkillPackBuildApiResult> {
  const endpoint = `/skill-pack/bundles/${encodeURIComponent(bundleName)}/append/stream`
  const res = await fetch(apiUrl(endpoint), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const raw = (await res.text()).trim()
    let message: string | null = null
    try {
      const payload = JSON.parse(raw) as { detail?: unknown; message?: unknown }
      const detail = payload.detail ?? payload.message
      const enriched = skillPackFailFromDetail(detail)
      if (enriched) throw new SkillPackBuildRequestError(enriched.message, enriched.buildLog)
      if (typeof detail === 'string' && detail.trim()) message = detail.trim()
    } catch (err) {
      if (err instanceof SkillPackBuildRequestError) throw err
    }
    if (message) throw new Error(message)
    throw new Error(raw || res.statusText)
  }
  const reader = res.body?.getReader()
  if (!reader) {
    throw new Error('Streaming skill pack append is not supported in this browser (no response body).')
  }
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
    for (;;) {
      const sep = buffer.indexOf('\n\n')
      if (sep === -1) break
      const block = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const dataLines = block
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
      if (dataLines.length === 0) continue
      const dataPayload = dataLines.join('\n')
      let evt: unknown
      try {
        evt = JSON.parse(dataPayload) as unknown
      } catch {
        continue
      }
      if (!evt || typeof evt !== 'object' || !('event' in evt)) continue
      const row = evt as {
        event: string
        entry?: unknown
        result?: unknown
        message?: unknown
        build_log?: unknown
      }
      if (row.event === 'log' && row.entry && typeof row.entry === 'object' && onLog) {
        onLog(row.entry as SkillPackBuildLogEntry)
      }
      if (row.event === 'done' && row.result && typeof row.result === 'object') {
        return parseOrThrow(skillPackBuildSchema, row.result, endpoint) as SkillPackBuildApiResult
      }
      if (row.event === 'error') {
        const msg = typeof row.message === 'string' && row.message.trim() ? row.message.trim() : 'Skill pack append failed.'
        let bl: SkillPackBuildLogEntry[] = []
        if (Array.isArray(row.build_log)) {
          bl = row.build_log.filter((x): x is SkillPackBuildLogEntry => Boolean(x && typeof x === 'object'))
        }
        throw new SkillPackBuildRequestError(msg, bl)
      }
    }
    if (done) break
  }
  throw new Error('Skill pack append stream ended before a completion event.')
}

export function postAppendSkillPack(
  bundleName: string,
  body: { json_text: string; package_name?: string },
): Promise<{
  name: string
  bundle_slug?: string
  index_json: string
  skill_md: string
  execution_json: string
  recovery_json: string
  inputs_json: string
  manifest_json: string
  input_count: number
  step_count: number
  used_llm: boolean
  warnings: string[]
  workflow_names?: string[]
  build_log?: SkillPackBuildLogEntry[]
}> {
  const endpoint = `/skill-pack/bundles/${encodeURIComponent(bundleName)}/append`
  return fetch(apiUrl(endpoint), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
    .then(json)
    .then(
      (payload) =>
        parseOrThrow(skillPackBuildSchema, payload, endpoint) as {
          name: string
          bundle_slug?: string
          index_json: string
          skill_md: string
          execution_json: string
          recovery_json: string
          inputs_json: string
          manifest_json: string
          input_count: number
          step_count: number
          used_llm: boolean
          warnings: string[]
          workflow_names?: string[]
          build_log?: SkillPackBuildLogEntry[]
        },
    )
}

export function fetchSkillPackageList(): Promise<{ packages: SkillPackageSummary[]; bundle_root: string }> {
  const endpoint = '/skill-pack/packages'
  return fetch(apiUrl(endpoint))
    .then((r) => json<{ packages: SkillPackageSummary[]; bundle_root?: string }>(r))
    .then((payload) => parseOrThrow(skillPackageListSchema, payload, endpoint))
}

export function fetchSkillPackageFiles(bundleName: string): Promise<SkillPackageFiles> {
  const endpoint = `/skill-pack/bundles/${encodeURIComponent(bundleName)}`
  return fetch(apiUrl(endpoint))
    .then((r) => json<SkillPackageFiles>(r))
    .then((payload) => parseOrThrow(skillPackageFilesSchema, payload, endpoint))
}

export function deleteStoredSkillPackage(bundleName: string): Promise<{ package_name: string; deleted: boolean }> {
  const endpoint = `/skill-pack/bundles/${encodeURIComponent(bundleName)}`
  return fetch(apiUrl(endpoint), { method: 'DELETE' })
    .then(json)
    .then((payload) => parseOrThrow(deleteSkillPackageRecordSchema, payload, endpoint))
}

export function renameStoredSkillPackage(
  bundleName: string,
  newName: string,
): Promise<{ package_name: string; previous_name: string }> {
  const endpoint = `/skill-pack/bundles/${encodeURIComponent(bundleName)}`
  return fetch(apiUrl(endpoint), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_name: newName }),
  })
    .then(json)
    .then((payload) => parseOrThrow(renameSkillPackageRecordSchema, payload, endpoint))
}

const patchBundleRootResponseSchema = z.object({
  bundle_root: z.string(),
})

export function patchSkillPackBundleRoot(bundleRoot: string): Promise<{ bundle_root: string }> {
  const endpoint = '/skill-pack/bundle-root'
  return fetch(apiUrl(endpoint), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bundle_root: bundleRoot }),
  })
    .then(json)
    .then((payload) => parseOrThrow(patchBundleRootResponseSchema, payload, endpoint))
}
