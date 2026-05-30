'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { getCompiledSkill, type Plugin } from '@/api/pluginApi'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ChevronDown, ChevronRight, Edit2 } from 'lucide-react'

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
      <Card className="border-white/8 bg-white/[0.03] shadow-none">
        <CardContent className="px-4 py-8 text-sm text-zinc-500">
          No workflows yet. Record a workflow before compiled skills can appear here.
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="border-white/8 bg-white/[0.03] shadow-none">
      <CardHeader className="border-b border-white/8 pb-3">
        <CardTitle className="text-sm font-medium text-white flex items-center gap-2">
          Compiled Skills
          <Badge variant="outline" className="border-white/10 bg-white/5 text-zinc-400">
            {compiledCount}/{plugin.workflows.length}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {plugin.workflows.map((workflow) => {
          const canInspect = workflow.status === 'compiled' && Boolean(workflow.skill_id)
          const isOpen = canInspect && expandedWorkflowId === workflow.id
          const recordedAt = new Date(workflow.recorded_at * 1000).toLocaleString([], {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
          })

          return (
            <div key={workflow.id} className="border-t border-white/6 first:border-t-0">
              <div className="flex flex-wrap items-center gap-3 px-4 py-3">
                <button
                  type="button"
                  className="flex min-w-0 flex-1 items-center gap-3 text-left disabled:cursor-default"
                  onClick={() => canInspect && setExpandedWorkflowId(isOpen ? null : workflow.id)}
                  disabled={!canInspect}
                >
                  {canInspect ? (
                    isOpen ? (
                      <ChevronDown className="size-4 shrink-0 text-zinc-500" />
                    ) : (
                      <ChevronRight className="size-4 shrink-0 text-zinc-500" />
                    )
                  ) : (
                    <span className="size-4 shrink-0" />
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
                    className="border-blue-500/30 bg-blue-500/5 text-blue-300 hover:bg-blue-500/10 hover:text-blue-200"
                    title="Edit workflow"
                  >
                    <Link href={`/edit/${workflow.skill_id}?from=${encodeURIComponent('/plugins/' + plugin.id)}`}>
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
      </CardContent>
    </Card>
  )
}
