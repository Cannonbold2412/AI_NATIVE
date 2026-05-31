
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { getCompiledSkill, type Plugin } from '@/api/pluginApi'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ChevronDown, ChevronRight, Edit2, PackageCheck } from 'lucide-react'

type SkillTab = 'execution.json' | 'recovery.json' | 'input.json'

function SkillFilesViewer({
  pluginId,
  skillSlug,
}: {
  pluginId: string
  skillSlug: string
}) {
  const [activeFile, setActiveFile] = useState<SkillTab>('execution.json')

  const q = useQuery({
    queryKey: ['compiled-skill', pluginId, skillSlug],
    queryFn: () => getCompiledSkill(pluginId, skillSlug),
    staleTime: 30_000,
  })

  const files = q.data?.files
  const activeData = files?.[activeFile]

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        {(['execution.json', 'recovery.json', 'input.json'] as SkillTab[]).map((f) => (
          <Button
            key={f}
            size="sm"
            variant={activeFile === f ? 'default' : 'outline'}
            className={activeFile === f ? '' : 'border-white/10 bg-white/5 text-zinc-400'}
            onClick={() => setActiveFile(f)}
          >
            {f}
          </Button>
        ))}
      </div>

      {q.isLoading ? <p className="text-sm text-zinc-500">Loading…</p> : null}
      {q.isError ? <p className="text-sm text-red-400">{(q.error as Error).message}</p> : null}

      {activeData != null ? (
        <>
          <div className="overflow-auto max-h-[480px] rounded-lg border border-white/8 bg-black/30 p-4">
            <pre className="text-xs text-zinc-300 whitespace-pre-wrap break-words font-mono">
              {JSON.stringify(activeData, null, 2)}
            </pre>
          </div>
        </>
      ) : !q.isLoading ? (
        <p className="text-xs text-zinc-600">{activeFile} not generated yet.</p>
      ) : null}
    </div>
  )
}

// ─────────────────────────────────────────────────
// Tab root
// ─────────────────────────────────────────────────

function workflowStatusClass(status: Plugin['workflows'][number]['status']) {
  if (status === 'compiled') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (status === 'error') return 'border-red-500/30 bg-red-500/10 text-red-300'
  return 'border-white/10 bg-white/5 text-zinc-400'
}

export function CompiledSkillsTab({ plugin }: { plugin: Plugin }) {
  const [expandedWorkflowId, setExpandedWorkflowId] = useState<string | null>(null)

  const compiledCount = plugin.workflows.filter((w) => w.status === 'compiled' && w.skill_id).length

  if (plugin.workflows.length === 0) {
    return (
      <section>
        <div className="flex items-start justify-between gap-3 border-b border-white/8 px-5 py-4">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-emerald-500/20 bg-emerald-500/10">
              <PackageCheck className="size-4 text-emerald-300" />
            </span>
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-white">Compiled Skills</h2>
              <p className="mt-1 text-xs text-zinc-500">Inspect compiled workflow output and open skills for editing.</p>
            </div>
          </div>
          <Badge variant="outline" className="shrink-0 border-white/10 bg-white/5 text-zinc-400">
            0/0
          </Badge>
        </div>
        <div className="flex flex-col items-center gap-2 px-4 py-16 text-center">
          <span className="flex size-10 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04]">
            <PackageCheck className="size-4 text-zinc-500" />
          </span>
          <p className="text-sm font-medium text-zinc-300">No compiled skills yet</p>
          <p className="max-w-sm text-xs text-zinc-500">
            Record and compile a workflow before compiled skills can appear here.
          </p>
        </div>
      </section>
    )
  }

  return (
    <section>
      <div className="flex items-center justify-between gap-3 border-b border-white/8 px-5 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-emerald-500/20 bg-emerald-500/10">
            <PackageCheck className="size-4 text-emerald-300" />
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-white">Compiled Skills</h2>
            <p className="mt-1 text-xs text-zinc-500">Inspect compiled workflow output and open skills for editing.</p>
          </div>
        </div>
        <Badge variant="outline" className="shrink-0 border-white/10 bg-white/5 text-zinc-400">
          {compiledCount}/{plugin.workflows.length}
        </Badge>
      </div>
      <div className="p-5">
        <div className="overflow-hidden rounded-lg border border-white/8 bg-white/[0.03]">
          {plugin.workflows.map((workflow) => {
            const canInspect = workflow.status === 'compiled' && Boolean(workflow.skill_id)
            const isOpen = canInspect && expandedWorkflowId === workflow.id
            const recordedAt = new Date(workflow.recorded_at * 1000).toLocaleString([], {
              month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
            })

            return (
              <div key={workflow.id} className="border-t border-white/6 first:border-t-0">
                <div className="flex flex-wrap items-center gap-3 px-4 py-3 transition-colors hover:bg-white/[0.025]">
                  <button
                    type="button"
                    className="flex min-w-[14rem] flex-1 items-center gap-3 rounded-md text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-white/20 disabled:cursor-default"
                    onClick={() => canInspect && setExpandedWorkflowId(isOpen ? null : workflow.id)}
                    disabled={!canInspect}
                  >
                    {canInspect ? (
                      isOpen ? (
                        <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/[0.04]">
                          <ChevronDown className="size-4 text-zinc-400" />
                        </span>
                      ) : (
                        <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/[0.04]">
                          <ChevronRight className="size-4 text-zinc-400" />
                        </span>
                      )
                    ) : (
                      <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-white/8 bg-white/[0.02]">
                        <PackageCheck className="size-3.5 text-zinc-600" />
                      </span>
                    )}
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-white">{workflow.name}</span>
                      <span className="mt-0.5 block truncate font-mono text-xs text-zinc-500">
                        {workflow.skill_id ?? workflow.slug} · {recordedAt}
                      </span>
                    </span>
                  </button>
                  <Badge variant="outline" className={workflowStatusClass(workflow.status)}>
                    {workflow.status}
                  </Badge>
                  {workflow.skill_id ? (
                    <Button
                      asChild
                      size="sm"
                      variant="outline"
                      className="h-8 min-w-[5.5rem] border-blue-500/35 bg-blue-500/10 px-3 font-medium text-blue-100 hover:border-blue-400/50 hover:bg-blue-500/20 hover:text-white"
                      title="Edit workflow"
                    >
                      <Link to={`/edit/${workflow.skill_id}?from=${encodeURIComponent('/plugins/' + plugin.id)}`}>
                        <Edit2 className="size-3.5" />
                        Edit
                      </Link>
                    </Button>
                  ) : null}
                </div>
                {isOpen ? (
                  <div className="border-t border-white/6 bg-white/[0.015] px-4 py-4">
                    <SkillFilesViewer pluginId={plugin.id} skillSlug={workflow.slug} />
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
