import { useEffect } from 'react'
import { Layers } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useUpdater } from '@/hooks/useUpdater'

interface Props {
  currentVersion: string
  latestVersion: string
}

function formatBytes(bytes: number): string {
  const units = ['B', 'KB', 'MB', 'GB']
  let n = bytes
  let unit = 0
  while (n >= 1024 && unit < units.length - 1) { n /= 1024; unit++ }
  return `${n.toFixed(unit === 0 || n >= 100 ? 0 : 1)} ${units[unit]}`
}

export function UpdateRequiredScreen({ currentVersion, latestVersion }: Props) {
  const { status, startDownload, install } = useUpdater()

  useEffect(() => {
    if (status.phase === 'downloaded') install()
  }, [status.phase, install])

  const isIdle = status.phase === 'idle'
  const isDownloading = status.phase === 'downloading'
  const isDownloaded = status.phase === 'downloaded'
  const hasError = status.phase === 'error'

  return (
    <div className="fixed inset-0 flex items-center justify-center bg-[#090b0d]">
      <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-[#0d0f12] p-8 shadow-2xl">
        <div className="mb-6 flex justify-center">
          <div className="flex size-12 items-center justify-center rounded-xl border border-white/10 bg-white/5">
            <Layers className="size-6 text-white/70" />
          </div>
        </div>

        <h1 className="mb-1 text-center text-xl font-semibold text-white">Update Required</h1>
        <p className="mb-6 text-center text-sm text-zinc-400">
          A new version of Conxa Build Studio is available. Please update to continue.
        </p>

        <div className="mb-6 space-y-2">
          <div className="rounded-lg border border-white/8 bg-black/20 p-3">
            <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">Installed version</p>
            <p className="mt-1 text-sm text-white">{currentVersion}</p>
          </div>
          <div className="rounded-lg border border-white/8 bg-black/20 p-3">
            <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">New version</p>
            <p className="mt-1 text-sm text-white">{latestVersion}</p>
          </div>
        </div>

        {isDownloading && status.phase === 'downloading' && (
          <div className="mb-5">
            <div className="mb-1.5 flex justify-between text-xs text-zinc-500">
              <span>
                {formatBytes(status.transferred)} of {formatBytes(status.total)}
                {status.bytesPerSecond > 0 && ` — ${formatBytes(status.bytesPerSecond)}/s`}
              </span>
              <span>{Math.round(status.percent)}%</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-white/5">
              <div
                className="h-full rounded-full bg-blue-500 transition-all duration-300"
                style={{ width: `${status.percent}%` }}
              />
            </div>
          </div>
        )}

        {isDownloaded && (
          <p className="mb-5 text-center text-sm text-zinc-400">Installing and restarting...</p>
        )}

        {hasError && status.phase === 'error' && (
          <div className="mb-5 rounded-lg border border-red-900/60 bg-red-950/30 p-3">
            <p className="text-xs text-red-400">{status.message}</p>
          </div>
        )}

        <div className="space-y-2">
          {(isIdle || hasError) && (
            <Button className="w-full" onClick={startDownload}>
              {hasError ? 'Retry update' : 'Update now'}
            </Button>
          )}
          {isDownloading && (
            <Button className="w-full" disabled>
              Downloading...
            </Button>
          )}
          {isDownloaded && (
            <Button className="w-full" disabled>
              Installing...
            </Button>
          )}
          {(isIdle || hasError) && (
            <Button
              variant="ghost"
              className="w-full text-zinc-600 hover:text-zinc-400"
              onClick={() => window.conxa.windowControls.close()}
            >
              Quit
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
