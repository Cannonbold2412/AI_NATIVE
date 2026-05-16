'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { fetchPlugins, normalizePluginList } from '@/api/pluginApi'
import { fetchDashboard } from '@/api/productApi'
import { AppShell } from '@/components/layout/AppLayout'
import {
  EmptyState,
  ErrorState,
  GlobalCreateMenu,
  LoadingState,
  StatCard,
  StatusBadge,
} from '@/components/product/ProductPrimitives'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ArrowRight, CircleAlert, PackageCheck, ShieldCheck } from 'lucide-react'

function formatTime(value: unknown) {
  const n = typeof value === 'number' ? value : 0
  if (!n) return ''
  return new Date(n * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export function DashboardPage() {
  const q = useQuery({ queryKey: ['dashboard'], queryFn: fetchDashboard, staleTime: 30_000 })
  const pluginsQ = useQuery({ queryKey: ['plugins'], queryFn: fetchPlugins, staleTime: 10_000 })
  const stats = q.data?.stats
  const plugins = normalizePluginList(pluginsQ.data)
  const criticalPlugins = plugins.filter((p) => p.auth == null || p.status === 'error' || p.workflows.some((w) => w.status === 'error')).length

  return (
    <AppShell
      title="Dashboard"
      description="Workspace overview for recording, building, packaging, and release activity."
      actions={<GlobalCreateMenu />}
      mainClassName="overflow-y-auto"
    >
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-4 sm:px-6">
        {q.isLoading ? <LoadingState label="Loading dashboard" /> : null}
        {q.isError ? <ErrorState message={(q.error as Error).message} /> : null}
        {q.data ? (
          <>
            <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
              <StatCard label="Skills" value={stats?.skills ?? 0} />
              <StatCard label="Packages" value={stats?.packages ?? 0} />
              <StatCard label="Workflows" value={stats?.workflows ?? 0} />
              <StatCard label="Active jobs" value={stats?.active_jobs ?? 0} tone={stats?.active_jobs ? 'warn' : 'neutral'} />
              <StatCard label="Published" value={stats?.published_packages ?? 0} tone="good" />
            </section>

            <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
              <Card className="border-white/8 bg-white/[0.03] shadow-none">
                <CardHeader className="flex-row items-center justify-between border-b border-white/8">
                  <CardTitle className="text-white">Recent workflows</CardTitle>
                  <Button asChild size="sm" variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-200">
                    <Link href="/workflows">
                      View all
                      <ArrowRight className="size-3.5" />
                    </Link>
                  </Button>
                </CardHeader>
                <CardContent className="p-3">
                  {q.data.recent_workflows.length === 0 ? (
                    <EmptyState
                      title="No workflows yet"
                      description="Record a browser flow to create the first saved skill."
                      action={
                        <Button asChild size="sm">
                          <Link href="/plugins">Create plugin</Link>
                        </Button>
                      }
                    />
                  ) : (
                    <div className="divide-y divide-white/6">
                      {q.data.recent_workflows.map((workflow) => (
                        <Link
                          key={String(workflow.skill_id)}
                          href={`/edit/${String(workflow.skill_id)}`}
                          className="flex items-center justify-between gap-3 px-2 py-3 transition-colors hover:bg-white/[0.03]"
                        >
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium text-white">{String(workflow.title ?? workflow.skill_id)}</p>
                            <p className="mt-0.5 text-xs text-zinc-500">
                              {String(workflow.step_count ?? 0)} steps · {formatTime(workflow.modified_at)}
                            </p>
                          </div>
                          <ArrowRight className="size-4 shrink-0 text-zinc-500" />
                        </Link>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card className="border-white/8 bg-white/[0.03] shadow-none">
                <CardHeader className="border-b border-white/8">
                  <CardTitle className="text-white">Package health</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 p-3">
                  {q.data.package_health.length === 0 ? (
                    <EmptyState title="No packages" description="Build a package from a saved workflow." />
                  ) : (
                    q.data.package_health.map((pkg) => (
                      <div key={String(pkg.package_name)} className="rounded-lg border border-white/8 bg-black/20 p-3">
                        <div className="flex items-center justify-between gap-2">
                          <p className="truncate text-sm font-medium text-white">{String(pkg.package_name)}</p>
                          <StatusBadge status={String(pkg.release_state ?? 'draft')} />
                        </div>
                        <p className="mt-1 text-xs text-zinc-500">
                          {String(pkg.workflow_count)} workflows · {String(pkg.file_count)} files
                        </p>
                      </div>
                    ))
                  )}
                </CardContent>
              </Card>
            </section>

            <section className="grid gap-4 xl:grid-cols-2">
              <Card className="border-white/8 bg-white/[0.03] shadow-none">
                <CardHeader className="border-b border-white/8">
                  <CardTitle className="flex items-center gap-2 text-white">
                    <ShieldCheck className="size-4 text-sky-300" />
                    Plugin health
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 p-3">
                  <div className="flex items-center justify-between gap-2 rounded-lg border border-white/8 bg-black/20 p-3">
                    <p className="text-sm text-zinc-300">
                      {plugins.length} plugin{plugins.length === 1 ? '' : 's'} tracked
                    </p>
                    <Badge
                      variant="outline"
                      className={criticalPlugins > 0 ? 'border-red-500/25 bg-red-500/10 text-red-200' : 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200'}
                    >
                      {criticalPlugins > 0 ? `${criticalPlugins} critical` : 'All healthy'}
                    </Badge>
                  </div>
                  <Button asChild variant="outline" className="w-full justify-between border-white/10 bg-white/[0.04] text-zinc-200">
                    <Link href="/plugin-health">
                      Open plugin health
                      <ArrowRight className="size-4" />
                    </Link>
                  </Button>
                  {criticalPlugins > 0 ? (
                    <p className="flex items-center gap-1.5 text-xs text-red-300">
                      <CircleAlert className="size-3.5" />
                      Review plugins missing auth or with workflow errors.
                    </p>
                  ) : null}
                </CardContent>
              </Card>

              <Card className="border-white/8 bg-white/[0.03] shadow-none">
                <CardHeader className="border-b border-white/8">
                  <CardTitle className="flex items-center gap-2 text-white">
                    <PackageCheck className="size-4 text-emerald-300" />
                    Next actions
                  </CardTitle>
                </CardHeader>
                <CardContent className="grid gap-2 p-3">
                  <Button asChild className="justify-between">
                    <Link href="/plugins">
                      Create plugin
                      <ArrowRight className="size-4" />
                    </Link>
                  </Button>
                  <Button asChild variant="secondary" className="justify-between">
                    <Link href="/skill-pack-builder">
                      Build or append package
                      <ArrowRight className="size-4" />
                    </Link>
                  </Button>
                  <Button asChild variant="outline" className="justify-between border-white/10 bg-white/[0.04] text-zinc-200">
                    <Link href="/publish">
                      Publish release
                      <ArrowRight className="size-4" />
                    </Link>
                  </Button>
                </CardContent>
              </Card>
            </section>
          </>
        ) : null}
      </div>
    </AppShell>
  )
}
