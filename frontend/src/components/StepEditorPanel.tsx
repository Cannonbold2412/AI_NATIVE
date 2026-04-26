import { useEffect } from 'react'
import { FormProvider, useForm, useFormState } from 'react-hook-form'
import { toast } from 'sonner'
import type { StepEditorDTO, WorkflowResponse } from '../types/workflow'
import type { WaitNode } from '../types/waitValidation'
import { patchStep } from '../api/workflowApi'
import { ValidationEditor } from './ValidationEditor'
import { ScreenshotViewer } from './ScreenshotViewer'
import { useEditorStore } from '../store/editorStore'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { fieldTextareaClass } from '@/lib/fieldStyles'
import { cn } from '@/lib/utils'

type FormValues = {
  intent: string
  primary_selector: string
  fallback_selectors: string
  value: string
  css: string
  aria: string
  text_based: string
  xpath: string
  wait_validation_shape: 'single' | 'compound'
  wait_tree: WaitNode
  anchor_rows: string
  strategies_selected: string[]
}

const RECOVERY_STRATEGY_OPTIONS = [
  {
    value: 'semantic match',
    label: 'Match by meaning and intent',
    help: 'Use the step intent and nearby text meaning to find the right element.',
  },
  {
    value: 'position match',
    label: 'Match by same position',
    help: 'Use page/layout position when labels are unstable.',
  },
  {
    value: 'visual match',
    label: 'Match by visual look',
    help: 'Use screenshot appearance and target region.',
  },
  {
    value: 'role_match',
    label: 'Match by role/type',
    help: 'Use role/type hints such as button, dropdown, list, combobox.',
  },
  {
    value: 'overlay_anchor',
    label: 'Check overlay or modal context',
    help: 'Useful for dialogs, popovers, drawers, and menus.',
  },
  {
    value: 'url_state_match',
    label: 'Use URL/state clues',
    help: 'Verify page state or URL changes before retrying.',
  },
  {
    value: 'intent_outcome_probe',
    label: 'Probe expected outcome text',
    help: 'Look for expected outcome tokens from the intent.',
  },
  {
    value: 'scroll_anchor',
    label: 'Use scroll anchor',
    help: 'Retry around the same scroll position/context.',
  },
] as const

const emptyForm: FormValues = {
  intent: '',
  primary_selector: '',
  fallback_selectors: '',
  value: '',
  css: '',
  aria: '',
  text_based: '',
  xpath: '',
  wait_validation_shape: 'single',
  wait_tree: { kind: 'leaf', type: 'none', target: '', timeout: 5000 },
  anchor_rows: '',
  strategies_selected: [],
}

function isGroupRecord(w: Record<string, unknown>): boolean {
  const op = String(w.op || '').toLowerCase()
  return (op === 'and' || op === 'or') && Array.isArray(w.conditions) && (w.conditions as unknown[]).length > 0
}

function parseWaitNode(w: Record<string, unknown>): WaitNode {
  if (isGroupRecord(w)) {
    const op = String(w.op || '').toLowerCase() === 'and' ? 'and' : 'or'
    return {
      kind: 'group',
      op,
      children: (w.conditions as unknown[]).map((c) => parseWaitNode(c as Record<string, unknown>)),
    }
  }
  return {
    kind: 'leaf',
    type: String(w.type || 'none'),
    target: String(w.target || ''),
    timeout: Number(w.timeout ?? 5000),
  }
}

function parseWaitForToForm(wfRaw: unknown): Pick<FormValues, 'wait_validation_shape' | 'wait_tree'> {
  const wf = (wfRaw && typeof wfRaw === 'object' ? wfRaw : {}) as Record<string, unknown>
  if (isGroupRecord(wf)) {
    return { wait_validation_shape: 'compound', wait_tree: parseWaitNode(wf) }
  }
  return {
    wait_validation_shape: 'single',
    wait_tree: {
      kind: 'leaf',
      type: String(wf.type || 'none'),
      target: String(wf.target || ''),
      timeout: Number(wf.timeout ?? 5000),
    },
  }
}

function jsonFromWaitNode(n: WaitNode): Record<string, unknown> {
  if (n.kind === 'leaf') {
    return {
      type: n.type,
      target: (n.target || '').trim(),
      timeout: Number(n.timeout) || 5000,
    }
  }
  return {
    op: n.op,
    conditions: n.children.map(jsonFromWaitNode),
  }
}

