import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { buildPlugin, fetchPlugins, normalizePluginList, type PluginBuild } from '@/api/pluginApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { PluginWorkflowTests, workflowTestSummary } from '@/components/PluginWorkflowTests'
import {
  BuildPipelineStepper,
  type PipelineStep,
  type StepState,
} from '@/components/build/BuildPipelineStepper'
import { StatCard } from '@/components/build/StatCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  CheckCircle2,
  FolderKanban,
  Loader2,
  PackageCheck,
  XCircle,
  Layers,
  FlaskConical,
  CalendarDays,
  Cpu,
} from 'lucide-react'
import { cn } from '@/lib/utils'

// ─── helpers ─────────────────────────────────────────────────────────────────

function fmtDate(epoch: number) {
  return new Date(epoch * 1000).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function pluginStatusColor(status: string) {
  if (status === 'ready') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (status === 'needs_auth') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  return 'border-red-500/30 bg-red-500/10 text-red-300'
}

// ─── main page ───────────────────────────────────────────────────────────────

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

  // ── pipeline stepper state ─────────────────────────────────────────────────

  function pipelineSteps(): PipelineStep[] {
    if (!selectedPlugin) {
      return [
        { label: 'Compile', state: 'pending' },
        { label: 'Edit', state: 'pending' },
        { label: 'Build', state: 'pending' },
        { label: 'Test', state: 'pending' },
        { label: 'Installer', state: 'pending' },
      ]
    }

    const compileState: StepState =
      uncompiled.length === 0 ? 'done' : 'blocked'

    const editState: StepState =
      uncompiled.length > 0
        ? 'pending'
        : unedited.length === 0
          ? 'done'
          : 'blocked'

    const buildState: StepState = buildBlocked
      ? 'pending'
      : building
        ? 'active'
        : hasBuiltPackage
          ? 'done'
          : 'active'

    const testState: StepState = !hasBuiltPackage
      ? 'pending'
      : testSummary.allPassed
        ? 'done'
        : testSummary.total > 0
          ? 'active'
          : 'pending'

    const installerState: StepState = testSummary.allPassed ? 'active' : 'pending'

    return [
      {
        label: 'Compile',
        state: compileState,
        subtitle:
          uncompiled.length > 0 ? `${uncompiled.length} pending` : undefined,
      },
      {
        label: 'Edit',
        state: editState,
        subtitle:
          unedited.length > 0 ? `${unedited.length} pending` : undefined,
      },
      {
        label: 'Build',
        state: buildState,
        subtitle: selectedPlugin.build
          ? `v${selectedPlugin.build.version}`
          : undefined,
      },
      {
        label: 'Test',
        state: testState,
        subtitle:
          testSummary.total > 0
            ? `${testSummary.passed}/${testSummary.total} passed`
            : undefined,
      },
      {
        label: 'Installer',
        state: installerState,
      },
    ]
  }

  // ── loading / error states ─────────────────────────────────────────────────

  if (pluginsQ.isLoading) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <PageHeader title="Build Plugin" description="Compile a recorded plugin into a generated package." />
        <div className="flex min-h-0 flex-1 gap-4 p-6">
          {/* sidebar skeleton */}
          <div className="flex w-72 flex-col gap-3 rounded-xl border border-white/8 bg-white/[0.03] p-4">
            <Skeleton className="h-4 w-24" />
            <div className="space-y-2 pt-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-14 w-full rounded-lg" />
              ))}
            </div>
          </div>
          {/* main area skeleton */}
          <div className="flex flex-1 flex-col gap-4 rounded-xl border border-white/8 bg-white/[0.03] p-6">
            <Skeleton className="h-6 w-48" />
            <div className="flex gap-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-20 flex-1 rounded-lg" />
              ))}
            </div>
            <Skeleton className="h-px w-full" />
            <Skeleton className="h-9 w-28" />
            <Skeleton className="mt-auto h-40 w-full rounded-lg" />
          </div>
        </div>
      </div>
    )
  }

  if (pluginsQ.isError || !pluginsQ.data) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <PageHeader title="Build Plugin" />
        <div className="flex flex-1 flex-col items-center justify-center gap-3">
          <XCircle className="size-9 text-red-400" />
          <p className="text-sm font-medium text-red-300">Failed to load plugins</p>
          <p className="text-xs text-zinc-500">
            {(pluginsQ.error as Error)?.message ?? 'Unknown error'}
          </p>
          <Button size="sm" variant="outline" onClick={() => void pluginsQ.refetch()}>
            Retry
          </Button>
        </div>
      </div>
    )
  }

  // ── main render ────────────────────────────────────────────────────────────

  const headerActions = selectedPlugin?.build ? (
    <Button size="sm" variant="outline" asChild>
      <Link to="/packages">
        <FolderKanban className="size-3.5" />
        Open Packages
      </Link>
    </Button>
  ) : undefined

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        title="Build Plugin"
        description="Compile recorded workflows into a distributable plugin package."
        actions={headerActions}
      />

      <div className="flex min-h-0 flex-1 gap-4 p-6">
        {/* ── Left rail: plugin list ─────────────────────────────────────── */}
        <div className="flex min-h-0 w-72 flex-col rounded-xl border border-white/8 bg-white/[0.03]">
          {/* rail header */}
          <div className="flex items-center justify-between border-b border-white/8 px-4 py-3">
            <div>
              <h2 className="text-sm font-semibold text-white">Plugins</h2>
              <p className="mt-0.5 text-[11px] text-zinc-500">
                {plugins.length} plugin{plugins.length !== 1 ? 's' : ''}
                {plugins.filter((p) => p.status === 'ready').length > 0 &&
                  ` · ${plugins.filter((p) => p.status === 'ready').length} ready`}
              </p>
            </div>
          </div>

          {/* plugin list */}
          <ScrollArea className="min-h-0 flex-1">
            <div className="space-y-1 p-2">
              {plugins.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-10 text-center">
                  <Layers className="size-7 text-zinc-700" />
                  <p className="text-xs text-zinc-500">No plugins yet.</p>
                  <p className="text-[11px] text-zinc-600">Record a workflow to get started.</p>
                </div>
              ) : (
                plugins.map((plugin) => (
                  <button
                    key={plugin.id}
                    onClick={() => selectPlugin(plugin.id)}
                    className={cn(
                      'group w-full cursor-pointer rounded-lg border px-3 py-2.5 text-left text-sm transition-all duration-150',
                      'hover:border-white/10 hover:bg-white/[0.07]',
                      selectedId === plugin.id
                        ? 'border-white/12 bg-white/[0.09] shadow-sm'
                        : 'border-transparent',
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <p
                          className={cn(
                            'truncate text-sm font-medium',
                            selectedId === plugin.id ? 'text-white' : 'text-zinc-200',
                          )}
                        >
                          {plugin.name}
                        </p>
                        <p className="mt-0.5 truncate text-[11px] text-zinc-600">{plugin.id}</p>
                      </div>
                      <Badge
                        variant="outline"
                        className={cn('shrink-0 text-[10px]', pluginStatusColor(plugin.status))}
                      >
                        {plugin.status}
                      </Badge>
                    </div>

                    {/* build info strip */}
                    {plugin.build ? (
                      <div className="mt-2 flex items-center gap-3 border-t border-white/6 pt-2">
                        <span className="text-[10px] text-zinc-600">
                          v{plugin.build.version}
                        </span>
                        <span className="text-[10px] text-zinc-700">·</span>
                        <span className="text-[10px] text-zinc-600">
                          {fmtDate(plugin.build.last_built_at)}
                        </span>
                      </div>
                    ) : (
                      <div className="mt-2 border-t border-white/6 pt-2">
                        <span className="text-[10px] text-zinc-700">Never built</span>
                      </div>
                    )}
                  </button>
                ))
              )}
            </div>
          </ScrollArea>
        </div>

        {/* ── Right panel: build workspace ──────────────────────────────── */}
        <div className="flex min-h-0 flex-1 flex-col gap-0 rounded-xl border border-white/8 bg-white/[0.03]">
          {selectedPlugin ? (
            <>
              {/* workspace header */}
              <div className="flex items-start justify-between gap-4 border-b border-white/8 px-5 py-4">
                <div className="min-w-0">
                  <h3 className="text-base font-semibold text-white">{selectedPlugin.name}</h3>
                  <p className="mt-0.5 text-[11px] text-zinc-500">
                    {selectedPlugin.workflows.length} workflow
                    {selectedPlugin.workflows.length !== 1 ? 's' : ''}
                    {selectedPlugin.build ? ` · last built ${fmtDate(selectedPlugin.build.last_built_at)}` : ''}
                  </p>
                </div>
                <Badge
                  variant="outline"
                  className={cn('shrink-0 text-xs', pluginStatusColor(selectedPlugin.status))}
                >
                  {selectedPlugin.status}
                </Badge>
              </div>

              {/* stat strip */}
              <div className="grid grid-cols-3 gap-3 border-b border-white/8 px-5 py-4">
                <StatCard
                  label="Workflows"
                  value={selectedPlugin.workflows.length}
                  subvalue={
                    uncompiled.length > 0
                      ? `${uncompiled.length} uncompiled`
                      : 'all compiled'
                  }
                  accent={uncompiled.length > 0 ? 'amber' : 'emerald'}
                  icon={<Layers />}
                />
                <StatCard
                  label="Tests passed"
                  value={
                    testSummary.total === 0
                      ? '—'
                      : `${testSummary.passed}/${testSummary.total}`
                  }
                  subvalue={testSummary.allPassed ? 'All clear' : testSummary.total > 0 ? 'Pending tests' : 'Run tests after build'}
                  accent={testSummary.allPassed ? 'emerald' : testSummary.total > 0 ? 'amber' : 'zinc'}
                  icon={<FlaskConical />}
                />
                <StatCard
                  label="Last build"
                  value={selectedPlugin.build ? `v${selectedPlugin.build.version}` : '—'}
                  subvalue={
                    selectedPlugin.build
                      ? fmtDate(selectedPlugin.build.last_built_at)
                      : 'No build yet'
                  }
                  accent={selectedPlugin.build ? 'sky' : 'zinc'}
                  icon={<CalendarDays />}
                />
              </div>

              {/* pipeline stepper */}
              <div className="border-b border-white/8 px-5 py-4">
                <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                  Build Pipeline
                </p>
                <BuildPipelineStepper steps={pipelineSteps()} />
              </div>

              {/* notices */}
              {buildBlocked && (
                <div className="mx-5 mt-4 rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-xs text-amber-300">
                  <p className="font-medium text-amber-200">Action required before building</p>
                  {uncompiled.length > 0 && (
                    <p className="mt-1 text-amber-300/80">
                      Compile first:{' '}
                      <span className="font-mono">{uncompiled.map((w) => w.name).join(', ')}</span>
                    </p>
                  )}
                  {unedited.length > 0 && (
                    <p className="mt-1 text-amber-300/80">
                      Open editor and sign off:{' '}
                      <span className="font-mono">{unedited.map((w) => w.name).join(', ')}</span>
                    </p>
                  )}
                </div>
              )}
              {stale && !buildBlocked && (
                <div className="mx-5 mt-4 rounded-lg border border-sky-500/20 bg-sky-500/5 px-4 py-3 text-xs text-sky-300">
                  <p className="font-medium text-sky-200">Workflows edited since last build</p>
                  <p className="mt-1 text-sky-300/80">
                    Rebuild and re-test before creating the installer.
                  </p>
                </div>
              )}

              {/* action row */}
              <div className="flex items-center gap-2 px-5 py-4">
                <Button
                  size="sm"
                  onClick={handleBuild}
                  disabled={
                    building ||
                    selectedPlugin.status !== 'ready' ||
                    selectedPlugin.workflows.length === 0 ||
                    buildBlocked
                  }
                >
                  {building ? (
                    <>
                      <Loader2 className="size-4 animate-spin" />
                      Building...
                    </>
                  ) : (
                    <>
                      <Cpu className="size-3.5" />
                      Build Plugin
                    </>
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

                {testSummary.allPassed ? (
                  <Button size="sm" variant="outline" asChild className="ml-auto border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 hover:text-emerald-200">
                    <Link to="/build-installer">
                      <PackageCheck className="size-3.5" />
                      Build Installer
                    </Link>
                  </Button>
                ) : null}
              </div>

              {/* build result / error */}
              {buildDone && (
                <div className="mx-5 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-4 py-3">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="size-4 shrink-0 text-emerald-400" />
                    <div>
                      <p className="text-xs font-semibold text-emerald-200">Plugin package built successfully</p>
                      <p className="mt-0.5 text-[11px] text-emerald-100/60">
                        Run the workflow tests below before building the installer.
                      </p>
                    </div>
                  </div>
                </div>
              )}
              {buildError && (
                <div className="mx-5 flex items-start gap-2 rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-3">
                  <XCircle className="mt-0.5 size-4 shrink-0 text-red-400" />
                  <div>
                    <p className="text-xs font-semibold text-red-300">Build failed</p>
                    <p className="mt-0.5 text-[11px] text-red-300/70">{buildError}</p>
                  </div>
                </div>
              )}

              {/* log / test panel */}
              <div className="mx-5 mb-5 mt-3 min-h-0 flex-1 overflow-hidden rounded-xl border border-white/8 bg-black/20">
                {hasBuiltPackage && !building ? (
                  <>
                    <div className="flex items-center justify-between border-b border-white/8 px-4 py-3">
                      <div>
                        <p className="text-xs font-semibold text-white">Workflow tests</p>
                        <p className="mt-0.5 text-[11px] text-zinc-500">
                          {testSummary.passed}/{testSummary.total} workflows passed
                        </p>
                      </div>
                      {testSummary.allPassed && (
                        <Button size="sm" variant="outline" asChild>
                          <Link to="/build-installer">
                            <PackageCheck className="size-3.5" />
                            Build Installer
                          </Link>
                        </Button>
                      )}
                    </div>
                    <div className="p-3">
                      <PluginWorkflowTests
                        plugin={selectedPlugin}
                        onComplete={() => {
                          void pluginsQ.refetch()
                        }}
                      />
                    </div>
                  </>
                ) : (
                  <>
                    <div className="border-b border-white/8 px-4 py-3">
                      <p className="text-xs font-semibold text-white">Build log</p>
                      <p className="mt-0.5 text-[11px] text-zinc-500">
                        {building ? 'Build in progress…' : 'Logs will appear here after you start a build.'}
                      </p>
                    </div>
                    <div
                      ref={logRef}
                      className="max-h-64 overflow-y-auto p-3 font-mono text-[11px] text-zinc-400"
                    >
                      {logs.length === 0 ? (
                        <p className="py-4 text-center text-zinc-700">
                          {building ? 'Starting…' : 'No logs yet.'}
                        </p>
                      ) : (
                        <div className="space-y-px">
                          {logs.map((line, i) => (
                            <div key={i} className="flex gap-2">
                              <span className="shrink-0 text-zinc-700">›</span>
                              <span>{line}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
            </>
          ) : (
            /* empty selection state */
            <div className="flex flex-1 flex-col items-center justify-center gap-3 py-20">
              <div className="flex size-14 items-center justify-center rounded-2xl border border-white/8 bg-white/[0.04]">
                <Layers className="size-7 text-zinc-600" />
              </div>
              <div className="text-center">
                <p className="text-sm font-medium text-zinc-300">Select a plugin to build</p>
                <p className="mt-1 text-xs text-zinc-600">
                  Choose a plugin from the left to view its build pipeline.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
