'use client'

import { useEffect, useRef, useState } from 'react'
import { fetchWorkflow } from '@/api/workflowApi'
import {
  readPluginSse,
  testWorkflow,
  type Plugin,
  type PluginWorkflow,
} from '@/api/pluginApi'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { CheckCircle2, ChevronDown, ChevronUp, Loader2, PlayCircle, XCircle } from 'lucide-react'

type InputSpec = { id: string; label?: string; type?: string; default?: string | null; pattern?: string | null }

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
  const [expanded, setExpanded] = useState(false)
  const [running, setRunning] = useState(false)
  const [logs, setLogs] = useState<string[]>([])
  const [runError, setRunError] = useState('')
  const [runDone, setRunDone] = useState(false)
  const logRef = useRef<HTMLDivElement>(null)

  const stale = isStaleTest(wf, plugin)

  // Load input specs eagerly so we know which button layout to use
  useEffect(() => {
    if (!wf.skill_id) {
      setInputSpecs([])
      return
    }
    fetchWorkflow(wf.skill_id)
      .then((wfData) => {
        const specs = (wfData.inputs ?? []) as InputSpec[]
        setInputSpecs(specs)
        setInputs((prev) => {
          const next = { ...prev }
          for (const spec of specs) if (spec.id && !(spec.id in next)) next[spec.id] = spec.default ?? ''
          return next
        })
      })
      .catch(() => setInputSpecs([]))
  }, [wf.skill_id])

  async function runTest() {
    setLogs([])
    setRunError('')
    setRunDone(false)
    setRunning(true)
    setExpanded(true)
    try {
      const parsedInputs: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(inputs)) parsedInputs[k] = v
      const response = await testWorkflow(plugin.id, wf.id, parsedInputs)
      await readPluginSse(response, (msg) => {
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

  const canRun = !stale && !running && wf.skill_id

  function LogSection() {
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
          <div className="flex items-start gap-2 text-xs text-red-300">
            <XCircle className="mt-0.5 size-3.5 shrink-0" />
            <span>{runError}</span>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-white/8 bg-white/[0.02]">
      {/* Header row */}
      <div className="flex items-center justify-between gap-3 px-3 py-2.5">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-white">{wf.name}</p>
          {stale && (
            <p className="mt-0.5 text-xs text-amber-400">Edited since last build — rebuild before testing</p>
          )}
          {wf.last_test_status === 'failed' && wf.last_test_error && !expanded && (
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

          {/* Input workflows: Configure toggle expands the form */}
          {inputSpecs !== null && inputSpecs.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setExpanded((e) => !e)}
              disabled={stale || !wf.skill_id}
              title={stale ? 'Rebuild the plugin first' : undefined}
            >
              {expanded ? (
                <ChevronUp className="size-3.5" />
              ) : (
                <ChevronDown className="size-3.5" />
              )}
              Configure
            </Button>
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

      {/* Expanded panel: input form for workflows that need inputs */}
      {expanded && inputSpecs !== null && inputSpecs.length > 0 && (
        <div className="border-t border-white/8 px-3 pb-3 pt-3">
          <p className="mb-3 text-xs text-zinc-400">
            Fill in the inputs below to run this workflow test.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void runTest()
            }}
            className="space-y-3"
          >
            <div className="grid gap-3">
              {inputSpecs.map((spec) => {
                const displayLabel = spec.label || spec.id
                return (
                  <div key={spec.id} className="grid gap-1">
                    <Label className="text-xs font-medium text-zinc-300">{displayLabel}</Label>
                    <Input
                      value={inputs[spec.id] ?? ''}
                      onChange={(e) => setInputs((prev) => ({ ...prev, [spec.id]: e.target.value }))}
                      placeholder={displayLabel ? `Enter ${displayLabel.toLowerCase()}…` : ''}
                      className="h-7 text-xs"
                    />
                  </div>
                )
              })}
            </div>
            <Button type="submit" size="sm" disabled={!canRun}>
              {running ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" />
                  Testing...
                </>
              ) : (
                <>
                  <PlayCircle className="size-3.5" />
                  Run test
                </>
              )}
            </Button>
          </form>
        </div>
      )}

      {/* Log + result panel — shown whenever there's output */}
      {(logs.length > 0 || runDone || runError) && <LogSection />}
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
