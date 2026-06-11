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

const DEFAULT_RECOVERY_USAGE: TrackingDashboardResponse['recovery_type_usage'] = [
  { type: 'Selector', count: 0 },
  { type: 'Text Anchor', count: 0 },
  { type: 'Text Variant', count: 0 },
  { type: 'Vision', count: 0 },
]

type Tone = 'good' | 'warn' | 'bad' | 'neutral'

type DashboardHealth = {
  label: 'Healthy' | 'Degraded' | 'Attention needed' | 'No telemetry'
  tone: Tone
  description: string
}

type RiskRow = {
  id: string
  type: 'Workflow' | 'Step'
  name: string
  context: string
  failedExecutions: number
  failureCode: string
  lastSeen: number
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

function clampPercent(value: number) {
  return `${Math.max(0, Math.min(100, Math.round(value)))}%`
}

function deriveDashboardHealth(metrics: TrackingDashboardResponse['metrics']): DashboardHealth {
  if (metrics.total_executions === 0) {
    return {
      label: 'No telemetry',
      tone: 'neutral',
      description: 'Production runtime data will appear here after the first customer execution.',
    }
  }

  if (metrics.success_rate >= 95 && metrics.failed_executions === 0) {
    return {
      label: 'Healthy',
      tone: 'good',
      description: 'Executions are completing cleanly with no active failure pressure.',
    }
  }

  if (metrics.success_rate >= 85) {
    return {
      label: 'Degraded',
      tone: 'warn',
      description: 'Reliability is usable, but failures or recoveries need operator review.',
    }
  }

  return {
    label: 'Attention needed',
    tone: 'bad',
    description: 'Execution health is below target. Prioritize the risk queue before new rollout work.',
  }
}

function buildRiskRows(data?: TrackingDashboardResponse): RiskRow[] {
  if (!data) return []

  const workflowRows = data.most_failed_workflows.map((row) => ({
    id: `workflow:${row.workflow}`,
    type: 'Workflow' as const,
    name: row.workflow,
    context: 'Workflow failure',
    failedExecutions: row.failed_executions,
    failureCode: row.last_failure_code || 'unknown failure',
    lastSeen: row.last_seen,
  }))

  const stepRows = data.most_failed_steps.map((row) => ({
    id: `step:${row.workflow}:${row.step_index ?? 'unknown'}:${row.step_label}`,
    type: 'Step' as const,
    name: row.step_label,
    context: `${row.workflow}${row.step_index === null ? '' : ` / step ${row.step_index + 1}`}`,
    failedExecutions: row.failed_executions,
    failureCode: row.last_failure_code || 'unknown failure',
    lastSeen: row.last_seen,
  }))

  return [...workflowRows, ...stepRows]
    .sort((a, b) => b.failedExecutions - a.failedExecutions || b.lastSeen - a.lastSeen)
    .slice(0, 8)
}

function toneClasses(tone: Tone) {
  if (tone === 'good') {
    return {
      text: 'text-emerald-300',
      bg: 'bg-emerald-500/10',
      border: 'border-emerald-500/25',
      icon: 'bg-emerald-500/10 text-emerald-300',
    }
  }
  if (tone === 'warn') {
    return {
      text: 'text-amber-300',
      bg: 'bg-amber-500/10',
      border: 'border-amber-500/25',
      icon: 'bg-amber-500/10 text-amber-300',
    }
  }
  if (tone === 'bad') {
    return {
      text: 'text-red-300',
      bg: 'bg-red-500/10',
      border: 'border-red-500/25',
      icon: 'bg-red-500/10 text-red-300',
    }
  }
  return {
    text: 'text-zinc-100',
    bg: 'bg-white/[0.035]',
    border: 'border-white/10',
    icon: 'bg-white/[0.05] text-zinc-400',
  }
}

function MetricCell({
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
  tone?: Tone
}) {
  const classes = toneClasses(tone)

  return (
    <div className="min-w-0 rounded-lg border border-white/8 bg-white/[0.025] px-3 py-3">
      <div className="flex items-center gap-2">
        <span className={`flex size-7 shrink-0 items-center justify-center rounded-md ${classes.icon}`}>
          <Icon className="size-3.5" />
        </span>
        <p className="truncate text-[11px] font-medium text-zinc-500">{label}</p>
      </div>
      <p className={`mt-2 truncate text-xl font-semibold tabular-nums leading-none ${classes.text}`}>{value}</p>
      <p className="mt-1 truncate text-[11px] text-zinc-600">{sub}</p>
    </div>
  )
}

function CommandSummary({
  metrics,
  range,
}: {
  metrics: TrackingDashboardResponse['metrics']
  range: TrackingDashboardRange
}) {
  const health = deriveDashboardHealth(metrics)
  const classes = toneClasses(health.tone)
  const rangeText = rangeLabel(range).toLowerCase()

  return (
    <Card className="border-white/8 bg-white/[0.03] shadow-none">
      <CardContent className="grid gap-4 p-4 xl:grid-cols-[minmax(18rem,0.32fr)_minmax(0,1fr)]">
        <div className={`rounded-lg border px-4 py-4 ${classes.border} ${classes.bg}`}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs font-medium text-zinc-500">Operational status</p>
              <p className={`mt-2 text-2xl font-semibold leading-tight ${classes.text}`}>{health.label}</p>
            </div>
            <span className={`flex size-9 shrink-0 items-center justify-center rounded-lg ${classes.icon}`}>
              {health.tone === 'good' ? <CheckCircle2 className="size-5" /> : <AlertTriangle className="size-5" />}
            </span>
          </div>
          <p className="mt-3 text-sm leading-5 text-zinc-400">{health.description}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Badge variant="outline" className="border-white/10 bg-black/10 text-[10px] text-zinc-400">
              {rangeLabel(range)}
            </Badge>
            <Badge variant="outline" className="border-white/10 bg-black/10 text-[10px] text-zinc-400">
              {fmtNumber(metrics.failed_executions)} failures
            </Badge>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <MetricCell label="Total executions" value={fmtNumber(metrics.total_executions)} sub={`${fmtNumber(metrics.executions_last_24h)} in last 24h`} icon={Activity} />
          <MetricCell label="Active users" value={fmtNumber(metrics.active_users)} sub={`active in ${rangeText}`} icon={Users} />
          <MetricCell label="Active companies" value={fmtNumber(metrics.active_companies)} sub="companies with usage" icon={Building2} />
          <MetricCell label="Success rate" value={fmtPercent(metrics.success_rate)} sub="completed executions" icon={ShieldCheck} tone={health.tone === 'bad' ? 'bad' : health.tone === 'warn' ? 'warn' : 'good'} />
          <MetricCell label="Recovery rate" value={fmtPercent(metrics.recovery_rate)} sub="executions saved" icon={RotateCcw} tone={metrics.recovery_rate > 0 ? 'good' : 'neutral'} />
          <MetricCell label="Avg duration" value={fmtDuration(metrics.average_execution_time)} sub="all completed runs" icon={Clock3} />
        </div>
      </CardContent>
    </Card>
  )
}

function TrendChart({
  rows,
  range,
}: {
  rows: TrackingDashboardResponse['execution_trend']
  range: TrackingDashboardRange
}) {
  const max = Math.max(1, ...rows.map((row) => row.executions))
  const hasExecutions = rows.some((row) => row.executions > 0)
  const width = 720
  const height = 190
  const barSlot = rows.length ? width / rows.length : width
  const chartHeight = 126

  return (
    <Card className="h-full border-white/8 bg-white/[0.025] shadow-none">
      <CardHeader className="border-b border-white/6 pb-3">
        <CardTitle className="flex flex-wrap items-center gap-2 text-xs font-semibold text-zinc-400">
          <TrendingUp className="size-3.5" />
          Execution trend
          <span className="ml-auto text-[11px] font-normal text-zinc-600">{rangeLabel(range)}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-4">
        <div className="relative h-[190px] w-full overflow-hidden">
          <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" preserveAspectRatio="none" role="img" aria-label="Execution trend graph">
            <line x1="0" x2={width} y1="142" y2="142" className="stroke-white/10" />
            {rows.map((row, index) => {
              const x = index * barSlot + barSlot * 0.18
              const barWidth = Math.max(8, barSlot * 0.64)
              const totalHeight = Math.max(row.executions > 0 ? 3 : 0, (row.executions / max) * chartHeight)
              const failedHeight = row.executions ? (row.failed / row.executions) * totalHeight : 0
              const recoveredHeight = row.executions ? (row.recovered / row.executions) * totalHeight : 0
              const successHeight = Math.max(0, totalHeight - failedHeight - recoveredHeight)
              const y = 142 - totalHeight

              return (
                <g key={row.date}>
                  <rect x={x} y={y} width={barWidth} height={successHeight} rx="3" className="fill-emerald-500/75" />
                  <rect x={x} y={y + successHeight} width={barWidth} height={recoveredHeight} rx="3" className="fill-blue-500/75" />
                  <rect x={x} y={y + successHeight + recoveredHeight} width={barWidth} height={failedHeight} rx="3" className="fill-red-500/75" />
                  {(index === 0 || index === rows.length - 1 || rows.length <= 7) && (
                    <text x={x + barWidth / 2} y="166" textAnchor="middle" className="fill-zinc-600 text-[10px]">
                      {new Date(`${row.date}T00:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })}
                    </text>
                  )}
                </g>
              )
            })}
          </svg>
          {!hasExecutions && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="rounded-lg border border-white/8 bg-black/20 px-3 py-2 text-xs text-zinc-500">
                No executions in this range
              </div>
            </div>
          )}
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

function RuntimeFootprint({ metrics }: { metrics: TrackingDashboardResponse['metrics'] }) {
  const items = [
    { label: 'Installed runtimes', value: fmtNumber(metrics.total_installs), icon: Download },
    { label: 'Active users', value: fmtNumber(metrics.active_users), icon: Users },
    { label: 'Active companies', value: fmtNumber(metrics.active_companies), icon: Building2 },
    { label: 'Last 24h runs', value: fmtNumber(metrics.executions_last_24h), icon: Activity },
  ]

  return (
    <Card className="h-full border-white/8 bg-white/[0.025] shadow-none">
      <CardHeader className="border-b border-white/6 pb-3">
        <CardTitle className="flex items-center gap-2 text-xs font-semibold text-zinc-400">
          <Download className="size-3.5" />
          Runtime footprint
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2 p-4 sm:grid-cols-2 xl:grid-cols-1">
        {items.map(({ label, value, icon: Icon }) => (
          <div key={label} className="flex items-center justify-between gap-3 rounded-lg border border-white/8 bg-white/[0.025] px-3 py-3">
            <span className="flex min-w-0 items-center gap-2 text-xs text-zinc-500">
              <Icon className="size-3.5 shrink-0 text-zinc-600" />
              <span className="truncate">{label}</span>
            </span>
            <span className="shrink-0 text-sm font-semibold tabular-nums text-zinc-200">{value}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function RiskQueue({ rows }: { rows: RiskRow[] }) {
  return (
    <Card className="h-full border-white/8 bg-white/[0.025] shadow-none">
      <CardHeader className="border-b border-white/6 pb-3">
        <CardTitle className="flex items-center gap-2 text-xs font-semibold text-zinc-400">
          <AlertTriangle className="size-3.5" />
          Risk queue
          {rows.length > 0 && (
            <Badge variant="outline" className="ml-auto border-red-500/25 bg-red-500/10 text-[10px] text-red-300">
              {rows.length} active
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {rows.length === 0 ? (
          <div className="flex min-h-72 flex-col items-center justify-center px-4 py-10 text-center">
            <CheckCircle2 className="mb-3 size-7 text-emerald-500/70" />
            <p className="text-sm font-medium text-zinc-300">No active risks</p>
            <p className="mt-1 max-w-xs text-xs leading-5 text-zinc-600">No failed workflows or failed steps were reported in this range.</p>
          </div>
        ) : rows.map((row) => {
          const isWorkflow = row.type === 'Workflow'
          return (
            <div key={row.id} className="grid gap-3 border-t border-white/6 px-4 py-3 first:border-t-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-2">
                  <Badge
                    variant="outline"
                    className={isWorkflow ? 'border-red-500/25 bg-red-500/10 text-[10px] text-red-300' : 'border-amber-500/25 bg-amber-500/10 text-[10px] text-amber-300'}
                  >
                    {isWorkflow ? 'Workflow' : 'Step'}
                  </Badge>
                  <p className="truncate text-xs font-medium text-zinc-200">{row.name}</p>
                </div>
                <p className="mt-1 truncate text-[11px] text-zinc-600">{row.context} / {row.failureCode} / {fmtRelative(row.lastSeen)}</p>
              </div>
              <div className="flex items-center gap-2 sm:justify-end">
                {isWorkflow ? <AlertTriangle className="size-3.5 text-red-400" /> : <Zap className="size-3.5 text-amber-300" />}
                <span className="text-sm font-semibold tabular-nums text-red-200">{fmtNumber(row.failedExecutions)}</span>
              </div>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}

function RecoveryTypeBars({ rows }: { rows: TrackingDashboardResponse['recovery_type_usage'] }) {
  const max = Math.max(1, ...rows.map((row) => row.count))

  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {rows.map((row) => (
        <div key={row.type} className="rounded-lg border border-white/8 bg-white/[0.025] px-3 py-3">
          <div className="flex items-center justify-between gap-3 text-xs">
            <span className="truncate text-zinc-400">{row.type}</span>
            <span className="shrink-0 tabular-nums text-zinc-500">{fmtNumber(row.count)}</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/8">
            <div
              className="h-full rounded-full bg-blue-500/80"
              style={{ width: clampPercent((row.count / max) * 100) }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

function RecoveryIntelligence({
  typeRows,
  workflows,
}: {
  typeRows: TrackingDashboardResponse['recovery_type_usage']
  workflows: TrackingDashboardResponse['recovery_usage_by_workflow']
}) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const selectedWorkflow = useMemo(() => {
    if (workflows.length === 0) return null
    return workflows.find((row) => `${row.company}:${row.workflow}` === selectedKey) ?? workflows[0]
  }, [selectedKey, workflows])
  const activeKey = selectedWorkflow ? `${selectedWorkflow.company}:${selectedWorkflow.workflow}` : null

  return (
    <Card className="h-full border-white/8 bg-white/[0.025] shadow-none">
      <CardHeader className="border-b border-white/6 pb-3">
        <CardTitle className="flex items-center gap-2 text-xs font-semibold text-zinc-400">
          <RotateCcw className="size-3.5" />
          Recovery intelligence
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 p-4">
        <RecoveryTypeBars rows={typeRows} />

        {workflows.length === 0 || !selectedWorkflow ? (
          <div className="flex min-h-56 flex-col items-center justify-center rounded-lg border border-white/8 bg-white/[0.02] px-4 py-8 text-center">
            <CheckCircle2 className="mb-3 size-7 text-zinc-700" />
            <p className="text-sm font-medium text-zinc-400">No recovery usage recorded</p>
            <p className="mt-1 max-w-sm text-xs leading-5 text-zinc-600">Tier and selector recovery data will appear after runtime self-healing events are reported.</p>
          </div>
        ) : (
          <div className="grid overflow-hidden rounded-lg border border-white/8 lg:grid-cols-[minmax(14rem,0.36fr)_minmax(0,1fr)]">
            <div className="max-h-[26rem] overflow-y-auto border-b border-white/8 lg:border-b-0 lg:border-r">
              {workflows.map((row) => {
                const key = `${row.company}:${row.workflow}`
                const selected = key === activeKey
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setSelectedKey(key)}
                    className={`flex w-full cursor-pointer items-center gap-3 border-t border-white/6 px-3 py-3 text-left transition-colors first:border-t-0 ${
                      selected ? 'bg-white/[0.06]' : 'hover:bg-white/[0.035]'
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium text-zinc-200">{row.workflow}</p>
                      <p className="mt-0.5 truncate text-[11px] text-zinc-600">{row.company} / {fmtRelative(row.last_seen)}</p>
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
                    {fmtNumber(selectedWorkflow.count)} recoveries across {fmtNumber(selectedWorkflow.steps.length)} recovered steps
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
                  className="grid gap-3 border-t border-white/6 px-4 py-3 first:border-t-0 md:grid-cols-[minmax(0,0.42fr)_minmax(0,1fr)] md:items-center"
                >
                  <div className="min-w-0">
                    <p className="truncate text-xs font-medium text-zinc-200">{step.step_label}</p>
                    <p className="mt-0.5 text-[11px] text-zinc-600">
                      {step.step_index === null ? 'step unknown' : `step ${step.step_index + 1}`} / {fmtNumber(step.total_count)} recoveries / {fmtRelative(step.last_seen)}
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
                        <span className="text-zinc-600">/</span>
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

function DashboardSkeleton() {
  return (
    <div className="space-y-4">
      <Card className="border-white/8 bg-white/[0.03] shadow-none">
        <CardContent className="grid gap-4 p-4 xl:grid-cols-[minmax(18rem,0.32fr)_minmax(0,1fr)]">
          <div className="h-40 animate-pulse rounded-lg bg-white/[0.05]" />
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2, 3, 4, 5].map((item) => (
              <div key={item} className="h-24 animate-pulse rounded-lg bg-white/[0.045]" />
            ))}
          </div>
        </CardContent>
      </Card>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="h-72 animate-pulse rounded-lg border border-white/8 bg-white/[0.035]" />
        <div className="h-72 animate-pulse rounded-lg border border-white/8 bg-white/[0.035]" />
      </div>
    </div>
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
  const riskRows = useMemo(() => buildRiskRows(data), [data])
  const recoveryTypeRows = data?.recovery_type_usage ?? DEFAULT_RECOVERY_USAGE
  const recoveryWorkflows = data?.recovery_usage_by_workflow ?? []
  const isInitialLoading = dashboardQ.isLoading && !data

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title="Dashboard"
        description="Operations overview for installed automations, execution health, and recovery behavior."
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <div className="flex rounded-lg border border-white/8 bg-white/[0.025] p-0.5">
              {(['7d', '30d'] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setRange(item)}
                  className={`h-8 cursor-pointer rounded-md px-3 text-xs font-medium transition-colors ${
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

      <div className="mx-auto w-full max-w-7xl space-y-4 px-4 py-5 sm:px-6">
        {dashboardQ.isError && (
          <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            Dashboard metrics could not be loaded.
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-zinc-600">{rangeLabel(range)}</p>
          {dashboardQ.dataUpdatedAt > 0 && (
            <p className="text-xs text-zinc-600">Updated {fmtRelative(dashboardQ.dataUpdatedAt)}</p>
          )}
        </div>

        {isInitialLoading ? (
          <DashboardSkeleton />
        ) : (
          <>
            <CommandSummary metrics={metrics} range={range} />

            <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
              <TrendChart rows={data?.execution_trend ?? []} range={range} />
              <RuntimeFootprint metrics={metrics} />
            </section>

            <section className="grid gap-4 xl:grid-cols-[minmax(20rem,0.38fr)_minmax(0,1fr)]">
              <RiskQueue rows={riskRows} />
              <RecoveryIntelligence typeRows={recoveryTypeRows} workflows={recoveryWorkflows} />
            </section>
          </>
        )}
      </div>
    </div>
  )
}
