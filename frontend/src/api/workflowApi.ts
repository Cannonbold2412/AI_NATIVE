import type { WorkflowResponse } from '../types/workflow'
import { apiUrl } from '@/lib/apiBase'
import { z } from 'zod'

const json = (r: Response) => {
  if (!r.ok) {
    return r.text().then((t) => {
      throw new Error(t || r.statusText)
    })
  }
  return r.json()
}

const recordUnknown = z.record(z.string(), z.unknown())
const recordNumber = z.record(z.string(), z.number())

const stepFlagsSchema = z.object({
  is_destructive: z.boolean(),
  is_scroll: z.boolean(),
  generic_intent: z.boolean(),
})

const stepScreenshotSchema = z.object({
  full_url: z.string().nullable(),
  element_url: z.string().nullable(),
  scroll_url: z.string().nullable(),
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
  input_binding: z.string().nullable(),
  screenshot: stepScreenshotSchema,
  editable_fields: z.record(z.string(), z.boolean()),
  flags: stepFlagsSchema,
  parameter_bindings: z.array(recordUnknown),
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

export type SkillSummary = {
  skill_id: string
  title: string
  version: number
  step_count: number
  modified_at: number
}

export function fetchSkillList(): Promise<{ skills: SkillSummary[] }> {
  return fetch(apiUrl('/skills'))
    .then(json)
    .then((payload) => parseOrThrow(skillListSchema, payload, '/skills'))
}

export function fetchWorkflow(skillId: string): Promise<WorkflowResponse> {
  const endpoint = `/skills/${encodeURIComponent(skillId)}/workflow`
  return fetch(apiUrl(endpoint))
    .then(json)
    .then((payload) => parseOrThrow(workflowSchema, payload, endpoint))
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
    .then((payload) => parseOrThrow(patchStepSchema, payload, endpoint))
}

export function patchSkillInputs(
  skillId: string,
  body: { inputs: Record<string, unknown>[]; title?: string | null },
): Promise<Record<string, unknown>> {
  return fetch(apiUrl(`/skills/${encodeURIComponent(skillId)}`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(json)
}

export function postValidate(skillId: string): Promise<Record<string, unknown>> {
  return fetch(apiUrl(`/skills/${encodeURIComponent(skillId)}/validate`), {
    method: 'POST',
  }).then(json)
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
    .then((payload) => parseOrThrow(workflowMutationSchema, payload, endpoint))
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
    .then((payload) => parseOrThrow(workflowMutationSchema, payload, endpoint))
}

export function postCompileUpdated(
  skillId: string,
  skillTitle?: string,
): Promise<Record<string, unknown>> {
  return fetch(apiUrl(`/skills/${encodeURIComponent(skillId)}/compile-updated`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ skill_title: skillTitle ?? null }),
  }).then(json)
}

export function postStartRecording(startUrl: string): Promise<{ session_id: string; start_url: string }> {
  return fetch(apiUrl('/record'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ start_url: startUrl }),
  }).then(json)
}

export function getRecordingStatus(sessionId: string): Promise<{
  session_id: string
  browser_open: boolean
  event_count: number
  ended_by_user: boolean
  binding_errors: string[]
}> {
  return fetch(apiUrl(`/record/${encodeURIComponent(sessionId)}/status`)).then(json)
}

export function postStopRecording(sessionId: string): Promise<{ session_id: string; status: string }> {
  return fetch(apiUrl(`/record/${encodeURIComponent(sessionId)}/stop`), {
    method: 'POST',
  }).then(json)
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
  }).then(json)
}

export function fetchSkillDocument(skillId: string): Promise<Record<string, unknown>> {
  return fetch(apiUrl(`/skill/${encodeURIComponent(skillId)}`)).then(json)
}

export function fetchMetrics(): Promise<Record<string, unknown>> {
  return fetch(apiUrl('/metrics')).then(json)
}
