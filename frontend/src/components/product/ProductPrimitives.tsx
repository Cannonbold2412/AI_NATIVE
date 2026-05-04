import { type ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { AlertCircle, CheckCircle2, Loader2, Search } from 'lucide-react'

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: string
  actions?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-lg font-semibold tracking-tight text-white">{title}</h2>
        {description ? <p className="mt-1 max-w-2xl text-sm leading-6 text-zinc-400">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </div>
  )
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <Card className="border-dashed border-white/10 bg-white/[0.025] shadow-none">
      <CardContent className="flex min-h-48 flex-col items-center justify-center px-6 py-8 text-center">
        <p className="text-sm font-medium text-white">{title}</p>
        {description ? <p className="mt-1 max-w-md text-sm text-zinc-500">{description}</p> : null}
        {action ? <div className="mt-4">{action}</div> : null}
      </CardContent>
    </Card>
  )
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-red-500/25 bg-red-500/8 px-3 py-2 text-sm text-red-100">
      <AlertCircle className="size-4 shrink-0" />
      <span>{message}</span>
    </div>
  )
}

export function LoadingState({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-zinc-400">
      <Loader2 className="size-4 animate-spin" />
      <span>{label}</span>
    </div>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase()
  const className =
    normalized === 'succeeded' || normalized === 'published' || normalized === 'active'
      ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200'
      : normalized === 'failed' || normalized === 'archived'
        ? 'border-red-500/25 bg-red-500/10 text-red-200'
        : normalized === 'running' || normalized === 'queued'
          ? 'border-sky-500/25 bg-sky-500/10 text-sky-200'
          : 'border-white/10 bg-white/[0.04] text-zinc-300'
  return (
    <Badge variant="outline" className={cn('capitalize', className)}>
      {status.replace(/_/g, ' ')}
    </Badge>
  )
}

export function StatCard({ label, value, tone = 'neutral' }: { label: string; value: ReactNode; tone?: 'neutral' | 'good' | 'warn' }) {
  return (
    <div className="rounded-lg border border-white/8 bg-black/20 px-3.5 py-3">
      <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-500">{label}</p>
      <p
        className={cn(
          'mt-1 text-2xl font-semibold tracking-tight',
          tone === 'good' ? 'text-emerald-200' : tone === 'warn' ? 'text-amber-200' : 'text-white',
        )}
      >
        {value}
      </p>
    </div>
  )
}

export function ResourceToolbar({
  search,
  onSearch,
  placeholder,
  actions,
}: {
  search: string
  onSearch: (value: string) => void
  placeholder: string
  actions?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-white/8 bg-black/20 p-2">
      <label className="relative min-w-56 flex-1">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-zinc-500" />
        <Input
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder={placeholder}
          className="h-9 border-white/10 bg-white/[0.03] pl-9 text-zinc-100"
        />
      </label>
      {actions}
    </div>
  )
}

export function DataTable({ children }: { children: ReactNode }) {
  return <div className="overflow-hidden rounded-lg border border-white/8 bg-white/[0.03]">{children}</div>
}

export function ActivityTimeline({ rows }: { rows: Array<{ id: string; title: string; detail?: string; at?: string }> }) {
  if (rows.length === 0) return <EmptyState title="No activity yet" />
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <div key={row.id} className="flex gap-3 rounded-lg border border-white/8 bg-black/20 p-3">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-300" />
          <div className="min-w-0">
            <p className="text-sm font-medium text-white">{row.title}</p>
            {row.detail ? <p className="mt-0.5 text-xs text-zinc-500">{row.detail}</p> : null}
            {row.at ? <p className="mt-1 text-[11px] text-zinc-600">{row.at}</p> : null}
          </div>
        </div>
      ))}
    </div>
  )
}

export function UsageMeter({ label, value, limit }: { label: string; value: number; limit?: number | null }) {
  const pct = limit ? Math.min(100, Math.round((value / limit) * 100)) : 0
  return (
    <div className="space-y-2">
      <div className="flex justify-between gap-3 text-sm">
        <span className="text-zinc-300">{label}</span>
        <span className="text-zinc-500">{limit ? `${value}/${limit}` : value}</span>
      </div>
      <div className="h-2 rounded-full bg-white/[0.06]">
        <div className="h-full rounded-full bg-emerald-400/70" style={{ width: limit ? `${pct}%` : '18%' }} />
      </div>
    </div>
  )
}

export function GlobalCreateMenu() {
  return (
    <div className="flex flex-wrap gap-2">
      <Button asChild size="sm">
        <a href="/recordings/new">New recording</a>
      </Button>
      <Button asChild size="sm" variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-200">
        <a href="/skill-pack-builder">Build package</a>
      </Button>
    </div>
  )
}

export const ConfirmDialog = null
export const RenameDialog = null
