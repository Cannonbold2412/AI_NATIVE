import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import type { WorkflowResponse } from './types/workflow'
import {
  deleteStep,
  fetchMetrics,
  fetchSkillList,
  fetchWorkflow,
  postCompileSession,
  postCompileUpdated,
  postReorder,
  postStartRecording,
  postStopRecording,
  postValidate,
  getRecordingStatus,
} from './api/workflowApi'
import { WorkflowViewer } from './components/WorkflowViewer'
import { StepEditorPanel } from './components/StepEditorPanel'
import { SuggestionsPanel } from './components/SuggestionsPanel'
import { ParameterizationDrawer } from './components/ParameterizationDrawer'
import { useEditorStore } from './store/editorStore'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { ValidationReportPanel } from './components/ValidationReportPanel'
import { fieldSelectClass } from '@/lib/fieldStyles'
import { cn } from '@/lib/utils'

function FlowStatusBadge({
  isRecording,
  isCompiling,
  hasSkill,
}: {
  isRecording: boolean
  isCompiling: boolean
  hasSkill: boolean
}) {
  if (isCompiling) {
    return <Badge variant="secondary">Compiling</Badge>
  }
  if (isRecording) {
    return <Badge>Recording</Badge>
  }
  if (hasSkill) {
    return <Badge variant="outline">Editing</Badge>
  }
  return <Badge variant="secondary">Ready</Badge>
}