function firstLeafInTree(n: WaitNode): WaitNode {
  if (n.kind === 'leaf') return n
  for (const c of n.children) {
    const f = firstLeafInTree(c)
    if (f.kind === 'leaf') return f
  }
  return { kind: 'leaf', type: 'none', target: '', timeout: 5000 }
}

function buildWaitFor(values: FormValues): Record<string, unknown> {
  const t = values.wait_tree
  if (values.wait_validation_shape !== 'compound') {
    if (t.kind === 'leaf') return jsonFromWaitNode(t)
    return jsonFromWaitNode(firstLeafInTree(t))
  }
  if (t.kind === 'group') return jsonFromWaitNode(t)
  return { op: 'or', conditions: [jsonFromWaitNode(t)] }
}

function defaultsFromStep(step: StepEditorDTO): FormValues {
  const tgt = step.target as { primary_selector?: string; fallback_selectors?: string[] }
  const sel = step.selectors as { css?: string; aria?: string; text_based?: string; xpath?: string }
  const waitBits = parseWaitForToForm(step.validation.wait_for)
  const anc = (step.anchors_signals || [])
    .map((a) => {
      const o = a as Record<string, string>
      return `${o.kind || o.type || 'text'}:${o.value || o.text || JSON.stringify(a)}`
    })
    .join('\n')
  const strat = ((step.recovery.strategies || []) as string[])
  return {
    intent: step.intent || step.final_intent,
    primary_selector: String(tgt.primary_selector || ''),
    fallback_selectors: (tgt.fallback_selectors || []).join('\n'),
    value: typeof step.value === 'string' ? step.value : '',
    css: String(sel.css || ''),
    aria: String(sel.aria || ''),
    text_based: String(sel.text_based || ''),
    xpath: String(sel.xpath || ''),
    ...waitBits,
    anchor_rows: anc,
    strategies_selected: strat,
  }
}

function parseAnchorRows(text: string): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = []
  for (const line of text.split('\n')) {
    const t = line.trim()
    if (!t) continue
    const idx = t.indexOf(':')
    if (idx === -1) {
      out.push({ kind: 'text', value: t })
    } else {
      out.push({ kind: t.slice(0, idx).trim(), value: t.slice(idx + 1).trim() })
    }
  }
  return out
}

type Props = {
  step: StepEditorDTO | null
  skillId: string
  onWorkflowUpdated: (wf: WorkflowResponse) => void
}

function DirtySync({ stepIndex }: { stepIndex: number }) {
  const { isDirty } = useFormState()
  const markDirty = useEditorStore((s) => s.markStepDirty)
  const clearDirty = useEditorStore((s) => s.clearStepDirty)
  useEffect(() => {
    if (isDirty) markDirty(stepIndex)
    else clearDirty(stepIndex)
  }, [isDirty, stepIndex, markDirty, clearDirty])
  return null
}

const checkboxClass = 'border-input size-4 shrink-0 rounded border'

