'use client'

import { useMemo, useState, type ComponentType } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchTrackingDashboard,
  type TrackingDashboardRange,
  type TrackingDashboardResponse,
} from '@/api/pluginApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Activity,
  AlertTriangle,
  Building2,
  ChevronRight,
  CheckCircle2,
  Clock3,
  Download,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  TrendingUp,
  Users,
  Zap,
} from 'lucide-react'

const EMPTY_METRICS: TrackingDashboardResponse['metrics'] = {
  total_installs: 0,
  active_users: 0,
  active_companies: 0,
  total_executions: 0,
  executions_last_24h: 0,
  success_rate: 0,
  failed_executions: 0,
  recovery_rate: 0,
  average_execution_time: 0,
}

function fmtNumber(value: number) {
  return new Intl.NumberFormat().format(value || 0)
}

function fmtPercent(value: number) {
  return `${Number(value || 0).toFixed(1).replace(/\.0$/, '')}%`
}

function fmtDuration(ms: number) {
  if (!ms) return '0ms'
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1).replace(/\.0$/, '')}s`
  return `${Math.round(ms / 60_000)}m`
}

function fmtRelative(epochMs: number) {
  if (!epochMs) return 'No timestamp'
  const diff = Date.now() - epochMs
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return new Date(epochMs).toLocaleDateString([], { month: 'short', day: 'numeric' })
}

function rangeLabel(range: TrackingDashboardRange) {
  return range === '30d' ? 'Last 30 days' : 'Last 7 days'
}

function KpiCard({
  label,
  value,
  sub,
  icon: Icon,
  tone = 'neutral',
}: {
  label: string
  value: string
  sub: string
  icon: ComponentType<{ className?: string }>
  tone?: 'good' | 'warn' | 'bad' | 'neutral'
}) {
  const toneClass =
    tone === 'good' ? 'text-emerald-300' :
      tone === 'warn' ? 'text-amber-300' :
        tone === 'bad' ? 'text-red-300' :
          'text-zinc-100'
  const iconClass =
    tone === 'good' ? 'bg-emerald-500/10 text-emerald-300' :
      tone === 'warn' ? 'bg-amber-500/10 text-amber-300' :
        tone === 'bad' ? 'bg-red-500/10 text-red-300' :
          'bg-white/[0.04] text-zinc-400'

  return (
    <Card className="border-white/8 bg-white/[0.025] shadow-none">
      <CardContent className="flex min-h-[7rem] items-start justify-between gap-3 p-4">
        <div className="min-w-0">
          <p className="text-xs font-medium text-zinc-500">{label}</p>
          <p className={`mt-2 text-2xl font-semibold leading-none tabular-nums ${toneClass}`}>{value}</p>
          <p className="mt-2 text-[11px] leading-snug text-zinc-600">{sub}</p>
        </div>
        <div className={`rounded-lg p-2 ${iconClass}`}>
          <Icon className="size-4" />
        </div>
      </CardContent>
    </Card>
  )
}

function TrendChart({ rows }: { rows: TrackingDashboardResponse['execution_trend'] }) {
  const max = Math.max(1, ...rows.map((row) => row.executions))
  const width = 720
  const height = 170
  const barSlot = rows.length ? width / rows.length : width
  const chartHeight = 116

  return (
    <Card className="border-white/8 bg-white/[0.025] shadow-none">
      <CardHeader className="border-b border-white/6 pb-3">
        <CardTitle className="flex items-center gap-2 text-xs font-semibold text-zinc-400">
          <TrendingUp className="size-3.5" />
          Execution Trend
          <span className="ml-auto text-[11px] font-normal text-zinc-600">success, failure, and recovery volume</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-4">
        <div className="h-[170px] w-full overflow-hidden">
          <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" preserveAspectRatio="none" role="img" aria-label="Execution trend graph">
            <line x1="0" x2={width} y1="132" y2="132" className="stroke-white/10" />
            {rows.map((row, index) => {
              const x = index * barSlot + barSlot * 0.18
              const barWidth = Math.max(8, barSlot * 0.64)
              const totalHeight = Math.max(2, (row.executions / max) * chartHeight)
              const failedHeight = row.executions ? (row.failed / row.executions) * totalHeight : 0
              const recoveredHeight = row.executions ? (row.recovered / row.executions) * totalHeight : 0
              const successHeight = Math.max(0, totalHeight - failedHeight - recoveredHeight)
              const y = 132 - totalHeight
              return (
                <g key={row.date}>
                  <rect x={x} y={y} width={barWidth} height={successHeight} rx="3" className="fill-emerald-500/75" />
                  <rect x={x} y={y + successHeight} width={barWidth} height={recoveredHeight} rx="3" className="fill-blue-500/75" />
                  <rect x={x} y={y + successHeight + recoveredHeight} width={barWidth} height={failedHeight} rx="3" className="fill-red-500/75" />
                  {(index === 0 || index === rows.length - 1 || rows.length <= 7) && (
                    <text x={x + barWidth / 2} y="154" textAnchor="middle" className="fill-zinc-600 text-[10px]">
                      {new Date(`${row.date}T00:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })}
                    </text>
                  )}
                </g>
              )
            })}
          </svg>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-4 text-[11px] text-zinc-600">
          <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-emerald-500" />Successful</span>
          <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-blue-500" />Recovered</span>
          <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-red-500" />Failed</span>
        </div>
      </CardContent>
    </Card>
  )
}

