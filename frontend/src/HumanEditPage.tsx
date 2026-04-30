import { type ChangeEvent, type CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AppShell } from '@/components/layout/AppLayout'
import type { WorkflowResponse } from './types/workflow'
import {
  deleteStep,
  fetchMetrics,
  fetchSkillList,
  fetchWorkflow,
  postCompileUpdated,
  postReorder,
  postValidate,
} from './api/workflowApi'
import { WorkflowViewer } from './components/WorkflowViewer'
import { StepEditorPanel, type StepEditorPanelHandle } from './components/StepEditorPanel'
import { SuggestionsInlinePanel } from './components/SuggestionsPanel'
import { ParameterizationInlinePanel } from './components/ParameterizationDrawer'
import { useEditorStore } from './store/editorStore'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import { ValidationReportPanel } from './components/ValidationReportPanel'
import { fieldSelectClass } from '@/lib/fieldStyles'
import { cn } from '@/lib/utils'
import {
  AlertCircle,
  ChevronDown,
  CircleHelp,
  Copy,
  Home,
  Lightbulb,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
} from 'lucide-react'

/** Monospace caption — max width + truncate only; alignment set per placement. */
const SKILL_ID_CAPTION_CLASS =
  'max-w-[12rem] truncate font-mono text-[10px] leading-none text-zinc-500 sm:max-w-[16rem]'

