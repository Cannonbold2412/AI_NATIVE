import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import {
  fetchMetrics,
  postCompileSession,
  postStartRecording,
  getRecordingStatus,
} from '../api/workflowApi'

type Options = {
  onCompileSuccess?: (skillId: string) => void
}

/**
 * Start recording from home, poll until browser closes, then compile.
 * No "stop" control — user closes the browser to finish.
 */
export function useRecordingSession(options?: Options) {
  const onCompileSuccess = options?.onCompileSuccess
  const [startUrl, setStartUrl] = useState('')
  const [skillTitle, setSkillTitle] = useState('')
  const [flowStatus, setFlowStatus] = useState('Idle')
  const [logLines, setLogLines] = useState<string[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [isRecording, setIsRecording] = useState(false)
  const [isCompiling, setIsCompiling] = useState(false)
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null)
  const pollingRef = useRef<number | null>(null)
  const lastEventCount = useRef(0)

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

  const refreshMetrics = useCallback(() => {
    fetchMetrics()
      .then((data) => {
        setMetrics(data)
      })
      .catch((err: Error) => {
        setMetrics({ error: err.message })
        appendLog(`metrics_error: ${err.message}`)
      })
  }, [appendLog])

  const compileFromSession = useCallback(
    async (activeSessionId: string) => {
      setIsCompiling(true)
      setFlowStatus('Compiling skill package...')
      appendLog(`compile_started: session=${activeSessionId}`)
      try {
        const result = await postCompileSession(activeSessionId, skillTitle)
        setFlowStatus('Compiled. You can open Human edit to review steps.')
        appendLog(`compile_done: skill=${result.skill_id}, steps=${result.step_count}`)
        refreshMetrics()
        toast.success(
          onCompileSuccess
            ? 'Compiled. Opening Human edit…'
            : `Compiled skill ${result.skill_id} (${result.step_count} steps)`,
        )
        onCompileSuccess?.(result.skill_id)
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        setFlowStatus('Compile failed. Check logs and retry.')
        appendLog(`compile_error: ${msg}`)
        toast.error('Compile failed')
      } finally {
        setIsCompiling(false)
      }
    },
    [appendLog, onCompileSuccess, refreshMetrics, skillTitle],
  )

  const startFlow = useCallback(async () => {
    if (!startUrl.trim()) {
      setFlowStatus('Start URL is required.')
      toast.error('Start URL is required')
      return
    }
    if (isRecording || isCompiling) return
    stopPolling()
    setSessionId(null)
    setLogLines(['[system] flow started'])
    lastEventCount.current = 0
    setFlowStatus('Starting browser recorder...')
    try {
      const start = await postStartRecording(startUrl.trim())
      setSessionId(start.session_id)
      setIsRecording(true)
      setFlowStatus('Browser opened. When done, close the browser; capture will compile automatically.')
      appendLog(`recording_started: session=${start.session_id}`)
      toast.success('Recording started')
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setFlowStatus('Could not start recorder.')
      appendLog(`start_error: ${msg}`)
      toast.error('Could not start recorder')
    }
  }, [appendLog, isCompiling, isRecording, startUrl, stopPolling])

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

  useEffect(() => {
    void refreshMetrics()
  }, [refreshMetrics])

  return {
    startUrl,
    setStartUrl,
    skillTitle,
    setSkillTitle,
    flowStatus,
    logLines,
    sessionId,
    isRecording,
    isCompiling,
    metrics,
    appendLog,
    startFlow,
    refreshMetrics,
  }
}
