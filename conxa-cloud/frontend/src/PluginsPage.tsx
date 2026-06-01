'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createPlugin, deletePlugin, fetchPlugins, normalizePluginList, type Plugin } from '@/api/pluginApi'
import { fetchMe } from '@/api/productApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { ArrowRight, Globe, KeyRound, Plus, Search, Trash2 } from 'lucide-react'
import { OpenInStudioButton } from '@/components/OpenInStudioButton'

function statusBadge(status: Plugin['status']) {
  const map: Record<Plugin['status'], { label: string; className: string }> = {
    needs_auth: { label: 'Needs auth', className: 'border-amber-500/30 bg-amber-500/10 text-amber-300' },
    ready: { label: 'Ready', className: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' },
    building: { label: 'Building', className: 'border-blue-500/30 bg-blue-500/10 text-blue-300' },
    error: { label: 'Error', className: 'border-red-500/30 bg-red-500/10 text-red-300' },
  }
  const { label, className } = map[status] ?? map.error
  return (
    <Badge variant="outline" className={className}>
      {label}
    </Badge>
  )
}

function CreatePluginDialog({ onCreated }: { onCreated: () => void }) {
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [targetUrl, setTargetUrl] = useState('')
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: () => createPlugin({ name, target_url: targetUrl }),
    onSuccess: (data) => {
      setOpen(false)
      setName('')
      setTargetUrl('')
      setError('')
      onCreated()
      router.push(`/plugins/${data.plugin.id}`)
    },
    onError: (e: Error) => setError(e.message),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus className="size-4" />
          New Plugin
        </Button>
      </DialogTrigger>
      <DialogContent className="border-white/10 bg-[#0d0f12] text-zinc-100">
        <DialogHeader>
          <DialogTitle className="text-white">Create Plugin</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 pt-2">
          <div className="space-y-1.5">
            <Label className="text-zinc-300">Plugin name</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && mutation.mutate()}
              placeholder="e.g. Render.com"
              className="border-white/10 bg-white/5 text-zinc-100"
              disabled={mutation.isPending}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-zinc-300">Target URL</Label>
            <Input
              value={targetUrl}
              onChange={(e) => setTargetUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && mutation.mutate()}
              placeholder="https://render.com"
              className="border-white/10 bg-white/5 text-zinc-100"
              disabled={mutation.isPending}
            />
            <p className="text-xs text-zinc-500">The login or landing page for the site your plugin automates.</p>
          </div>
          {error ? <p className="text-sm text-red-400">{error}</p> : null}
          <Button
            className="w-full"
            onClick={() => mutation.mutate()}
            disabled={!name || !targetUrl || mutation.isPending}
          >
            {mutation.isPending ? 'Creating…' : 'Create Plugin'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function DeletePluginButton({ plugin, onDeleted }: { plugin: Plugin; onDeleted: () => void }) {
  const mutation = useMutation({
    mutationFn: () => deletePlugin(plugin.id),
    onSuccess: onDeleted,
  })
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button size="icon-sm" variant="ghost" className="text-zinc-500 hover:text-red-400">
          <Trash2 className="size-4" />
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent className="border-white/10 bg-[#0d0f12] text-zinc-100">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-white">Delete &ldquo;{plugin.name}&rdquo;?</AlertDialogTitle>
          <AlertDialogDescription className="text-zinc-400">
            This deletes the plugin, all its workflows, and the built output. This cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel className="border-white/10 bg-white/5 text-zinc-200">Cancel</AlertDialogCancel>
          <AlertDialogAction
            className="bg-red-600 text-white hover:bg-red-700"
            onClick={() => mutation.mutate()}
          >
            Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

const STATUS_FILTERS = ['all', 'ready', 'needs_auth', 'building', 'error'] as const
type StatusFilter = typeof STATUS_FILTERS[number]

export function PluginsPage() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['plugins'], queryFn: fetchPlugins, staleTime: 10_000 })
  const meQuery = useQuery({ queryKey: ['me'], queryFn: fetchMe, staleTime: 60_000 })
  const refetch = () => qc.invalidateQueries({ queryKey: ['plugins'] })
  const plugins = normalizePluginList(q.data)
  const workspace = meQuery.data?.workspace
  const isPersonalWorkspace = Boolean(workspace?.id?.startsWith('personal_'))

  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

  const filtered = plugins.filter((p) => {
    const matchesSearch = !search || p.name.toLowerCase().includes(search.toLowerCase()) || p.target_url.toLowerCase().includes(search.toLowerCase())
    const matchesStatus = statusFilter === 'all' || p.status === statusFilter
    return matchesSearch && matchesStatus
  })

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title="Plugins"
        description="Each plugin bundles auth + workflows for one web app."
        actions={
          <div className="flex items-center gap-2">
            <OpenInStudioButton size="default" />
            <CreatePluginDialog onCreated={refetch} />
          </div>
        }
      />
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-4 py-6 sm:px-6">
        {/* Search + filter bar */}
        {plugins.length > 0 ? (
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-zinc-500" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search plugins…"
                className="pl-8 border-white/10 bg-white/[0.04] text-zinc-100 placeholder:text-zinc-600 h-8 text-sm"
              />
            </div>
            <div className="flex gap-1.5">
              {STATUS_FILTERS.map((f) => (
                <button
                  key={f}
                  onClick={() => setStatusFilter(f)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    statusFilter === f
                      ? 'bg-white/10 text-white'
                      : 'text-zinc-500 hover:text-zinc-300 hover:bg-white/[0.04]'
                  }`}
                >
                  {f === 'all' ? 'All' : f === 'needs_auth' ? 'Needs auth' : f.charAt(0).toUpperCase() + f.slice(1)}
                </button>
              ))}
            </div>
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
              <p className="text-sm font-medium text-zinc-300">No cloud-published plugins for this workspace</p>
              <p className="max-w-xs text-xs text-zinc-500">
                Build and install a plugin from Build Studio, then refresh this page after the cloud publish finishes.
              </p>
              {workspace ? (
                <p className="max-w-md text-[11px] text-zinc-600">
                  Workspace: {workspace.name || workspace.slug} ({workspace.id})
                </p>
              ) : null}
              {isPersonalWorkspace ? (
                <p className="max-w-md text-xs text-amber-300/80">
                  The backend is using a personal workspace. If this should show organization plugins, configure the shared API proxy secret for the frontend and backend.
                </p>
              ) : null}
              <CreatePluginDialog onCreated={refetch} />
            </CardContent>
          </Card>
        ) : filtered.length === 0 ? (
          <p className="text-sm text-zinc-500">No plugins match your filter.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((plugin) => (
              <Card
                key={plugin.id}
                className="group border-white/8 bg-white/[0.03] shadow-none transition-colors hover:border-white/12 hover:bg-white/[0.05]"
              >
                <CardHeader className="flex-row items-start justify-between gap-2 pb-2">
                  <div className="min-w-0">
                    <CardTitle className="truncate text-sm font-medium text-white">{plugin.name}</CardTitle>
                    <p className="mt-0.5 truncate text-xs text-zinc-500">{plugin.target_url}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    {statusBadge(plugin.status)}
                    <DeletePluginButton plugin={plugin} onDeleted={refetch} />
                  </div>
                </CardHeader>
                <CardContent className="pt-0">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3 text-xs text-zinc-500">
                      <span className="flex items-center gap-1">
                        <KeyRound className="size-3" />
                        {plugin.auth ? 'Auth ✓' : 'No auth'}
                      </span>
                      <span>{plugin.workflows.length} workflow{plugin.workflows.length !== 1 ? 's' : ''}</span>
                      {plugin.build ? <span>v{plugin.build.version}</span> : null}
                    </div>
                    <div className="flex items-center gap-1">
                      <OpenInStudioButton pluginId={plugin.id} />
                      <Button asChild size="icon-sm" variant="ghost" className="text-zinc-400 hover:text-white">
                        <Link href={`/plugins/${plugin.id}`}>
                          <ArrowRight className="size-4" />
                        </Link>
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
