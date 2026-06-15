import { cmd } from '@/lib/ipc'
import type { BackendEvent } from '@/lib/ipc'
import type { WorkflowResponse } from '../types/workflow'

export { RECORDING_SCREENSHOT_DRAG_MIME, RECORDING_DRAG_MODE_CLEAR_VISUAL } from '@/lib/dragConstants'

export type SkillPackBuildLogEntry = Record<string, unknown>

export class SkillPackBuildRequestError extends Error {
  readonly buildLog: SkillPackBuildLogEntry[]

  constructor(message: string, buildLog: SkillPackBuildLogEntry[]) {
    super(message)
    this.name = 'SkillPackBuildRequestError'
    this.buildLog = buildLog
    Object.setPrototypeOf(this, new.target.prototype)
  }
}

export const errorMessage = (err: unknown, fallback: string) => {
  if (err instanceof Error) {
    const msg = err.message.trim()
    if (msg) return msg
  }
  if (typeof err === 'string' && err.trim()) return err.trim()
  return fallback
}

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
  package_name: string
  package_folder?: string
  package_path?: string
  modified_at: number
  workflows: SkillPackageWorkflowSummary[]
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
  frame: Record<string, unknown>
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

export type JobEvent = {
  ts: number
  event: string
  message: string
  data: Record<string, unknown>
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

// ─────────────────────────────────────────────────
// Skills
// ─────────────────────────────────────────────────

export function fetchSkillList(): Promise<{ skills: SkillSummary[] }> {
  return cmd<{ skills: SkillSummary[] }>('list_skills')
}

export function deleteSkillPackage(skillId: string): Promise<{ skill_id: string; title: string; deleted: boolean }> {
  return cmd<{ skill_id: string; title: string; deleted: boolean }>('delete_skill', { skill_id: skillId })
}

export function fetchWorkflow(skillId: string): Promise<WorkflowResponse> {
  return cmd<WorkflowResponse>('get_workflow', { skill_id: skillId })
}

export function fetchRecordingScreenshots(skillId: string): Promise<{
  skill_id: string
  session_id: string | null
  items: RecordingScreenshotItemDTO[]
}> {
  return cmd('list_recording_screenshots', { skill_id: skillId })
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
  can_undo?: boolean
  can_redo?: boolean
}> {
  return cmd('apply_recording_visual', { skill_id: skillId, step_index: stepIndex, ...body })
}

export function postApplyStepFrame(
  skillId: string,
  stepIndex: number,
  frameLabel: string,
): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  revalidation: Record<string, unknown>
  workflow: WorkflowResponse
  can_undo?: boolean
  can_redo?: boolean
}> {
  return cmd('apply_step_frame', { skill_id: skillId, step_index: stepIndex, frame_label: frameLabel })
}

export function postClearStepVisual(
  skillId: string,
  stepIndex: number,
): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  revalidation: Record<string, unknown>
  workflow: WorkflowResponse
  can_undo?: boolean
  can_redo?: boolean
}> {
  return cmd('clear_step_visual', { skill_id: skillId, step_index: stepIndex })
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
  can_undo?: boolean
  can_redo?: boolean
}> {
  return cmd('update_visual_bbox', { skill_id: skillId, step_index: stepIndex, ...body })
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
  can_undo?: boolean
  can_redo?: boolean
}> {
  return cmd('patch_step', { skill_id: skillId, step_index: stepIndex, patch, assist_llm: assistLlm })
}

export function patchSkillInputs(
  skillId: string,
  body: { inputs: Record<string, unknown>[]; title?: string | null },
): Promise<Record<string, unknown>> {
  return cmd<Record<string, unknown>>('update_workflow_inputs', { skill_id: skillId, ...body })
}

export function postWorkflowReplaceLiterals(
  skillId: string,
  body: { find: string; replace_with: string },
): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  workflow: WorkflowResponse
}> {
  return cmd('replace_literals', { skill_id: skillId, ...body })
}

export function renameSkill(skillId: string, title: string): Promise<Record<string, unknown>> {
  return cmd<Record<string, unknown>>('rename_skill', { skill_id: skillId, title })
}

