'use client'

import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { buildPlugin, fetchPlugins, normalizePluginList } from '@/api/pluginApi'
import { AppShell } from '@/components/layout/AppLayout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CheckCircle2, Loader2, XCircle } from 'lucide-react'
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
  const logRef = useRef<HTMLDivElement>(null)

  const plugins = normalizePluginList(pluginsQ.data)
  const selectedPlugin = plugins.find((p) => p.id === selectedId)

  async function handleBuild() {
    if (!selectedId) return
    setLogs([])
    setBuildError('')
    setBuildDone(false)
    setBuilding(true)
    try {
      const response = await buildPlugin(selectedId)
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
              setLogs((prev) => [...prev, msg])
              setTimeout(() => logRef.current?.scrollTo(0, logRef.current.scrollHeight), 0)
            } else if (parsed.event === 'done') {
              setBuildDone(true)
              void pluginsQ.refetch()
            } else if (parsed.event === 'error') {
              setBuildError(parsed.message ?? 'Build failed')
            }
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (e) {
      setBuildError(e instanceof Error ? e.message : 'Build failed')
    } finally {
      setBuilding(false)
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
                    building || selectedPlugin.status !== 'ready' || selectedPlugin.workflows.length === 0
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
              </div>

              {/* Logs */}
              <div className="flex min-h-0 flex-1 flex-col gap-2 px-4 pb-4">
                {buildDone && (
                  <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2.5 space-y-1.5">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="size-4 shrink-0 text-emerald-400" />
                      <p className="text-xs font-medium text-emerald-300">MCP server built — ready to install</p>
                    </div>
                    <p className="text-xs text-emerald-200/70 pl-6">
                      In Claude Code: <span className="font-mono">Settings → MCP Servers → Add from GitHub</span>
                    </p>
                    <p className="text-xs text-emerald-200/70 pl-6">
                      First run: ask Claude to call <span className="font-mono">bootstrap_auth</span>
                    </p>
                  </div>
                )}
                {buildError && (
                  <div className="flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2">
                    <XCircle className="size-4 shrink-0 text-red-400" />
                    <p className="text-xs text-red-300">{buildError}</p>
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
