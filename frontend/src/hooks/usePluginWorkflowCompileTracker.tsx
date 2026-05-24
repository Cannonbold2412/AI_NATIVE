'use client'

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { updateWorkflow } from '@/api/pluginApi'
import { enqueueCompileJob, fetchJob, type JobStatus } from '@/api/workflowApi'

type CompileStatus = JobStatus | 'enqueuing'

export type PluginWorkflowCompileEntry = {
  pluginId: string
  workflowId: string
  sessionId: string
  workflowName: string
  jobId: string | null
  status: CompileStatus
  error: string | null
  updatedAt: number
}

type StartCompileInput = {
  pluginId: string
  workflowId: string
  sessionId: string
  workflowName: string
}

type CompileTrackerContextValue = {
  getCompile: (pluginId: string, workflowId: string) => PluginWorkflowCompileEntry | undefined
  isCompileActive: (pluginId: string, workflowId: string) => boolean
  startCompile: (input: StartCompileInput) => Promise<void>
  clearCompile: (pluginId: string, workflowId: string) => void
}

const STORAGE_KEY = 'conxa.pluginWorkflowCompileJobs.v1'
const ACTIVE_STATUSES: CompileStatus[] = ['enqueuing', 'queued', 'running']
const TERMINAL_STATUSES: JobStatus[] = ['succeeded', 'failed', 'canceled']

const PluginWorkflowCompileContext = createContext<CompileTrackerContextValue | null>(null)

function compileKey(pluginId: string, workflowId: string) {
  return `${pluginId}:${workflowId}`
}

function isActiveStatus(status: CompileStatus) {
  return ACTIVE_STATUSES.includes(status)
}

function messageFromError(err: unknown, fallback: string) {
  if (err instanceof Error && err.message.trim()) return err.message.trim()
  return fallback
}

function isStoredEntry(value: unknown): value is PluginWorkflowCompileEntry {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const entry = value as Partial<PluginWorkflowCompileEntry>
  return (
    typeof entry.pluginId === 'string' &&
    typeof entry.workflowId === 'string' &&
    typeof entry.sessionId === 'string' &&
    typeof entry.workflowName === 'string' &&
    (typeof entry.jobId === 'string' || entry.jobId === null) &&
    typeof entry.status === 'string' &&
    [...ACTIVE_STATUSES, ...TERMINAL_STATUSES].includes(entry.status as CompileStatus)
  )
}

function loadStoredEntries(): Record<string, PluginWorkflowCompileEntry> {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}

    const entries: Record<string, PluginWorkflowCompileEntry> = {}
    Object.values(parsed).forEach((value) => {
      if (!isStoredEntry(value)) return
      const key = compileKey(value.pluginId, value.workflowId)
      entries[key] =
        value.status === 'enqueuing' && !value.jobId
          ? {
              ...value,
              status: 'failed',
              error: 'Compile was interrupted before a job was created. Retry compile.',
              updatedAt: Date.now(),
            }
          : { ...value, error: value.error ?? null, updatedAt: value.updatedAt || Date.now() }
    })
    return entries
  } catch {
    return {}
  }
}

function extractSkillId(job: Awaited<ReturnType<typeof fetchJob>>) {
  const resultSkillId = job.result?.skill_id
  if (typeof resultSkillId === 'string' && resultSkillId.trim()) return resultSkillId
  if (typeof job.resource_id === 'string' && job.resource_id.trim() && !job.resource_id.startsWith('skill_')) {
    return job.resource_id
  }
  return null
}

