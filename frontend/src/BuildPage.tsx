'use client'

import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { buildInstaller, buildPlugin, fetchPlugins, installerDownloadUrl, normalizePluginList } from '@/api/pluginApi'
import { AppShell } from '@/components/layout/AppLayout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CheckCircle2, Download, Loader2, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

export function BuildPage() {
  const pluginsQ = useQuery({
    queryKey: ['plugins'],
    queryFn: fetchPlugins,
  })

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [building, setBuilding] = useState(false)
  const [buildError, setBuildError] = useState('')
  const [buildDone, setBuildDone] = useState(false)
  const [buildingInstaller, setBuildingInstaller] = useState(false)
  const [installerDone, setInstallerDone] = useState(false)
  const [installerError, setInstallerError] = useState('')
  const logRef = useRef<HTMLDivElement>(null)

  const plugins = normalizePluginList(pluginsQ.data)
  const selectedPlugin = plugins.find((p) => p.id === selectedId)

  async function streamSse(response: Response, onLog: (msg: string) => void): Promise<boolean> {
    if (!response.body) throw new Error('No response body')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const parts = buf.split('\n\n')
      buf = parts.pop() ?? ''
      for (const part of parts) {
        const line = part.replace(/^data: /, '').trim()
        if (!line) continue
        try {
          const parsed = JSON.parse(line) as { event: string; entry?: { message?: string }; message?: string }
          if (parsed.event === 'log') {
            const msg = parsed.entry?.message ?? JSON.stringify(parsed.entry)
            onLog(msg)
            setTimeout(() => logRef.current?.scrollTo(0, logRef.current.scrollHeight), 0)
          } else if (parsed.event === 'done') {
            return true
          } else if (parsed.event === 'error') {
            throw new Error(parsed.message ?? 'Failed')
          }
        } catch (e) {
          if (e instanceof Error && (e.message.includes('Failed') || e.message.includes('error'))) throw e
        }
      }
    }
    return false
  }

  async function handleBuild() {
    if (!selectedId) return
    setLogs([])
    setBuildError('')
    setBuildDone(false)
    setInstallerDone(false)
    setInstallerError('')
    setBuilding(true)
    try {
      const response = await buildPlugin(selectedId)
      await streamSse(response, (msg) => setLogs((prev) => [...prev, msg]))
      setBuildDone(true)
      void pluginsQ.refetch()
    } catch (e) {
      setBuildError(e instanceof Error ? e.message : 'Build failed')
    } finally {
      setBuilding(false)
    }
  }

  async function handleBuildInstaller() {
    if (!selectedId) return
    setInstallerError('')
    setInstallerDone(false)
    setBuildingInstaller(true)
    try {
      const response = await buildInstaller(selectedId)
      await streamSse(response, (msg) => setLogs((prev) => [...prev, `[installer] ${msg}`]))
      setInstallerDone(true)
      void pluginsQ.refetch()
    } catch (e) {
      setInstallerError(e instanceof Error ? e.message : 'Installer build failed')
    } finally {
      setBuildingInstaller(false)
    }
  }

  if (pluginsQ.isLoading) {
    return (
      <AppShell title="Build Plugin" mainClassName="overflow-hidden">
        <p className="p-6 text-sm text-zinc-500">Loading…</p>
      </AppShell>
    )
  }

  if (pluginsQ.isError || !pluginsQ.data) {
    return (
      <AppShell title="Build Plugin" mainClassName="overflow-hidden">
        <p className="p-6 text-sm text-red-400">{(pluginsQ.error as Error)?.message ?? 'Failed to load plugins'}</p>
      </AppShell>
    )
  }

  return (
    <AppShell title="Build Plugin" mainClassName="overflow-hidden">
      <div className="flex h-full min-h-0 flex-1 gap-4 p-6">
        {/* Left: Plugin list */}
        <div className="flex min-h-0 w-72 flex-col gap-3 rounded-lg border border-white/8 bg-white/[0.03]">
          <div className="border-b border-white/8 px-4 py-3">
            <h2 className="text-sm font-medium text-white">Plugins</h2>
            <p className="mt-0.5 text-xs text-zinc-500">{plugins.length} total</p>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-2">
            {plugins.length === 0 ? (
              <p className="px-2 py-4 text-xs text-zinc-500">No plugins</p>
            ) : (
              <div className="space-y-1">
                {plugins.map((plugin) => (
                  <button
                    key={plugin.id}
                    onClick={() => setSelectedId(plugin.id)}
                    className={cn(
                      'w-full rounded-lg border border-transparent px-3 py-2.5 text-left text-sm transition-colors',
                      'hover:border-white/8 hover:bg-white/[0.07] hover:text-white',
                      selectedId === plugin.id
                        ? 'border-white/10 bg-white/[0.10] text-white'
                        : 'text-zinc-300',
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate font-medium">{plugin.name}</p>
                        <p className="mt-0.5 truncate text-xs text-zinc-500">{plugin.id}</p>
                      </div>
                      <Badge
                        variant="outline"
                        className={cn(
                          'shrink-0 text-[10px]',
                          plugin.status === 'ready'
                            ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                            : plugin.status === 'needs_auth'
                              ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
                              : 'border-red-500/30 bg-red-500/10 text-red-300',
                        )}
                      >
                        {plugin.status}
                      </Badge>
                    </div>
                    {plugin.build && (
                      <p className="mt-1 text-xs text-zinc-500">
                        v{plugin.build.version} • {new Date(plugin.build.last_built_at * 1000).toLocaleDateString()}
                      </p>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right: Build area */}
        <div className="flex min-h-0 flex-1 flex-col gap-3 rounded-lg border border-white/8 bg-white/[0.03]">
          {selectedPlugin ? (
            <>
              {/* Header */}
              <div className="border-b border-white/8 px-4 py-3">
                <h3 className="text-sm font-medium text-white">{selectedPlugin.name}</h3>
                <p className="mt-0.5 text-xs text-zinc-500">{selectedPlugin.workflows.length} workflows</p>
              </div>

              {/* Build controls */}
              <div className="flex flex-wrap gap-2 px-4">
                <Button
                  size="sm"
                  onClick={handleBuild}
                  disabled={
                    building || buildingInstaller || selectedPlugin.status !== 'ready' || selectedPlugin.workflows.length === 0
                  }
                >
                  {building ? (
                    <>
                      <Loader2 className="size-4 animate-spin" />
                      Building…
                    </>
                  ) : (
                    'Build Plugin'
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleBuildInstaller}
                  disabled={buildingInstaller || building || !selectedPlugin.build}
                  title={!selectedPlugin.build ? 'Build the plugin first' : 'Build Windows installer EXE'}
                >
                  {buildingInstaller ? (
                    <>
                      <Loader2 className="size-4 animate-spin" />
                      Building installer…
                    </>
                  ) : (
                    'Build Installer (.exe)'
                  )}
                </Button>
                {selectedPlugin.installer && (
                  <a
                    href={installerDownloadUrl(selectedPlugin.id)}
                    download
                    className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-white hover:bg-white/10 transition-colors"
                  >
                    <Download className="size-3.5" />
                    Download {selectedPlugin.installer.filename}
                  </a>
                )}
              </div>

              {/* Logs */}
              <div className="flex min-h-0 flex-1 flex-col gap-2 px-4 pb-4">
                {buildDone && (
                  <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2.5 space-y-1.5">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="size-4 shrink-0 text-emerald-400" />
                      <p className="text-xs font-medium text-emerald-300">Plugin built — now build the installer</p>
                    </div>
                    <p className="text-xs text-emerald-200/70 pl-6">
                      Click <strong>Build Installer (.exe)</strong> to generate a Windows setup file your users can double-click.
                    </p>
                  </div>
                )}
                {installerDone && (
                  <div className="rounded-lg border border-sky-500/20 bg-sky-500/5 px-3 py-2.5 space-y-1.5">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="size-4 shrink-0 text-sky-400" />
                      <p className="text-xs font-medium text-sky-300">Installer ready — share it with your users</p>
                    </div>
                    <p className="text-xs text-sky-200/70 pl-6">
                      Users double-click the EXE, then open Claude Desktop. Skills appear automatically.
                    </p>
                  </div>
                )}
                {buildError && (
                  <div className="flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2">
                    <XCircle className="size-4 shrink-0 text-red-400" />
                    <p className="text-xs text-red-300">{buildError}</p>
                  </div>
                )}
                {installerError && (
                  <div className="flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2">
                    <XCircle className="size-4 shrink-0 text-red-400" />
                    <p className="text-xs text-red-300">{installerError}</p>
                  </div>
                )}
                <div
                  ref={logRef}
                  className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-white/8 bg-black/30 p-3 font-mono text-[11px] text-zinc-400"
                >
                  {logs.length === 0 ? (
                    <p className="text-zinc-600">Build logs will appear here…</p>
                  ) : (
                    logs.map((line, i) => (
                      <div key={i}>{line}</div>
                    ))
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center">
              <p className="text-sm text-zinc-500">Select a plugin to build</p>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  )
}
