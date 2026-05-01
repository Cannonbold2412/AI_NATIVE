import { forwardRef, useCallback, useEffect, useImperativeHandle, useState } from 'react'
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
import { fieldSelectClass } from '@/lib/fieldStyles'
import { cn } from '@/lib/utils'
import { GripVertical, Trash2 } from 'lucide-react'

type FormValues = {
  intent: string
  scroll_amount: string
  selectors: string[]
  value: string
  css: string
  aria: string
  text_based: string
  xpath: string
  wait_validation_shape: 'single' | 'compound'
  wait_tree: WaitNode
  anchors: string[]
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
  scroll_amount: '',
  selectors: [''],
  value: '',
  css: '',
  aria: '',
  text_based: '',
  xpath: '',
  wait_validation_shape: 'single',
  wait_tree: { kind: 'leaf', type: 'none', target: '', timeout: 5000 },
  anchors: [''],
  strategies_selected: [],
}

const ANCHOR_RELATIONS = new Set(['target', 'inside', 'above', 'below', 'near'])

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
      const element = String(o.element || o.value || o.text || '').trim()
      if (!element) return ''
      const relation = String(o.relation || '').trim().toLowerCase()
      return `${ANCHOR_RELATIONS.has(relation) ? relation : 'near'}:${element}`
    })
    .filter(Boolean)
  const strat = ((step.recovery.strategies || []) as string[])
  return {
    intent: step.intent || step.final_intent,
    scroll_amount: step.scroll_amount === null || step.scroll_amount === undefined ? '' : String(step.scroll_amount),
    selectors: [String(tgt.primary_selector || ''), ...(tgt.fallback_selectors || [])].filter(
      (selector, index, arr) => index === 0 || Boolean(selector) || arr.length === 1,
    ),
    value: typeof step.value === 'string' ? step.value : '',
    css: String(sel.css || ''),
    aria: String(sel.aria || ''),
    text_based: String(sel.text_based || ''),
    xpath: String(sel.xpath || ''),
    ...waitBits,
    anchors: anc.length > 0 ? anc : [''],
    strategies_selected: strat,
  }
}

function parseAnchorRows(rows: string[]): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = []
  for (const line of rows) {
    const t = line.trim()
    if (!t) continue
    const idx = t.indexOf(':')
    if (idx === -1) {
      out.push({ element: t, relation: 'near' })
    } else {
      const left = t.slice(0, idx).trim().toLowerCase()
      const right = t.slice(idx + 1).trim()
      if (!right) continue
      out.push({
        element: right,
        relation: ANCHOR_RELATIONS.has(left) ? left : 'near',
      })
    }
  }
  return out
}

type Props = {
  step: StepEditorDTO | null
  skillId: string
  onWorkflowUpdated: (wf: WorkflowResponse) => void
  recordingShotDragActive?: boolean
  onDroppedRecordingScreenshot?: (stepIndex: number, eventIndex: number) => void | Promise<void>
  onClearStepVisual?: (stepIndex: number) => void | Promise<void>
}

export type StepEditorPanelHandle = {
  /** Saves the open step form if dirty. Returns whether save succeeded or was not needed. */
  submitIfDirty: () => Promise<boolean>
}

function compactStepLabel(label: string): string {
  return label.replace(/^Step\s+\d+:\s*/i, '').trim()
}

function humanizeAction(action: string): string {
  const cleaned = action.trim().replace(/[_-]+/g, ' ')
  if (!cleaned) return 'Action'
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1)
}

