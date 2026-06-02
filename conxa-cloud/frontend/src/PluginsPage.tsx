'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchInstallerVersions, fetchPlugins, normalizePluginList, type Plugin } from '@/api/pluginApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Download, Globe, Search } from 'lucide-react'

function formatBytes(size: number) {
  if (!Number.isFinite(size) || size <= 0) return '0 KB'
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(ts: number) {
  if (!ts) return 'Unknown'
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
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

function InstallerVersionHistory({ plugin }: { plugin: Plugin }) {
  const q = useQuery({
    queryKey: ['installer-versions', plugin.slug],
    queryFn: () => fetchInstallerVersions(plugin.slug),
    enabled: !!plugin.installer,
    staleTime: 30_000,
  })
  if (!plugin.installer) return null

  const versions = q.data?.versions ?? []
  return (
    <div className="mt-3 border-t border-white/8 pt-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-zinc-300">Version history</p>
        {q.isLoading ? <span className="text-[11px] text-zinc-600">Loading...</span> : null}
      </div>
      {versions.length === 0 && !q.isLoading ? (
        <p className="text-xs text-zinc-600">No versions tracked yet</p>
      ) : (
        <div className="space-y-2">
          {versions.slice(0, 4).map((item) => (
            <div key={item.version} className="rounded-md border border-white/8 bg-black/20 p-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-xs text-zinc-200">v{item.version}</span>
                    {item.is_latest ? (
                      <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0 text-[10px] text-emerald-300">
                        latest
                      </Badge>
                    ) : null}
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs text-zinc-500">{item.release_notes}</p>
                  <p className="mt-1 text-[11px] text-zinc-600">
                    {formatDate(item.uploaded_at)} / {formatBytes(item.size)}
                  </p>
                </div>
                <a
                  href={item.download_url}
                  download={item.filename}
                  className="rounded-md border border-white/10 p-1.5 text-zinc-400 hover:bg-white/10 hover:text-zinc-100"
                  title={`Download v${item.version}`}
                >
                  <Download className="size-3.5" />
                </a>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function PluginsPage() {
  const q = useQuery({ queryKey: ['plugins'], queryFn: fetchPlugins, staleTime: 10_000 })
  const plugins = normalizePluginList(q.data)

  const [search, setSearch] = useState('')

  const filtered = plugins.filter((p) =>
    !search ||
    p.name.toLowerCase().includes(search.toLowerCase()) ||
    p.target_url.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title="Plugins"
        description="Published skills available to your customers."
      />
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-4 py-6 sm:px-6">

        {/* Search bar — only shown when plugins exist */}
        {plugins.length > 0 ? (
          <div className="relative max-w-xs">
            <Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-zinc-500" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search plugins…"
              className="pl-8 border-white/10 bg-white/[0.04] text-zinc-100 placeholder:text-zinc-600 h-8 text-sm"
            />
          </div>
        ) : null}

        {q.isLoading ? (
          <p className="text-sm text-zinc-500">Loading…</p>
        ) : q.isError ? (
          <p className="text-sm text-red-400">{(q.error as Error).message}</p>
        ) : plugins.length === 0 ? (
          <Card className="border-white/8 bg-white/[0.03] shadow-none">
            <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
              <Globe className="size-8 text-zinc-600" />
              <p className="text-sm font-medium text-zinc-300">No published plugins yet</p>
              <p className="max-w-xs text-xs text-zinc-500">
                Build and publish a plugin from the Build Studio. It will appear here once published.
              </p>
            </CardContent>
          </Card>
        ) : filtered.length === 0 ? (
          <p className="text-sm text-zinc-500">No plugins match your search.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((plugin) => {
              const version = plugin.installer?.version ?? plugin.build?.version
              const hasInstaller = !!plugin.installer
              return (
                <Card
                  key={plugin.id}
                  className="border-white/8 bg-white/[0.03] shadow-none"
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
                    <div className="mb-3 flex items-center gap-3 text-xs text-zinc-500">
                      <span>
                        {version ? (
                          <>Version <span className="font-mono text-zinc-300">v{version}</span></>
                        ) : (
                          <span className="text-zinc-600">Not built yet</span>
                        )}
                      </span>
                      <span>{plugin.workflows.length} workflow{plugin.workflows.length !== 1 ? 's' : ''}</span>
                    </div>
                    {hasInstaller ? (
                      <Button asChild size="sm" className="w-full">
                        <a
                          href={`/api/v1/installers/${plugin.slug}`}
                          download={plugin.installer?.filename}
                        >
                          <Download className="size-3.5" />
                          Download installer
                        </a>
                      </Button>
                    ) : (
                      <p className="text-xs text-zinc-600">Installer not published yet</p>
                    )}
                    <InstallerVersionHistory plugin={plugin} />
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
