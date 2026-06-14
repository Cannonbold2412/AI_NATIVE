import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchPlugins, normalizePluginList } from '@/api/pluginApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { EntitlementMeters } from '@/components/EntitlementMeters'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { Code2, ExternalLink, Loader2, Puzzle, RefreshCw } from 'lucide-react'

export function CompilePage() {
  const pluginsQ = useQuery({
    queryKey: ['plugins'],
    queryFn: fetchPlugins,
  })

  const plugins = normalizePluginList(pluginsQ.data)
  const workflows = plugins.flatMap((plugin) =>
    plugin.workflows.map((workflow) => ({
      plugin,
      workflow,
    })),
  )

  if (pluginsQ.isLoading) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <PageHeader title="Compile" />
        <div className="flex items-center gap-2 p-6 text-sm text-zinc-500">
          <Loader2 className="size-4 animate-spin" />
          Loading workflows...
        </div>
      </div>
    )
  }

  if (pluginsQ.isError) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <PageHeader title="Compile" />
        <p className="p-6 text-sm text-red-400">{(pluginsQ.error as Error)?.message ?? 'Failed to load plugins'}</p>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader title="Compile" description="Compile and inspect plugin workflow recordings." />
      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
          <EntitlementMeters meters={['compile_credits', 'human_edit_tokens']} compact />
          {workflows.length === 0 ? (
            <div className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-lg border border-white/8 bg-white/[0.03] text-center">
              <Puzzle className="size-6 text-zinc-500" />
              <div>
                <p className="text-sm font-medium text-white">No workflows to compile</p>
                <p className="mt-1 text-xs text-zinc-500">Create a plugin workflow first, then it will appear here.</p>
              </div>
              <Button size="sm" variant="outline" asChild>
                <Link to="/dashboard">
                  <ExternalLink className="size-3.5" />
                  Open Dashboard
                </Link>
              </Button>
            </div>
          ) : (
            <div className="rounded-lg border border-white/8 bg-white/[0.03]">
              <div className="flex items-center justify-between gap-3 border-b border-white/8 px-4 py-3">
                <div>
                  <h2 className="text-sm font-medium text-white">Workflow Compile Queue</h2>
                  <p className="mt-0.5 text-xs text-zinc-500">{workflows.length} workflow{workflows.length === 1 ? '' : 's'}</p>
                </div>
                <Badge variant="outline" className="border-white/10 bg-white/5 text-zinc-300">
                  {plugins.length} plugin{plugins.length === 1 ? '' : 's'}
                </Badge>
              </div>
              <div className="divide-y divide-white/8">
                {workflows.map(({ plugin, workflow }) => {
                  const compiled = Boolean(workflow.skill_id)
                  const to = compiled
                    ? `/plugins/${encodeURIComponent(plugin.id)}/compile/${encodeURIComponent(workflow.session_id)}?mode=recompile`
                    : `/plugins/${encodeURIComponent(plugin.id)}/compile/${encodeURIComponent(workflow.session_id)}`
                  return (
                    <div key={`${plugin.id}:${workflow.id}`} className="flex items-center justify-between gap-4 px-4 py-3">
                      <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-2">
                          <p className="truncate text-sm font-medium text-white">{workflow.name}</p>
                          <Badge
                            variant="outline"
                            className={cn(
                              'shrink-0 text-[10px]',
                              compiled
                                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                                : 'border-amber-500/30 bg-amber-500/10 text-amber-300',
                            )}
                          >
                            {compiled ? 'compiled' : 'recorded'}
                          </Badge>
                        </div>
                        <p className="mt-1 truncate text-xs text-zinc-500">
                          {plugin.name} - {compiled ? 'Recompile uses Human Edit pool' : 'Compile uses 1 compile credit'}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <Button size="sm" variant="outline" asChild>
                          <Link to={`/plugins/${encodeURIComponent(plugin.id)}`}>
                            <Puzzle className="size-3.5" />
                            Plugin
                          </Link>
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="border-amber-500/30 bg-amber-500/5 text-amber-300 hover:bg-amber-500/10"
                          asChild
                        >
                          <Link to={to}>
                            {compiled ? <RefreshCw className="size-3.5" /> : <Code2 className="size-3.5" />}
                            {compiled ? 'Recompile' : 'Compile'}
                          </Link>
                        </Button>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