export function SkillReviewPage() {
  const qc = useQueryClient()
  const [paramOpen, setParamOpen] = useState(false)
  const [startUrl, setStartUrl] = useState('')
  const [skillTitle, setSkillTitle] = useState('')
  const [flowStatus, setFlowStatus] = useState('Idle')
  const [logLines, setLogLines] = useState<string[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [skillId, setSkillId] = useState<string | null>(null)
  const [resumePick, setResumePick] = useState('')
  const [manualSkillId, setManualSkillId] = useState('')
  const [switchSkillPick, setSwitchSkillPick] = useState('')
  const [isRecording, setIsRecording] = useState(false)
  const [isCompiling, setIsCompiling] = useState(false)
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null)
  const pollingRef = useRef<number | null>(null)
  const lastEventCount = useRef(0)
  const selected = useEditorStore((s) => s.selectedStepIndex)
  const setValidationReport = useEditorStore((s) => s.setValidationReport)
  const validationReport = useEditorStore((s) => s.validationReport)
  const setSelectedStepIndex = useEditorStore((s) => s.setSelectedStepIndex)

  const appendLog = useCallback((line: string) => {
    const ts = new Date().toLocaleTimeString()
    setLogLines((prev) => [...prev, `[${ts}] ${line}`])
  }, [])

  const stopPolling = useCallback(() => {
    if (pollingRef.current !== null) {
      window.clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }, [])

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

  const compileUpdated = () => {
    if (!skillId) return
    postCompileUpdated(skillId)
      .then(() => {
        void q.refetch()
        toast.success('Recompiled from session')
      })
      .catch((e: Error) => {
        toast.error(e.message)
      })
  }

  const openSkillForEdit = useCallback(
    (id: string) => {
      const sid = id.trim()
      if (!sid) {
        setFlowStatus('Enter or choose a skill id.')
        toast.error('Enter or pick a skill id first.')
        return
      }
      stopPolling()
      setSessionId(null)
      setIsRecording(false)
      setSkillId(sid)
      setSelectedStepIndex(0)
      setValidationReport(null)
      setFlowStatus(`Opened skill ${sid} for editing.`)
      setSwitchSkillPick(sid)
      appendLog(`skill_opened: ${sid}`)
      void qc.invalidateQueries({ queryKey: ['workflow', sid] })
      void qc.invalidateQueries({ queryKey: ['skillList'] })
    },
    [appendLog, qc, setSelectedStepIndex, setValidationReport, stopPolling],
  )

  const refreshMetrics = useCallback(() => {
    fetchMetrics()
      .then((data) => {
        setMetrics(data)
        toast.message('Metrics refreshed')
      })
      .catch((err: Error) => {
        setMetrics({ error: err.message })
        appendLog(`metrics_error: ${err.message}`)
        toast.error('Could not load metrics')
      })
  }, [appendLog])

  const compileFromSession = useCallback(
    async (activeSessionId: string) => {
      setIsCompiling(true)
      setFlowStatus('Compiling skill package...')
      appendLog(`compile_started: session=${activeSessionId}`)
      try {
        const result = await postCompileSession(activeSessionId, skillTitle)
        setSkillId(result.skill_id)
        setSwitchSkillPick(result.skill_id)
        setSelectedStepIndex(0)
        setFlowStatus('Compiled. Continue with human-in-the-loop editing below.')
        appendLog(`compile_done: skill=${result.skill_id}, steps=${result.step_count}`)
        await qc.invalidateQueries({ queryKey: ['workflow', result.skill_id] })
        refreshMetrics()
        toast.success(`Compiled skill ${result.skill_id} (${result.step_count} steps)`)
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        setFlowStatus('Compile failed. Check logs and retry.')
        appendLog(`compile_error: ${msg}`)
        toast.error('Compile failed')
      } finally {
        setIsCompiling(false)
      }
    },
    [appendLog, qc, refreshMetrics, setSelectedStepIndex, skillTitle],
  )

  const stopRecording = useCallback(async () => {
    if (!sessionId || !isRecording) return
    stopPolling()
    setFlowStatus('Stopping recording...')
    try {
      await postStopRecording(sessionId)
      appendLog(`recording_stopped: session=${sessionId}`)
      setIsRecording(false)
      await compileFromSession(sessionId)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setFlowStatus('Stop failed. Check logs and retry.')
      appendLog(`stop_error: ${msg}`)
      setIsRecording(false)
      toast.error('Stop failed')
    }
  }, [appendLog, compileFromSession, isRecording, sessionId, stopPolling])

  const startFlow = useCallback(async () => {
    if (!startUrl.trim()) {
      setFlowStatus('Start URL is required.')
      toast.error('Start URL is required')
      return
    }
    if (isRecording || isCompiling) return
    stopPolling()
    setSessionId(null)
    setSwitchSkillPick('')
    setSkillId(null)
    setSelectedStepIndex(null)
    setValidationReport(null)
    setLogLines(['[system] flow started'])
    lastEventCount.current = 0
    setFlowStatus('Starting browser recorder...')
    try {
      const start = await postStartRecording(startUrl.trim())
      setSessionId(start.session_id)
      setIsRecording(true)
      setFlowStatus('Browser opened. Perform actions, then close browser or click Stop Recording.')
      appendLog(`recording_started: session=${start.session_id}`)
      toast.success('Recording started')
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setFlowStatus('Could not start recorder.')
      appendLog(`start_error: ${msg}`)
      toast.error('Could not start recorder')
    }
  }, [
    appendLog,
    isCompiling,
    isRecording,
    setSelectedStepIndex,
    setValidationReport,
    startUrl,
    stopPolling,
  ])

  useEffect(() => {
    if (!isRecording || !sessionId) return
    pollingRef.current = window.setInterval(() => {
      getRecordingStatus(sessionId)
        .then((status) => {
          if (status.event_count !== lastEventCount.current) {
            lastEventCount.current = status.event_count
            appendLog(`events_captured: ${status.event_count}`)
          }
          if (Array.isArray(status.binding_errors) && status.binding_errors.length > 0) {
            appendLog(`capture_warning: ${status.binding_errors[status.binding_errors.length - 1]}`)
          }
          if (!status.browser_open) {
            stopPolling()
            setIsRecording(false)
            setFlowStatus('Browser closed. Compiling captured events...')
            void compileFromSession(sessionId)
          }
        })
        .catch((err: Error) => {
          stopPolling()
          setIsRecording(false)
          setFlowStatus('Polling failed. Check logs and retry.')
          appendLog(`polling_error: ${err.message}`)
          toast.error('Recording status poll failed')
        })
    }, 2000)

    return () => stopPolling()
  }, [appendLog, compileFromSession, isRecording, sessionId, stopPolling])

  useEffect(() => {
    return () => stopPolling()
  }, [stopPolling])

  if (!skillId) {
    return (
      <div className="bg-background text-foreground flex min-h-screen flex-col">
        <header className="bg-card/40 border-border flex items-center justify-between border-b px-4 py-3">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">AI Skill Platform</h1>
            <p className="text-muted-foreground text-sm">Record → compile → human edit → recompile</p>
          </div>
          <FlowStatusBadge isCompiling={isCompiling} isRecording={isRecording} hasSkill={false} />
        </header>
        <main className="flex flex-1 justify-center p-4 md:p-8">
          <Card className="border-border w-full max-w-3xl">
            <CardHeader>
              <CardTitle>Skill compiler</CardTitle>
              <CardDescription>Start a new recording or open a saved skill from disk.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid gap-2">
                <Label htmlFor="startUrl">Start URL</Label>
                <Input
                  id="startUrl"
                  type="url"
                  placeholder="https://example.com"
                  value={startUrl}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setStartUrl(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="skillTitle">Skill title (optional)</Label>
                <Input
                  id="skillTitle"
                  type="text"
                  placeholder="Checkout flow"
                  value={skillTitle}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setSkillTitle(e.target.value)}
                />
              </div>

              <fieldset className="border-border space-y-3 rounded-lg border p-4">
                <legend className="px-1 text-sm font-medium">Resume a previous skill</legend>
                <p className="text-muted-foreground text-sm">Pick a compiled skill or paste its id, then open the editor.</p>
                <div className="grid gap-2">
                  <Label htmlFor="resume">Saved skills</Label>
                  <select
                    id="resume"
                    className={fieldSelectClass}
                    value={resumePick}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) => {
                      setResumePick(e.target.value)
                      setManualSkillId('')
                    }}
                  >
                    <option value="">Choose…</option>
                    {(skillsListQ.data?.skills ?? []).map((s) => (
                      <option key={s.skill_id} value={s.skill_id}>
                        {s.title} — v{s.version}, {s.step_count} steps
                      </option>
                    ))}
                  </select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="manualId">Or skill id</Label>
                  <Input
                    id="manualId"
                    type="text"
                    placeholder="skill_abc123"
                    value={manualSkillId}
                    onChange={(e: ChangeEvent<HTMLInputElement>) => {
                      setManualSkillId(e.target.value)
                      setResumePick('')
                    }}
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" onClick={() => openSkillForEdit(resumePick || manualSkillId)}>
                    Load & edit
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => void skillsListQ.refetch()}
                    disabled={skillsListQ.isFetching}
                  >
                    Refresh list
                  </Button>
                </div>
                {skillsListQ.isError ? (
                  <p className="text-destructive text-sm">{(skillsListQ.error as Error).message}</p>
                ) : null}
              </fieldset>

              <div className="flex flex-wrap gap-2">
                <Button type="button" disabled={isRecording || isCompiling} onClick={startFlow}>
                  Start recording
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={!isRecording || isCompiling}
                  onClick={() => void stopRecording()}
                >
                  Stop recording
                </Button>
                <Button type="button" variant="outline" onClick={refreshMetrics}>
                  Refresh metrics
                </Button>
              </div>

              <div
                className="text-muted-foreground text-sm"
                role="status"
                aria-live="polite"
              >
                {flowStatus}
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-1">
                  <p className="text-muted-foreground text-xs font-medium">Activity log</p>
                  <ScrollArea className="bg-muted/30 border-border h-40 rounded-md border p-3">
                    <pre className="font-mono text-xs break-words whitespace-pre-wrap">{logLines.join('\n')}</pre>
                  </ScrollArea>
                </div>
                <div className="space-y-1">
                  <p className="text-muted-foreground text-xs font-medium">Metrics (JSON)</p>
                  <ScrollArea className="bg-muted/30 border-border h-40 rounded-md border p-3">
                    <pre className="font-mono text-xs break-words">
                      {JSON.stringify(metrics ?? { info: 'No metrics yet' }, null, 2)}
                    </pre>
                  </ScrollArea>
                </div>
              </div>
            </CardContent>
          </Card>
        </main>
      </div>
    )
  }

  if (q.isLoading) {
    return (
      <div className="bg-background text-foreground flex min-h-screen flex-col gap-4 p-6">
        <Skeleton className="h-10 w-64" />
        <div className="grid flex-1 grid-cols-1 gap-4 min-h-0 md:grid-cols-3">
          <Skeleton className="h-full min-h-[200px]" />
          <Skeleton className="h-full min-h-[200px] md:col-span-1" />
          <Skeleton className="h-full min-h-[200px]" />
        </div>
      </div>
    )
  }
  if (q.isError) {
    return (
      <div className="text-destructive bg-background min-h-screen p-6 text-sm">{(q.error as Error).message}</div>
    )
  }
  if (!q.data) return null

  const wf = q.data

  return (
    <div className="bg-background text-foreground flex min-h-screen flex-col">
      <header className="bg-card/40 border-border z-10 flex flex-col gap-3 border-b px-3 py-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-semibold tracking-tight">Skill review</h1>
            <FlowStatusBadge
              isCompiling={isCompiling}
              isRecording={isRecording}
              hasSkill
            />
          </div>
          <p className="text-muted-foreground truncate text-xs">
            {skillId} — v{version} — {flowStatus}
          </p>
        </div>
        <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-1.5 sm:max-w-[80%]">
          <Button
            type="button"
            size="sm"
            disabled={isRecording || isCompiling}
            onClick={startFlow}
            title="Start a new session (resets in-memory selection)"
          >
            New recording
          </Button>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={!isRecording || isCompiling}
            onClick={() => void stopRecording()}
          >
            Stop
          </Button>
          <Separator orientation="vertical" className="h-6 hidden sm:block" />
          <label className="text-muted-foreground flex items-center gap-1.5 text-xs">
            <span className="whitespace-nowrap">Open skill</span>
            <select
              className={cn(fieldSelectClass, 'h-8 w-[min(11rem,28vw)] py-0 sm:w-44')}
              value={switchSkillPick}
              onChange={(e: ChangeEvent<HTMLSelectElement>) => setSwitchSkillPick(e.target.value)}
              title="Switch to another saved skill"
            >
              <option value="">Choose…</option>
              {(skillsListQ.data?.skills ?? []).map((s) => (
                <option key={s.skill_id} value={s.skill_id}>
                  {s.skill_id}
                </option>
              ))}
            </select>
          </label>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!switchSkillPick.trim() || switchSkillPick === skillId}
            onClick={() => {
              const next = switchSkillPick.trim()
              if (next) openSkillForEdit(next)
            }}
          >
            Load
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => void skillsListQ.refetch()}
            disabled={skillsListQ.isFetching}
          >
            List
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => void q.refetch()}>
            Reload
          </Button>
          <Button type="button" size="sm" onClick={runValidate}>
            Validate
          </Button>
          <Button type="button" size="sm" variant="secondary" onClick={() => setParamOpen(true)}>
            Variables
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={compileUpdated}
            title="Requires session events on disk"
          >
            Recompile
          </Button>
        </div>
      </header>
      <ValidationReportPanel data={validationReport} defaultOpen />
      <div
        className="grid min-h-0 w-full min-w-0 flex-1 grid-cols-1 md:min-h-0 md:grid-cols-[minmax(200px,0.9fr)_1.2fr_minmax(200px,0.9fr)] md:items-stretch"
        style={{ minHeight: 'min(100vh, calc(100dvh - 4rem))' }}
      >
        <WorkflowViewer
          steps={wf.steps}
          version={version}
          onReorder={onReorder}
          onDelete={onDelete}
        />
        <StepEditorPanel step={currentStep} skillId={skillId} onWorkflowUpdated={onWorkflowUpdated} />
        <SuggestionsPanel suggestions={wf.suggestions} />
      </div>
      <ParameterizationDrawer
        open={paramOpen}
        onClose={() => setParamOpen(false)}
        workflow={wf}
        onSaved={onWorkflowUpdated}
      />
    </div>
  )
}