function parseScrollAmount(raw: string): number {
  const trimmed = raw.trim()
  if (!trimmed) throw new Error('Scroll amount is required')
  if (!/^-?\d+$/.test(trimmed)) throw new Error('Scroll amount must be a whole number')
  return Number.parseInt(trimmed, 10)
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

export const StepEditorPanel = forwardRef<StepEditorPanelHandle, Props>(
  function StepEditorPanel(
    {
      step,
      skillId,
      onWorkflowUpdated,
      recordingShotDragActive,
      onDroppedRecordingScreenshot,
      onClearStepVisual,
    },
    ref,
  ) {
  const methods = useForm<FormValues>({ defaultValues: emptyForm })
  const [draggingRecoveryIndex, setDraggingRecoveryIndex] = useState<number | null>(null)

  useEffect(() => {
    if (step) methods.reset(defaultsFromStep(step))
  }, [step, methods])

  const saveVisualBbox = useCallback(
    async (b: { x: number; y: number; w: number; h: number }) => {
      if (!step || step.flags.is_scroll) return
      try {
        const res = await patchStep(
          skillId,
          step.step_index,
          {
            signals: {
              visual: {
                bbox: { x: b.x, y: b.y, w: b.w, h: b.h },
              },
            },
          },
          false,
        )
        onWorkflowUpdated(res.workflow)
        const next = res.workflow.steps.find((s) => s.step_index === step.step_index)
        if (next) methods.reset(defaultsFromStep(next))
        toast.success('Visual bbox saved')
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Could not save visual bbox'
        toast.error(msg)
        throw e
      }
    },
    [methods, onWorkflowUpdated, skillId, step],
  )

  const persistStepValues = useCallback(
    async (values: FormValues, options?: { silentToast?: boolean }) => {
      if (!step) return
      const silent = options?.silentToast ?? false
      const editable = step.editable_fields
      const canEditField = (key: string) => editable[key] !== false
      if (step.flags.is_scroll) {
        const scrollAmount = parseScrollAmount(values.scroll_amount)
        const patch: Record<string, unknown> = {
          intent: values.intent,
          action: {
            action: 'scroll',
            delta: scrollAmount,
          },
        }
        try {
          const res = await patchStep(skillId, step.step_index, patch, false)
          onWorkflowUpdated(res.workflow)
          const next = res.workflow.steps.find((s) => s.step_index === step.step_index)
          if (next) methods.reset(defaultsFromStep(next))
          if (!silent) toast.success('Step saved')
          return
        } catch (e) {
          const msg = e instanceof Error ? e.message : 'Save failed'
          methods.setError('root', { message: msg })
          if (!silent) toast.error(msg)
          throw e
        }
      }
      const selectors = values.selectors
        .map((s) => s.trim())
        .filter(Boolean)
      const primarySelector = selectors[0] || ''
      const fallbackSelectors = selectors.slice(1)
      const strategies = (values.strategies_selected || []).map((s) => s.trim()).filter(Boolean)
      const anchors = parseAnchorRows(values.anchors)
      const patch: Record<string, unknown> = {
        intent: values.intent,
        target: {
          primary_selector: primarySelector,
          fallback_selectors: fallbackSelectors,
        },
        signals: {
          selectors: {
            css: values.css || primarySelector,
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
      if (canEditField('value')) patch.value = values.value
      try {
        const res = await patchStep(skillId, step.step_index, patch, false)
        onWorkflowUpdated(res.workflow)
        const next = res.workflow.steps.find((s) => s.step_index === step.step_index)
        if (next) methods.reset(defaultsFromStep(next))
        if (!silent) toast.success('Step saved')
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Save failed'
        methods.setError('root', { message: msg })
        if (!silent) toast.error(msg)
        throw e
      }
    },
    [methods, onWorkflowUpdated, skillId, step],
  )

  useImperativeHandle(
    ref,
    () => ({
      submitIfDirty: async () => {
        if (!step) return true
        if (!methods.formState.isDirty) return true
        return await new Promise<boolean>((resolve) => {
          void methods.handleSubmit(
            async (values) => {
              try {
                await persistStepValues(values, { silentToast: true })
                resolve(true)
              } catch {
                resolve(false)
              }
            },
            () => resolve(false),
          )()
        })
      },
    }),
    [methods, persistStepValues, step],
  )

  if (!step) {
    return (
      <div className="text-muted-foreground border-border/60 bg-card/25 supports-[backdrop-filter]:bg-card/15 flex min-h-0 min-w-0 items-center justify-center border-x p-4 text-sm backdrop-blur-sm">
        Select a step to edit
      </div>
    )
  }

  const editable = step.editable_fields
  const canEdit = (key: string) => editable[key] !== false
  const isScrollStep = step.flags.is_scroll
  const selectors = methods.watch('selectors') || ['']
  const anchors = methods.watch('anchors') || ['']
  const selectedStrategies = methods.watch('strategies_selected') || []
  const recoveryOptions = [
    ...RECOVERY_STRATEGY_OPTIONS,
    ...((step.recovery.strategies || []) as string[])
      .filter((v) => !RECOVERY_STRATEGY_OPTIONS.some((o) => o.value === v))
      .map((v) => ({ value: v, label: v, help: 'Existing strategy on this step.' })),
  ]
  const recoveryHelpByValue = new Map(recoveryOptions.map((opt) => [opt.value, opt.help]))

  const addRecoveryStrategy = (value: string) => {
    if (!canEdit('recovery_strategies')) return
    if (!value) return
    const current = methods.getValues('strategies_selected') || []
    const existingIndex = current.indexOf(value)
    if (existingIndex === 0) return
    if (existingIndex > 0) {
      const next = [value, ...current.filter((v) => v !== value)]
      methods.setValue('strategies_selected', next, { shouldDirty: true })
      return
    }
    methods.setValue('strategies_selected', [value, ...current], { shouldDirty: true })
  }

  const moveRecoveryStrategy = (from: number, to: number) => {
    if (from === to || from < 0 || to < 0 || to >= selectedStrategies.length) return
    const next = [...selectedStrategies]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    methods.setValue('strategies_selected', next, { shouldDirty: true })
  }

  const removeRecoveryStrategy = (value: string) => {
    const current = methods.getValues('strategies_selected') || []
    methods.setValue(
      'strategies_selected',
      current.filter((v) => v !== value),
      { shouldDirty: true },
    )
  }

  const onSubmit = methods.handleSubmit(async (values) => {
    try {
      await persistStepValues(values, { silentToast: false })
    } catch {
      /* persistStepValues surfaces toast/error state */
    }
  })

  return (
    <div className="bg-card/30 border-border/60 supports-[backdrop-filter]:bg-card/20 relative z-0 min-h-0 min-w-0 space-y-2 border-t p-2 backdrop-blur-sm md:border-t-0 md:border-l md:overflow-x-hidden md:overflow-y-auto">
      <ScreenshotViewer
        screenshot={step.screenshot}
        label={step.human_readable_description}
        stepIndex={step.step_index}
        recordingShotDragActive={recordingShotDragActive}
        onDroppedRecordingScreenshot={onDroppedRecordingScreenshot}
        onClearStepVisual={onClearStepVisual}
        isScrollStep={step.flags.is_scroll}
        onSaveVisualBbox={!step.flags.is_scroll ? saveVisualBbox : undefined}
      />
      <FormProvider {...methods}>
        <DirtySync stepIndex={step.step_index} />
        <form onSubmit={onSubmit} className="space-y-2">
          <Card className="gap-2 py-3">
            <CardHeader className="p-2.5 pb-1">
              <CardTitle className="text-lg font-semibold tracking-tight">Action: {humanizeAction(step.action_type)}</CardTitle>
              <CardDescription className="line-clamp-2">{compactStepLabel(step.human_readable_description)}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 p-2.5 pt-0">
              <div className="grid gap-2">
                <Label htmlFor="intent">Intent</Label>
                <Input
                  id="intent"
                  type="text"
                  disabled={!canEdit('intent')}
                  {...methods.register('intent')}
                />
              </div>
              {isScrollStep ? (
                <div className="grid gap-2">
                  <Label htmlFor="scroll_amount">Scroll amount</Label>
                  <Input
                    id="scroll_amount"
                    type="number"
                    inputMode="numeric"
                    placeholder="150"
                    disabled={!canEdit('intent')}
                    {...methods.register('scroll_amount')}
                  />
                  <p className="text-muted-foreground text-xs">Use a signed number. Positive scrolls down; negative scrolls up.</p>
                </div>
              ) : null}
              {!isScrollStep ? (
                <>
                  <div className="grid gap-2">
                    <div className="flex items-center justify-between gap-2">
                      <Label htmlFor="selector_0">Selectors</Label>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={!canEdit('selectors')}
                        onClick={() => methods.setValue('selectors', [...selectors, ''], { shouldDirty: true })}
                      >
                        Add selector
                      </Button>
                    </div>
                    <p className="text-muted-foreground text-xs">
                      Top selector is primary. Selectors below are fallbacks.
                    </p>
                    <div className="space-y-2">
                      {selectors.map((_, index) => (
                        <div key={`selector-${index}`} className="flex items-center gap-2">
                          <Input
                            id={`selector_${index}`}
                            type="text"
                            placeholder={index === 0 ? 'Primary selector' : `Fallback selector ${index}`}
                            disabled={!canEdit('selectors')}
                            {...methods.register(`selectors.${index}` as const)}
                          />
                          <Button
                            type="button"
                            size="icon-sm"
                            variant="ghost"
                            className="text-destructive hover:text-destructive h-7 w-7"
                            disabled={!canEdit('selectors') || selectors.length <= 1}
                            onClick={() =>
                              methods.setValue(
                                'selectors',
                                selectors.filter((_, i) => i !== index),
                                { shouldDirty: true },
                              )
                            }
                            aria-label={`Remove selector ${index + 1}`}
                          >
                            <Trash2 className="size-3.5" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </div>
                  {canEdit('value') ? (
                    <div className="grid gap-2">
                      <Label htmlFor="value">Value (for type/fill)</Label>
                      <Input id="value" type="text" {...methods.register('value')} />
                    </div>
                  ) : null}
                </>
              ) : null}
            </CardContent>
          </Card>

          {!isScrollStep ? (
          <>
          <Card className="gap-2 py-3">
            <CardHeader className="p-2.5 pb-1">
              <CardTitle className="text-sm">Selector channels</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2 p-2.5 pt-0">
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

          <Card className="gap-2 py-3">
            <CardHeader className="p-2.5 pb-1">
              <CardTitle className="text-sm">Anchors</CardTitle>
              <CardDescription className="text-xs">Use format `relation:element` such as `near:Sign in` or `above:Email`.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2.5 p-2.5 pt-0">
              <div className="flex items-center justify-between gap-2">
                <Label htmlFor="anchor_0">Anchors</Label>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={!canEdit('anchors')}
                  onClick={() => methods.setValue('anchors', [...anchors, ''], { shouldDirty: true })}
                >
                  Add anchor
                </Button>
              </div>
              <div className="space-y-1.5">
                {anchors.map((_, index) => (
                  <div key={`anchor-${index}`} className="flex items-center gap-1.5">
                    <Input
                      id={`anchor_${index}`}
                      type="text"
                      placeholder={index === 0 ? 'near:Sign in' : `Anchor ${index + 1}`}
                      disabled={!canEdit('anchors')}
                      {...methods.register(`anchors.${index}` as const)}
                    />
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      className="text-destructive hover:text-destructive h-7 w-7"
                      disabled={!canEdit('anchors') || anchors.length <= 1}
                      onClick={() =>
                        methods.setValue(
                          'anchors',
                          anchors.filter((_, i) => i !== index),
                          { shouldDirty: true },
                        )
                      }
                      aria-label={`Remove anchor ${index + 1}`}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <ValidationEditor />

          <Card className="gap-2 py-3">
            <CardHeader className="p-2.5 pb-1">
              <CardTitle className="text-sm">Recovery (ordered)</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5 p-2.5 pt-0">
              <p className="text-muted-foreground text-xs">Choose from dropdown to add/move to top. Drag rows to reorder.</p>
              <div className="grid gap-1.5">
                <Label htmlFor="recovery_strategy_picker">Recovery strategy</Label>
                <select
                  id="recovery_strategy_picker"
                  className={fieldSelectClass}
                  disabled={!canEdit('recovery_strategies')}
                  value=""
                  onChange={(event) => {
                    addRecoveryStrategy(event.target.value)
                    event.currentTarget.value = ''
                  }}
                >
                  <option value="">Select recovery strategy...</option>
                  {recoveryOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5 pt-1">
                {selectedStrategies.map((strategy, index) => (
                  <div
                    key={`${strategy}-${index}`}
                    className={cn(
                      'border-border bg-background/40 flex items-center justify-between gap-2 rounded-md border px-2 py-1.5 text-xs',
                      draggingRecoveryIndex === index && 'opacity-70',
                    )}
                    draggable={canEdit('recovery_strategies')}
                    onDragStart={() => setDraggingRecoveryIndex(index)}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={() => {
                      if (draggingRecoveryIndex === null) return
                      moveRecoveryStrategy(draggingRecoveryIndex, index)
                      setDraggingRecoveryIndex(null)
                    }}
                    onDragEnd={() => setDraggingRecoveryIndex(null)}
                  >
                    <span className="text-muted-foreground shrink-0" aria-hidden>
                      <GripVertical className="size-3.5" />
                    </span>
                    <span className="text-muted-foreground">{index + 1}.</span>
                    <span className="min-w-0 flex-1">
                      <span className="block break-words">{strategy}</span>
                      <span className="text-muted-foreground block break-words text-[11px] leading-4">
                        {recoveryHelpByValue.get(strategy) || 'Recovery strategy selected for this step.'}
                      </span>
                    </span>
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      className="text-destructive hover:text-destructive h-7 w-7"
                      disabled={!canEdit('recovery_strategies')}
                      onClick={() => removeRecoveryStrategy(strategy)}
                      aria-label={`Remove recovery strategy ${strategy}`}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                ))}
                {selectedStrategies.length === 0 ? (
                  <p className="text-muted-foreground text-xs">No recovery strategy selected.</p>
                ) : null}
              </div>
            </CardContent>
          </Card>
          </>
          ) : null}

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
    </div>
  )
})
