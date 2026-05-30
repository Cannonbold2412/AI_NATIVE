import type { StepEditorDTO } from '../types/workflow'

/** Aligned with `app/editor/workflow_service.py` `_parameter_bindings_from_step` pattern. */
const PLACEHOLDER = /\{\{([a-zA-Z][a-zA-Z0-9_]*)\}\}/g

const ID_PATTERN = /^[a-zA-Z][a-zA-Z0-9_]*$/

function collectStringsFromValue(v: unknown, out: string[]): void {
  if (v == null) return
  if (typeof v === 'string') {
    out.push(v)
    return
  }
  if (Array.isArray(v)) {
    for (const x of v) collectStringsFromValue(x, out)
    return
  }
  if (typeof v === 'object') {
    for (const x of Object.values(v as object)) collectStringsFromValue(x, out)
  }
}

export function collectVariableIdsFromSteps(steps: StepEditorDTO[]): string[] {
  const set = new Set<string>()
  for (const step of steps) {
    for (const b of step.parameter_bindings ?? []) {
      const rec = b as { variable_id?: string }
      if (rec.variable_id) set.add(rec.variable_id)
    }
    const blob: string[] = []
    collectStringsFromValue(step, blob)
    for (const s of blob) {
      for (const m of s.matchAll(PLACEHOLDER)) {
        if (m[1]) set.add(m[1])
      }
    }
  }
  return [...set].sort((a, b) => a.localeCompare(b))
}

export function labelFromId(id: string): string {
  if (!id.trim()) return ''
  return id
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .split(' ')
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ')
}

export type InputVariableType = 'text' | 'select'

export type VariableFormRow = {
  key: string
  id: string
  label: string
  varType: InputVariableType
  optionsText: string
}

/** Accepts `db_name` or full `{{db_name}}` for bulk replace / placeholders. */
export function normalizeVariablePlaceholder(raw: string): { ok: true; value: string } | { ok: false; error: string } {
  const t = raw.trim()
  if (!t) {
    return { ok: false, error: 'Enter a variable id (e.g. db_name) or paste {{db_name}}.' }
  }
  const fullMatch = /^\{\{([a-zA-Z][a-zA-Z0-9_]*)\}\}$/.exec(t)
  if (fullMatch?.[1]) {
    return { ok: true, value: `{{${fullMatch[1]}}}` }
  }
  if (!ID_PATTERN.test(t)) {
    return {
      ok: false,
      error: 'Invalid id. Use letters, numbers, underscore; start with a letter (same as in {{id}}).',
    }
  }
  return { ok: true, value: `{{${t}}}` }
}

export function newEmptyRow(): VariableFormRow {
  return {
    key: `new-${globalThis.crypto?.randomUUID?.() ?? String(Date.now())}`,
    id: '',
    label: '',
    varType: 'text',
    optionsText: '',
  }
}

export function rowsFromServerInputs(inputs: Record<string, unknown>[]): VariableFormRow[] {
  return inputs.map((raw, i) => {
    const id = String(raw.id ?? '')
    return {
      key: `row-${i}`,
      id,
      label: String(raw.label ?? (id ? labelFromId(id) : '')),
      varType: raw.type === 'select' ? 'select' : 'text',
      optionsText: Array.isArray(raw.options) ? (raw.options as unknown[]).map((o) => String(o)).join(', ') : '',
    }
  })
}

export function rowsToServerPayload(
  rows: VariableFormRow[],
): { ok: true; data: Record<string, unknown>[] } | { ok: false; error: string } {
  const byId = new Set<string>()
  const data: Record<string, unknown>[] = []
  for (const row of rows) {
    const id = row.id.trim()
    if (!id) continue
    if (byId.has(id)) {
      return { ok: false, error: `Duplicate variable id: ${id}` }
    }
    if (!ID_PATTERN.test(id)) {
      return {
        ok: false,
        error: `Invalid id "${id}". Use letters, numbers, underscore; start with a letter (same as in {{id}}).`,
      }
    }
    byId.add(id)
    const rec: Record<string, unknown> = {
      id,
      label: row.label.trim() || labelFromId(id),
      type: row.varType,
      default: null,
    }
    if (row.varType === 'select') {
      const options = row.optionsText
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      rec.options = options
    } else {
      rec.options = []
    }
    data.push(rec)
  }
  return { ok: true, data }
}

export function missingSpottedIds(spotted: string[], rows: VariableFormRow[]): string[] {
  const have = new Set(rows.map((r) => r.id.trim()).filter(Boolean))
  return spotted.filter((id) => !have.has(id))
}

export function addSpottedToRows(
  rows: VariableFormRow[],
  ids: string[],
): VariableFormRow[] {
  if (ids.length === 0) return rows
  const additions = ids.map((id) => ({
    key: `spot-${id}-${globalThis.crypto?.randomUUID?.() ?? id}`,
    id,
    label: labelFromId(id),
    varType: 'text' as const,
    optionsText: '',
  }))
  return [...rows, ...additions]
}
