'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { fetchPlugins, normalizePluginList, type Plugin } from '@/api/pluginApi'
import { fetchEntitlements } from '@/api/productApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ChevronRight, Globe, PackageCheck } from 'lucide-react'

function formatCount(value: number | null | undefined) {
  if (value == null) return 'Unlimited'
  return new Intl.NumberFormat().format(value)
}

function statusBadge(status: Plugin['status']) {
  const map: Record<Plugin['status'], { label: string; className: string }> = {
    needs_auth: { label: 'Needs auth',  className: 'border-amber-500/30 bg-amber-500/10 text-amber-300' },
    ready:      { label: 'Ready',       className: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' },
    building:   { label: 'Building',    className: 'border-blue-500/30 bg-blue-500/10 text-blue-300' },
    error:      { label: 'Error',       className: 'border-red-500/30 bg-red-500/10 text-red-300' },
  }
  const { label, className } = map[status] ?? map.error
  return (
    <Badge variant="outline" className={className}>
      {label}
    </Badge>
  )
}

function InstallerSlotSummary() {
  const q = useQuery({ queryKey: ['entitlements'], queryFn: fetchEntitlements, staleTime: 30_000, retry: 1 })
  const meter = q.data?.meters?.installer_slots

  if (q.isLoading) {
    return (
      <div className="flex h-9 min-w-56 items-center border-l border-white/10 pl-4">
        <div className="space-y-1.5">
          <div className="h-2.5 w-20 animate-pulse rounded bg-white/[0.08]" />
          <div className="h-2.5 w-28 animate-pulse rounded bg-white/[0.06]" />
        </div>
      </div>
    )
  }

  if (q.isError || !meter) {
    return (
      <div className="flex h-9 min-w-56 items-center justify-between gap-4 border-l border-white/10 pl-4">
        <div className="leading-none">
          <p className="text-[11px] font-medium text-zinc-500">Installer slots</p>
          <p className="mt-1 text-[11px] text-amber-300">Usage unavailable</p>
        </div>
      </div>
    )
  }

  const usage = meter.unlimited ? formatCount(meter.used) : `${formatCount(meter.used)} / ${formatCount(meter.limit)}`
  const capacity = meter.unlimited ? 'Unlimited capacity' : `${formatCount(meter.remaining)} available`

  return (
    <div className="flex h-9 min-w-56 items-center justify-between gap-4 border-l border-white/10 pl-4">
      <div className="leading-none">
        <p className="text-[11px] font-medium text-zinc-500">Installer slots</p>
        <p className="mt-1 text-[11px] text-zinc-600">{capacity}</p>
      </div>
      <div className="whitespace-nowrap text-right">
        <span className="text-sm font-semibold text-white">{usage}</span>
        <span className="ml-1 text-xs text-zinc-500">used</span>
      </div>
    </div>
  )
}

export function PluginsPage() {
  const q = useQuery({ queryKey: ['plugins'], queryFn: fetchPlugins, staleTime: 10_000 })
  const plugins = normalizePluginList(q.data)

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title="Plugins"
        description={q.isSuccess && plugins.length > 0 ? `${plugins.length} published plugin${plugins.length !== 1 ? 's' : ''}` : 'Published skills for customer installation.'}
        actions={<InstallerSlotSummary />}
      />
      <div className="flex w-full max-w-7xl flex-col gap-3 px-4 py-4 sm:px-6">
        {q.isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((item) => (
              <Card key={item} size="sm" className="gap-0 border-white/8 bg-white/[0.03] py-3 shadow-none">
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1 space-y-1.5">
                      <div className="h-4 w-28 animate-pulse rounded bg-white/10" />
                      <div className="h-3 w-44 animate-pulse rounded bg-white/[0.06]" />
                    </div>
                    <div className="h-5 w-14 animate-pulse rounded-full bg-white/[0.06]" />
                  </div>
                </CardHeader>
                <CardContent className="space-y-2 pt-0">
                  <div className="h-3 w-36 animate-pulse rounded bg-white/[0.06]" />
                  <div className="h-7 w-full animate-pulse rounded-md bg-white/[0.06]" />
                </CardContent>
              </Card>
            ))}
          </div>
        ) : q.isError ? (
          <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">
            {(q.error as Error).message}
          </div>
        ) : plugins.length === 0 ? (
          <Card className="border-white/8 bg-white/[0.03] shadow-none">
            <CardContent className="flex flex-col items-center gap-2.5 py-9 text-center">
              <Globe className="size-7 text-zinc-600" />
              <p className="text-sm font-medium text-zinc-300">No published plugins yet</p>
              <p className="max-w-xs text-xs text-zinc-500">
                Build and publish a plugin from the Build Studio. It will appear here once published.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {plugins.map((plugin) => {
              const version = plugin.installer?.version ?? plugin.build?.version
              const hasInstaller = !!plugin.installer
              return (
                <Link
                  key={plugin.id}
                  href={`/plugins/${encodeURIComponent(plugin.id)}`}
                  className="group block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30"
                  aria-label={`Open ${plugin.name} release history`}
                >
                  <Card
                    size="sm"
                    className="h-full gap-0 border-white/8 bg-white/[0.035] py-3 shadow-none transition-colors group-hover:border-white/15 group-hover:bg-white/[0.05]"
                  >
                    <CardHeader className="pb-2">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <CardTitle className="truncate text-sm font-medium text-white">
                            {plugin.name}
                          </CardTitle>
                          <p className="mt-0.5 truncate text-xs text-zinc-500">{plugin.target_url}</p>
                        </div>
                        {statusBadge(plugin.status)}
                      </div>
                    </CardHeader>
                    <CardContent className="pt-0">
                      <div className="grid grid-cols-3 gap-2 border-y border-white/8 py-2.5 text-xs">
                        <div>
                          <p className="text-[10px] uppercase tracking-[0.08em] text-zinc-600">Version</p>
                          <p className="mt-1 truncate font-mono text-zinc-300">{version ? `v${version}` : 'Not built'}</p>
                        </div>
                        <div>
                          <p className="text-[10px] uppercase tracking-[0.08em] text-zinc-600">Workflows</p>
                          <p className="mt-1 text-zinc-300">{plugin.workflows.length}</p>
                        </div>
                        <div>
                          <p className="text-[10px] uppercase tracking-[0.08em] text-zinc-600">Installer</p>
                          <p className={hasInstaller ? 'mt-1 text-emerald-300' : 'mt-1 text-zinc-600'}>
                            {hasInstaller ? 'Published' : 'Pending'}
                          </p>
                        </div>
                      </div>
                      <div className="mt-2.5 flex items-center justify-between gap-2 text-xs text-zinc-500">
                        <span className="inline-flex items-center gap-1.5">
                          <PackageCheck className="size-3.5 text-zinc-600" />
                          Release history
                        </span>
                        <span className="inline-flex items-center gap-1 text-zinc-400 transition-colors group-hover:text-white">
                          Open
                          <ChevronRight className="size-3.5" />
                        </span>
                      </div>
                    </CardContent>
                  </Card>
                </Link>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
