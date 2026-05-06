import { forwardRef, useCallback, useEffect, useImperativeHandle } from 'react'
import { FormProvider, useForm, useFormState, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import type { StepEditorDTO, WorkflowResponse } from '../types/workflow'
import { patchStep, postUpdateVisualBbox } from '../api/workflowApi'
import { ScreenshotViewer } from './ScreenshotViewer'
import { useEditorStore } from '../store/editorStore'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { fieldSelectClass } from '@/lib/fieldStyles'
import { cn } from '@/lib/utils'
import { BoxSelect, Info, Trash2 } from 'lucide-react'

type FormValues = {
  intent: string
  url: string
  scroll_mode: 'scroll_only' | 'scroll_to_locate'
  scroll_amount: string
  scroll_selector: string
  selectors: string[]
  value: string
  css: string
  aria: string
  text_based: string
  xpath: string
  anchors: string[]
  check_kind: string
  check_pattern: string
  check_threshold: string
  check_selector: string
  check_text: string
}

const emptyForm: FormValues = {
  intent: '',
  url: '',
  scroll_mode: 'scroll_only',
  scroll_amount: '',
  scroll_selector: '',
  selectors: [''],
  value: '',
  css: '',
  aria: '',
  text_based: '',
  xpath: '',
  anchors: [''],
  check_kind: 'url',
  check_pattern: '',
  check_threshold: '0.9',
  check_selector: '',
  check_text: '',
}

const ANCHOR_RELATIONS = new Set(['target', 'inside', 'above', 'below', 'near'])
const URL_CHECK_KINDS = new Set(['url', 'url_exact', 'url_must_be'])
const EXACT_URL_CHECK_KINDS = new Set(['url_exact', 'url_must_be'])

function defaultsFromStep(step: StepEditorDTO): FormValues {
  const tgt = step.target as { primary_selector?: string; fallback_selectors?: string[] }
  const sel = step.selectors as { css?: string; aria?: string; text_based?: string; xpath?: string }
  const anc = (step.anchors_signals || [])
    .map((a) => {
      const o = a as Record<string, string>
      const element = String(o.element || o.value || o.text || '').trim()
      if (!element) return ''
      const relation = String(o.relation || '').trim().toLowerCase()
      return `${ANCHOR_RELATIONS.has(relation) ? relation : 'near'}:${element}`
    })
    .filter(Boolean)
  return {
    intent: step.intent || step.final_intent,
    url: step.url || '',
    scroll_mode: step.scroll_mode === 'scroll_to_locate' ? 'scroll_to_locate' : 'scroll_only',
    scroll_amount: step.scroll_amount === null || step.scroll_amount === undefined ? '' : String(step.scroll_amount),
    scroll_selector: String(step.scroll_selector || ''),
    selectors: [String(tgt.primary_selector || ''), ...(tgt.fallback_selectors || [])].filter(
      (selector, index, arr) => index === 0 || Boolean(selector) || arr.length === 1,
    ),
    value: typeof step.value === 'string' ? step.value : '',
    css: String(sel.css || ''),
    aria: String(sel.aria || ''),
    text_based: String(sel.text_based || ''),
    xpath: String(sel.xpath || ''),
    anchors: anc.length > 0 ? anc : [''],
    check_kind: String(step.check_kind || 'url'),
    check_pattern: String(step.check_pattern || ''),
    check_threshold: String(step.check_threshold ?? 0.9),
    check_selector: String(step.check_selector || ''),
    check_text: String(step.check_text || ''),
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

function visualBboxSummary(step: StepEditorDTO): {
  usable: boolean
  label: string
  title: string
} {
  if (step.flags.is_scroll) {
    return {
      usable: false,
      label: 'Scroll step: no target bbox',
      title: 'Scroll steps use scroll position instead of a visual target rectangle.',
    }
  }
  const bbox = step.screenshot.bbox || {}
  const x = Number(bbox.x ?? 0)
  const y = Number(bbox.y ?? 0)
  const w = Number(bbox.w ?? 0)
  const h = Number(bbox.h ?? 0)
  if (w >= 2 && h >= 2) {
    return {
      usable: true,
      label: `x ${Math.round(x)} | y ${Math.round(y)} | w ${Math.round(w)} | h ${Math.round(h)}`,
      title: 'Saved in signals.visual.bbox and used by visual matching, LLM anchor refresh, and static confidence checks.',
    }
  }
  return {
    usable: false,
    label: 'No usable visual bbox saved',
    title: 'Draw a target region on the screenshot to save signals.visual.bbox for this action.',
  }
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

  useEffect(() => {
    if (step) methods.reset(defaultsFromStep(step))
  }, [step, methods])

  const saveVisualBbox = useCallback(
    async (b: { x: number; y: number; w: number; h: number }) => {
      if (!step || step.flags.is_scroll) return
      try {
        const res = await postUpdateVisualBbox(
          skillId,
          step.step_index,
          { x: b.x, y: b.y, w: b.w, h: b.h },
        )
        onWorkflowUpdated(res.workflow)
        const next = res.workflow.steps.find((s) => s.step_index === step.step_index)
        if (next) methods.reset(defaultsFromStep(next))
        toast.success('Visual bbox saved; anchors recomputed')
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Could not save visual bbox and recompute anchors'
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
      const isCheckStep = step.action_type === 'check'
      const isNavigateStep = step.action_type.toLowerCase() === 'navigate'
      if (isNavigateStep) {
        const url = values.url.trim()
        if (!/^https?:\/\//i.test(url)) {
          const err = new Error('Navigate URL must start with http:// or https://')
          methods.setError('url', { message: err.message })
          if (!silent) toast.error(err.message)
          throw err
        }
        const patch: Record<string, unknown> = {
          intent: values.intent,
          url,
          action: {
            action: 'navigate',
            url,
          },
          validation: {
            wait_for: { type: 'url_change', target: url, timeout: 15000 },
            success_conditions: { url },
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
      if (isCheckStep) {
        const patch: Record<string, unknown> = {
          intent: values.intent,
          check_kind: values.check_kind,
        }
        if (URL_CHECK_KINDS.has(values.check_kind)) {
          patch.check_pattern = values.check_pattern
          patch.signals = { anchors: [] }
          patch.recovery = { anchors: [] }
        }
        else if (values.check_kind === 'snapshot') patch.check_threshold = Number(values.check_threshold)
        else if (values.check_kind === 'selector') patch.check_selector = values.check_selector
        else if (values.check_kind === 'text') patch.check_text = values.check_text
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
      if (step.flags.is_scroll) {
        const patch: Record<string, unknown> = {
          intent: values.intent,
          action: {
            action: 'scroll',
          },
        }
        if (values.scroll_mode === 'scroll_to_locate') {
          const selector = values.scroll_selector.trim()
          if (!selector) {
            const err = new Error('Scroll target selector is required')
            methods.setError('scroll_selector', { message: err.message })
            if (!silent) toast.error(err.message)
            throw err
          }
          patch.action = {
            action: 'scroll',
            selector,
          }
        } else {
          const scrollAmount = parseScrollAmount(values.scroll_amount)
          patch.action = {
            action: 'scroll',
            delta: scrollAmount,
          }
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

  const selectors = useWatch({ control: methods.control, name: 'selectors' }) || ['']
  const anchors = useWatch({ control: methods.control, name: 'anchors' }) || ['']
  const checkKind = useWatch({ control: methods.control, name: 'check_kind' }) || 'url'
  const scrollMode = useWatch({ control: methods.control, name: 'scroll_mode' }) || 'scroll_only'

  if (!step) {
    return (
      <div className="text-muted-foreground border-border/60 bg-card/25 supports-[backdrop-filter]:bg-card/15 flex min-h-0 min-w-0 items-center justify-center border-x p-4 text-sm backdrop-blur-sm">
        Select a step to edit
      </div>
    )
  }

  const editable = step.editable_fields
  const canEdit = (key: string) => editable[key] !== false
  const isCheckStep = step.action_type === 'check'
  const isNavigateStep = step.action_type.toLowerCase() === 'navigate'
  const isScrollStep = step.flags.is_scroll
  const showSelectorAndAnchorTools = !isScrollStep && !isNavigateStep && !(isCheckStep && URL_CHECK_KINDS.has(checkKind))
  const bboxSummary = visualBboxSummary(step)

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
      <div
        className={cn(
          'border-border/60 bg-background/35 flex min-w-0 items-start gap-2 rounded-lg border px-2.5 py-2 text-xs',
          bboxSummary.usable ? 'text-zinc-300' : 'text-zinc-500',
        )}
      >
        <span
          className={cn(
            'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded border',
            bboxSummary.usable
              ? 'border-sky-400/30 bg-sky-400/10 text-sky-300'
              : 'border-white/10 bg-white/[0.03] text-zinc-500',
          )}
          aria-hidden
        >
          <BoxSelect className="size-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5">
            <span className="shrink-0 font-medium text-zinc-300">Visual bbox</span>
            <span className="inline-flex shrink-0 text-zinc-500 hover:text-zinc-400" title={bboxSummary.title}>
              <Info className="size-3.5" aria-hidden />
              <span className="sr-only">Visual bbox usage</span>
            </span>
          </div>
          <p className="mt-0.5 min-w-0 font-mono text-[11px] leading-5 break-words text-zinc-400">
            {bboxSummary.label}
          </p>
        </div>
      </div>
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
              {isCheckStep ? (
                <>
                  <div className="grid gap-2">
                    <Label htmlFor="check_kind">Check type</Label>
                    <select
                      id="check_kind"
                      className={fieldSelectClass}
                      {...methods.register('check_kind')}
                    >
                      <option value="url">URL contains pattern</option>
                      <option value="url_exact">URL must be</option>
                      <option value="snapshot">Snapshot similarity (≥ threshold)</option>
                      <option value="selector">Element present</option>
                      <option value="text">Text appears on page</option>
                    </select>
                  </div>
                  {URL_CHECK_KINDS.has(checkKind) && (
                    <div className="grid gap-2">
                      <Label htmlFor="check_pattern">
                        {EXACT_URL_CHECK_KINDS.has(checkKind) ? 'Expected URL' : 'URL pattern (substring)'}
                      </Label>
                      <Input
                        id="check_pattern"
                        type="text"
                        placeholder={EXACT_URL_CHECK_KINDS.has(checkKind) ? 'https://example.com/dashboard' : 'e.g., /dashboard'}
                        {...methods.register('check_pattern')}
                      />
                    </div>
                  )}
                  {checkKind === 'snapshot' && (
                    <div className="grid gap-2">
                      <Label htmlFor="check_threshold">Similarity threshold (0.0 - 1.0)</Label>
                      <Input
                        id="check_threshold"
                        type="number"
                        step="0.05"
                        min="0"
                        max="1"
                        defaultValue="0.9"
                        {...methods.register('check_threshold')}
                      />
                      <p className="text-muted-foreground text-xs">Default: 0.9 (90% match)</p>
                    </div>
                  )}
                  {checkKind === 'selector' && (
                    <div className="grid gap-2">
                      <Label htmlFor="check_selector">CSS selector</Label>
                      <Input
                        id="check_selector"
                        type="text"
                        placeholder="e.g., .success-message"
                        {...methods.register('check_selector')}
                      />
                    </div>
                  )}
                  {checkKind === 'text' && (
                    <div className="grid gap-2">
                      <Label htmlFor="check_text">Expected text</Label>
                      <Input
                        id="check_text"
                        type="text"
                        placeholder="e.g., Success"
                        {...methods.register('check_text')}
                      />
                    </div>
                  )}
                </>
              ) : null}
              {isNavigateStep ? (
                <div className="grid gap-2">
                  <Label htmlFor="url">URL</Label>
                  <Input
                    id="url"
                    type="url"
                    placeholder="https://example.com"
                    disabled={!canEdit('url')}
                    {...methods.register('url')}
                  />
                  {methods.formState.errors.url ? (
                    <p className="text-destructive text-xs">{methods.formState.errors.url.message}</p>
                  ) : null}
                </div>
              ) : null}
              {isScrollStep ? (
                <>
                  <div className="grid gap-2">
                    <Label htmlFor="scroll_mode">Scroll mode</Label>
                    <select id="scroll_mode" className={fieldSelectClass} {...methods.register('scroll_mode')}>
                      <option value="scroll_only">Scroll only</option>
                      <option value="scroll_to_locate">Scroll to locate</option>
                    </select>
                  </div>
                  {scrollMode === 'scroll_to_locate' ? (
                    <div className="grid gap-2">
                      <Label htmlFor="scroll_selector">Target selector</Label>
                      <Input
                        id="scroll_selector"
                        type="text"
                        placeholder="text=Load more"
                        {...methods.register('scroll_selector')}
                      />
                    </div>
                  ) : (
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
                  )}
                </>
              ) : null}
              {!isScrollStep && !isCheckStep && !isNavigateStep ? (
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

          {showSelectorAndAnchorTools ? (
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
              <CardDescription className="text-xs">Use format `relation:element`; above/below describes the target relative to that anchor.</CardDescription>
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