export function postValidate(skillId: string): Promise<Record<string, unknown>> {
  return cmd<Record<string, unknown>>('validate_workflow', { skill_id: skillId })
}

export function postReorder(skillId: string, newOrder: number[]): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  workflow: WorkflowResponse
  can_undo?: boolean
  can_redo?: boolean
}> {
  return cmd('reorder_steps', { skill_id: skillId, new_order: newOrder })
}

export function postInsertStep(
  skillId: string,
  body: { action_kind: string; insert_after?: number | null },
): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  workflow: WorkflowResponse
  can_undo?: boolean
  can_redo?: boolean
}> {
  return cmd('insert_step', { skill_id: skillId, ...body })
}

export function deleteStep(skillId: string, stepIndex: number): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  workflow: WorkflowResponse
  can_undo?: boolean
  can_redo?: boolean
}> {
  return cmd('delete_step', { skill_id: skillId, step_index: stepIndex })
}

export function undoWorkflow(skillId: string): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  revalidation: Record<string, unknown>
  workflow: WorkflowResponse
  can_undo: boolean
  can_redo: boolean
}> {
  return cmd('undo_workflow', { skill_id: skillId })
}

export function redoWorkflow(skillId: string): Promise<{
  skill_id: string
  meta: Record<string, unknown>
  revalidation: Record<string, unknown>
  workflow: WorkflowResponse
  can_undo: boolean
  can_redo: boolean
}> {
  return cmd('redo_workflow', { skill_id: skillId })
}

export function postCompileUpdated(
  skillId: string,
  skillTitle?: string,
): Promise<Record<string, unknown>> {
  return cmd<Record<string, unknown>>('compile_updated', { skill_id: skillId, skill_title: skillTitle ?? null })
}

export function postSignOff(skillId: string): Promise<{ skill_id: string; signed_off: boolean }> {
  return cmd<{ skill_id: string; signed_off: boolean }>('sign_off_workflow', { skill_id: skillId })
}

export function postStartRecording(body: { capture_hover?: boolean } = {}): Promise<{ session_id: string }> {
  return cmd<{ session_id: string }>('start_recording', body)
}

export function getRecordingStatus(sessionId: string): Promise<{
  session_id: string
  browser_open: boolean
  event_count: number
  ended_by_user: boolean
  binding_errors: string[]
  capture_hover?: boolean
}> {
  return cmd('get_recording_status', { session_id: sessionId })
}

export function postStopRecording(sessionId: string): Promise<{ session_id: string; status: string }> {
  return cmd<{ session_id: string; status: string }>('stop_recording', { session_id: sessionId })
}

export function postCompileSession(sessionId: string, skillTitle?: string): Promise<{
  skill_id: string
  version: number
  step_count: number
  audit_status: string
}> {
  return cmd('compile', { session_id: sessionId, skill_title: skillTitle ?? '' })
}

export function fetchSkillDocument(skillId: string): Promise<Record<string, unknown>> {
  return cmd<Record<string, unknown>>('get_skill_document', { skill_id: skillId })
}

export function fetchMetrics(): Promise<Record<string, unknown>> {
  return cmd<Record<string, unknown>>('get_metrics')
}

// ─────────────────────────────────────────────────
// Skill packages
// ─────────────────────────────────────────────────

export function fetchSkillPackageList(): Promise<{ packages: SkillPackageSummary[]; bundle_root: string }> {
  return cmd('list_skill_packages')
}

export function fetchSkillPackageFiles(bundleName: string): Promise<SkillPackageFiles> {
  return cmd<SkillPackageFiles>('list_skill_package_files', { package_name: bundleName })
}

export function deleteStoredSkillPackage(bundleName: string): Promise<{ package_name: string; deleted: boolean }> {
  return cmd<{ package_name: string; deleted: boolean }>('delete_skill_package', { package_name: bundleName })
}

