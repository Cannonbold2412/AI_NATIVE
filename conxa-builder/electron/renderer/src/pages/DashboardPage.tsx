import { useQuery } from '@tanstack/react-query'
import { fetchMetrics } from '@/api/workflowApi'
import { fetchPlugins, fetchRuns, normalizePluginList } from '@/api/pluginApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Link } from 'react-router-dom'
import { Activity, CheckCircle2, CircleAlert, Clock, Layers, Package, Puzzle, RefreshCw } from 'lucide-react'

function fmtRelative(epochSec: number) {
  const diff = Date.now() - epochSec * 1000
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return new Date(epochSec * 1000).toLocaleDateString()
}

function KpiCard({ label, value, icon: Icon, sub }: {
  label: string
  value: number | string
  sub?: string
  icon: React.FC<{ className?: string }>
}) {
  return (
    <Card className="border-white/8 bg-white/[0.025] shadow-none">
      <CardContent className="flex items-start justify-between gap-3 p-4">
        <div>
          <p className="text-xs text-zinc-500">{label}</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums leading-none text-zinc-200">{value}</p>
          {sub && <p className="mt-1 text-[11px] text-zinc-600">{sub}</p>}
        </div>
        <div className="rounded-lg bg-white/5 p-2 text-zinc-400">
          <Icon className="size-4" />
        </div>
      </CardContent>
    </Card>
  )
}

export function DashboardPage() {
  const metricsQ = useQuery({ queryKey: ['metrics'], queryFn: fetchMetrics, staleTime: 30_000 })
  const pluginsQ = useQuery({ queryKey: ['plugins'], queryFn: fetchPlugins, staleTime: 30_000 })
  const runsQ = useQuery({ queryKey: ['runs'], queryFn: () => fetchRuns(), staleTime: 30_000 })

  const metrics = metricsQ.data ?? {}
  const plugins = normalizePluginList(pluginsQ.data)
  const runs = runsQ.data?.runs ?? []

  const compiledWorkflows = plugins.flatMap((p) => p.workflows.filter((w) => w.skill_id)).length
  const totalWorkflows = plugins.flatMap((p) => p.workflows).length

  function refetchAll() {
    void metricsQ.refetch()
    void pluginsQ.refetch()
    void runsQ.refetch()
  }

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title="Dashboard"
        description="Overview of your local Build Studio — plugins, skills, and recent runs."
        actions={
          <Button variant="ghost" size="sm" onClick={refetchAll} className="gap-1.5 border border-white/8">
            <RefreshCw className="size-3.5" />
            Refresh
          </Button>
        }
      />

      <div className="mx-auto w-full max-w-6xl space-y-5 px-4 py-5 sm:px-6">

        {/* KPI strip */}
        <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <KpiCard label="Plugins" value={plugins.length} icon={Puzzle} sub={`${compiledWorkflows}/${totalWorkflows} workflows compiled`} />
          <KpiCard label="Skills" value={(metrics.skill_count as number) ?? 0} icon={Layers} sub="in local skill library" />
          <KpiCard label="Packages" value={(metrics.pack_count as number) ?? 0} icon={Package} sub="built skill packages" />
          <KpiCard label="Run Logs" value={(metrics.run_file_count as number) ?? 0} icon={Activity} sub="execution log files" />
        </section>

        <div className="grid gap-4 lg:grid-cols-2">
          {/* Plugins at a glance */}
          <Card className="border-white/8 bg-white/[0.025] shadow-none">
            <CardHeader className="border-b border-white/6 pb-3">
              <CardTitle className="flex items-center gap-2 text-xs font-semibold text-zinc-400">
                <Puzzle className="size-3.5" />
                Plugins
                <Button asChild size="sm" variant="ghost" className="ml-auto text-xs text-zinc-500 hover:text-zinc-300">
                  <Link to="/plugins">View all</Link>
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {plugins.length === 0 ? (
                <div className="px-4 py-8 text-center">
                  <p className="text-xs text-zinc-600">No plugins yet. <Link to="/plugins" className="text-zinc-400 underline">Create one →</Link></p>
                </div>
              ) : (
                plugins.slice(0, 6).map((plugin) => (
                  <Link
                    key={plugin.id}
                    to={`/plugins/${plugin.id}`}
                    className="flex items-center gap-3 border-t border-white/6 px-4 py-3 transition-colors hover:bg-white/[0.03] first:border-t-0"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium text-zinc-200">{plugin.name}</p>
                      <p className="text-[11px] text-zinc-600">{plugin.workflows.length} workflow{plugin.workflows.length !== 1 ? 's' : ''}</p>
                    </div>
                    <Badge
                      variant="outline"
                      className={
                        plugin.status === 'ready'
                          ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                          : plugin.status === 'needs_auth'
                            ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
                            : 'border-red-500/30 bg-red-500/10 text-red-300'
                      }
                    >
                      {plugin.status}
                    </Badge>
                  </Link>
                ))
              )}
            </CardContent>
          </Card>

          {/* Recent runs */}
          <Card className="border-white/8 bg-white/[0.025] shadow-none">
            <CardHeader className="border-b border-white/6 pb-3">
              <CardTitle className="flex items-center gap-2 text-xs font-semibold text-zinc-400">
                <Activity className="size-3.5" />
                Recent Runs
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {runs.length === 0 ? (
                <div className="px-4 py-8 text-center">
                  <p className="text-xs text-zinc-600">No runs logged yet. Test a workflow from the <Link to="/test" className="text-zinc-400 underline">Test Plugin</Link> page.</p>
                </div>
              ) : (
                runs.slice(0, 8).map((run, i) => {
                  const status = String((run as Record<string, unknown>).status ?? '')
                  const ts = Number((run as Record<string, unknown>).ts ?? 0)
                  const pluginId = String((run as Record<string, unknown>).plugin_id ?? '')
                  return (
                    <div
                      key={String((run as Record<string, unknown>).run_id ?? i)}
                      className="flex items-center gap-3 border-t border-white/6 px-4 py-3 first:border-t-0"
                    >
                      {status === 'success' || status === 'ok' ? (
                        <CheckCircle2 className="size-4 shrink-0 text-emerald-400" />
                      ) : status === 'failure' || status === 'fail' ? (
                        <CircleAlert className="size-4 shrink-0 text-red-400" />
                      ) : (
                        <Clock className="size-4 shrink-0 text-zinc-600" />
                      )}
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium text-zinc-200">{pluginId || 'Unknown plugin'}</p>
                        {ts > 0 && <p className="text-[11px] text-zinc-600">{fmtRelative(ts)}</p>}
                      </div>
                      <Badge
                        variant="outline"
                        className={
                          status === 'success' || status === 'ok'
                            ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                            : status === 'failure' || status === 'fail'
                              ? 'border-red-500/30 bg-red-500/10 text-red-300'
                              : 'border-zinc-500/30 bg-zinc-500/10 text-zinc-400'
                        }
                      >
                        {status || 'unknown'}
                      </Badge>
                    </div>
                  )
                })
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
