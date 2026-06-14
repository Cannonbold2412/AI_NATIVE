import { useCallback, useEffect, useRef, useState } from 'react'

export type UpdateStatus =
  | { phase: 'idle' }
  | { phase: 'checking' }
  | { phase: 'not-available' }
  | { phase: 'available'; currentVersion: string; latestVersion: string }
  | { phase: 'downloading'; percent: number; bytesPerSecond: number; transferred: number; total: number }
  | { phase: 'downloaded' }
  | { phase: 'error'; message: string }

export function useUpdater() {
  const [status, setStatus] = useState<UpdateStatus>({ phase: 'idle' })
  const [currentVersion, setCurrentVersion] = useState('')
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    window.conxa.update.getVersion()
      .then((v) => { if (mounted.current) setCurrentVersion(v) })
      .catch(() => {})

    const unsub = window.conxa.update.onStatus((msg) => {
      if (!mounted.current) return
      if (msg.phase === 'download-progress') {
        setStatus({ phase: 'downloading', percent: msg.percent, bytesPerSecond: msg.bytesPerSecond, transferred: msg.transferred, total: msg.total })
      } else if (msg.phase === 'downloaded') {
        setStatus({ phase: 'downloaded' })
      } else if (msg.phase === 'error') {
        setStatus({ phase: 'error', message: msg.message })
      }
    })

    return () => {
      mounted.current = false
      unsub()
    }
  }, [])

  const check = useCallback(async () => {
    setStatus({ phase: 'checking' })
    try {
      const result = await window.conxa.update.check()
      if (!mounted.current) return
      setCurrentVersion(result.currentVersion)
      if (result.available && result.latestVersion) {
        setStatus({ phase: 'available', currentVersion: result.currentVersion, latestVersion: result.latestVersion })
      } else {
        setStatus({ phase: 'not-available' })
      }
    } catch {
      if (mounted.current) setStatus({ phase: 'not-available' })
    }
  }, [])

  const startDownload = useCallback(async () => {
    try {
      await window.conxa.update.start()
    } catch (err) {
      if (mounted.current) setStatus({ phase: 'error', message: String(err) })
    }
  }, [])

  const install = useCallback(() => {
    window.conxa.update.install()
  }, [])

  return { status, currentVersion, check, startDownload, install }
}