export function StepEditorPanel({ step, skillId, onWorkflowUpdated }: Props) {
  const methods = useForm<FormValues>({ defaultValues: emptyForm })

  useEffect(() => {
    if (step) methods.reset(defaultsFromStep(step))
  }, [step, methods])

  if (!step) {
    return (
      <div className="text-muted-foreground border-border/60 flex min-h-0 min-w-0 items-center justify-center border-x p-4 text-sm">
        Select a step to edit
      </div>
    )
  }

  const editable = step.editable_fields
  const canEdit = (key: string) => editable[key] !== false

  const onSubmit = methods.handleSubmit(async (values) => {
    const fallbacks = values.fallback_selectors
      .split(/\n+/)
      .map((s) => s.trim())
      .filter(Boolean)
    const strategies = (values.strategies_selected || []).map((s) => s.trim()).filter(Boolean)
    const anchors = parseAnchorRows(values.anchor_rows)
    const patch: Record<string, unknown> = {
      intent: values.intent,
      target: {
        primary_selector: values.primary_selector,
        fallback_selectors: fallbacks,
      },
      signals: {
        selectors: {
          css: values.css || values.primary_selector,
          aria: values.aria,
          text_based: values.text_based,
          xpath: values.xpath,
        },
        anchors,
      },
      validation: {
        wait_for: buildWaitFor(values),
      },
      recovery: {
        strategies,
      },
    }
    if (canEdit('value')) patch.value = values.value
    try {
      const res = await patchStep(skillId, step.step_index, patch, false)
      onWorkflowUpdated(res.workflow)
      const next = res.workflow.steps.find((s) => s.step_index === step.step_index)
      if (next) methods.reset(defaultsFromStep(next))
      toast.success('Step saved')
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Save failed'
      methods.setError('root', { message: msg })
      toast.error(msg)
    }
  })

  return (
    <div className="bg-background border-border/60 min-h-0 min-w-0 space-y-3 border-x p-2 md:overflow-y-auto">
      <FormProvider {...methods}>
        <DirtySync stepIndex={step.step_index} />
        <form onSubmit={onSubmit} className="space-y-3">
          <Card>
            <CardHeader className="p-3 pb-2">
              <CardTitle className="text-base">Edit step</CardTitle>
              <CardDescription className="line-clamp-2">{step.human_readable_description}</CardDescription>
              <p className="text-muted-foreground font-mono text-xs">
                Action: <code>{step.action_type}</code>
              </p>
            </CardHeader>
            <CardContent className="space-y-4 p-3 pt-0">
              <div className="grid gap-2">
                <Label htmlFor="intent">Intent</Label>
                <Input
                  id="intent"
                  type="text"
                  disabled={!canEdit('intent')}
                  {...methods.register('intent')}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="primary_selector">Primary selector</Label>
                <Input
                  id="primary_selector"
                  type="text"
                  disabled={!canEdit('selectors')}
                  {...methods.register('primary_selector')}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="fallback_selectors">Fallback selectors (one per line)</Label>
                <textarea
                  id="fallback_selectors"
                  className={fieldTextareaClass}
                  rows={3}
                  disabled={!canEdit('selectors')}
                  {...methods.register('fallback_selectors')}
                />
              </div>
              {canEdit('value') ? (
                <div className="grid gap-2">
                  <Label htmlFor="value">Value (for type/fill)</Label>
                  <Input id="value" type="text" {...methods.register('value')} />
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="p-3 pb-2">
              <CardTitle className="text-sm">Selector channels</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 p-3 pt-0">
              <div className="grid gap-1.5">
                <Label htmlFor="css">CSS</Label>
                <Input id="css" disabled={!canEdit('selectors')} {...methods.register('css')} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="aria">ARIA</Label>
                <Input
                  id="aria"
                  disabled={!canEdit('selectors')}
                  {...methods.register('aria')}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="text_based">Text-based</Label>
                <Input
                  id="text_based"
                  disabled={!canEdit('selectors')}
                  {...methods.register('text_based')}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="xpath">XPath</Label>
                <Input
                  id="xpath"
                  disabled={!canEdit('selectors')}
                  {...methods.register('xpath')}
                />
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-2">
            <Label htmlFor="anchor_rows">Anchors (kind:value per line)</Label>
            <textarea
              id="anchor_rows"
              className={fieldTextareaClass}
              rows={4}
              disabled={!canEdit('anchors')}
              {...methods.register('anchor_rows')}
            />
          </div>

          <Card>
            <CardHeader className="p-3 pb-2">
              <CardTitle className="text-sm">Recovery (multi-select)</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 p-3 pt-0">
              {[
                ...RECOVERY_STRATEGY_OPTIONS,
                ...((step.recovery.strategies || []) as string[])
                  .filter((v) => !RECOVERY_STRATEGY_OPTIONS.some((o) => o.value === v))
                  .map((v) => ({ value: v, label: v, help: 'Existing strategy on this step.' })),
              ].map((opt) => (
                <label key={opt.value} className="hover:bg-muted/30 flex cursor-pointer gap-2 rounded-md p-1.5">
                  <input
                    type="checkbox"
                    className={cn(checkboxClass, 'mt-0.5')}
                    value={opt.value}
                    disabled={!canEdit('recovery_strategies')}
                    {...methods.register('strategies_selected')}
                  />
                  <span className="min-w-0 text-sm">
                    {opt.label}
                    <span className="text-muted-foreground block text-xs">— {opt.help}</span>
                  </span>
                </label>
              ))}
            </CardContent>
          </Card>

          <ValidationEditor />
          <Separator />
          <div className="flex items-center justify-end">
            <Button type="submit" size="default" disabled={methods.formState.isSubmitting}>
              {methods.formState.isSubmitting ? 'Saving…' : 'Save step'}
            </Button>
          </div>
          {methods.formState.errors.root ? (
            <p className="text-destructive text-sm">{(methods.formState.errors.root as { message?: string }).message}</p>
          ) : null}
        </form>
      </FormProvider>
      <div className="pt-1">
        <ScreenshotViewer screenshot={step.screenshot} label={step.human_readable_description} />
      </div>
    </div>
  )
}
