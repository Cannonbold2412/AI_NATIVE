import { apiUrl } from '@/lib/apiBase'
import { postBuildSkillPack } from '@/api/workflowApi'

const VARIABLE_PATTERN = /\{\{\s*([^{}]+?)\s*\}\}/g

export type SkillPackInput = {
  name: string
  type: 'string'
  description: string
  sensitive?: boolean
}

export type SkillPackBuildResult = {
  name: string
  skillMd: string
  skillJson: string
  inputJson: string
  manifestJson: string
  inputCount: number
  stepCount: number
  usedLlm: boolean
  warnings: string[]
}

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
  const skills = (payload as { skills?: unknown }).skills
  if (!Array.isArray(skills)) return []
  const out: Record<string, unknown>[] = []
  for (const skill of skills) {
    if (!skill || typeof skill !== 'object') continue
    const steps = (skill as { steps?: unknown }).steps
    if (!Array.isArray(steps)) continue
    out.push(...steps.filter((item): item is Record<string, unknown> => item != null && typeof item === 'object'))
  }
  return out
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
  version: string
  inputs: Array<{ name: string; type: 'string'; sensitive?: boolean }>
} {
  return {
    name: packageName,
    version: '1.0.0',
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

export async function buildSkillPackage(jsonText: string): Promise<SkillPackBuildResult> {
  const payload = parseJsonSource(jsonText)
  validateSource(payload)
  const result = await postBuildSkillPack({ json_text: JSON.stringify(payload) })
  return {
    name: result.name,
    skillMd: result.skill_md,
    skillJson: result.skill_json,
    inputJson: result.input_json,
    manifestJson: result.manifest_json,
    inputCount: result.input_count,
    stepCount: result.step_count,
    usedLlm: result.used_llm,
    warnings: result.warnings,
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
      skill_md: result.skillMd,
      skill_json: result.skillJson,
      input_json: result.inputJson,
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
  anchor.download = `${result.name}.zip`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
