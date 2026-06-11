'use client'

import { useMemo, useState, type ComponentType } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAuditEvents, type AuditEvent } from '@/api/productApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '@/components/product/ProductPrimitives'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Activity,
  Clock3,
  Database,
  Download,
  Filter,
  RefreshCw,
  Search,
  ShieldCheck,
  UserRound,
} from 'lucide-react'

const ALL_ACTIONS = 'all'

function formatAction(value: string) {
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function formatTime(value: number) {
  return new Date(value * 1000).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function formatRelative(value: number) {
  const diff = Date.now() - value * 1000
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

function eventSearchText(event: AuditEvent) {
  return [
    event.id,
    event.user_id,
    event.action,
    event.resource_type,
    event.resource_id,
    JSON.stringify(event.metadata ?? {}),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

function csvEscape(value: unknown) {
  const text = typeof value === 'string' ? value : JSON.stringify(value ?? '')
  return `"${text.replace(/"/g, '""')}"`
}

function downloadCsv(rows: AuditEvent[]) {
  const headers = ['time', 'action', 'resource_type', 'resource_id', 'user_id', 'event_id', 'metadata']
  const lines = rows.map((event) =>
    [
      new Date(event.created_at * 1000).toISOString(),
      event.action,
      event.resource_type,
      event.resource_id ?? '',
      event.user_id,
      event.id,
      event.metadata ?? {},
    ]
      .map(csvEscape)
      .join(','),
  )
  const blob = new Blob([[headers.join(','), ...lines].join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `conxa-audit-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

function SummaryMetric({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string
  value: string
  detail: string
  icon: ComponentType<{ className?: string }>
}) {
  return (
    <div className="rounded-lg border border-white/8 bg-white/[0.025] p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-medium text-zinc-500">{label}</p>
        <div className="flex size-8 items-center justify-center rounded-lg bg-white/[0.04] text-zinc-400">
          <Icon className="size-4" />
        </div>
      </div>
      <p className="mt-3 truncate text-2xl font-semibold tracking-tight text-white">{value}</p>
      <p className="mt-1 truncate text-xs text-zinc-600">{detail}</p>
    </div>
  )
}

function ActionBadge({ action }: { action: string }) {
  const normalized = action.toLowerCase()
  const className =
    normalized.includes('publish') || normalized.includes('create') || normalized.includes('build')
      ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200'
      : normalized.includes('delete') || normalized.includes('archive') || normalized.includes('cancel')
        ? 'border-red-500/25 bg-red-500/10 text-red-200'
        : normalized.includes('billing') || normalized.includes('checkout')
          ? 'border-amber-500/25 bg-amber-500/10 text-amber-200'
          : 'border-blue-500/25 bg-blue-500/10 text-blue-200'

  return (
    <Badge variant="outline" className={className}>
      {formatAction(action)}
    </Badge>
  )
}

function MetadataPreview({ metadata }: { metadata: Record<string, unknown> }) {
  const keys = Object.keys(metadata ?? {})
  if (keys.length === 0) return <span className="text-zinc-600">No metadata</span>

  return (
    <div className="flex max-w-md flex-wrap gap-1.5">
      {keys.slice(0, 3).map((key) => (
        <Badge key={key} variant="outline" className="border-white/10 bg-white/[0.035] font-mono text-[11px] text-zinc-400">
          {key}
        </Badge>
      ))}
      {keys.length > 3 ? (
        <Badge variant="outline" className="border-white/10 bg-white/[0.035] text-[11px] text-zinc-500">
          +{keys.length - 3}
        </Badge>
      ) : null}
    </div>
  )
}

function AuditTable({ rows }: { rows: AuditEvent[] }) {
  if (rows.length === 0) {
    return <EmptyState title="No audit events match the current filters" description="Try a broader search or action filter." />
  }

  return (
    <Card className="border-white/8 bg-white/[0.025] shadow-none">
      <CardHeader className="border-b border-white/6 pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold text-white">
          <ShieldCheck className="size-4 text-zinc-400" />
          Audit Events
          <span className="ml-auto text-xs font-normal text-zinc-600">{rows.length} visible</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="min-w-[58rem] w-full text-left text-sm">
            <thead className="border-b border-white/6 bg-black/20 text-xs text-zinc-500">
              <tr>
                <th className="px-4 py-3 font-medium">Time</th>
                <th className="px-4 py-3 font-medium">Action</th>
                <th className="px-4 py-3 font-medium">Resource</th>
                <th className="px-4 py-3 font-medium">Actor</th>
                <th className="px-4 py-3 font-medium">Metadata</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/6">
              {rows.map((event) => (
                <tr key={event.id} className="hover:bg-white/[0.025]">
                  <td className="px-4 py-3 align-top">
                    <p className="whitespace-nowrap text-zinc-200">{formatTime(event.created_at)}</p>
                    <p className="mt-0.5 text-xs text-zinc-600">{formatRelative(event.created_at)}</p>
                  </td>
                  <td className="px-4 py-3 align-top">
                    <ActionBadge action={event.action} />
                    <p className="mt-1 font-mono text-[11px] text-zinc-700">{event.id}</p>
                  </td>
                  <td className="px-4 py-3 align-top">
                    <p className="font-medium text-zinc-200">{event.resource_type}</p>
                    {event.resource_id ? <p className="mt-0.5 max-w-56 truncate font-mono text-xs text-zinc-600">{event.resource_id}</p> : null}
                  </td>
                  <td className="px-4 py-3 align-top">
                    <p className="max-w-44 truncate font-mono text-xs text-zinc-400">{event.user_id}</p>
                  </td>
                  <td className="px-4 py-3 align-top">
                    <MetadataPreview metadata={event.metadata} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

export function AuditPage() {
  const [search, setSearch] = useState('')
  const [action, setAction] = useState(ALL_ACTIONS)
  const auditQ = useQuery({ queryKey: ['auditEvents'], queryFn: () => fetchAuditEvents(200) })

  const events = useMemo(() => auditQ.data?.audit_events ?? [], [auditQ.data?.audit_events])
  const actions = useMemo(() => Array.from(new Set(events.map((event) => event.action))).sort(), [events])

  const filteredRows = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase()
    return events.filter((event) => {
      if (action !== ALL_ACTIONS && event.action !== action) return false
      if (!normalizedSearch) return true
      return eventSearchText(event).includes(normalizedSearch)
    })
  }, [action, events, search])

  const summary = useMemo(() => {
    const uniqueUsers = new Set(events.map((event) => event.user_id).filter(Boolean))
    const resources = new Set(events.map((event) => event.resource_type).filter(Boolean))
    const latest = events.reduce<AuditEvent | null>((current, event) => {
      if (!current || event.created_at > current.created_at) return event
      return current
    }, null)
    return {
      total: events.length,
      users: uniqueUsers.size,
      resources: resources.size,
      latest,
    }
  }, [events])

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title="Audit"
        description="Workspace event history for plugin operations, releases, billing, and administrative actions."
        actions={
          <>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08]"
              onClick={() => auditQ.refetch()}
              disabled={auditQ.isFetching}
            >
              <RefreshCw className={auditQ.isFetching ? 'size-3.5 animate-spin' : 'size-3.5'} />
              Refresh
            </Button>
            <Button
              type="button"
              size="sm"
              className="bg-blue-600 text-white hover:bg-blue-500"
              onClick={() => downloadCsv(filteredRows)}
              disabled={filteredRows.length === 0}
            >
              <Download className="size-3.5" />
              Export CSV
            </Button>
          </>
        }
      />

      <div className="mx-auto w-full max-w-7xl space-y-4 px-4 py-4 sm:px-6">
        {auditQ.isLoading ? <LoadingState /> : null}
        {auditQ.isError ? <ErrorState message={(auditQ.error as Error).message} /> : null}
        {auditQ.data ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <SummaryMetric label="Events loaded" value={String(summary.total)} detail="Latest 200 records" icon={Activity} />
              <SummaryMetric label="Actors" value={String(summary.users)} detail="Unique user IDs" icon={UserRound} />
              <SummaryMetric label="Resource types" value={String(summary.resources)} detail="Operational surfaces" icon={Database} />
              <SummaryMetric
                label="Latest event"
                value={summary.latest ? formatRelative(summary.latest.created_at) : 'None'}
                detail={summary.latest ? formatAction(summary.latest.action) : 'No events found'}
                icon={Clock3}
              />
            </div>

            <div className="flex flex-col gap-2 rounded-lg border border-white/8 bg-black/20 p-2 sm:flex-row sm:items-center">
              <label className="relative min-w-0 flex-1">
                <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-zinc-500" />
                <Input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search action, actor, resource, or metadata"
                  className="h-9 border-white/10 bg-white/[0.03] pl-9 text-zinc-100"
                />
              </label>
              <label className="flex min-w-52 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-zinc-400">
                <Filter className="size-4 text-zinc-500" />
                <select
                  value={action}
                  onChange={(event) => setAction(event.target.value)}
                  className="min-w-0 flex-1 bg-transparent text-sm text-zinc-200 outline-none"
                >
                  <option value={ALL_ACTIONS}>All actions</option>
                  {actions.map((item) => (
                    <option key={item} value={item}>
                      {formatAction(item)}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <AuditTable rows={filteredRows} />
          </>
        ) : null}
      </div>
    </div>
  )
}
