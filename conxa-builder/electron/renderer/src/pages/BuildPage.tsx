import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { buildPlugin, fetchPlugins, normalizePluginList, type PluginBuild } from '@/api/pluginApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { PluginWorkflowTests, workflowTestSummary } from '@/components/PluginWorkflowTests'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CheckCircle2, FolderKanban, Loader2, PackageCheck, XCircle } from 'lucide-react'
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
  const [buildResult, setBuildResult] = useState<PluginBuild | null>(null)
  const logRef = useRef<HTMLDivElement>(null)

  const plugins = normalizePluginList(pluginsQ.data)
  const selectedPlugin = plugins.find((p) => p.id === selectedId)
  const currentBuildResult = buildResult
  const hasBuiltPackage = Boolean(selectedPlugin?.build || currentBuildResult)
  const testSummary = selectedPlugin
    ? workflowTestSummary(selectedPlugin)
    : { passed: 0, total: 0, allPassed: false }

  const uncompiled = selectedPlugin?.workflows.filter((w) => !w.skill_id) ?? []
  const unedited = selectedPlugin?.workflows.filter((w) => w.skill_id && !w.edited_at) ?? []
  const buildBlocked = uncompiled.length > 0 || unedited.length > 0
  const stale =
    selectedPlugin?.build &&
    selectedPlugin.workflows.some(
      (w) => w.edited_at && w.edited_at > (selectedPlugin.build?.last_built_at ?? 0),
    )

  function selectPlugin(pluginId: string) {
    setSelectedId(pluginId)
    setLogs([])
    setBuildError('')
    setBuildDone(false)
    setBuildResult(null)
  }

  async function handleBuild() {
    if (!selectedId) return
    setLogs([])
    setBuildError('')
    setBuildDone(false)
    setBuildResult(null)
    setBuilding(true)
    try {
      const result = await buildPlugin(selectedId, '0.1.0', (msg) => {
        setLogs((prev) => [...prev, msg])
        setTimeout(() => logRef.current?.scrollTo(0, logRef.current.scrollHeight), 0)
      })
      setBuildResult(result)
      setBuildDone(true)
      void pluginsQ.refetch()
    } catch (e) {
      setBuildError(e instanceof Error ? e.message : 'Build failed')
    } finally {
      setBuilding(false)
    }
  }

  if (pluginsQ.isLoading) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <PageHeader title="Build Plugin" />
        <div className="min-h-0 flex-1 overflow-hidden">
          <p className="p-6 text-sm text-zinc-500">Loading...</p>
        </div>
      </div>
    )
  }

  if (pluginsQ.isError || !pluginsQ.data) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <PageHeader title="Build Plugin" />
        <div className="min-h-0 flex-1 overflow-hidden">
          <p className="p-6 text-sm text-red-400">{(pluginsQ.error as Error)?.message ?? 'Failed to load plugins'}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader title="Build Plugin" description="Compile a recorded plugin into a generated package. Installer builds now live on Build Installer." />
      <div className="flex min-h-0 flex-1 gap-4 p-6">
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
                    onClick={() => selectPlugin(plugin.id)}
                    className={cn(
                      'w-full cursor-pointer rounded-lg border border-transparent px-3 py-2.5 text-left text-sm transition-colors',
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
                        v{plugin.build.version} - {new Date(plugin.build.last_built_at * 1000).toLocaleDateString()}
                      </p>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 rounded-lg border border-white/8 bg-white/[0.03]">
          {selectedPlugin ? (
            <>
              <div className="border-b border-white/8 px-4 py-3">
                <h3 className="text-sm font-medium text-white">{selectedPlugin.name}</h3>
                <p className="mt-0.5 text-xs text-zinc-500">{selectedPlugin.workflows.length} workflows</p>
              </div>

              {buildBlocked && (
                <div className="mx-4 mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-300">
                  {uncompiled.length > 0 && (
                    <p>Compile first: {uncompiled.map((w) => w.name).join(', ')}</p>
                  )}
                  {unedited.length > 0 && (
                    <p>Open editor and sign off: {unedited.map((w) => w.name).join(', ')}</p>
                  )}
                </div>
              )}
              {stale && !buildBlocked && (
                <div className="mx-4 mt-3 rounded-lg border border-sky-500/20 bg-sky-500/5 px-3 py-2 text-xs text-sky-300">
                  Workflows edited since last build — rebuild then re-test before creating the installer.
                </div>
              )}
              <div className="flex flex-wrap gap-2 px-4">
                <Button
                  size="sm"
                  onClick={handleBuild}
                  disabled={building || selectedPlugin.status !== 'ready' || selectedPlugin.workflows.length === 0 || buildBlocked}
                >
                  {building ? (
                    <>
                      <Loader2 className="size-4 animate-spin" />
                      Building...
                    </>
                  ) : (
                    'Build Plugin'
                  )}
                </Button>
                {selectedPlugin.build ? (
                  <Button size="sm" variant="outline" asChild>
                    <Link to="/packages">
                      <FolderKanban className="size-3.5" />
                      Open Packages
                    </Link>
                  </Button>
                ) : null}
              </div>

              <div className="flex min-h-0 flex-1 flex-col gap-2 px-4 pb-4">
                {buildDone && (
                  <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2.5">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <CheckCircle2 className="size-4 shrink-0 text-emerald-400" />
                        <div className="min-w-0">
                          <p className="text-xs font-medium text-emerald-300">Plugin package built</p>
                          <p className="mt-1 text-[11px] text-emerald-100/60">Run the workflow tests below before building the installer.</p>
                        </div>
                      </div>
                      <Button size="sm" variant="outline" asChild>
                        <Link to="/packages">
                          <FolderKanban className="size-3.5" />
                          Open Packages
                        </Link>
                      </Button>
                    </div>
                  </div>
                )}
                {buildError && (
                  <div className="flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2">
                    <XCircle className="size-4 shrink-0 text-red-400" />
                    <p className="text-xs text-red-300">{buildError}</p>
                  </div>
                )}
                {hasBuiltPackage && !building ? (
                  <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-white/8 bg-black/20">
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/8 px-3 py-2.5">
                      <div>
                        <p className="text-xs font-medium text-white">Workflow tests</p>
                        <p className="mt-0.5 text-xs text-zinc-500">
                          {testSummary.passed}/{testSummary.total} workflows passed
                        </p>
                      </div>
                      {testSummary.allPassed ? (
                        <Button size="sm" variant="outline" asChild>
                          <Link to="/build-installer">
                            <PackageCheck className="size-3.5" />
                            Build Installer
                          </Link>
                        </Button>
                      ) : null}
                    </div>
                    <div className="p-3">
                      <PluginWorkflowTests
                        plugin={selectedPlugin}
                        onComplete={() => {
                          void pluginsQ.refetch()
                        }}
                      />
                    </div>
                  </div>
                ) : (
                  <div
                    ref={logRef}
                    className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-white/8 bg-black/30 p-3 font-mono text-[11px] text-zinc-400"
                  >
                    {logs.length === 0 ? (
                      <p className="text-zinc-600">Build logs will appear here...</p>
                    ) : (
                      logs.map((line, i) => <div key={i}>{line}</div>)
                    )}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center">
              <p className="text-sm text-zinc-500">Select a plugin to build</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
