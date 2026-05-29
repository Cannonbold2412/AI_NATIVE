import { apiUrl } from '@/lib/apiBase'
import {
  postAppendSkillPack,
  postAppendSkillPackStream,
  postBuildSkillPack,
  postBuildSkillPackStream,
  type SkillPackBuildLogEntry,
} from '@/api/workflowApi'

const VARIABLE_PATTERN = /\{\{\s*([^{}]+?)\s*\}\}/g

export type SkillPackInput = {
  name: string
  type: 'string'
  description: string
  sensitive?: boolean
}

export type SkillPackBuildResult = {
  name: string
  bundleSlug: string
  workflowNames: string[]
  indexJson: string
  skillMd: string
  executionJson: string
  recoveryJson: string
  inputsJson: string
  manifestJson: string
  inputCount: number
  stepCount: number
  usedLlm: boolean
  warnings: string[]
  buildLog: SkillPackBuildLogEntry[]
}

export type { SkillPackBuildLogEntry }

const SKILL_PACK_BUILD_SECONDS = {
  min: 15,
  max: 300,
  base: 15,
  perStep: 2.5,
  perInput: 0.5,
} as const

function normalizeName(raw: string): string {
  const withSnakeCase = raw.replace(/([a-z0-9])([A-Z])/g, '$1_$2')
  const collapsed = withSnakeCase.replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase()
  if (!collapsed) return 'input_value'
  return /^\d/.test(collapsed) ? `input_${collapsed}` : collapsed
}

function humanizeName(name: string): string {
  return name.replace(/_/g, ' ').trim()
}

function isSensitiveName(name: string): boolean {
  return ['password', 'passcode', 'passwd', 'secret', 'token', 'api_key', 'apikey', 'private_key', 'credential', 'auth', 'otp', 'pin'].some(
    (part) => name.includes(part),
  )
}

function parseJsonSource(jsonText: string): unknown {
  const trimmed = jsonText.trim()
  if (!trimmed) {
    throw new Error('Paste a workflow JSON payload or upload a .json file first.')
  }
  try {
    return JSON.parse(trimmed) as unknown
  } catch {
    throw new Error('Invalid JSON. Fix the source payload before generating the package.')
  }
}

function extractExistingInputNames(payload: unknown): string[] {
  if (!payload || typeof payload !== 'object' || !('inputs' in payload)) return []
  const items = (payload as { inputs?: unknown }).inputs
  if (!Array.isArray(items)) return []
  const names: string[] = []
  for (const item of items) {
    if (typeof item === 'string' && item.trim()) {
      names.push(item)
      continue
    }
    if (!item || typeof item !== 'object') continue
    for (const key of ['name', 'id', 'key', 'label'] as const) {
      const value = (item as Record<string, unknown>)[key]
      if (typeof value === 'string' && value.trim()) {
        names.push(value)
        break
      }
    }
  }
  return names
}

function extractSteps(payload: unknown): Record<string, unknown>[] {
  if (Array.isArray(payload)) {
    return payload.filter((item): item is Record<string, unknown> => item != null && typeof item === 'object')
  }
  if (!payload || typeof payload !== 'object') return []
  const directSteps = (payload as { steps?: unknown }).steps
  if (Array.isArray(directSteps)) {
    return directSteps.filter((item): item is Record<string, unknown> => item != null && typeof item === 'object')
  }
  const container = ['skills', 'workflows', 'flows', 'scenarios', 'recordings']
    .map((key) => (payload as Record<string, unknown>)[key])
    .find(Array.isArray)
  if (!Array.isArray(container)) return []
  const out: Record<string, unknown>[] = []
  for (const skill of container) {
    if (!skill || typeof skill !== 'object') continue
    const steps = (skill as { steps?: unknown }).steps
    if (!Array.isArray(steps)) continue
    out.push(...steps.filter((item): item is Record<string, unknown> => item != null && typeof item === 'object'))
  }
  return out
}

export function estimateSkillPackBuildSeconds(jsonText: string): number {
  const payload = parseJsonSource(jsonText)
  const stepCount = extractSteps(payload).length
  const inputCount = extractInputs(JSON.stringify(payload)).length
  const rawEstimate = SKILL_PACK_BUILD_SECONDS.base + stepCount * SKILL_PACK_BUILD_SECONDS.perStep + inputCount * SKILL_PACK_BUILD_SECONDS.perInput
  return Math.max(SKILL_PACK_BUILD_SECONDS.min, Math.min(SKILL_PACK_BUILD_SECONDS.max, Math.round(rawEstimate)))
}

export function extractInputs(jsonText: string): SkillPackInput[] {
  const payload = parseJsonSource(jsonText)
  const seen = new Set<string>()
  const ordered: string[] = []
  const serialized = JSON.stringify(payload)

  for (const match of serialized.matchAll(VARIABLE_PATTERN)) {
    const name = normalizeName(match[1] ?? '')
    if (!seen.has(name)) {
      seen.add(name)
      ordered.push(name)
    }
  }

  for (const raw of extractExistingInputNames(payload)) {
    const name = normalizeName(raw)
    if (!seen.has(name)) {
      seen.add(name)
      ordered.push(name)
    }
  }

  return ordered.map((name) => ({
    name,
    type: 'string',
    description: `Enter ${humanizeName(name)}`,
    ...(isSensitiveName(name) ? { sensitive: true } : {}),
  }))
}

