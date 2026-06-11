'use client'

import Link from 'next/link'
import { type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchMe, type MeResponse, type ProxyIdentityStatus } from '@/api/productApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { ErrorState, LoadingState } from '@/components/product/ProductPrimitives'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ArrowRight,
  Building2,
  ClipboardCheck,
  CreditCard,
  KeyRound,
  LockKeyhole,
  ShieldCheck,
  Users,
} from 'lucide-react'

type Tone = 'good' | 'warn' | 'neutral'

function titleCase(value: string) {
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function proxyStatusTone(status?: ProxyIdentityStatus): Tone {
  if (status === 'trusted') return 'good'
  if (!status) return 'neutral'
  return 'warn'
}

function StatusBadge({ label, tone = 'neutral' }: { label: string; tone?: Tone }) {
  const toneClass =
    tone === 'good'
      ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200'
      : tone === 'warn'
        ? 'border-amber-500/25 bg-amber-500/10 text-amber-200'
        : 'border-white/10 bg-white/[0.04] text-zinc-300'

  return (
    <Badge variant="outline" className={toneClass}>
      {label}
    </Badge>
  )
}

function identityStatusLabel(status?: ProxyIdentityStatus) {
  if (status === 'trusted') return 'Trusted'
  if (!status) return 'Local session'
  return 'Needs attention'
}

function FieldRow({ label, value, mono = false }: { label: string; value?: string | null; mono?: boolean }) {
  return (
    <div className="flex min-h-12 items-center justify-between gap-4 border-t border-white/6 py-3 first:border-t-0">
      <span className="text-sm text-zinc-500">{label}</span>
      <span className={mono ? 'min-w-0 truncate font-mono text-xs text-zinc-200' : 'min-w-0 truncate text-sm font-medium text-zinc-200'}>
        {value || 'Not configured'}
      </span>
    </div>
  )
}

function PostureRow({
  icon: Icon,
  label,
  detail,
  status,
  tone,
}: {
  icon: typeof ShieldCheck
  label: string
  detail: string
  status: string
  tone: Tone
}) {
  return (
    <div className="flex items-start gap-3 border-t border-white/6 py-4 first:border-t-0">
      <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-white/8 bg-white/[0.035] text-zinc-300">
        <Icon className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium text-white">{label}</p>
          <StatusBadge label={status} tone={tone} />
        </div>
        <p className="mt-1 text-sm leading-6 text-zinc-500">{detail}</p>
      </div>
    </div>
  )
}

function SettingsCard({
  title,
  icon: Icon,
  children,
}: {
  title: string
  icon: typeof ShieldCheck
  children: ReactNode
}) {
  return (
    <Card className="border-white/8 bg-white/[0.025] shadow-none">
      <CardHeader className="border-b border-white/6 pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold text-white">
          <Icon className="size-4 text-zinc-400" />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-4">{children}</CardContent>
    </Card>
  )
}

function AdminLink({
  href,
  icon: Icon,
  title,
  detail,
}: {
  href: string
  icon: typeof ShieldCheck
  title: string
  detail: string
}) {
  return (
    <Link
      href={href}
      className="group flex min-h-24 items-start gap-3 rounded-lg border border-white/8 bg-black/20 p-4 transition-colors hover:border-white/14 hover:bg-white/[0.045]"
    >
      <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-white/8 bg-white/[0.035] text-zinc-300">
        <Icon className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-white">{title}</p>
        <p className="mt-1 text-sm leading-6 text-zinc-500">{detail}</p>
      </div>
      <ArrowRight className="mt-1 size-4 shrink-0 text-zinc-600 transition-colors group-hover:text-zinc-300" />
    </Link>
  )
}

function SettingsBody({ me }: { me: MeResponse }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(22rem,0.9fr)]">
        <SettingsCard title="Workspace" icon={Building2}>
          <FieldRow label="Workspace name" value={me.workspace.name} />
          <FieldRow label="Workspace slug" value={me.workspace.slug} mono />
          <FieldRow label="Workspace ID" value={me.workspace.id} mono />
          <FieldRow label="Current role" value={titleCase(me.workspace.role)} />
        </SettingsCard>

        <SettingsCard title="Access & Security" icon={ShieldCheck}>
          <PostureRow
            icon={LockKeyhole}
            label="Authentication"
            detail="Dashboard access is bound to the active Clerk organization context."
            status={me.auth_required ? 'Enforced' : 'Local mode'}
            tone={me.auth_required ? 'good' : 'warn'}
          />
          <PostureRow
            icon={KeyRound}
            label="Session verification"
            detail="Shows whether this dashboard request is tied to a verified workspace identity."
            status={identityStatusLabel(me.proxy_identity_status)}
            tone={proxyStatusTone(me.proxy_identity_status)}
          />
          <PostureRow
            icon={Users}
            label="Signed-in user"
            detail={me.user.email ?? me.user.id}
            status={titleCase(me.user.auth_provider)}
            tone="neutral"
          />
        </SettingsCard>
      </div>

      <SettingsCard title="Administration" icon={Users}>
        <div className="grid gap-3 md:grid-cols-3">
          <AdminLink href="/team" icon={Users} title="Team" detail="Manage workspace members and access." />
          <AdminLink href="/billing" icon={CreditCard} title="Billing" detail="Review plan, usage, and subscription state." />
          <AdminLink href="/audit" icon={ClipboardCheck} title="Audit" detail="Inspect workspace activity and export evidence." />
        </div>
      </SettingsCard>
    </div>
  )
}

export function SettingsPage() {
  const meQ = useQuery({ queryKey: ['me'], queryFn: fetchMe })

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader title="Settings" description="Workspace identity, access context, and admin entry points." />
      <div className="mx-auto w-full max-w-6xl px-4 py-4 sm:px-6">
        {meQ.isLoading ? <LoadingState /> : null}
        {meQ.isError ? <ErrorState message={(meQ.error as Error).message} /> : null}
        {meQ.data ? <SettingsBody me={meQ.data} /> : null}
      </div>
    </div>
  )
}
