'use client'

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchPlugins,
  fetchTrackingRun,
  fetchTrackingRuns,
  normalizePluginList,
  type TrackingEvent,
  type TrackingRunSummary,
} from '@/api/pluginApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CircleAlert,
  Clock,
  RefreshCw,
  Zap,
} from 'lucide-react'

// ─── Label maps ───────────────────────────────────────────────────────────────

const STRATEGY_LABELS: Record<string, string> = {
  selector_retry:     'Selector Retry',
  candidate_fallback: 'Candidate Fallback',
  dialog_scope:       'Dialog Scope',
  fuzzy_dom:          'Fuzzy DOM',
  vision_recovery:    'Vision',
  llm_intent:         'LLM Intent',
}

const FAILURE_LABELS: Record<string, string> = {
  selector_missing:  'Selector Missing',
  url_mismatch:      'URL Mismatch',
  timeout:           'Timeout',
  navigation_failed: 'Navigation Failed',
  cancelled:         'Cancelled',
  unknown:           'Unknown',
}

const EVENT_LABELS: Record<string, string> = {
  wf_start:  'Workflow Started',
  wf_ok:     'Workflow Success',
  wf_fail:   'Workflow Failed',
  step_fail: 'Step Failed',
  rec_start: 'Recovery Started',
  rec_ok:    'Recovery Succeeded',
  rec_fail:  'Recovery Failed',
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function toCompanySlug(name: string): string {
  let s = name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
  if (!s || !/^[a-z]/.test(s)) s = `p_${s}`
  return s.slice(0, 40)
}

function fmtDuration(ms: number) {
  if (!ms) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function fmtTs(epochMs: number) {
  if (!epochMs) return '—'
  return new Date(epochMs).toLocaleString([], {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

function fmtRelative(epochMs: number) {
  const diff = Date.now() - epochMs
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return fmtTs(epochMs)
}

// ─── Analytics ────────────────────────────────────────────────────────────────

function useAnalytics(runs: TrackingRunSummary[]) {
  return useMemo(() => {
    const total       = runs.length
    const ok          = runs.filter((r) => r.status === 'ok').length
    const failed      = runs.filter((r) => r.status === 'fail').length
    const withRec     = runs.filter((r) => r.recovered_steps > 0).length
    const totalRec    = runs.reduce((s, r) => s + r.recovered_steps, 0)
    const durations   = runs.filter((r) => r.duration_ms > 0).map((r) => r.duration_ms)
    const avgDur      = durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : 0

    const failureCodes: Record<string, number> = {}
    for (const r of runs) {
      if (r.failure_code) failureCodes[r.failure_code] = (failureCodes[r.failure_code] || 0) + 1
    }

    const pluginMap: Record<string, { ok: number; fail: number; rec: number }> = {}
    for (const r of runs) {
      const pid = r.plugin_id || 'unknown'
      if (!pluginMap[pid]) pluginMap[pid] = { ok: 0, fail: 0, rec: 0 }
      if (r.status === 'ok')   pluginMap[pid].ok++
      if (r.status === 'fail') pluginMap[pid].fail++
      pluginMap[pid].rec += r.recovered_steps
    }

    return {
      total, ok, failed, withRec, totalRec,
      avgDur: Math.round(avgDur),
      successRate: total ? Math.round((ok / total) * 100) : 0,
      failureCodes: Object.entries(failureCodes).sort((a, b) => b[1] - a[1]),
      pluginStats: Object.entries(pluginMap).sort((a, b) => (b[1].ok + b[1].fail) - (a[1].ok + a[1].fail)),
      sparkline: runs.slice().reverse().slice(0, 40).reverse(),
    }
  }, [runs])
}

function computeStrategyStats(timeline: TrackingEvent[]) {
  const ok:   Record<string, number> = {}
  const fail: Record<string, number> = {}
  for (const e of timeline) {
    if (!e.sc) continue
    if (e.e === 'rec_ok')   ok[e.sc]   = (ok[e.sc]   || 0) + 1
    if (e.e === 'rec_fail') fail[e.sc] = (fail[e.sc] || 0) + 1
  }
  const keys = Array.from(new Set([...Object.keys(ok), ...Object.keys(fail)]))
  return keys.map((sc) => ({ sc, ok: ok[sc] || 0, fail: fail[sc] || 0 }))
}

// ─── KPI card ─────────────────────────────────────────────────────────────────

function KpiCard({
  label, value, sub, icon: Icon, tone = 'neutral',
}: {
  label: string
  value: string | number
  sub?: string
  icon: React.FC<{ className?: string }>
  tone?: 'good' | 'warn' | 'bad' | 'neutral'
}) {
  const accent =
    tone === 'good' ? 'text-emerald-400' :
    tone === 'warn' ? 'text-amber-400' :
    tone === 'bad'  ? 'text-red-400' :
    'text-zinc-200'
  const iconBg =
    tone === 'good' ? 'bg-emerald-500/10 text-emerald-400' :
    tone === 'warn' ? 'bg-amber-500/10 text-amber-400' :
    tone === 'bad'  ? 'bg-red-500/10 text-red-400' :
    'bg-white/5 text-zinc-400'

  return (
    <Card className="border-white/8 bg-white/[0.025] shadow-none">
      <CardContent className="flex items-start justify-between gap-3 p-4">
        <div>
          <p className="text-xs text-zinc-500">{label}</p>
          <p className={`mt-1 text-2xl font-semibold tabular-nums leading-none ${accent}`}>{value}</p>
          {sub && <p className="mt-1 text-[11px] text-zinc-600">{sub}</p>}
        </div>
        <div className={`rounded-lg p-2 ${iconBg}`}>
          <Icon className="size-4" />
        </div>
      </CardContent>
    </Card>
  )
}

// ─── Run sparkline (last 40 runs as mini bars) ────────────────────────────────

function RunSparkline({ runs }: { runs: TrackingRunSummary[] }) {
  if (runs.length === 0) return null
  return (
    <div className="flex h-10 items-end gap-0.5">
      {runs.map((r) => {
        const color =
          r.status === 'ok'   ? 'bg-emerald-500' :
          r.status === 'fail' ? 'bg-red-500' :
          'bg-zinc-700'
        const height =
          r.duration_ms > 0
            ? Math.max(20, Math.min(100, (r.duration_ms / 10000) * 100))
            : 40
        return (
          <div
            key={r.run_id}
            title={`${r.status} · ${fmtDuration(r.duration_ms)}`}
            className={`w-2 min-w-[6px] flex-1 rounded-sm ${color} opacity-80 transition-opacity hover:opacity-100`}
            style={{ height: `${height}%` }}
          />
        )
      })}
    </div>
  )
}

// ─── Strategy effectiveness bars ─────────────────────────────────────────────

function StrategyBar({ sc, ok, fail }: { sc: string; ok: number; fail: number }) {
  const total = ok + fail
  const pct   = total ? Math.round((ok / total) * 100) : 0
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-zinc-300">{STRATEGY_LABELS[sc] ?? sc}</span>
        <span className="tabular-nums text-zinc-500">{pct}% ok <span className="text-zinc-700">({total})</span></span>
      </div>
      <div className="h-1.5 rounded-full bg-white/8 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${pct >= 80 ? 'bg-emerald-500' : pct >= 50 ? 'bg-amber-500' : 'bg-red-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: TrackingRunSummary['status'] }) {
  if (status === 'ok')
    return <Badge variant="outline" className="text-[10px] border-emerald-500/30 bg-emerald-500/10 text-emerald-300">ok</Badge>
  if (status === 'fail')
    return <Badge variant="outline" className="text-[10px] border-red-500/30 bg-red-500/10 text-red-300">fail</Badge>
  return <Badge variant="outline" className="text-[10px] border-zinc-500/30 bg-zinc-500/10 text-zinc-400">running</Badge>
}

// ─── Timeline drawer ──────────────────────────────────────────────────────────

function TimelineDrawer({
  company, runId, run, open, onClose,
}: {
  company: string
  runId: string
  run: TrackingRunSummary | undefined
  open: boolean
  onClose: () => void
}) {
  const { data, isFetching } = useQuery({
    queryKey: ['tracking-run-detail', company, runId],
    queryFn: () => fetchTrackingRun(company, runId),
    enabled: open && !!runId,
    staleTime: 60_000,
  })

  const strategyStats = data ? computeStrategyStats(data.timeline) : []

  return (
    <Sheet open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <SheetContent className="w-full max-w-md overflow-y-auto border-white/8 bg-zinc-950 p-0">
        <div className="border-b border-white/8 p-5">
          <SheetHeader>
            <SheetTitle className="text-sm font-semibold text-zinc-100">Run Detail</SheetTitle>
          </SheetHeader>
          {run && (
            <div className="mt-3 grid grid-cols-3 gap-2">
              <div className="rounded-md bg-white/[0.03] p-2 text-center">
                <p className="text-[10px] text-zinc-600">Status</p>
                <StatusBadge status={run.status} />
              </div>
              <div className="rounded-md bg-white/[0.03] p-2 text-center">
                <p className="text-[10px] text-zinc-600">Duration</p>
                <p className="text-xs font-medium text-zinc-300">{fmtDuration(run.duration_ms)}</p>
              </div>
              <div className="rounded-md bg-white/[0.03] p-2 text-center">
                <p className="text-[10px] text-zinc-600">Recoveries</p>
                <p className="text-xs font-medium text-blue-300">{run.recovered_steps}</p>
              </div>
            </div>
          )}
          <p className="mt-2 font-mono text-[10px] text-zinc-600 break-all">{runId}</p>
        </div>

        <div className="p-5 space-y-4">
          {isFetching && (
            <p className="text-xs text-zinc-600 animate-pulse">Loading timeline…</p>
          )}

          {data && strategyStats.length > 0 && (
            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-zinc-600">Recovery</p>
              <div className="space-y-3">
                {strategyStats.map((s) => (
                  <StrategyBar key={s.sc} {...s} />
                ))}
              </div>
            </div>
          )}

          {data && data.timeline.length > 0 && (
            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-zinc-600">Timeline</p>
              <div className="relative pl-4">
                <div className="absolute left-[5px] top-0 bottom-0 w-px bg-white/8" />
                {data.timeline.map((evt, idx) => {
                  const dot =
                    evt.e === 'wf_ok' || evt.e === 'rec_ok'   ? 'bg-emerald-500 ring-emerald-500/20' :
                    evt.e === 'wf_fail' || evt.e === 'step_fail' || evt.e === 'rec_fail' ? 'bg-red-500 ring-red-500/20' :
                    'bg-zinc-600 ring-zinc-600/20'
                  return (
                    <div key={idx} className="relative mb-3 last:mb-0">
                      <span className={`absolute -left-4 mt-1 size-2.5 rounded-full ring-2 ${dot}`} />
                      <p className="text-xs font-medium text-zinc-300">{EVENT_LABELS[evt.e] ?? evt.e}</p>
                      <p className="mt-0.5 text-[11px] text-zinc-600 flex flex-wrap gap-x-2">
                        {evt.sc && <span>{STRATEGY_LABELS[evt.sc] ?? evt.sc}</span>}
                        {evt.fc && <span className="text-red-400">{FAILURE_LABELS[evt.fc] ?? evt.fc}</span>}
                        {evt.si != null && <span>step {evt.si + 1}</span>}
                        {evt.dur != null && <span>{fmtDuration(evt.dur)}</span>}
                        {evt.tot != null && <span>{evt.tot} steps</span>}
                        <span className="ml-auto">{new Date(evt.ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })}</span>
                      </p>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export function DashboardPage() {
  const [selectedRun, setSelectedRun] = useState<TrackingRunSummary | null>(null)
  const [company, setCompany] = useState<string>('')

  const { data: pluginsData } = useQuery({
    queryKey: ['plugins'],
    queryFn: fetchPlugins,
    staleTime: 60_000,
  })
  const plugins   = normalizePluginList(pluginsData)
  const companies = Array.from(new Set(plugins.map((p) => toCompanySlug(p.name || '')).filter(Boolean)))
  const activeCompany = company || companies[0] || ''

  const { data, isFetching, refetch, dataUpdatedAt } = useQuery({
    queryKey:        ['tracking-runs', activeCompany],
    queryFn:         () => fetchTrackingRuns(activeCompany),
    enabled:         !!activeCompany,
    staleTime:       30_000,
    refetchInterval: 30_000,
  })

  const runs = data?.runs ?? []
  const stats = useAnalytics(runs)

  const lastUpdated = dataUpdatedAt ? fmtRelative(dataUpdatedAt) : null

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title="Dashboard"
        description="Live monitoring of workflow executions, recovery effectiveness, and failure patterns."
        actions={
          <div className="flex items-center gap-3">
            {lastUpdated && (
              <span className="hidden text-[11px] text-zinc-600 sm:block">Updated {lastUpdated}</span>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => refetch()}
              disabled={isFetching}
              className="gap-1.5 border border-white/8"
            >
              <RefreshCw className={`size-3.5 ${isFetching ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </div>
        }
      />

      <div className="mx-auto w-full max-w-7xl space-y-5 px-4 py-5 sm:px-6">

        {/* Company tabs */}
        {companies.length > 1 && (
          <div className="flex flex-wrap gap-2">
            {companies.map((c) => (
              <button
                key={c}
                onClick={() => setCompany(c)}
                className={`rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
                  activeCompany === c
                    ? 'border-white/20 bg-white/10 text-white'
                    : 'border-white/8 text-zinc-500 hover:border-white/14 hover:text-zinc-300'
                }`}
              >
                {c}
              </button>
            ))}
          </div>
        )}

        {!activeCompany ? (
          <div className="rounded-xl border border-white/8 bg-white/[0.02] px-6 py-16 text-center">
            <Activity className="mx-auto mb-3 size-8 text-zinc-700" />
            <p className="text-sm font-medium text-zinc-400">No plugins found</p>
            <p className="mt-1 text-xs text-zinc-600">Build an installer to start seeing execution data.</p>
          </div>
        ) : (
          <>
            {/* KPI strip */}
            <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <KpiCard
                label="Total Runs"
                value={stats.total}
                sub={stats.total > 0 ? `${stats.ok} passed · ${stats.failed} failed` : 'No data yet'}
                icon={Activity}
              />
              <KpiCard
                label="Success Rate"
                value={`${stats.successRate}%`}
                sub={`${stats.ok} of ${stats.total} runs`}
                icon={CheckCircle2}
                tone={stats.successRate >= 80 ? 'good' : stats.successRate >= 50 ? 'warn' : stats.total > 0 ? 'bad' : 'neutral'}
              />
              <KpiCard
                label="Avg Duration"
                value={fmtDuration(stats.avgDur)}
                sub="across completed runs"
                icon={Clock}
                tone="neutral"
              />
              <KpiCard
                label="Recovered Steps"
                value={stats.totalRec}
                sub={`${stats.withRec} runs needed recovery`}
                icon={Zap}
                tone={stats.totalRec > 0 ? 'warn' : 'good'}
              />
            </section>

            {/* Run history sparkline */}
            {stats.sparkline.length > 0 && (
              <Card className="border-white/8 bg-white/[0.025] shadow-none">
                <CardContent className="px-4 pt-3 pb-4">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-medium text-zinc-400">Run History</p>
                    <span className="text-[11px] text-zinc-600">last {stats.sparkline.length} runs</span>
                  </div>
                  <RunSparkline runs={stats.sparkline} />
                  <div className="mt-2 flex items-center gap-4 text-[10px] text-zinc-600">
                    <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-emerald-500" />success</span>
                    <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-red-500" />failure</span>
                    <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-zinc-700" />running</span>
                    <span className="ml-auto">height ∝ duration</span>
                  </div>
                </CardContent>
              </Card>
            )}

            <div className="grid gap-4 lg:grid-cols-3">
              {/* Left column: Failure reasons + Per-plugin */}
              <div className="space-y-4 lg:col-span-1">

                {/* Failure reasons */}
                <Card className="border-white/8 bg-white/[0.025] shadow-none">
                  <CardHeader className="border-b border-white/6 pb-3">
                    <CardTitle className="flex items-center gap-2 text-xs font-semibold text-zinc-400">
                      <AlertTriangle className="size-3.5" />
                      Failure Reasons
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-4">
                    {stats.failureCodes.length === 0 ? (
                      <p className="text-xs text-zinc-600">No failures recorded.</p>
                    ) : (
                      <div className="space-y-3">
                        {stats.failureCodes.map(([code, count]) => {
                          const max = stats.failureCodes[0][1]
                          const pct = Math.round((count / max) * 100)
                          return (
                            <div key={code} className="space-y-1">
                              <div className="flex items-center justify-between text-xs">
                                <span className="text-zinc-300">{FAILURE_LABELS[code] ?? code}</span>
                                <span className="tabular-nums text-red-400">{count}</span>
                              </div>
                              <div className="h-1 rounded-full bg-white/8 overflow-hidden">
                                <div className="h-full rounded-full bg-red-500/60" style={{ width: `${pct}%` }} />
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* Per-plugin breakdown */}
                {stats.pluginStats.length > 1 && (
                  <Card className="border-white/8 bg-white/[0.025] shadow-none">
                    <CardHeader className="border-b border-white/6 pb-3">
                      <CardTitle className="flex items-center gap-2 text-xs font-semibold text-zinc-400">
                        <Activity className="size-3.5" />
                        By Plugin
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="p-0">
                      {stats.pluginStats.map(([pid, s]) => {
                        const total = s.ok + s.fail
                        const rate  = total ? Math.round((s.ok / total) * 100) : 0
                        return (
                          <div key={pid} className="flex items-center gap-3 border-t border-white/6 px-4 py-2.5 first:border-t-0">
                            <div className="min-w-0 flex-1">
                              <p className="truncate text-xs font-medium text-zinc-300">{pid}</p>
                              <p className="text-[11px] text-zinc-600">{total} runs · {s.rec} recovered</p>
                            </div>
                            <div className={`text-xs font-semibold tabular-nums ${rate >= 80 ? 'text-emerald-400' : rate >= 50 ? 'text-amber-400' : 'text-red-400'}`}>
                              {rate}%
                            </div>
                          </div>
                        )
                      })}
                    </CardContent>
                  </Card>
                )}
              </div>

              {/* Right column: Recovery effectiveness + Run feed */}
              <div className="space-y-4 lg:col-span-2">

                {/* Run feed */}
                <Card className="border-white/8 bg-white/[0.025] shadow-none">
                  <CardHeader className="border-b border-white/6 pb-3">
                    <CardTitle className="flex items-center gap-2 text-xs font-semibold text-zinc-400">
                      <Activity className="size-3.5" />
                      Live Run Feed
                      <span className="ml-auto text-zinc-700">{runs.length} total</span>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-0">
                    {runs.length === 0 && !isFetching && (
                      <div className="px-4 py-10 text-center">
                        <p className="text-xs text-zinc-600">
                          No executions for <span className="font-mono text-zinc-500">{activeCompany}</span> yet.
                        </p>
                      </div>
                    )}
                    {isFetching && runs.length === 0 && (
                      <div className="space-y-px p-1">
                        {[...Array(5)].map((_, i) => (
                          <div key={i} className="h-12 animate-pulse rounded bg-white/[0.02]" />
                        ))}
                      </div>
                    )}
                    {runs.map((run) => (
                      <button
                        key={run.run_id}
                        className="group flex w-full items-center gap-3 border-t border-white/6 px-4 py-3 text-left transition-colors hover:bg-white/[0.03] first:border-t-0"
                        onClick={() => setSelectedRun(run)}
                      >
                        {/* Status icon */}
                        <div className="shrink-0">
                          {run.status === 'ok' ? (
                            <CheckCircle2 className="size-4 text-emerald-400" />
                          ) : run.status === 'fail' ? (
                            <CircleAlert className="size-4 text-red-400" />
                          ) : (
                            <Clock className="size-4 text-zinc-600" />
                          )}
                        </div>

                        {/* Plugin + time */}
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-xs font-medium text-zinc-200 group-hover:text-white">
                            {run.plugin_id || run.run_id.slice(0, 16)}
                          </p>
                          <p className="text-[11px] text-zinc-600">{fmtRelative(run.started_at)}</p>
                        </div>

                        {/* Failure code */}
                        {run.failure_code && (
                          <span className="hidden text-[10px] text-red-400/80 sm:block">
                            {FAILURE_LABELS[run.failure_code] ?? run.failure_code}
                          </span>
                        )}

                        {/* Recovery badge */}
                        {run.recovered_steps > 0 && (
                          <Badge variant="outline" className="text-[10px] border-blue-500/30 bg-blue-500/10 text-blue-300">
                            <Zap className="mr-0.5 size-2.5" />
                            {run.recovered_steps}
                          </Badge>
                        )}

                        {/* Duration */}
                        <span className="hidden text-[11px] text-zinc-600 sm:block">{fmtDuration(run.duration_ms)}</span>

                        {/* Status badge */}
                        <StatusBadge status={run.status} />
                      </button>
                    ))}
                  </CardContent>
                </Card>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Timeline drawer */}
      {selectedRun && (
        <TimelineDrawer
          company={activeCompany}
          runId={selectedRun.run_id}
          run={selectedRun}
          open={!!selectedRun}
          onClose={() => setSelectedRun(null)}
        />
      )}
    </div>
  )
}