function RecoveryUsage({ rows }: { rows: TrackingDashboardResponse['recovery_type_usage'] }) {
  const max = Math.max(1, ...rows.map((row) => row.count))
  return (
    <Card className="border-white/8 bg-white/[0.025] shadow-none">
      <CardHeader className="border-b border-white/6 pb-3">
        <CardTitle className="flex items-center gap-2 text-xs font-semibold text-zinc-400">
          <RotateCcw className="size-3.5" />
          Recovery Type Usage
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 p-4">
        {rows.map((row) => (
          <div key={row.type} className="space-y-1.5">
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className="text-zinc-300">{row.type}</span>
              <span className="tabular-nums text-zinc-500">{fmtNumber(row.count)}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-white/8">
              <div
                className="h-full rounded-full bg-blue-500/80"
                style={{ width: `${Math.max(0, Math.round((row.count / max) * 100))}%` }}
              />
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function FailureLists({
  workflows,
  steps,
}: {
  workflows: TrackingDashboardResponse['most_failed_workflows']
  steps: TrackingDashboardResponse['most_failed_steps']
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="border-white/8 bg-white/[0.025] shadow-none">
        <CardHeader className="border-b border-white/6 pb-3">
          <CardTitle className="flex items-center gap-2 text-xs font-semibold text-zinc-400">
            <AlertTriangle className="size-3.5" />
            Most Failed Workflows
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {workflows.length === 0 ? (
            <p className="px-4 py-8 text-center text-xs text-zinc-600">No workflow failures in this range.</p>
          ) : workflows.map((row) => (
            <div key={row.workflow} className="flex items-center gap-3 border-t border-white/6 px-4 py-3 first:border-t-0">
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-zinc-200">{row.workflow}</p>
                <p className="mt-0.5 text-[11px] text-zinc-600">{row.last_failure_code || 'unknown failure'} · {fmtRelative(row.last_seen)}</p>
              </div>
              <span className="text-sm font-semibold tabular-nums text-red-300">{fmtNumber(row.failed_executions)}</span>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="border-white/8 bg-white/[0.025] shadow-none">
        <CardHeader className="border-b border-white/6 pb-3">
          <CardTitle className="flex items-center gap-2 text-xs font-semibold text-zinc-400">
            <Zap className="size-3.5" />
            Most Failed Steps
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {steps.length === 0 ? (
            <p className="px-4 py-8 text-center text-xs text-zinc-600">No step failures in this range.</p>
          ) : steps.map((row) => (
            <div key={`${row.workflow}:${row.step_index ?? 'unknown'}`} className="flex items-center gap-3 border-t border-white/6 px-4 py-3 first:border-t-0">
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-zinc-200">{row.step_label}</p>
                <p className="mt-0.5 truncate text-[11px] text-zinc-600">{row.workflow} · {row.last_failure_code || 'unknown failure'}</p>
              </div>
              <span className="text-sm font-semibold tabular-nums text-red-300">{fmtNumber(row.failed_executions)}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

function RecoveryByStep({ workflows }: { workflows: TrackingDashboardResponse['recovery_usage_by_workflow'] }) {
  return <RecoveryWorkflowDrilldown workflows={workflows} />
}

function RecoveryWorkflowDrilldown({
  workflows,
}: {
  workflows: TrackingDashboardResponse['recovery_usage_by_workflow']
}) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const selectedWorkflow = useMemo(() => {
    if (workflows.length === 0) return null
    return workflows.find((row) => `${row.company}:${row.workflow}` === selectedKey) ?? workflows[0]
  }, [selectedKey, workflows])
  const activeKey = selectedWorkflow ? `${selectedWorkflow.company}:${selectedWorkflow.workflow}` : null

  return (
    <Card className="border-white/8 bg-white/[0.025] shadow-none">
      <CardHeader className="border-b border-white/6 pb-3">
        <CardTitle className="flex items-center gap-2 text-xs font-semibold text-zinc-400">
          <RotateCcw className="size-3.5" />
          Recovery By Workflow And Step
          <span className="ml-auto text-[11px] font-normal text-zinc-600">click a workflow for step tier counts</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {workflows.length === 0 || !selectedWorkflow ? (
          <p className="px-4 py-10 text-center text-xs text-zinc-600">No recovery usage recorded in this range.</p>
        ) : (
          <div className="grid min-h-[22rem] lg:grid-cols-[minmax(18rem,0.36fr)_minmax(0,1fr)]">
            <div className="border-b border-white/6 lg:border-b-0 lg:border-r">
              {workflows.map((row) => {
                const key = `${row.company}:${row.workflow}`
                const selected = key === activeKey
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setSelectedKey(key)}
                    className={`flex w-full items-center gap-3 border-t border-white/6 px-4 py-3 text-left transition-colors first:border-t-0 ${
                      selected ? 'bg-white/[0.055]' : 'hover:bg-white/[0.035]'
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium text-zinc-200">{row.workflow}</p>
                      <p className="mt-0.5 truncate text-[11px] text-zinc-600">{row.company} · {fmtRelative(row.last_seen)}</p>
                    </div>
                    <span className="text-sm font-semibold tabular-nums text-blue-200">{fmtNumber(row.count)}</span>
                    <ChevronRight className={`size-3.5 shrink-0 ${selected ? 'text-zinc-200' : 'text-zinc-700'}`} />
                  </button>
                )
              })}
            </div>

            <div className="min-w-0">
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/6 px-4 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-zinc-100">{selectedWorkflow.workflow}</p>
                  <p className="mt-0.5 text-[11px] text-zinc-600">
                    {fmtNumber(selectedWorkflow.count)} recovery executions across {fmtNumber(selectedWorkflow.steps.length)} recovered steps
                  </p>
                </div>
                <Badge variant="outline" className="border-blue-500/30 bg-blue-500/10 text-[10px] text-blue-300">
                  {selectedWorkflow.company}
                </Badge>
              </div>

              {selectedWorkflow.steps.length === 0 ? (
                <p className="px-4 py-10 text-center text-xs text-zinc-600">No step-level tier data recorded for this workflow.</p>
              ) : selectedWorkflow.steps.map((step) => (
                <div
                  key={`${step.step_index ?? 'unknown'}:${step.step_label}`}
                  className="grid gap-3 border-t border-white/6 px-4 py-3 first:border-t-0 md:grid-cols-[minmax(0,0.45fr)_minmax(0,1fr)] md:items-center"
                >
                  <div className="min-w-0">
                    <p className="truncate text-xs font-medium text-zinc-200">{step.step_label}</p>
                    <p className="mt-0.5 text-[11px] text-zinc-600">
                      {step.step_index === null ? 'step unknown' : `step ${step.step_index + 1}`} · {fmtNumber(step.total_count)} recoveries · {fmtRelative(step.last_seen)}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {step.tier_counts.length === 0 ? (
                      <span className="text-xs text-zinc-600">No tier counts</span>
                    ) : step.tier_counts.map((tier) => (
                      <Badge
                        key={`${step.step_index ?? 'unknown'}:${tier.tier}:${tier.recovery_type}`}
                        variant="outline"
                        className="gap-1.5 border-white/10 bg-white/[0.035] px-2 py-1 text-[10px] text-zinc-300"
                      >
                        <span>{tier.tier}</span>
                        <span className="text-zinc-600">·</span>
                        <span className="text-zinc-500">{tier.recovery_type}</span>
                        <span className="ml-1 font-semibold tabular-nums text-blue-200">{fmtNumber(tier.count)}</span>
                      </Badge>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function DashboardPage() {
  const [range, setRange] = useState<TrackingDashboardRange>('7d')
  const dashboardQ = useQuery({
    queryKey: ['tracking-dashboard', range],
    queryFn: () => fetchTrackingDashboard(range),
    staleTime: 30_000,
    refetchInterval: 30_000,
  })

  const data = dashboardQ.data
  const metrics = data?.metrics ?? EMPTY_METRICS
  const successTone = metrics.total_executions === 0 ? 'neutral' : metrics.success_rate >= 90 ? 'good' : metrics.success_rate >= 75 ? 'warn' : 'bad'
  const recoveryTone = metrics.recovery_rate > 0 ? 'good' : 'neutral'

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title="Dashboard"
        description="Adoption, usage, reliability, and recovery health for installed automations."
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <div className="flex rounded-lg border border-white/8 bg-white/[0.025] p-0.5">
              {(['7d', '30d'] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setRange(item)}
                  className={`h-8 rounded-md px-3 text-xs font-medium transition-colors ${
                    range === item ? 'bg-white/10 text-white' : 'text-zinc-500 hover:text-zinc-300'
                  }`}
                >
                  {item}
                </button>
              ))}
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => dashboardQ.refetch()}
              disabled={dashboardQ.isFetching}
              className="gap-1.5 border border-white/8"
            >
              <RefreshCw className={`size-3.5 ${dashboardQ.isFetching ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </div>
        }
      />

      <div className="mx-auto w-full max-w-7xl space-y-5 px-4 py-5 sm:px-6">
        {dashboardQ.isError && (
          <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            Dashboard metrics could not be loaded.
          </div>
        )}

        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-zinc-600">{rangeLabel(range)}</p>
          {dashboardQ.dataUpdatedAt > 0 && (
            <p className="text-xs text-zinc-600">Updated {fmtRelative(dashboardQ.dataUpdatedAt)}</p>
          )}
        </div>

        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <KpiCard label="Total Installs" value={fmtNumber(metrics.total_installs)} sub="registered runtimes" icon={Download} />
          <KpiCard label="Active Users" value={fmtNumber(metrics.active_users)} sub={`active in ${rangeLabel(range).toLowerCase()}`} icon={Users} />
          <KpiCard label="Active Companies" value={fmtNumber(metrics.active_companies)} sub="companies with usage" icon={Building2} />
          <KpiCard label="Total Executions" value={fmtNumber(metrics.total_executions)} sub={`${fmtNumber(metrics.executions_last_24h)} in the last 24h`} icon={Activity} />
        </section>

        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <KpiCard label="Success Rate" value={fmtPercent(metrics.success_rate)} sub="completed executions" icon={ShieldCheck} tone={successTone} />
          <KpiCard label="Failed Executions" value={fmtNumber(metrics.failed_executions)} sub={`failures in ${rangeLabel(range).toLowerCase()}`} icon={AlertTriangle} tone={metrics.failed_executions > 0 ? 'bad' : 'good'} />
          <KpiCard label="Recovery Rate" value={fmtPercent(metrics.recovery_rate)} sub="executions saved by recovery" icon={RotateCcw} tone={recoveryTone} />
          <KpiCard label="Avg Execution Time" value={fmtDuration(metrics.average_execution_time)} sub="successful and failed runs" icon={Clock3} />
        </section>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <TrendChart rows={data?.execution_trend ?? []} />
          <RecoveryUsage rows={data?.recovery_type_usage ?? [
            { type: 'Selector', count: 0 },
            { type: 'Text Anchor', count: 0 },
            { type: 'Text Variant', count: 0 },
            { type: 'Vision', count: 0 },
          ]} />
        </div>

        <FailureLists
          workflows={data?.most_failed_workflows ?? []}
          steps={data?.most_failed_steps ?? []}
        />

        <RecoveryByStep workflows={data?.recovery_usage_by_workflow ?? []} />

        {!dashboardQ.isFetching && metrics.total_installs === 0 && metrics.total_executions === 0 && (
          <div className="rounded-lg border border-white/8 bg-white/[0.02] px-5 py-6 text-center">
            <CheckCircle2 className="mx-auto mb-3 size-7 text-zinc-700" />
            <p className="text-sm font-medium text-zinc-400">No production telemetry yet</p>
            <p className="mt-1 text-xs text-zinc-600">Install and run a published plugin to populate adoption and reliability metrics.</p>
          </div>
        )}
      </div>
    </div>
  )
}