export function PluginWorkflowCompileProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const pollingKeysRef = useRef(new Set<string>())
  const [entries, setEntries] = useState<Record<string, PluginWorkflowCompileEntry>>(loadStoredEntries)

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries))
    } catch {
      // Tracking is best-effort; a storage failure should not break compile controls.
    }
  }, [entries])

  const clearCompile = useCallback((pluginId: string, workflowId: string) => {
    const key = compileKey(pluginId, workflowId)
    setEntries((prev) => {
      if (!prev[key]) return prev
      const next = { ...prev }
      delete next[key]
      return next
    })
  }, [])

  const markFailed = useCallback((entry: PluginWorkflowCompileEntry, error: string, status: JobStatus = 'failed') => {
    const key = compileKey(entry.pluginId, entry.workflowId)
    setEntries((prev) => ({
      ...prev,
      [key]: {
        ...entry,
        status,
        error,
        updatedAt: Date.now(),
      },
    }))
  }, [])

  const pollEntry = useCallback(
    async (entry: PluginWorkflowCompileEntry) => {
      if (!entry.jobId) return
      const key = compileKey(entry.pluginId, entry.workflowId)
      if (pollingKeysRef.current.has(key)) return
      pollingKeysRef.current.add(key)

      try {
        const job = await fetchJob(entry.jobId)
        if (job.status === 'queued' || job.status === 'running') {
          setEntries((prev) => ({
            ...prev,
            [key]: {
              ...entry,
              status: job.status,
              error: null,
              updatedAt: Date.now(),
            },
          }))
          return
        }

        if (job.status === 'succeeded') {
          const skillId = extractSkillId(job)
          if (!skillId) {
            markFailed(entry, 'Compile finished but did not return a skill id.')
            return
          }
          try {
            await updateWorkflow(entry.pluginId, entry.workflowId, { skill_id: skillId })
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: ['plugin', entry.pluginId] }),
              queryClient.invalidateQueries({ queryKey: ['plugins'] }),
            ])
            clearCompile(entry.pluginId, entry.workflowId)
          } catch (err) {
            markFailed(entry, messageFromError(err, 'Compiled, but failed to save workflow status. Retry compile.'))
          }
          return
        }

        markFailed(entry, job.user_error || `Compile job ${job.status}.`, job.status)
      } catch (err) {
        markFailed(entry, messageFromError(err, 'Compile status unavailable. Retry compile.'))
      } finally {
        pollingKeysRef.current.delete(key)
      }
    },
    [clearCompile, markFailed, queryClient],
  )

  useEffect(() => {
    const activeEntries = Object.values(entries).filter((entry) => entry.jobId && isActiveStatus(entry.status))
    if (activeEntries.length === 0) return

    const tick = () => {
      activeEntries.forEach((entry) => {
        void pollEntry(entry)
      })
    }

    tick()
    const interval = window.setInterval(tick, 1500)
    return () => window.clearInterval(interval)
  }, [entries, pollEntry])

  const startCompile = useCallback(async (input: StartCompileInput) => {
    const key = compileKey(input.pluginId, input.workflowId)
    let shouldStart = true

    setEntries((prev) => {
      const existing = prev[key]
      if (existing && isActiveStatus(existing.status)) {
        shouldStart = false
        return prev
      }
      return {
        ...prev,
        [key]: {
          ...input,
          jobId: null,
          status: 'enqueuing',
          error: null,
          updatedAt: Date.now(),
        },
      }
    })

    if (!shouldStart) return

    try {
      const job = await enqueueCompileJob(input.sessionId, input.workflowName)
      setEntries((prev) => ({
        ...prev,
        [key]: {
          ...(prev[key] ?? input),
          jobId: job.job_id,
          status: job.status,
          error: null,
          updatedAt: Date.now(),
        },
      }))
    } catch (err) {
      setEntries((prev) => ({
        ...prev,
        [key]: {
          ...(prev[key] ?? input),
          jobId: null,
          status: 'failed',
          error: messageFromError(err, 'Could not start compile job.'),
          updatedAt: Date.now(),
        },
      }))
    }
  }, [])

  const getCompile = useCallback(
    (pluginId: string, workflowId: string) => entries[compileKey(pluginId, workflowId)],
    [entries],
  )

  const isCompileActive = useCallback(
    (pluginId: string, workflowId: string) => {
      const entry = entries[compileKey(pluginId, workflowId)]
      return Boolean(entry && isActiveStatus(entry.status))
    },
    [entries],
  )

  const value = useMemo(
    () => ({ getCompile, isCompileActive, startCompile, clearCompile }),
    [clearCompile, getCompile, isCompileActive, startCompile],
  )

  return (
    <PluginWorkflowCompileContext.Provider value={value}>
      {children}
    </PluginWorkflowCompileContext.Provider>
  )
}

export function usePluginWorkflowCompileTracker() {
  const context = useContext(PluginWorkflowCompileContext)
  if (!context) {
    throw new Error('usePluginWorkflowCompileTracker must be used within PluginWorkflowCompileProvider')
  }
  return context
}