export function HumanEditPage() {
  const EDITOR_SIDEBAR_WIDTH_KEY = 'ai-native-editor-sidebar-width'
  const EDITOR_SIDEBAR_MIN = 280
  const EDITOR_SIDEBAR_MAX = 560
  const { skillId: skillIdParam } = useParams<{ skillId?: string }>()
  const skillId = skillIdParam?.trim() || null
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [flowStatus, setFlowStatus] = useState('Load a saved skill to edit, or go home to record a new one.')
  const [resumePick, setResumePick] = useState('')
  const [manualSkillId, setManualSkillId] = useState('')
  const [workflowPaneWidth, setWorkflowPaneWidth] = useState(340)
  const [isResizingPane, setIsResizingPane] = useState(false)
  const [showValidationPane, setShowValidationPane] = useState(false)
  const [showSuggestionsPane, setShowSuggestionsPane] = useState(true)
  const [showVariablesPane, setShowVariablesPane] = useState(false)
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null)
  const splitPaneRef = useRef<HTMLDivElement | null>(null)
  const stepEditorRef = useRef<StepEditorPanelHandle>(null)
  const selected = useEditorStore((s) => s.selectedStepIndex)
  const setValidationReport = useEditorStore((s) => s.setValidationReport)
  const validationReport = useEditorStore((s) => s.validationReport)
  const setSelectedStepIndex = useEditorStore((s) => s.setSelectedStepIndex)

  const skillsListQ = useQuery({
    queryKey: ['skillList'],
    queryFn: fetchSkillList,
    staleTime: 60_000,
  })

  const q = useQuery({
    queryKey: ['workflow', skillId],
    queryFn: () => fetchWorkflow(skillId as string),
    enabled: Boolean(skillId),
  })

  const version = Number((q.data?.package_meta.version as number) ?? 0)
  const savedSkills = skillsListQ.data?.skills ?? []

  const onWorkflowUpdated = useCallback(
    (wf: WorkflowResponse) => {
      if (!skillId) return
      qc.setQueryData(['workflow', skillId], wf)
    },
    [qc, skillId],
  )

  const currentStep = useMemo(() => {
    if (!q.data || selected === null) return null
    return q.data.steps.find((s) => s.step_index === selected) ?? null
  }, [q.data, selected])

  useEffect(() => {
    if (skillId) {
      setFlowStatus('Editing workflow.')
    }
  }, [skillId])

  useEffect(() => {
    const stored = window.localStorage.getItem(EDITOR_SIDEBAR_WIDTH_KEY)
    if (!stored) return
    const parsed = Number.parseInt(stored, 10)
    if (Number.isNaN(parsed)) return
    setWorkflowPaneWidth(Math.max(EDITOR_SIDEBAR_MIN, Math.min(EDITOR_SIDEBAR_MAX, parsed)))
  }, [])

  useEffect(() => {
    window.localStorage.setItem(EDITOR_SIDEBAR_WIDTH_KEY, String(workflowPaneWidth))
  }, [workflowPaneWidth])

  useEffect(() => {
    if (!isResizingPane) return
    const onMouseMove = (event: MouseEvent) => {
      const rect = splitPaneRef.current?.getBoundingClientRect()
      if (!rect) return
      const proposed = event.clientX - rect.left
      const nextWidth = Math.max(EDITOR_SIDEBAR_MIN, Math.min(EDITOR_SIDEBAR_MAX, proposed))
      setWorkflowPaneWidth(nextWidth)
    }
    const onMouseUp = () => {
      setIsResizingPane(false)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [isResizingPane])

  const runValidate = () => {
    if (!skillId) return
    postValidate(skillId)
      .then((r) => {
        setValidationReport(r)
        toast.success('Validation complete')
      })
      .catch(() => {
        setValidationReport({ error: 'validate failed' })
        toast.error('Validation failed')
      })
  }

  const onReorder = (newOrder: number[]) => {
    if (!skillId) return
    postReorder(skillId, newOrder).then((r) => onWorkflowUpdated(r.workflow))
  }

  const onDelete = (index: number) => {
    if (!skillId) return
    deleteStep(skillId, index).then((r) => {
      onWorkflowUpdated(r.workflow)
      const n = r.workflow.steps.length
      const sel = useEditorStore.getState().selectedStepIndex
      if (n === 0) {
        useEditorStore.getState().setSelectedStepIndex(null)
        return
      }
      if (sel === null) {
        useEditorStore.getState().setSelectedStepIndex(0)
        return
      }
      if (index < sel) useEditorStore.getState().setSelectedStepIndex(sel - 1)
      else if (index === sel) useEditorStore.getState().setSelectedStepIndex(Math.min(sel, n - 1))
    })
  }

  /** Re-runs compile from recorded session JSON — replaces the skill package and wipes hand-edited patches. */
  const rebuildSkillFromRecording = () => {
    if (!skillId) return
    const ok = window.confirm(
      'Rebuild this skill from the original recording? Any changes you saved in the editor (selectors, validation, etc.) will be replaced by a fresh compile from the session.',
    )
    if (!ok) return
    postCompileUpdated(skillId)
      .then(() => {
        void q.refetch()
        toast.success('Skill rebuilt from recording')
      })
      .catch((e: Error) => {
        toast.error(e.message)
      })
  }

  const finishEditing = async () => {
    if (!skillId) return
    const savedOk = await (stepEditorRef.current?.submitIfDirty() ?? Promise.resolve(true))
    if (!savedOk) {
      toast.error('Could not save the open step — fix errors or tap Save step, then try Finish.')
      return
    }
    const dirtySteps = useEditorStore.getState().dirtySteps
    if (dirtySteps.size > 0) {
      const label =
        dirtySteps.size === 1
          ? `step ${[...dirtySteps][0]}`
          : `${dirtySteps.size} steps (${[...dirtySteps].sort((a, b) => a - b).join(', ')})`
      toast.warning(`Still have unsaved changes on ${label} — switch to each and save before finishing`)
      return
    }
    setFlowStatus('Finished editing; your skill stays the same id and title on disk.')
    void qc.invalidateQueries({ queryKey: ['skillList'] })
    toast.success(`${skillId} saved in place — same skill id as when you compiled from the recording.`)
    navigate('/edit')
  }

  const toggleToolsPane = (pane: 'validation' | 'suggestions' | 'variables') => {
    const isValidationNext = pane === 'validation'
    const isSuggestionsNext = pane === 'suggestions'
    const isVariablesNext = pane === 'variables'

    setShowValidationPane(isValidationNext)
    setShowSuggestionsPane(isSuggestionsNext)
    setShowVariablesPane(isVariablesNext)
  }

  const openSkillForEdit = useCallback(
    (id: string) => {
      const sid = id.trim()
      if (!sid) {
        setFlowStatus('Enter or choose a skill id.')
        toast.error('Enter or pick a skill id first.')
        return
      }
      setSelectedStepIndex(0)
      setValidationReport(null)
      setFlowStatus(`Opened skill ${sid} for editing.`)
      navigate(`/edit/${sid}`)
      void qc.invalidateQueries({ queryKey: ['workflow', sid] })
      void qc.invalidateQueries({ queryKey: ['skillList'] })
    },
    [navigate, qc, setSelectedStepIndex, setValidationReport],
  )

  const refreshMetrics = useCallback(() => {
    fetchMetrics()
      .then((data) => {
        setMetrics(data)
        toast.message('Metrics refreshed')
      })
      .catch((err: Error) => {
        setMetrics({ error: err.message })
        toast.error('Could not load metrics')
      })
  }, [])

  if (!skillId) {
    return (
      <AppShell
        title="Edit Skill"
        description="After recording compiles into a skill, open it here — your edits overwrite that same skill package (same id/title)."
        actions={
          <>
            <Button variant="outline" size="sm" asChild className="border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08]">
              <Link to="/">
                <Home className="size-3.5" />
                Home
              </Link>
            </Button>
          </>
        }
      >
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
          <section className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
            <Card className="border-white/8 bg-white/[0.035] shadow-none">
              <CardHeader className="border-b border-white/8">
                <CardTitle className="text-white">Open a skill</CardTitle>
                <CardDescription className="text-zinc-500">
                  Flow: Record → Compile → tune steps here → Finish saves to the same skill id. Use "Rebuild from recording" only if you want to discard edits and regenerate from raw events.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6 pt-6">
                <fieldset className="space-y-4 rounded-xl border border-white/8 bg-black/20 p-4">
                  <legend className="px-1.5 text-sm font-semibold text-zinc-200">Resume a skill</legend>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="grid gap-2">
                      <Label className="text-zinc-200" htmlFor="resume">
                        Saved skills
                      </Label>
                      <div className="relative">
                        <select
                          id="resume"
                          className={cn(
                            fieldSelectClass,
                            'h-10 appearance-none border-white/10 bg-black/30 pr-10 text-zinc-100 transition-colors hover:border-white/20 focus-visible:border-white/25',
                          )}
                          value={resumePick}
                          onChange={(e: ChangeEvent<HTMLSelectElement>) => {
                            setResumePick(e.target.value)
                            setManualSkillId('')
                          }}
                        >
                          <option value="" className="bg-zinc-950 text-zinc-200">
                            Choose a skill to resume...
                          </option>
                          {savedSkills.map((s) => (
                            <option key={s.skill_id} value={s.skill_id} className="bg-zinc-950 text-zinc-100">
                              {s.title} - v{s.version} - {s.step_count} steps
                            </option>
                          ))}
                        </select>
                        <ChevronDown className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-zinc-400" />
                      </div>
                      <p className="text-xs text-zinc-500">
                        {savedSkills.length > 0
                          ? `${savedSkills.length} saved skill${savedSkills.length === 1 ? '' : 's'} available`
                          : 'No saved skills yet. Enter a skill id manually to continue.'}
                      </p>
                    </div>
                    <div className="grid gap-2">
                      <Label className="text-zinc-200" htmlFor="manualId">
                        Or enter skill id
                      </Label>
                      <Input
                        id="manualId"
                        type="text"
                        placeholder="skill_abc123"
                        value={manualSkillId}
                        onChange={(e: ChangeEvent<HTMLInputElement>) => {
                          setManualSkillId(e.target.value)
                          setResumePick('')
                        }}
                        className="border-white/10 bg-black/20 text-zinc-100 placeholder:text-zinc-500"
                      />
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" onClick={() => openSkillForEdit(resumePick || manualSkillId)} className="bg-white text-black hover:bg-zinc-200">
                      Load and edit
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => void skillsListQ.refetch()}
                      disabled={skillsListQ.isFetching}
                      className="gap-1.5 border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08]"
                    >
                      <RefreshCw className={cn('size-3.5', skillsListQ.isFetching && 'animate-spin')} />
                      Refresh list
                    </Button>
                  </div>
                  {skillsListQ.isError ? (
                    <p className="text-sm text-red-300" role="alert">
                      {(skillsListQ.error as Error).message}
                    </p>
                  ) : null}
                </fieldset>

                <p className="text-sm text-zinc-500" role="status" aria-live="polite">
                  {flowStatus}
                </p>
              </CardContent>
            </Card>

            <Card className="border-white/8 bg-white/[0.035] shadow-none">
              <CardHeader className="border-b border-white/8">
                <CardTitle className="text-white">Workspace signals</CardTitle>
                <CardDescription className="text-zinc-500">Current backend metrics for the editor and compiler workflow.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4 pt-6">
                <ScrollArea className="h-64 rounded-lg border border-white/8 bg-black/20 p-3">
                  <pre className="font-mono text-xs leading-6 break-words whitespace-pre-wrap text-zinc-400">
                    {JSON.stringify(metrics ?? { info: 'Click "Refresh metrics"' }, null, 2)}
                  </pre>
                </ScrollArea>
                <Button
                  type="button"
                  variant="outline"
                  onClick={refreshMetrics}
                  className="w-full gap-1.5 border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08]"
                >
                  <RefreshCw className="size-3.5" />
                  Refresh metrics
                </Button>
              </CardContent>
            </Card>
          </section>
        </div>
      </AppShell>
    )
  }

  if (q.isLoading) {
    return (
      <AppShell
        title="Edit Skill"
        description="Preparing the workflow editor and loading steps."
      >
        <div className="flex flex-1 flex-col gap-4 px-4 py-4 md:px-6">
          <div className="bg-muted/15 border-border/60 max-w-2xl rounded-lg border p-4 shadow-sm">
            <Skeleton className="mb-2 h-4 w-32" />
            <Skeleton className="h-3 w-full max-w-md" />
          </div>
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 md:min-h-0 md:grid-cols-3">
            <Skeleton className="h-full min-h-[220px] rounded-lg md:min-h-0" />
            <Skeleton className="h-full min-h-[220px] rounded-lg md:min-h-0" />
            <Skeleton className="h-full min-h-[220px] rounded-lg md:min-h-0" />
          </div>
        </div>
      </AppShell>
    )
  }
  if (q.isError) {
    return (
      <AppShell
        title="Edit Skill"
        description="The skill could not be opened."
      >
        <main className="flex flex-1 items-center justify-center p-6">
          <Card className="max-w-md border-red-500/20 bg-red-500/5 shadow-none">
            <CardHeader>
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-red-500/20 bg-red-500/10 text-red-300">
                  <AlertCircle className="size-5" />
                </div>
                <div className="min-w-0 space-y-1">
                  <CardTitle className="text-base text-white">Failed to load skill</CardTitle>
                  <CardDescription className="break-words text-red-200">{(q.error as Error).message}</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <Button variant="default" asChild className="bg-white text-black hover:bg-zinc-200">
                <Link to="/edit">Back to choose skill</Link>
              </Button>
            </CardContent>
          </Card>
        </main>
      </AppShell>
    )
  }
  if (!q.data) return null

  const wf = q.data
  const skillTitle =
    typeof wf.package_meta.title === 'string' && wf.package_meta.title.trim()
      ? wf.package_meta.title.trim()
      : skillId
  const suggestionCount = wf.suggestions.length
  const splitPaneStyle = {
    ['--workflow-pane-width' as string]: `${workflowPaneWidth}px`,
  } as CSSProperties

  return (
    <AppShell
      title={`Skill: ${skillTitle}`}
      description={
        skillId ? (
          <div className="flex max-w-full flex-wrap items-center gap-0.5">
            <span className="shrink-0 text-[10px] font-medium uppercase tracking-wide leading-none text-zinc-600">
              Skill id
            </span>
            <span className={cn(SKILL_ID_CAPTION_CLASS, 'min-w-0 text-left')} title={skillId}>
              {skillId}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="h-5 w-5 shrink-0 p-0 text-zinc-500 hover:bg-white/10 hover:text-zinc-200 [&_svg]:size-2.5"
              title="Copy skill id"
              aria-label="Copy skill id"
              onClick={() =>
                navigator.clipboard
                  .writeText(skillId)
                  .then(() => toast.success('Skill id copied'))
                  .catch(() => toast.error('Could not copy'))
              }
            >
              <Copy className="size-2.5" />
            </Button>
          </div>
        ) : null
      }
      actions={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button variant="outline" size="sm" className="border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08]" asChild>
            <Link to="/" title="Start a new recording (home)">
              <Home className="size-3.5" />
              <span className="hidden sm:inline">New recording</span>
            </Link>
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="border-white/10 bg-black text-white hover:bg-zinc-900"
            onClick={runValidate}
            title="Runs fast static checks on your current edited skill"
          >
            Check Issues
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08]"
            onClick={rebuildSkillFromRecording}
            title="Discard editor changes and regenerate the skill from the raw recording (destructive)"
          >
            Rebuild from recording
          </Button>
          <Button
            type="button"
            size="default"
            className="h-10 bg-white px-5 text-[0.9375rem] font-medium text-black hover:bg-zinc-200 sm:min-w-[6.75rem]"
            onClick={() => void finishEditing()}
            title="Saves the open step if needed, keeps this skill id and title — does not create a copy"
          >
            Finish
          </Button>
        </div>
      }
    >
      <div
        ref={splitPaneRef}
        className="relative grid h-full min-h-0 w-full min-w-0 grid-cols-1 overflow-hidden border-t border-white/8 md:min-h-0 md:[grid-template-columns:var(--workflow-pane-width)_minmax(0,1fr)_24rem] md:items-stretch"
        style={splitPaneStyle}
      >
        <WorkflowViewer
          steps={wf.steps}
          version={version}
          onReorder={onReorder}
          onDelete={onDelete}
        />
        <div
          className="group absolute inset-y-0 z-20 hidden w-3 -translate-x-1/2 cursor-col-resize md:block"
          style={{ left: workflowPaneWidth }}
          onMouseDown={(event) => {
            event.preventDefault()
            setIsResizingPane(true)
          }}
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize workflow sidebar"
        >
          <div className="mx-auto h-full w-px bg-white/10 transition-colors group-hover:bg-white/35 group-active:bg-white/45" />
        </div>
        <StepEditorPanel ref={stepEditorRef} step={currentStep} skillId={skillId} onWorkflowUpdated={onWorkflowUpdated} />
        <aside className="border-border/60 bg-card/20 supports-[backdrop-filter]:bg-card/10 hidden min-h-0 overflow-hidden border-l p-2 backdrop-blur-sm md:flex md:flex-col md:gap-2">
          <section className="shrink-0 space-y-2 px-1 py-1">
            <h2 className="px-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">Tools</h2>
            <div className="grid grid-cols-2 gap-2">
              <Button
                type="button"
                variant={showValidationPane ? 'default' : 'outline'}
                className={cn(
                  'h-10 w-full items-center justify-between gap-2 px-3',
                  showValidationPane
                    ? 'bg-white text-black hover:bg-zinc-200'
                    : 'border-white/12 bg-white/[0.02] text-zinc-200 hover:bg-white/[0.07]',
                )}
                onClick={() => toggleToolsPane('validation')}
                aria-pressed={showValidationPane}
                aria-controls="validation-pane"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <ShieldCheck className={cn('size-4 shrink-0', showValidationPane ? 'text-black' : 'text-emerald-300')} />
                  <span className="truncate text-sm font-medium">Validation</span>
                </span>
                <span
                  className={cn('inline-flex shrink-0', showValidationPane ? 'text-zinc-700' : 'text-zinc-400')}
                  title="View validation checks and failure details."
                >
                  <CircleHelp className="size-3.5" />
                </span>
              </Button>
              <Button
                type="button"
                variant={showSuggestionsPane ? 'default' : 'outline'}
                className={cn(
                  'h-10 w-full items-center justify-between gap-2 px-3',
                  showSuggestionsPane
                    ? 'bg-white text-black hover:bg-zinc-200'
                    : 'border-white/12 bg-white/[0.02] text-zinc-200 hover:bg-white/[0.07]',
                )}
                onClick={() => toggleToolsPane('suggestions')}
                aria-pressed={showSuggestionsPane}
                aria-controls="suggestions-pane"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <Lightbulb className={cn('size-4 shrink-0', showSuggestionsPane ? 'text-black' : 'text-amber-300')} />
                  <span className="truncate text-sm font-medium">Suggestions</span>
                </span>
                <span className="flex items-center gap-1.5">
                  <Badge
                    variant="outline"
                    className={cn('text-[0.65rem]', showSuggestionsPane ? 'border-black/20 text-black' : 'border-white/15 text-zinc-300')}
                  >
                    {suggestionCount}
                  </Badge>
                  <span
                    className={cn('inline-flex shrink-0', showSuggestionsPane ? 'text-zinc-700' : 'text-zinc-400')}
                    title="Review AI suggestions to improve this workflow."
                  >
                    <CircleHelp className="size-3.5" />
                  </span>
                </span>
              </Button>
              <Button
                type="button"
                variant={showVariablesPane ? 'default' : 'outline'}
                className={cn(
                  'col-span-2 h-10 w-full items-center justify-between gap-2 px-3',
                  showVariablesPane
                    ? 'bg-white text-black hover:bg-zinc-200'
                    : 'border-white/12 bg-white/[0.02] text-zinc-200 hover:bg-white/[0.07]',
                )}
                onClick={() => toggleToolsPane('variables')}
                aria-pressed={showVariablesPane}
                aria-controls="variables-pane"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <SlidersHorizontal className={cn('size-4 shrink-0', showVariablesPane ? 'text-black' : 'text-sky-300')} />
                  <span className="truncate text-sm font-medium">Input variables</span>
                </span>
                <span
                  className={cn('inline-flex shrink-0', showVariablesPane ? 'text-zinc-700' : 'text-zinc-400')}
                  title="Configure dynamic input variables and defaults."
                >
                  <CircleHelp className="size-3.5" />
                </span>
              </Button>
            </div>
          </section>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div id="validation-pane">{showValidationPane ? <ValidationReportPanel data={validationReport} defaultOpen /> : null}</div>
            <div id="suggestions-pane">{showSuggestionsPane ? <SuggestionsInlinePanel suggestions={wf.suggestions} /> : null}</div>
            <div id="variables-pane">{showVariablesPane ? <ParameterizationInlinePanel workflow={wf} onSaved={onWorkflowUpdated} /> : null}</div>
          </div>
        </aside>
      </div>
    </AppShell>
  )
}
