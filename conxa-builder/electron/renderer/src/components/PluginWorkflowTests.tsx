
import { type RefObject, useEffect, useRef, useState } from 'react'
import { fetchWorkflow } from '@/api/workflowApi'
import {
  getCompiledSkill,
  testWorkflow,
  type Plugin,
  type PluginWorkflow,
} from '@/api/pluginApi'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { CheckCircle2, Loader2, PlayCircle, SlidersHorizontal, XCircle } from 'lucide-react'

type InputSpec = {
  id: string
  label?: string
  type?: string
  default?: string | null
  pattern?: string | null
  options?: string[]
  sensitive?: boolean
  required?: boolean
}

const TEMPLATE_INPUT_RE = /\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

function normalizeInputSpec(raw: unknown): InputSpec | null {
  if (typeof raw === 'string') {
    const id = raw.trim()
    return id ? { id, label: id.replace(/_/g, ' ') } : null
  }

  const rec = asRecord(raw)
  if (!rec) return null

  const id = String(rec.id ?? rec.name ?? '').trim()
  if (!id) return null

  const labelRaw = rec.label ?? rec.description
  const label = typeof labelRaw === 'string' && labelRaw.trim() ? labelRaw.trim() : id.replace(/_/g, ' ')
  const rawOptions = Array.isArray(rec.options) ? rec.options : Array.isArray(rec.enum) ? rec.enum : []
  const options = rawOptions.map((item) => String(item)).filter(Boolean)
  const defaultValue = rec.default == null ? null : String(rec.default)
  const type = typeof rec.type === 'string' && rec.type.trim() ? rec.type.trim() : options.length > 0 ? 'select' : 'text'

  return {
    id,
    label,
    type,
    default: defaultValue,
    pattern: typeof rec.pattern === 'string' ? rec.pattern : null,
    options,
    sensitive: rec.sensitive === true,
    required: rec.required !== false,
  }
}

function inputSpecsFromPayload(payload: unknown): InputSpec[] {
  const rec = asRecord(payload)
  const rawItems = Array.isArray(payload)
    ? payload
    : Array.isArray(rec?.inputs)
      ? rec.inputs
      : Array.isArray(rec?.required)
        ? rec.required
        : []
  return rawItems.map(normalizeInputSpec).filter((item): item is InputSpec => item !== null)
}

function inferInputSpecsFromTemplates(...payloads: unknown[]): InputSpec[] {
  const seen = new Set<string>()
  const specs: InputSpec[] = []

  for (const payload of payloads) {
    if (payload == null) continue
    const text = typeof payload === 'string' ? payload : JSON.stringify(payload)
    for (const match of text.matchAll(TEMPLATE_INPUT_RE)) {
      const id = match[1]?.trim()
      if (!id || seen.has(id)) continue
      seen.add(id)
      specs.push({ id, label: id.replace(/_/g, ' '), type: 'text', required: true })
    }
  }

  return specs
}

function missingRequiredInputLabels(specs: InputSpec[], values: Record<string, string>) {
  return specs
    .filter((spec) => spec.required !== false && !String(values[spec.id] ?? '').trim())
    .map((spec) => spec.label || spec.id)
}

