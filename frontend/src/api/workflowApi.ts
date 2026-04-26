import type { WorkflowResponse } from '../types/workflow'
import { apiUrl } from '@/lib/apiBase'

const json = (r: Response) => {
  if (!r.ok) {
    return r.text().then((t) => {
      throw new Error(t || r.statusText)
    })
  }
  return r.json()
}

export type SkillSummary = {
  skill_id: string
  title: string
  version: number
  step_count: number
  modified_at: number
}

export function fetchSkillList(): Promise<{ skills: SkillSummary[] }> {
  return fetch(apiUrl('/skills')).then(json)
}

export function fetchWorkflow(skillId: string): Promise<WorkflowResponse> {
  return fetch(apiUrl(`/skills/${encodeURIComponent(skillId)}/workflow`)).then(json)
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
  return fetch(
    apiUrl(`/skills/${encodeURIComponent(skillId)}/steps/${stepIndex}`),
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ patch, assist_llm: assistLlm }),
    },
  ).then(json)
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
  return fetch(apiUrl(`/skills/${encodeURIComponent(skillId)}/steps:reorder`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_order: newOrder }),
  }).then(json)
}

export function deleteStep(skillId: string, stepIndex: number): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  workflow: WorkflowResponse
}> {
  return fetch(
    apiUrl(`/skills/${encodeURIComponent(skillId)}/steps/${stepIndex}`),
    { method: 'DELETE' },
  ).then(json)
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
