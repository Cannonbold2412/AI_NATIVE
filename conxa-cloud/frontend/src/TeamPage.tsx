'use client'

import Link from 'next/link'
import { OrganizationProfile } from '@clerk/nextjs'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CreditCard,
  FileText,
  KeyRound,
  ShieldCheck,
  Users,
  type LucideIcon,
} from 'lucide-react'
import {
  fetchAuditEvents,
  fetchEntitlements,
  fetchMe,
  fetchSubscription,
  type AuditEvent,
  type EntitlementMeter,
} from '@/api/productApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { clerkAppearance } from '@/lib/clerkAppearance'
import { cn } from '@/lib/utils'

type Tone = 'good' | 'warn' | 'neutral'

function formatCount(value: number | null | undefined) {
  if (value == null) return 'Unlimited'
  return new Intl.NumberFormat().format(value)
}

function formatTime(value?: number | null) {
  if (!value) return 'No activity yet'
  return new Date(value * 1000).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function titleCase(value?: string | null) {
  if (!value) return 'Member'
  return value.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function seatPercent(meter?: EntitlementMeter) {
  if (!meter || meter.unlimited || !meter.limit) return 0
  return Math.min(100, Math.round((meter.used / meter.limit) * 100))
}

function seatTone(meter?: EntitlementMeter): Tone {
  if (!meter || meter.unlimited || !meter.limit) return 'neutral'
  return seatPercent(meter) >= 80 ? 'warn' : 'good'
}

function toneClasses(tone: Tone) {
  if (tone === 'good') return 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200'
  if (tone === 'warn') return 'border-amber-500/25 bg-amber-500/10 text-amber-200'
  return 'border-white/10 bg-white/[0.04] text-zinc-300'
}

function StatusPill({
  children,
  tone = 'neutral',
  icon: Icon,
}: {
  children: React.ReactNode
  tone?: Tone
  icon?: LucideIcon
}) {
  return (
    <Badge variant="outline" className={cn('gap-1.5', toneClasses(tone))}>
      {Icon ? <Icon className="size-3" /> : null}
      {children}
    </Badge>
  )
}

function SkeletonBlock({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-md bg-white/[0.06]', className)} />
}

function AlertRow({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-amber-500/25 bg-amber-500/8 px-3 py-2 text-sm text-amber-100">
      <AlertTriangle className="size-4 shrink-0" />
      <span>{message}</span>
    </div>
  )
}

function SummaryMetric({
  label,
  value,
  detail,
  icon: Icon,
  tone = 'neutral',
}: {
  label: string
  value: React.ReactNode
  detail?: React.ReactNode
  icon: LucideIcon
  tone?: Tone
}) {
  return (
    <div className="min-w-0 border-t border-white/8 px-4 py-3 first:border-t-0 md:border-t-0 md:border-l md:first:border-l-0">
      <div className="flex items-center gap-2 text-zinc-500">
        <Icon className="size-3.5" />
        <p className="text-xs font-medium uppercase">{label}</p>
      </div>
      <p className="mt-2 truncate text-2xl font-semibold text-white">{value}</p>
      {detail ? <p className={cn('mt-1 truncate text-xs', tone === 'warn' ? 'text-amber-200' : 'text-zinc-500')}>{detail}</p> : null}
    </div>
  )
}

function TeamSummary({
  workspaceName,
  role,
  plan,
  seatMeter,
  latestAudit,
  seatsUnavailable,
  loading,
}: {
  workspaceName?: string
  role?: string
  plan?: string
  seatMeter?: EntitlementMeter
  latestAudit?: AuditEvent
  seatsUnavailable: boolean
  loading: boolean
}) {
  const seatState = seatTone(seatMeter)
  const seatUsage = seatMeter?.unlimited
    ? `${formatCount(seatMeter.used)} active`
    : `${formatCount(seatMeter?.used)} / ${formatCount(seatMeter?.limit)}`

  return (
    <section className="overflow-hidden rounded-xl border border-white/8 bg-[#0d1014]">
      <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill tone="good" icon={ShieldCheck}>
              {titleCase(role)}
            </StatusPill>
            <StatusPill icon={CreditCard}>{titleCase(plan ?? 'development')} plan</StatusPill>
          </div>
          {loading ? (
            <div className="mt-5 space-y-2">
              <SkeletonBlock className="h-7 w-64" />
              <SkeletonBlock className="h-4 w-80 max-w-full" />
            </div>
          ) : (
            <>
              <h2 className="mt-5 truncate text-2xl font-semibold text-white">{workspaceName ?? 'Team workspace'}</h2>
              <p className="mt-1 max-w-2xl text-sm text-zinc-500">
                Manage members, roles, and seats for this workspace.
              </p>
            </>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" className="bg-zinc-100 text-zinc-950 hover:bg-white">
            <a href="#members">
              <Users className="size-3.5" />
              Manage members
            </a>
          </Button>
          <Button asChild variant="outline" size="sm" className="border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08]">
            <Link href="/billing">
              <CreditCard className="size-3.5" />
              Seats
            </Link>
          </Button>
        </div>
      </div>

      {seatsUnavailable ? (
        <div className="border-t border-white/8 p-4">
          <AlertRow message="Seat usage is unavailable right now." />
        </div>
      ) : null}

      <div className="grid border-t border-white/8 md:grid-cols-4">
        <SummaryMetric
          icon={Users}
          label="Seats"
          value={seatUsage}
          detail={seatMeter?.unlimited ? 'Unlimited capacity' : `${formatCount(seatMeter?.remaining)} remaining`}
          tone={seatState}
        />
        <SummaryMetric icon={KeyRound} label="Your role" value={titleCase(role)} detail="Workspace permissions" tone="good" />
        <SummaryMetric icon={CreditCard} label="Plan" value={titleCase(plan ?? 'development')} detail="Billing controls seats" />
        <SummaryMetric
          icon={Activity}
          label="Last team activity"
          value={latestAudit ? titleCase(latestAudit.action) : 'None'}
          detail={formatTime(latestAudit?.created_at)}
        />
      </div>
    </section>
  )
}

function RoleGuide() {
  const roles = [
    {
      role: 'Owner',
      detail: 'Full workspace and billing control.',
    },
    {
      role: 'Admin',
      detail: 'Manage members and workspace operations.',
    },
    {
      role: 'Member',
      detail: 'Use shared workspace resources.',
    },
  ]

  return (
    <section className="overflow-hidden rounded-xl border border-white/8 bg-white/[0.025]">
      <div className="border-b border-white/8 px-4 py-3">
        <h2 className="text-sm font-semibold text-white">Role guide</h2>
        <p className="mt-1 text-sm text-zinc-500">Use the least access each teammate needs.</p>
      </div>
      <div className="divide-y divide-white/8">
        {roles.map((item) => (
          <div key={item.role} className="flex items-start justify-between gap-4 px-4 py-3">
            <div>
              <p className="text-sm font-medium text-white">{item.role}</p>
              <p className="mt-1 text-xs text-zinc-500">{item.detail}</p>
            </div>
            <StatusPill>{item.role}</StatusPill>
          </div>
        ))}
      </div>
    </section>
  )
}

function TeamLinks({ latestAudit }: { latestAudit?: AuditEvent }) {
  return (
    <section className="overflow-hidden rounded-xl border border-white/8 bg-white/[0.025]">
      <div className="border-b border-white/8 px-4 py-3">
        <h2 className="text-sm font-semibold text-white">Team operations</h2>
        <p className="mt-1 text-sm text-zinc-500">Related controls for seats and activity.</p>
      </div>
      <div className="divide-y divide-white/8">
        <Link href="/billing" className="flex items-center justify-between gap-4 px-4 py-3 text-sm transition-colors hover:bg-white/[0.04]">
          <span className="flex min-w-0 items-center gap-3">
            <CreditCard className="size-4 shrink-0 text-zinc-500" />
            <span>
              <span className="block font-medium text-white">Seat plan</span>
              <span className="mt-0.5 block text-xs text-zinc-500">Review included seats and billing.</span>
            </span>
          </span>
          <ArrowUpRight className="size-4 shrink-0 text-zinc-500" />
        </Link>
        <Link href="/audit" className="flex items-center justify-between gap-4 px-4 py-3 text-sm transition-colors hover:bg-white/[0.04]">
          <span className="flex min-w-0 items-center gap-3">
            <FileText className="size-4 shrink-0 text-zinc-500" />
            <span>
              <span className="block font-medium text-white">Audit activity</span>
              <span className="mt-0.5 block text-xs text-zinc-500">{latestAudit ? formatTime(latestAudit.created_at) : 'No activity yet'}</span>
            </span>
          </span>
          <ArrowUpRight className="size-4 shrink-0 text-zinc-500" />
        </Link>
      </div>
    </section>
  )
}

function MemberDirectory() {
  return (
    <section id="members" className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-white">Members</h2>
          <p className="mt-1 text-sm text-zinc-500">Invite teammates, update roles, and manage organization membership.</p>
        </div>
      </div>

      <div className="min-w-0 overflow-hidden rounded-xl border border-white/8 bg-[#111318]">
        <OrganizationProfile
          routing="hash"
          appearance={{
            ...clerkAppearance,
            elements: {
              ...clerkAppearance.elements,
              rootBox: 'w-full',
              cardBox: 'w-full max-w-none overflow-hidden border-0 bg-transparent shadow-none',
              card: 'w-full max-w-none bg-transparent shadow-none',
              navbar: 'border-r border-white/8 bg-transparent',
              navbarButton:
                'text-zinc-400 hover:bg-white/[0.05] hover:text-white data-[active=true]:bg-white/[0.07] data-[active=true]:text-white',
              pageScrollBox: 'p-0',
              profilePage: 'p-0',
            },
          }}
        />
      </div>
    </section>
  )
}

export function TeamPage() {
  const meQ = useQuery({ queryKey: ['me'], queryFn: fetchMe, staleTime: 30_000, retry: 1 })
  const entitlementsQ = useQuery({
    queryKey: ['entitlements'],
    queryFn: fetchEntitlements,
    staleTime: 30_000,
    retry: 1,
  })
  const subscriptionQ = useQuery({
    queryKey: ['subscription'],
    queryFn: fetchSubscription,
    staleTime: 30_000,
    retry: 1,
  })
  const auditQ = useQuery({
    queryKey: ['auditEvents', 'team'],
    queryFn: () => fetchAuditEvents(4),
    staleTime: 30_000,
    retry: 1,
  })

  const plan = entitlementsQ.data?.plan ?? subscriptionQ.data?.subscription.plan
  const latestAudit = auditQ.data?.audit_events[0]

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader title="Team" description="Manage members, roles, and seats." />

      <div className="flex w-full max-w-7xl flex-col gap-4 px-4 py-4 sm:px-6">
        <TeamSummary
          workspaceName={meQ.data?.workspace.name}
          role={meQ.data?.workspace.role}
          plan={plan}
          seatMeter={entitlementsQ.data?.meters.seats}
          latestAudit={latestAudit}
          seatsUnavailable={entitlementsQ.isError}
          loading={meQ.isLoading || entitlementsQ.isLoading || subscriptionQ.isLoading}
        />

        <div className="grid gap-4 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
          <RoleGuide />
          <TeamLinks latestAudit={latestAudit} />
        </div>

        <MemberDirectory />
      </div>
    </div>
  )
}