function WorkflowLogSection({
  logs,
  runDone,
  runError,
  logRef,
  onRetry,
}: {
  logs: string[]
  runDone: boolean
  runError: string
  logRef: RefObject<HTMLDivElement>
  onRetry?: () => void
}) {
  return (
    <div className="border-t border-white/8 px-3 pb-3 pt-2 space-y-3">
      {logs.length > 0 && (
        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            Execution log
          </p>
          <div
            ref={logRef}
            className="max-h-48 overflow-y-auto rounded border border-white/8 bg-black/40 p-2 font-mono text-[10px] text-zinc-300 space-y-px"
          >
            {logs.map((line, i) => (
              <div key={i} className="flex gap-1.5">
                <span className="shrink-0 text-zinc-600">›</span>
                <span>{line}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {runDone && (
        <div className="flex items-center gap-2 text-xs text-emerald-300">
          <CheckCircle2 className="size-3.5 shrink-0" />
          Test passed
        </div>
      )}
      {runError && (
        <div className="space-y-2">
          <div className="flex items-start gap-2 text-xs text-red-300">
            <XCircle className="mt-0.5 size-3.5 shrink-0" />
            <span className="whitespace-pre-line">{runError}</span>
          </div>
          {onRetry && (
            <Button size="sm" variant="outline" onClick={onRetry} className="border-white/10 bg-white/5 text-zinc-200 hover:bg-white/10">
              <PlayCircle className="size-3.5" />
              Try again
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

function testStatusBadge(wf: PluginWorkflow) {
  if (wf.last_test_status === 'passed') {
    return (
      <Badge variant="outline" className="shrink-0 border-emerald-500/30 bg-emerald-500/10 text-[10px] text-emerald-300">
        Passed
      </Badge>
    )
  }
  if (wf.last_test_status === 'failed') {
    return (
      <Badge variant="outline" className="shrink-0 border-red-500/30 bg-red-500/10 text-[10px] text-red-300">
        Failed
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="shrink-0 border-zinc-500/30 bg-zinc-500/10 text-[10px] text-zinc-400">
      Never tested
    </Badge>
  )
}

function isStaleTest(wf: PluginWorkflow, plugin: Plugin) {
  return (
    wf.edited_at != null &&
    plugin.build != null &&
    wf.edited_at > plugin.build.last_built_at
  )
}

export function workflowTestSummary(plugin: Plugin) {
  const passed = plugin.workflows.filter((w) => w.last_test_status === 'passed').length
  const total = plugin.workflows.length
  return {
    passed,
    total,
    allPassed: total > 0 && passed === total,
  }
}

export function WorkflowTestRow({
  plugin,
  wf,
  onComplete,
}: {
  plugin: Plugin
  wf: PluginWorkflow
  onComplete: () => void
}) {
  const [inputs, setInputs] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(wf.last_test_inputs ?? {}).map(([k, v]) => [k, String(v ?? '')]),
    ),
  )
  const [inputSpecs, setInputSpecs] = useState<InputSpec[] | null>(null)
  const [inputDialogOpen, setInputDialogOpen] = useState(false)
  const [inputDialogMode, setInputDialogMode] = useState<'edit' | 'run'>('run')
  const [inputError, setInputError] = useState('')
  const [running, setRunning] = useState(false)
  const [logs, setLogs] = useState<string[]>([])
  const [runError, setRunError] = useState('')
  const [runDone, setRunDone] = useState(false)
  const logRef = useRef<HTMLDivElement>(null)

  const stale = isStaleTest(wf, plugin)

  // Load input specs eagerly so we know which button layout to use.
  useEffect(() => {
    let alive = true
    const savedInputs = Object.fromEntries(
      Object.entries(wf.last_test_inputs ?? {}).map(([k, v]) => [k, String(v ?? '')]),
    )

    setInputSpecs(null)
    setInputs(savedInputs)

    async function loadInputSpecs() {
      let specs: InputSpec[] = []

      try {
        const compiled = await getCompiledSkill(plugin.id, wf.slug)
        specs = inputSpecsFromPayload(compiled.files['input.json'])
        if (specs.length === 0) {
          specs = inputSpecsFromPayload(compiled.files['inputs.json'])
        }
        if (specs.length === 0) {
          specs = inferInputSpecsFromTemplates(compiled.files['execution.json'], compiled.files['recovery.json'])
        }
      } catch {
        specs = []
      }

      if (specs.length === 0 && wf.skill_id) {
        try {
          const wfData = await fetchWorkflow(wf.skill_id)
          specs = inputSpecsFromPayload(wfData.inputs ?? [])
        } catch {
          specs = []
        }
      }

      if (!alive) return
      setInputSpecs(specs)
      setInputs((prev) => {
        const next = { ...prev }
        for (const spec of specs) {
          if (!(spec.id in next)) next[spec.id] = spec.default ?? ''
        }
        return next
      })
    }

    void loadInputSpecs()

    return () => {
      alive = false
    }
  }, [plugin.id, wf.id, wf.skill_id, wf.slug, wf.last_test_inputs])

  async function runTest() {
    setLogs([])
    setRunError('')
    setRunDone(false)
    setInputError('')
    if (inputSpecs === null) {
      setRunError('Inputs are still loading. Try again in a moment.')
      return
    }
    const missingInputs = missingRequiredInputLabels(inputSpecs, inputs)
    if (missingInputs.length > 0) {
      const message = `Enter required inputs before running: ${missingInputs.join(', ')}`
      setInputError(message)
      setRunError(message)
      setInputDialogMode('run')
      setInputDialogOpen(true)
      return
    }
    setRunning(true)
    setInputDialogOpen(false)
    try {
      const parsedInputs: Record<string, unknown> = {}
      if (inputSpecs.length > 0) {
        for (const spec of inputSpecs) parsedInputs[spec.id] = inputs[spec.id] ?? ''
      } else {
        for (const [k, v] of Object.entries(inputs)) parsedInputs[k] = v
      }
      await testWorkflow(plugin.id, wf.id, parsedInputs, false, (msg) => {
        setLogs((prev) => [...prev, msg])
        setTimeout(() => logRef.current?.scrollTo(0, logRef.current.scrollHeight), 0)
      })
      setRunDone(true)
      onComplete()
    } catch (err) {
      setRunError(err instanceof Error ? err.message : 'Test failed')
      onComplete()
    } finally {
      setRunning(false)
    }
  }

  function openInputDialog(mode: 'edit' | 'run') {
    setInputError('')
    setInputDialogMode(mode)
    setInputDialogOpen(true)
  }

  function saveInputs() {
    setInputError('')
    setInputDialogOpen(false)
  }

  const canRun = !stale && !running && Boolean(wf.skill_id)

  return (
    <div className="rounded-lg border border-white/8 bg-white/[0.02]">
      {/* Header row */}
      <div className="flex items-center justify-between gap-3 px-3 py-2.5">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-white">{wf.name}</p>
          {stale && (
            <p className="mt-0.5 text-xs text-amber-400">Edited since last build — rebuild before testing</p>
          )}
          {wf.last_test_status === 'failed' && wf.last_test_error && !runError && logs.length === 0 && (
            <p className="mt-0.5 truncate text-xs text-red-300">{wf.last_test_error}</p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {testStatusBadge(wf)}

          {/* No-inputs workflows: single "Run test" button runs directly */}
          {inputSpecs !== null && inputSpecs.length === 0 && (
            <Button
              size="sm"
              onClick={() => void runTest()}
              disabled={!canRun}
              title={stale ? 'Rebuild the plugin first' : undefined}
            >
              {running ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <PlayCircle className="size-3.5" />
              )}
              {running ? 'Testing...' : runDone ? 'Re-run' : 'Run test'}
            </Button>
          )}

          {/* Input workflows: edit values separately, then run through the same input dialog. */}
          {inputSpecs !== null && inputSpecs.length > 0 && (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={() => openInputDialog('edit')}
                disabled={stale || !wf.skill_id}
                title={stale ? 'Rebuild the plugin first' : undefined}
              >
                <SlidersHorizontal className="size-3.5" />
                Inputs
              </Button>
              <Button
                size="sm"
                onClick={() => openInputDialog('run')}
                disabled={!canRun}
                title={stale ? 'Rebuild the plugin first' : undefined}
              >
                {running ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <PlayCircle className="size-3.5" />
                )}
                {running ? 'Testing...' : runDone ? 'Re-run' : 'Run test'}
              </Button>
            </>
          )}

          {/* Loading state */}
          {inputSpecs === null && (
            <Button size="sm" variant="outline" disabled>
              <Loader2 className="size-3.5 animate-spin" />
              Loading...
            </Button>
          )}
        </div>
      </div>

      <Dialog open={inputDialogOpen} onOpenChange={setInputDialogOpen}>
        <DialogContent className="border-white/10 bg-[#0d0f12] text-zinc-100 sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-white">Workflow inputs</DialogTitle>
            <DialogDescription className="text-zinc-400">
              {inputDialogMode === 'run'
                ? 'Enter the required values, then run this workflow test.'
                : 'Edit the values that will be used the next time this workflow test runs.'}
            </DialogDescription>
          </DialogHeader>
          {inputSpecs !== null && inputSpecs.length > 0 && (
            <form
              id={`workflow-inputs-${wf.id}`}
              onSubmit={(e) => {
                e.preventDefault()
                if (inputDialogMode === 'run') {
                  void runTest()
                } else {
                  saveInputs()
                }
              }}
              className="space-y-3"
            >
              <div className="grid max-h-[50vh] gap-3 overflow-y-auto pr-1">
                {inputSpecs.map((spec) => {
                  const displayLabel = spec.label || spec.id
                  return (
                    <div key={spec.id} className="grid gap-1">
                      <Label className="text-xs font-medium text-zinc-300">{displayLabel}</Label>
                      {spec.options && spec.options.length > 0 ? (
                        <select
                          value={inputs[spec.id] ?? ''}
                          onChange={(e) => setInputs((prev) => ({ ...prev, [spec.id]: e.target.value }))}
                          required={spec.required !== false}
                          className="h-8 rounded-md border border-white/10 bg-black/30 px-2 text-xs text-white outline-none focus:border-white/25"
                        >
                          <option value="">Select {displayLabel.toLowerCase()}</option>
                          {spec.options.map((option) => (
                            <option key={option} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <Input
                          type={spec.sensitive ? 'password' : 'text'}
                          value={inputs[spec.id] ?? ''}
                          onChange={(e) => setInputs((prev) => ({ ...prev, [spec.id]: e.target.value }))}
                          placeholder={displayLabel ? `Enter ${displayLabel.toLowerCase()}...` : ''}
                          required={spec.required !== false}
                          pattern={spec.pattern ?? undefined}
                          className="h-8 text-xs"
                        />
                      )}
                    </div>
                  )
                })}
              </div>
              {inputError && (
                <div className="flex items-start gap-2 text-xs text-red-300">
                  <XCircle className="mt-0.5 size-3.5 shrink-0" />
                  <span>{inputError}</span>
                </div>
              )}
            </form>
          )}
          <DialogFooter className="border-white/8 bg-white/[0.03]">
            <Button
              type="button"
              variant="outline"
              onClick={() => setInputDialogOpen(false)}
              disabled={running}
              className="border-white/10 bg-white/5 text-zinc-200 hover:bg-white/10"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              form={`workflow-inputs-${wf.id}`}
              disabled={inputDialogMode === 'run' ? !canRun : stale || !wf.skill_id}
            >
              {inputDialogMode === 'run' ? (
                running ? (
                  <>
                    <Loader2 className="size-3.5 animate-spin" />
                    Testing...
                  </>
                ) : (
                  <>
                    <PlayCircle className="size-3.5" />
                    Run test
                  </>
                )
              ) : (
                <>
                  <SlidersHorizontal className="size-3.5" />
                  Save inputs
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Log + result panel — shown whenever there's output */}
      {(logs.length > 0 || runDone || runError) && (
        <WorkflowLogSection logs={logs} runDone={runDone} runError={runError} logRef={logRef} onRetry={runError ? () => void runTest() : undefined} />
      )}
    </div>
  )
}

export function PluginWorkflowTests({
  plugin,
  onComplete,
}: {
  plugin: Plugin
  onComplete: () => void
}) {
  if (plugin.workflows.length === 0) {
    return <p className="py-4 text-xs text-zinc-500">No workflows recorded yet.</p>
  }

  return (
    <div className="space-y-2">
      {plugin.workflows.map((wf) => (
        <WorkflowTestRow
          key={wf.id}
          plugin={plugin}
          wf={wf}
          onComplete={onComplete}
        />
      ))}
    </div>
  )
}
