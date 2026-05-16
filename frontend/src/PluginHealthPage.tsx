'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchPlugins, fetchRuns, normalizePluginList, type Plugin, type Run } from '@/api/pluginApi'
import { AppShell } from '@/components/layout/AppLayout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ArrowRight, CheckCircle2, ChevronDown, ChevronRight, CircleAlert, RefreshCw, ShieldCheck } from 'lucide-react'

type PluginHealthRow = {
  plugin: Plugin
  hasAuth: boolean
  workflowCount: number
  compiledCount: number
  errorCount: number
  hasBuild: boolean
  level: 'healthy' | 'warning' | 'critical'
}

function healthTone(level: PluginHealthRow['level']) {
  if (level === 'healthy') return 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200'
  if (level === 'warning') return 'border-amber-500/25 bg-amber-500/10 text-amber-200'
  return 'border-red-500/25 bg-red-500/10 text-red-200'
}

function healthLabel(level: PluginHealthRow['level']) {
  if (level === 'healthy') return 'Healthy'
  if (level === 'warning') return 'Needs attention'
  return 'Critical'
}

function RunSummaryRow({ run }: { run: Run }) {
  const [expanded, setExpanded] = useState(false)
  const outcome = run.outcome
  const status = outcome?.status ?? 'pending'
  const failures = run.events.filter((e) => e.event === 'step_failure')
  const recoveries = run.events.filter((e) => e.event === 'recovery_attempt')
  const ts = run.events[0]?.ts
    ? new Date(run.events[0].ts).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
    : null

  return (
    <div className="border-t border-white/6 first:border-t-0">
      <button
        className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-white/[0.02]"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex items-center gap-3 min-w-0">
          {status === 'success' ? (
            <CheckCircle2 className="size-3.5 shrink-0 text-emerald-400" />
          ) : (
            <CircleAlert className={`size-3.5 shrink-0 ${status === 'aborted' ? 'text-amber-400' : 'text-red-400'}`} />
          )}
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-white">
              {run.plugin_id} · {run.skill_slug || run.run_id.slice(0, 8)}
            </p>
            {ts ? <p className="text-xs text-zinc-600">{ts}</p> : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge
            variant="outline"
            className={`text-xs ${
              status === 'success'
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                : status === 'aborted'
                ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
                : 'border-red-500/30 bg-red-500/10 text-red-300'
            }`}
          >
            {status}
          </Badge>
          {outcome?.recovered_steps ? (
            <Badge variant="outline" className="text-xs border-blue-500/30 bg-blue-500/10 text-blue-300">
              {outcome.recovered_steps}↺
            </Badge>
          ) : null}
          {expanded ? <ChevronDown className="size-3.5 text-zinc-600" /> : <ChevronRight className="size-3.5 text-zinc-600" />}
        </div>
      </button>
      {expanded && (failures.length > 0 || recoveries.length > 0) ? (
        <div className="border-t border-white/6 bg-white/[0.015] px-3 py-2 space-y-1.5">
          {failures.map((e, i) => (
            <div key={i} className="text-xs text-zinc-400 flex gap-2">
              <CircleAlert className="size-3 text-red-400 shrink-0 mt-0.5" />
              <span>
                <span className="text-red-300">failure</span>
                {e.step_id ? ` · ${e.step_id}` : ''}
                {e.data.reason ? ` — ${String(e.data.reason)}` : ''}
              </span>
            </div>
          ))}
          {recoveries.map((e, i) => (
            <div key={i} className="text-xs text-zinc-400 flex gap-2">
              <RefreshCw className={`size-3 shrink-0 mt-0.5 ${e.data.success ? 'text-emerald-400' : 'text-amber-400'}`} />
              <span>
                <span className={e.data.success ? 'text-emerald-300' : 'text-amber-300'}>recovery</span>
                {e.step_id ? ` · ${e.step_id}` : ''}
                {e.data.strategy ? ` — ${String(e.data.strategy)}` : ''}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function AllRunsTimeline() {
  const q = useQuery({
    queryKey: ['runs'],
    queryFn: () => fetchRuns(),
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
  const runs = (q.data?.runs ?? []).slice().reverse().slice(0, 50)

  return (
    <Card className="border-white/8 bg-white/[0.03] shadow-none">
      <CardHeader className="border-b border-white/8">
        <CardTitle className="text-white">Recent runs</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {q.isLoading ? <p className="px-4 py-6 text-sm text-zinc-500">Loading runs…</p> : null}
        {q.isError ? <p className="px-4 py-6 text-sm text-red-400">{(q.error as Error).message}</p> : null}
        {!q.isLoading && !q.isError && runs.length === 0 ? (
          <p className="px-4 py-6 text-sm text-zinc-500">No run history yet.</p>
        ) : null}
        {runs.map((run) => <RunSummaryRow key={run.run_id} run={run} />)}
      </CardContent>
    </Card>
  )
}

export function PluginHealthPage() {
  const q = useQuery({ queryKey: ['plugins'], queryFn: fetchPlugins, staleTime: 10_000 })
  const plugins = normalizePluginList(q.data)

  const rows = useMemo<PluginHealthRow[]>(() => {
    return plugins.map((plugin) => {
      const workflowCount = plugin.workflows.length
      const compiledCount = plugin.workflows.filter((w) => w.status === 'compiled' && w.skill_id).length
      const errorCount = plugin.workflows.filter((w) => w.status === 'error').length
      const hasAuth = plugin.auth != null
      const hasBuild = plugin.build != null
      const level: PluginHealthRow['level'] = !hasAuth || errorCount > 0 ? 'critical' : compiledCount < workflowCount || !hasBuild ? 'warning' : 'healthy'
      return { plugin, hasAuth, workflowCount, compiledCount, errorCount, hasBuild, level }
    })
  }, [plugins])

  const healthyCount = rows.filter((row) => row.level === 'healthy').length
  const warningCount = rows.filter((row) => row.level === 'warning').length
  const criticalCount = rows.filter((row) => row.level === 'critical').length

  return (
    <AppShell
      title="Plugin health"
      description="Readiness checks for auth, workflow compile state, and latest build output."
      mainClassName="overflow-y-auto"
      actions={
        <Button asChild size="sm" variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08]">
          <Link href="/plugins">
            Open plugins
            <ArrowRight className="size-3.5" />
          </Link>
        </Button>
      }
    >
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-4 sm:px-6">
        <section className="grid gap-3 sm:grid-cols-3">
          <Card className="border-white/8 bg-white/[0.03] shadow-none">
            <CardContent className="flex items-center justify-between p-4">
              <div>
                <p className="text-xs text-zinc-500">Healthy</p>
                <p className="mt-1 text-lg font-semibold text-emerald-300">{healthyCount}</p>
              </div>
              <CheckCircle2 className="size-4 text-emerald-300" />
            </CardContent>
          </Card>
          <Card className="border-white/8 bg-white/[0.03] shadow-none">
            <CardContent className="flex items-center justify-between p-4">
              <div>
                <p className="text-xs text-zinc-500">Needs attention</p>
                <p className="mt-1 text-lg font-semibold text-amber-300">{warningCount}</p>
              </div>
              <ShieldCheck className="size-4 text-amber-300" />
            </CardContent>
          </Card>
          <Card className="border-white/8 bg-white/[0.03] shadow-none">
            <CardContent className="flex items-center justify-between p-4">
              <div>
                <p className="text-xs text-zinc-500">Critical</p>
                <p className="mt-1 text-lg font-semibold text-red-300">{criticalCount}</p>
              </div>
              <CircleAlert className="size-4 text-red-300" />
            </CardContent>
          </Card>
        </section>

        <AllRunsTimeline />

        <Card className="border-white/8 bg-white/[0.03] shadow-none">
          <CardHeader className="border-b border-white/8">
            <CardTitle className="text-white">Plugin readiness</CardTitle>
          </CardHeader>
          <CardContent className="p-3">
            {q.isLoading ? <p className="text-sm text-zinc-500">Loading plugin health…</p> : null}
            {q.isError ? <p className="text-sm text-red-400">{(q.error as Error).message}</p> : null}
            {!q.isLoading && !q.isError && rows.length === 0 ? (
              <p className="text-sm text-zinc-500">No plugins yet.</p>
            ) : null}
            {!q.isLoading && !q.isError && rows.length > 0 ? (
              <div className="divide-y divide-white/8">
                {rows.map((row) => (
                  <div key={row.plugin.id} className="flex flex-wrap items-center justify-between gap-2 px-1 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-white">{row.plugin.name}</p>
                      <p className="mt-0.5 text-xs text-zinc-500">
                        {row.compiledCount}/{row.workflowCount} workflows compiled · {row.hasAuth ? 'Auth saved' : 'Auth missing'} ·{' '}
                        {row.hasBuild ? `Build v${row.plugin.build?.version ?? '—'}` : 'No build'}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      {row.errorCount > 0 ? (
                        <Badge variant="outline" className="border-red-500/25 bg-red-500/10 text-red-200">
                          {row.errorCount} workflow error{row.errorCount === 1 ? '' : 's'}
                        </Badge>
                      ) : null}
                      <Badge variant="outline" className={healthTone(row.level)}>
                        {healthLabel(row.level)}
                      </Badge>
                      <Button asChild size="icon-sm" variant="ghost" className="text-zinc-400 hover:text-white">
                        <Link href={`/plugins/${row.plugin.id}`}>
                          <ArrowRight className="size-4" />
                        </Link>
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