export const parseInputs = extractInputs

export function buildManifest(inputs: SkillPackInput[], packageName = 'generated_skill'): {
  name: string
  description: string
  version: string
  entry: {
    execution: string
    recovery: string
    inputs: string
  }
  execution_mode: 'deterministic'
  recovery_mode: 'tiered'
  vision_enabled: true
  llm_required: false
  inputs: Array<{ name: string; type: 'string'; sensitive?: boolean }>
} {
  return {
    name: packageName,
    description: `Run the ${packageName.replace(/_/g, ' ')} workflow.`,
    version: '1.0.0',
    entry: {
      execution: './execution.json',
      recovery: './recovery.json',
      inputs: './inputs.json',
    },
    execution_mode: 'deterministic',
    recovery_mode: 'tiered',
    vision_enabled: true,
    llm_required: false,
    inputs: inputs.map((input) => ({
      name: input.name,
      type: input.type,
      ...(input.sensitive ? { sensitive: true } : {}),
    })),
  }
}

export const generateManifest = buildManifest

function validateSource(payload: unknown): void {
  const steps = extractSteps(payload)
  if (steps.length === 0) {
    throw new Error('No workflow steps detected in JSON.')
  }
  const inputs = extractInputs(JSON.stringify(payload))
  if (steps.length === 0 && inputs.length === 0) {
    throw new Error('The workflow must contain at least one step or one input.')
  }
}

export async function generateSkillMD(jsonText: string): Promise<string> {
  const result = await buildSkillPackage(jsonText)
  return result.skillMd
}

export type BuildSkillPackageOptions = {
  /** When set, uses ``POST /skill-pack/build/stream`` and invokes this for each server log row as it is produced. */
  onLog?: (entry: SkillPackBuildLogEntry) => void
}

export type AppendWorkflowToSkillPackageOptions = {
  /** When set, uses ``POST /skill-pack/bundles/:slug/append/stream`` and invokes this for each server log row. */
  onLog?: (entry: SkillPackBuildLogEntry) => void
}

export async function buildSkillPackage(
  jsonText: string,
  packageName?: string,
  bundleName?: string,
  options?: BuildSkillPackageOptions,
): Promise<SkillPackBuildResult> {
  const payload = parseJsonSource(jsonText)
  validateSource(payload)
  const body = {
    json_text: JSON.stringify(payload),
    ...(packageName ? { package_name: packageName } : {}),
    ...(bundleName ? { bundle_name: bundleName } : {}),
  }
  const result = options?.onLog
    ? await postBuildSkillPackStream(body, options.onLog)
    : await postBuildSkillPack(body)
  return {
    name: result.name,
    bundleSlug: result.bundle_slug ?? bundleName ?? 'default',
    workflowNames: result.workflow_names ?? [result.name],
    indexJson: result.index_json,
    skillMd: result.skill_md,
    executionJson: result.execution_json,
    recoveryJson: result.recovery_json,
    inputsJson: result.inputs_json,
    manifestJson: result.manifest_json,
    inputCount: result.input_count,
    stepCount: result.step_count,
    usedLlm: result.used_llm,
    warnings: result.warnings,
    buildLog: result.build_log ?? [],
  }
}

export async function appendWorkflowToSkillPackage(
  bundleSlug: string,
  jsonText: string,
  appendedPackageName?: string,
  options?: AppendWorkflowToSkillPackageOptions,
): Promise<SkillPackBuildResult> {
  const payload = parseJsonSource(jsonText)
  validateSource(payload)
  const body = {
    json_text: JSON.stringify(payload),
    ...(appendedPackageName ? { package_name: appendedPackageName } : {}),
  }
  const result = options?.onLog
    ? await postAppendSkillPackStream(bundleSlug, body, options.onLog)
    : await postAppendSkillPack(bundleSlug, body)
  return {
    name: result.name,
    bundleSlug: result.bundle_slug ?? bundleSlug,
    workflowNames: result.workflow_names ?? [result.name],
    indexJson: result.index_json,
    skillMd: result.skill_md,
    executionJson: result.execution_json,
    recoveryJson: result.recovery_json,
    inputsJson: result.inputs_json,
    manifestJson: result.manifest_json,
    inputCount: result.input_count,
    stepCount: result.step_count,
    usedLlm: result.used_llm,
    warnings: result.warnings,
    buildLog: result.build_log ?? [],
  }
}

export function downloadTextAsset(filename: string, content: string, type = 'text/plain;charset=utf-8'): void {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export async function downloadSkillPackZip(result: SkillPackBuildResult): Promise<void> {
  const response = await fetch(apiUrl('/skill-pack/export'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: result.name,
      bundle_name: result.bundleSlug,
      skill_md: result.skillMd,
      execution_json: result.executionJson,
      recovery_json: result.recoveryJson,
      inputs_json: result.inputsJson,
      manifest_json: result.manifestJson,
    }),
  })
  if (!response.ok) {
    const raw = (await response.text()).trim()
    throw new Error(raw || 'Could not export skill package zip.')
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `skill_package_${result.name}.zip`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
