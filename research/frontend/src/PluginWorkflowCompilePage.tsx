'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchPlugin, updateWorkflow } from '@/api/pluginApi'
import {
  enqueueCompileJob,
  enqueueRecompileSkillJob,
  fetchJob,
  streamJobEvents,
  type JobEvent,
  type JobRecord,
  type JobStatus,
} from '@/api/workflowApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { usePluginWorkflowCompileTracker } from '@/hooks/usePluginWorkflowCompileTracker'
import { cn } from '@/lib/utils'
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Code2,
  ExternalLink,
  Loader2,
  Play,
  Radio,
  RefreshCw,
  Terminal,
} from 'lucide-react'

type CompileMode = 'compile' | 'recompile'

const terminalStatuses: JobStatus[] = ['succeeded', 'failed', 'canceled']

function isTerminal(status: JobStatus | 'enqueuing' | 'idle') {
  return terminalStatuses.includes(status as JobStatus)
}

function formatTime(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function eventTone(event: JobEvent) {
  if (event.event === 'api_call') return 'border-sky-500/20 bg-sky-500/5 text-sky-200'
  if (event.event.includes('error') || event.event === 'failed') return 'border-red-500/20 bg-red-500/5 text-red-200'
  if (event.event === 'succeeded') return 'border-emerald-500/20 bg-emerald-500/5 text-emerald-200'
  return 'border-white/8 bg-white/[0.03] text-zinc-300'
}

function dataString(data: Record<string, unknown>) {
  const keys = Object.keys(data)
  if (keys.length === 0) return ''
  try {
    return JSON.stringify(data, null, 2)
  } catch {
    return String(data)
  }
}

function extractSkillId(job: JobRecord | null, fallback: string | null | undefined) {
  const resultSkillId = job?.result?.skill_id
  if (typeof resultSkillId === 'string' && resultSkillId.trim()) return resultSkillId
  if (typeof job?.resource_id === 'string' && job.resource_id.trim() && !job.resource_id.startsWith('skill_')) {
    return job.resource_id
  }
  return fallback || null
}

function clientEvent(event: string, message: string, data: Record<string, unknown> = {}): JobEvent {
  return {
    ts: Date.now() / 1000,
    event,
    message,
    data,
  }
}

export function PluginWorkflowCompilePage({
  pluginId,
  workflowId,
  initialMode = 'compile',
  autoStart = false,
}: {
  pluginId: string
  workflowId: string
  initialMode?: CompileMode
  autoStart?: boolean
}) {
  const queryClient = useQueryClient()
  const requestedMode: CompileMode = initialMode
  const shouldAutoStart = autoStart
  const { clearCompile } = usePluginWorkflowCompileTracker()
  const [jobId, setJobId] = useState<string | null>(null)
  const [job, setJob] = useState<JobRecord | null>(null)
  const [status, setStatus] = useState<JobStatus | 'enqueuing' | 'idle'>('idle')
  const [events, setEvents] = useState<JobEvent[]>([])
  const [error, setError] = useState('')
  const [streamError, setStreamError] = useState('')
  const startedRef = useRef(false)
  const logRef = useRef<HTMLDivElement>(null)

  const pluginQ = useQuery({
    queryKey: ['plugin', pluginId],
    queryFn: () => fetchPlugin(pluginId),
  })

  const plugin = pluginQ.data?.plugin
  const workflow = plugin?.workflows.find((item) => item.id === workflowId)
  const workflowName = workflow?.name ?? ''
  const workflowSessionId = workflow?.session_id ?? ''
  const workflowSkillId = workflow?.skill_id ?? null
  const workflowSlug = workflow?.slug ?? ''
  const mode: CompileMode = requestedMode === 'recompile' || workflowSkillId ? 'recompile' : 'compile'
  const apiEvents = events.filter((event) => event.event === 'api_call')
  const phaseEvents = events.filter((event) => event.event !== 'api_call')
  const skillId = extractSkillId(job, workflow?.skill_id)
  const jobActive = status === 'enqueuing' || status === 'queued' || status === 'running'

  const startFirstCompile = async () => {
    if (!workflowSessionId || !workflowName) return
    clearCompile(pluginId, workflowId)
    setError('')
    setStreamError('')
    setJob(null)
    setJobId(null)
    setEvents([
      clientEvent('client', 'Creating compile job.', {
        phase: 'enqueue_compile',
        session_id: workflowSessionId,
      }),
    ])
    setStatus('enqueuing')
    try {
      const next = await enqueueCompileJob(workflowSessionId, workflowName)
      setEvents((prev) => [
        ...prev,
        clientEvent('client', 'Compile job created.', { phase: 'enqueue_compile_done', job_id: next.job_id }),
      ])
      setStatus(next.status)
      setJobId(next.job_id)
    } catch (err) {
      const message = err instanceof Error && err.message ? err.message : 'Could not start compile.'
      setEvents((prev) => [
        ...prev,
        clientEvent('compile_error', message, { phase: 'enqueue_compile_failed' }),
      ])
      setStatus('failed')
      setError(message)
    }
  }

  const retryFirstCompile = async () => {
    await startFirstCompile()
  }

  const startRecompile = async () => {
    const recompileSkillId = skillId || workflowSkillId
    if (!recompileSkillId) {
      setError('Compile this workflow before running recompile.')
      return
    }
    setError('')
    setStreamError('')
    setJob(null)
    setJobId(null)
    setEvents([
      clientEvent('client', 'Creating recompile job.', {
        phase: 'enqueue_recompile',
        skill_id: recompileSkillId,
      }),
    ])
    setStatus('enqueuing')
    try {
      const next = await enqueueRecompileSkillJob(recompileSkillId, workflowName)
      setEvents((prev) => [
        ...prev,
        clientEvent('client', 'Recompile job created.', { phase: 'enqueue_recompile_done', job_id: next.job_id }),
      ])
      setStatus(next.status)
      setJobId(next.job_id)
    } catch (err) {
      const message = err instanceof Error && err.message ? err.message : 'Could not start recompile.'
      setEvents((prev) => [
        ...prev,
        clientEvent('compile_error', message, { phase: 'enqueue_recompile_failed' }),
      ])
      setStatus('failed')
      setError(message)
    }
  }

  useEffect(() => {
    if (!workflow || startedRef.current || !shouldAutoStart) return
    startedRef.current = true
    if (mode === 'recompile') {
      if (!workflowSkillId) {
        setError('Compile this workflow before running recompile.')
        return
      }
      setError('')
      setStreamError('')
      setJob(null)
      setJobId(null)
      setEvents([
        clientEvent('client', 'Creating recompile job.', {
          phase: 'enqueue_recompile',
          skill_id: workflowSkillId,
        }),
      ])
      setStatus('enqueuing')
      enqueueRecompileSkillJob(workflowSkillId, workflowName)
        .then((next) => {
          setEvents((prev) => [
            ...prev,
            clientEvent('client', 'Recompile job created.', { phase: 'enqueue_recompile_done', job_id: next.job_id }),
          ])
          setStatus(next.status)
          setJobId(next.job_id)
        })
        .catch((err) => {
          const message = err instanceof Error && err.message ? err.message : 'Could not start recompile.'
          setEvents((prev) => [
            ...prev,
            clientEvent('compile_error', message, { phase: 'enqueue_recompile_failed' }),
          ])
          setStatus('failed')
          setError(message)
        })
    } else {
      if (!workflowSessionId || !workflowName) return
      setError('')
      setStreamError('')
      setJob(null)
      setJobId(null)
      setEvents([
        clientEvent('client', 'Creating compile job.', {
          phase: 'enqueue_compile',
          session_id: workflowSessionId,
        }),
      ])
      setStatus('enqueuing')
      clearCompile(pluginId, workflowId)
      enqueueCompileJob(workflowSessionId, workflowName)
        .then((next) => {
          setEvents((prev) => [
            ...prev,
            clientEvent('client', 'Compile job created.', { phase: 'enqueue_compile_done', job_id: next.job_id }),
          ])
          setStatus(next.status)
          setJobId(next.job_id)
        })
        .catch((err) => {
          const message = err instanceof Error && err.message ? err.message : 'Could not start compile.'
          setEvents((prev) => [
            ...prev,
            clientEvent('compile_error', message, { phase: 'enqueue_compile_failed' }),
          ])
          setStatus('failed')
          setError(message)
        })
    }
  }, [
    clearCompile,
    mode,
    pluginId,
    shouldAutoStart,
    workflow,
    workflowId,
    workflowName,
    workflowSessionId,
    workflowSkillId,
  ])

  useEffect(() => {
    if (!jobId) return
    setStreamError('')
    setEvents((prev) => [
      ...prev,
      clientEvent('client', 'Opening compile log stream.', { phase: 'open_job_stream', job_id: jobId }),
    ])
    const controller = new AbortController()
    void streamJobEvents(
      jobId,
      (event) => {
        setEvents((prev) => [...prev, event])
        if (event.event === 'running' || event.event === 'queued' || event.event === 'succeeded' || event.event === 'failed' || event.event === 'canceled') {
          setStatus(event.event)
        }
        window.setTimeout(() => logRef.current?.scrollTo(0, logRef.current.scrollHeight), 0)
      },
      controller.signal,
    ).catch((err) => {
      if (controller.signal.aborted) return
      const message = err instanceof Error && err.message ? err.message : 'Job event stream failed.'
      setStreamError(message)
      setEvents((prev) => [
        ...prev,
        clientEvent('compile_error', message, { phase: 'open_job_stream_failed', job_id: jobId }),
      ])
    })
    return () => controller.abort()
  }, [jobId])

  useEffect(() => {
    if (!jobId || (isTerminal(status) && job)) return
    let canceled = false
    const poll = async () => {
      try {
        const next = await fetchJob(jobId)
        if (canceled) return
        setJob(next)
        setStatus(next.status)
        if (next.status === 'failed' || next.status === 'canceled') {
          setError(next.user_error || `Compile job ${next.status}.`)
        }
        if (next.status === 'succeeded') {
          const nextSkillId = extractSkillId(next, workflowSkillId)
          if (nextSkillId && !workflowSkillId) {
            await updateWorkflow(pluginId, workflowId, { skill_id: nextSkillId })
          }
          clearCompile(pluginId, workflowId)
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: ['plugin', pluginId] }),
            queryClient.invalidateQueries({ queryKey: ['plugins'] }),
            queryClient.invalidateQueries({ queryKey: ['skillList'] }),
            nextSkillId ? queryClient.invalidateQueries({ queryKey: ['workflow', nextSkillId] }) : Promise.resolve(),
            workflowSlug ? queryClient.invalidateQueries({ queryKey: ['compiled-skill', pluginId, workflowSlug] }) : Promise.resolve(),
          ])
        }
      } catch (err) {
        if (!canceled) {
          const message = err instanceof Error && err.message ? err.message : 'Could not check compile status.'
          setError(message)
          if (message.includes('unknown_job_id')) {
            clearCompile(pluginId, workflowId)
            setStatus('failed')
          }
        }
      }
    }
    void poll()
    const timer = window.setInterval(() => void poll(), 1500)
    return () => {
      canceled = true
      window.clearInterval(timer)
    }
  }, [clearCompile, job, jobId, pluginId, queryClient, status, workflowId, workflowSkillId, workflowSlug])

  const statusBadge = useMemo(() => {
    if (status === 'succeeded') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
    if (status === 'failed' || status === 'canceled') return 'border-red-500/30 bg-red-500/10 text-red-300'
    if (status === 'running' || status === 'queued' || status === 'enqueuing') {
      return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
    }
    return 'border-white/10 bg-white/5 text-zinc-300'
  }, [status])

  const handleRecompileClick = () => {
    if (skillId || workflowSkillId) {
      void startRecompile()
      return
    }
    void startFirstCompile()
  }

  if (pluginQ.isLoading) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <PageHeader title="Compile" />
        <p className="p-6 text-sm text-zinc-500">Loading...</p>
      </div>
    )
  }

  if (pluginQ.isError || !plugin || !workflow) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <PageHeader title="Compile" />
        <div className="p-6">
          <p className="text-sm text-red-400">
            {pluginQ.isError ? (pluginQ.error as Error)?.message : 'Workflow not found.'}
          </p>
          <Button className="mt-4" size="sm" variant="outline" asChild>
            <Link href={`/plugins/${pluginId}`}>
              <ArrowLeft className="size-3.5" />
              Back to Plugin
            </Link>
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        title={mode === 'recompile' ? 'Recompile Workflow' : 'Compile Workflow'}
        description={<span className="truncate text-xs text-zinc-500">{plugin.name} / {workflow.name}</span>}
      />
      <div className="flex min-h-0 flex-1 gap-4 p-6">
        <div className="flex min-h-0 w-80 flex-col gap-3 rounded-lg border border-white/8 bg-white/[0.03]">
          <div className="border-b border-white/8 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <h2 className="truncate text-sm font-medium text-white">{workflow.name}</h2>
                <p className="mt-0.5 truncate font-mono text-xs text-zinc-500">{workflow.id}</p>
              </div>
              <Badge variant="outline" className={cn('shrink-0', statusBadge)}>
                {status}
              </Badge>
            </div>
          </div>

          <div className="space-y-3 px-4 text-xs text-zinc-400">
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-lg border border-white/8 bg-black/20 p-3">
                <p className="text-zinc-500">Mode</p>
                <p className="mt-1 text-sm font-medium text-white">{mode === 'recompile' ? 'Recompile' : 'Compile'}</p>
              </div>
              <div className="rounded-lg border border-white/8 bg-black/20 p-3">
                <p className="text-zinc-500">API calls</p>
                <p className="mt-1 text-sm font-medium text-white">{apiEvents.length}</p>
              </div>
            </div>
            <div className="rounded-lg border border-white/8 bg-black/20 p-3">
              <p className="text-zinc-500">Job</p>
              <p className="mt-1 break-all font-mono text-[11px] text-zinc-300">{jobId || 'Not started'}</p>
            </div>
            {error ? (
              <div className="flex gap-2 rounded-lg border border-red-500/20 bg-red-500/5 p-3 text-red-300">
                <AlertCircle className="mt-0.5 size-4 shrink-0" />
                <p>{error}</p>
              </div>
            ) : null}
            {streamError ? (
              <div className="flex gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-amber-300">
                <Radio className="mt-0.5 size-4 shrink-0" />
                <p>{streamError}</p>
              </div>
            ) : null}
          </div>

          <div className="mt-auto space-y-2 border-t border-white/8 p-4">
            {!jobId && (
              <Button size="sm" onClick={() => void (mode === 'recompile' ? startRecompile() : startFirstCompile())}>
                <Play className="size-3.5" />
                Start {mode === 'recompile' ? 'Recompile' : 'Compile'}
              </Button>
            )}
            {status === 'enqueuing' && !jobId ? (
              <Button
                size="sm"
                variant="outline"
                className="border-amber-500/30 bg-amber-500/5 text-amber-300 hover:bg-amber-500/10"
                onClick={() => void retryFirstCompile()}
              >
                <RefreshCw className="size-3.5" />
                Force new compile job
              </Button>
            ) : null}
            {status === 'succeeded' ? (
              <div className="flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-xs text-emerald-300">
                <CheckCircle2 className="size-4 shrink-0" />
                Compile finished.
              </div>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" asChild>
                <Link href={`/plugins/${pluginId}`}>
                  <ArrowLeft className="size-3.5" />
                  Plugin
                </Link>
              </Button>
              {skillId ? (
                <Button
                  size="sm"
                  variant="outline"
                  className="border-amber-500/30 bg-amber-500/5 text-amber-300 hover:bg-amber-500/10"
                  onClick={() => void startRecompile()}
                  disabled={jobActive}
                >
                  {jobActive ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
                  Recompile
                </Button>
              ) : null}
              {!skillId && isTerminal(status) ? (
                <Button
                  size="sm"
                  variant="outline"
                  className="border-amber-500/30 bg-amber-500/5 text-amber-300 hover:bg-amber-500/10"
                  onClick={handleRecompileClick}
                  disabled={jobActive}
                >
                  <RefreshCw className="size-3.5" />
                  Recompile
                </Button>
              ) : null}
              {skillId ? (
                <Button size="sm" variant="outline" asChild>
                  <Link href={`/edit/${skillId}?from=${encodeURIComponent(`/plugins/${pluginId}`)}`}>
                    <ExternalLink className="size-3.5" />
                    Edit
                  </Link>
                </Button>
              ) : null}
            </div>
          </div>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(320px,0.45fr)] gap-4">
          <div className="flex min-h-0 flex-col rounded-lg border border-white/8 bg-white/[0.03]">
            <div className="flex items-center gap-2 border-b border-white/8 px-4 py-3">
              <Terminal className="size-4 text-zinc-400" />
              <h3 className="text-sm font-medium text-white">Compile Log</h3>
            </div>
            <div ref={logRef} className="min-h-0 flex-1 overflow-y-auto bg-black/30 p-3 font-mono text-[11px] text-zinc-400">
              {events.length === 0 ? (
                <p className="text-zinc-600">Compile logs will appear here...</p>
              ) : (
                events.map((event, index) => (
                  <div key={`${event.ts}-${index}`} className="whitespace-pre-wrap break-words">
                    <span className="text-zinc-600">[{formatTime(event.ts)}]</span>{' '}
                    <span className={event.event === 'api_call' ? 'text-sky-300' : 'text-zinc-300'}>{event.event}</span>{' '}
                    <span>{event.message}</span>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="flex min-h-0 flex-col gap-4">
            <div className="flex min-h-0 basis-44 shrink-0 flex-col rounded-lg border border-white/8 bg-white/[0.03]">
              <div className="flex items-center gap-2 border-b border-white/8 px-4 py-3">
                <RefreshCw className="size-4 text-zinc-400" />
                <h3 className="text-sm font-medium text-white">Phase Timeline</h3>
              </div>
              <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
                {phaseEvents.length === 0 ? (
                  <p className="text-xs text-zinc-600">No phase events yet.</p>
                ) : (
                  phaseEvents.map((event, index) => (
                    <div key={`${event.ts}-${index}`} className={cn('rounded-lg border px-3 py-2', eventTone(event))}>
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-xs font-medium">{event.message}</p>
                        <span className="shrink-0 text-[10px] opacity-60">{formatTime(event.ts)}</span>
                      </div>
                      <p className="mt-1 font-mono text-[10px] opacity-70">{String(event.data.phase || event.event)}</p>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-white/8 bg-white/[0.03]">
              <div className="flex items-center gap-2 border-b border-white/8 px-4 py-3">
                <Code2 className="size-4 text-zinc-400" />
                <h3 className="text-sm font-medium text-white">API Calls</h3>
              </div>
              <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
                {apiEvents.length === 0 ? (
                  <p className="text-xs text-zinc-600">LLM/API calls will appear here.</p>
                ) : (
                  apiEvents.map((event, index) => (
                    <details key={`${event.ts}-${index}`} className="rounded-lg border border-sky-500/20 bg-sky-500/5 px-3 py-2 text-xs text-sky-100">
                      <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
                        <span className="min-w-0 truncate">
                          {String(event.data.task || 'api')} / {String(event.data.provider || 'provider')}
                        </span>
                        <span className="shrink-0 text-[10px] text-sky-100/60">
                          {typeof event.data.duration_ms === 'number' ? `${event.data.duration_ms}ms` : formatTime(event.ts)}
                        </span>
                      </summary>
                      <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded border border-white/8 bg-black/30 p-2 font-mono text-[10px] text-sky-100/75">
                        {dataString(event.data)}
                      </pre>
                    </details>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
