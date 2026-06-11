'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import {
  fetchInstallerVersions,
  fetchPlugin,
  type InstallerVersion,
  type Plugin,
} from '@/api/pluginApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ChevronLeft, Clock3, Download, PackageCheck, ShieldCheck } from 'lucide-react'

function formatBytes(size: number) {
  if (!Number.isFinite(size) || size <= 0) return 'Unknown size'
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(ts: number) {
  if (!ts) return 'Unknown'
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function statusLabel(status: Plugin['status']) {
  const labels: Record<Plugin['status'], string> = {
    needs_auth: 'Needs auth',
    ready: 'Ready',
    building: 'Building',
    error: 'Error',
  }
  return labels[status] ?? 'Error'
}

function SummaryStat({
  label,
  value,
  sub,
}: {
  label: string
  value: string
  sub: string
}) {
  return (
    <div className="rounded-lg border border-white/8 bg-white/[0.025] px-3 py-2.5">
      <p className="text-[10px] font-medium uppercase tracking-[0.1em] text-zinc-600">{label}</p>
      <p className="mt-1 text-sm font-semibold text-white">{value}</p>
      <p className="mt-0.5 truncate text-xs text-zinc-600">{sub}</p>
    </div>
  )
}

function releaseRows(plugin: Plugin, versions: InstallerVersion[]) {
  if (versions.length > 0) return versions
  if (!plugin.installer) return []
  return [
    {
      slug: plugin.slug,
      version: plugin.installer.version,
      release_notes: plugin.installer.release_notes ?? '',
      filename: plugin.installer.filename,
      sha256: '',
      size: 0,
      uploaded_at: plugin.installer.built_at,
      workspace_id: '',
      is_latest: true,
      workflow_count: plugin.workflows.length,
      download_url: `/api/v1/installers/${plugin.slug}`,
    },
  ] satisfies InstallerVersion[]
}

export function PluginVersionsPage({ pluginId }: { pluginId: string }) {
  const pluginQ = useQuery({
    queryKey: ['plugin', pluginId],
    queryFn: () => fetchPlugin(pluginId),
    staleTime: 10_000,
  })
  const plugin = pluginQ.data?.plugin
  const versionsQ = useQuery({
    queryKey: ['installer-versions', plugin?.slug],
    queryFn: () => fetchInstallerVersions(plugin?.slug ?? ''),
    enabled: !!plugin?.slug,
    staleTime: 30_000,
  })

  const rows = plugin ? releaseRows(plugin, versionsQ.data?.versions ?? []) : []
  const latest = rows.find((row) => row.is_latest) ?? rows[0]
  const workflowCount = plugin?.workflows.length ?? 0

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title={plugin?.name ?? 'Plugin'}
        description={plugin?.target_url ?? 'Installer release history and downloads.'}
        actions={
          <Button
            asChild
            variant="outline"
            size="sm"
            className="border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08] hover:text-white"
          >
            <Link href="/plugins">
              <ChevronLeft className="size-3.5" />
              Back
            </Link>
          </Button>
        }
      />

      <main className="flex w-full max-w-7xl flex-col gap-3 px-4 py-4 sm:px-6">
        {pluginQ.isLoading ? (
          <div className="grid gap-3 md:grid-cols-4">
            {[0, 1, 2, 3].map((item) => (
              <div key={item} className="h-20 animate-pulse rounded-lg border border-white/8 bg-white/[0.03]" />
            ))}
          </div>
        ) : pluginQ.isError ? (
          <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">
            {(pluginQ.error as Error).message}
          </div>
        ) : plugin ? (
          <>
            <section className="grid gap-3 md:grid-cols-4">
              <SummaryStat label="Status" value={statusLabel(plugin.status)} sub="distribution state" />
              <SummaryStat
                label="Current version"
                value={latest ? `v${latest.version}` : 'Not published'}
                sub={latest?.is_latest ? 'latest installer' : 'waiting for installer'}
              />
              <SummaryStat
                label="Workflows"
                value={String(workflowCount)}
                sub={`${plugin.workflows.filter((wf) => wf.status === 'compiled').length} compiled`}
              />
              <SummaryStat
                label="Releases"
                value={String(rows.length)}
                sub="installer versions"
              />
            </section>

            <section className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_22rem]">
              <Card className="gap-0 border-white/8 bg-white/[0.03] py-0 shadow-none">
                <CardHeader className="border-b border-white/8 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <CardTitle className="text-sm font-semibold text-white">Installer Versions</CardTitle>
                      <p className="mt-0.5 text-xs text-zinc-600">
                        Previous releases, builder comments, workflow count, and version-specific downloads.
                      </p>
                    </div>
                    {versionsQ.isFetching ? (
                      <span className="text-[11px] text-zinc-600">Refreshing</span>
                    ) : null}
                  </div>
                </CardHeader>
                <CardContent className="p-0">
                  {versionsQ.isLoading ? (
                    <div className="space-y-2 p-3">
                      {[0, 1, 2].map((item) => (
                        <div key={item} className="h-12 animate-pulse rounded-lg bg-white/[0.04]" />
                      ))}
                    </div>
                  ) : rows.length === 0 ? (
                    <div className="px-4 py-8 text-center">
                      <PackageCheck className="mx-auto size-7 text-zinc-700" />
                      <p className="mt-2 text-sm font-medium text-zinc-300">No installer versions yet</p>
                      <p className="mt-1 text-xs text-zinc-600">Build and publish an installer to create the first release.</p>
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[760px] text-left text-sm">
                        <thead className="border-b border-white/8 text-[10px] uppercase tracking-[0.1em] text-zinc-600">
                          <tr>
                            <th className="px-4 py-2.5 font-medium">Version</th>
                            <th className="px-4 py-2.5 font-medium">Comments</th>
                            <th className="px-4 py-2.5 font-medium">Workflows</th>
                            <th className="px-4 py-2.5 font-medium">Uploaded</th>
                            <th className="px-4 py-2.5 font-medium">Size</th>
                            <th className="px-4 py-2.5 text-right font-medium">Download</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-white/8">
                          {rows.map((row) => {
                            const rowWorkflowCount = row.workflow_count ?? workflowCount
                            return (
                              <tr key={`${row.version}-${row.download_url}`} className="bg-transparent transition-colors hover:bg-white/[0.025]">
                                <td className="whitespace-nowrap px-4 py-3 align-top">
                                  <div className="flex items-center gap-2">
                                    <span className="font-mono text-xs text-zinc-200">v{row.version}</span>
                                    {row.is_latest ? (
                                      <Badge variant="outline" className="h-5 border-emerald-500/30 bg-emerald-500/10 text-[10px] text-emerald-300">
                                        Latest
                                      </Badge>
                                    ) : null}
                                  </div>
                                </td>
                                <td className="max-w-[24rem] px-4 py-3 align-top text-xs leading-relaxed text-zinc-400">
                                  {row.release_notes?.trim() ? row.release_notes : 'No release comment provided.'}
                                </td>
                                <td className="whitespace-nowrap px-4 py-3 align-top text-xs text-zinc-300">
                                  {rowWorkflowCount} workflow{rowWorkflowCount !== 1 ? 's' : ''}
                                </td>
                                <td className="whitespace-nowrap px-4 py-3 align-top text-xs text-zinc-500">
                                  {formatDate(row.uploaded_at)}
                                </td>
                                <td className="whitespace-nowrap px-4 py-3 align-top text-xs text-zinc-500">
                                  {formatBytes(row.size)}
                                </td>
                                <td className="px-4 py-3 text-right align-top">
                                  <Button
                                    asChild
                                    size="sm"
                                    variant="outline"
                                    className="border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08] hover:text-white"
                                  >
                                    <a href={row.download_url} download={row.filename}>
                                      <Download className="size-3.5" />
                                      Download
                                    </a>
                                  </Button>
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </CardContent>
              </Card>

              <div className="space-y-3">
                <Card className="gap-0 border-white/8 bg-white/[0.03] py-0 shadow-none">
                  <CardHeader className="border-b border-white/8 py-3">
                    <CardTitle className="text-sm font-semibold text-white">Workflow Coverage</CardTitle>
                    <p className="text-xs text-zinc-600">Workflows included by the current plugin record.</p>
                  </CardHeader>
                  <CardContent className="p-3">
                    {plugin.workflows.length === 0 ? (
                      <p className="text-xs text-zinc-600">No workflows published for this plugin.</p>
                    ) : (
                      <div className="space-y-2">
                        {plugin.workflows.map((workflow) => (
                          <div key={workflow.id} className="rounded-lg border border-white/8 bg-black/15 px-3 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <p className="truncate text-xs font-medium text-zinc-200">{workflow.name}</p>
                              <Badge
                                variant="outline"
                                className={
                                  workflow.status === 'compiled'
                                    ? 'border-emerald-500/30 bg-emerald-500/10 text-[10px] text-emerald-300'
                                    : 'border-white/10 bg-white/[0.03] text-[10px] text-zinc-500'
                                }
                              >
                                {workflow.status}
                              </Badge>
                            </div>
                            <p className="mt-1 flex items-center gap-1.5 text-[11px] text-zinc-600">
                              <ShieldCheck className="size-3" />
                              Test: {workflow.last_test_status}
                            </p>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card className="gap-0 border-white/8 bg-white/[0.03] py-0 shadow-none">
                  <CardHeader className="border-b border-white/8 py-3">
                    <CardTitle className="text-sm font-semibold text-white">Release Discipline</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 p-3 text-xs text-zinc-500">
                    <p className="flex items-start gap-2">
                      <Clock3 className="mt-0.5 size-3.5 shrink-0 text-zinc-600" />
                      Keep comments specific so customers can choose the right installer version.
                    </p>
                    <p>
                      Version rows use stored installer metadata. Older releases may show the current workflow count if their upload metadata predates workflow-count tracking.
                    </p>
                  </CardContent>
                </Card>
              </div>
            </section>
          </>
        ) : null}
      </main>
    </div>
  )
}