export function renameStoredSkillPackage(
  bundleName: string,
  newName: string,
): Promise<{ package_name: string; previous_name: string }> {
  return cmd<{ package_name: string; previous_name: string }>('rename_skill_package', {
    package_name: bundleName,
    new_name: newName,
  })
}

export async function postBuildSkillPack(body: SkillPackBuildPayload): Promise<SkillPackBuildApiResult> {
  return cmd<SkillPackBuildApiResult>('build_skill_pack', body)
}

export async function postBuildSkillPackStream(
  body: SkillPackBuildPayload,
  onLog?: (entry: SkillPackBuildLogEntry) => void,
): Promise<SkillPackBuildApiResult> {
  return new Promise<SkillPackBuildApiResult>((resolve, reject) => {
    const unsub = window.conxa.onEvent((ev: BackendEvent) => {
      if (ev.phase === 'pack_log' && onLog) onLog(ev.entry as SkillPackBuildLogEntry)
      if (ev.phase === 'pack_done') {
        unsub()
        resolve(ev.result as SkillPackBuildApiResult)
      }
      if (ev.phase === 'pack_error') {
        unsub()
        const bl = Array.isArray(ev.build_log) ? (ev.build_log as SkillPackBuildLogEntry[]) : []
        reject(new SkillPackBuildRequestError(String(ev.message ?? 'Skill pack build failed'), bl))
      }
    })
    cmd('build_skill_pack_stream', body).catch((err) => {
      unsub()
      reject(err)
    })
  })
}

export async function postAppendSkillPackStream(
  bundleName: string,
  body: { json_text: string; package_name?: string },
  onLog?: (entry: SkillPackBuildLogEntry) => void,
): Promise<SkillPackBuildApiResult> {
  return new Promise<SkillPackBuildApiResult>((resolve, reject) => {
    const unsub = window.conxa.onEvent((ev: BackendEvent) => {
      if (ev.phase === 'pack_log' && onLog) onLog(ev.entry as SkillPackBuildLogEntry)
      if (ev.phase === 'pack_done') {
        unsub()
        resolve(ev.result as SkillPackBuildApiResult)
      }
      if (ev.phase === 'pack_error') {
        unsub()
        const bl = Array.isArray(ev.build_log) ? (ev.build_log as SkillPackBuildLogEntry[]) : []
        reject(new SkillPackBuildRequestError(String(ev.message ?? 'Skill pack append failed'), bl))
      }
    })
    cmd('append_skill_pack_stream', { bundle_name: bundleName, ...body }).catch((err) => {
      unsub()
      reject(err)
    })
  })
}

export function postAppendSkillPack(
  bundleName: string,
  body: { json_text: string; package_name?: string },
): Promise<SkillPackBuildApiResult> {
  return cmd<SkillPackBuildApiResult>('append_skill_pack', { bundle_name: bundleName, ...body })
}

export function patchSkillPackBundleRoot(bundleRoot: string): Promise<{ bundle_root: string }> {
  return cmd<{ bundle_root: string }>('set_skill_pack_bundle_root', { bundle_root: bundleRoot })
}

// ─────────────────────────────────────────────────
// Cloud job queue stubs (not available in Studio)
// ─────────────────────────────────────────────────

export function fetchJob(_jobId: string): Promise<JobRecord> {
  return Promise.reject(new Error('Job queue not available in Build Studio'))
}

export function streamJobEvents(
  _jobId: string,
  _onEvent: (event: JobEvent) => void,
  _signal?: AbortSignal,
): Promise<void> {
  return Promise.reject(new Error('Job queue not available in Build Studio'))
}

export function enqueueCompileJob(_sessionId: string, _skillTitle?: string): Promise<EnqueuedJob> {
  return Promise.reject(new Error('Job queue not available in Build Studio'))
}

export function enqueueRecompileSkillJob(_skillId: string, _skillTitle?: string): Promise<EnqueuedJob> {
  return Promise.reject(new Error('Job queue not available in Build Studio'))
}

export function enqueuePackageBuildJob(_body: SkillPackBuildPayload): Promise<EnqueuedJob> {
  return Promise.reject(new Error('Job queue not available in Build Studio'))
}
