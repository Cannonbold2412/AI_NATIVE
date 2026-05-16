'use client'

import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { getCompiledSkill, updateStepUrlState, type Plugin } from '@/api/pluginApi'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ChevronDown, ChevronRight, Edit2, ExternalLink, RefreshCw } from 'lucide-react'

type SkillTab = 'execution.json' | 'recovery.json' | 'input.json'

// ─────────────────────────────────────────────────
// URL state editor for a single step
// ─────────────────────────────────────────────────

function UrlStateEditor({
  pluginId,
  skillSlug,
  stepId,
  urlState,
  onSaved,
}: {
  pluginId: string
  skillSlug: string
  stepId: string
  urlState: Record<string, unknown>
  onSaved: () => void
}) {
  const before = (urlState.before ?? {}) as Record<string, string>
  const after = (urlState.after ?? {}) as Record<string, string>

  const [beforePattern, setBeforePattern] = useState(before.url_pattern ?? '')
  const [afterPattern, setAfterPattern] = useState(after.url_pattern ?? '')
  const [testResult, setTestResult] = useState<{ before?: boolean; after?: boolean } | null>(null)
  const editedByUser = urlState.edited_by_user === true

  const saveMut = useMutation({
    mutationFn: () =>
      updateStepUrlState(pluginId, skillSlug, stepId, {
        before: { url_pattern: beforePattern },
        after: { url_pattern: afterPattern },
      }),
    onSuccess: onSaved,
  })

  const testPattern = () => {
    const testUrl = before.url ?? ''
    let beforeOk: boolean | undefined
    let afterOk: boolean | undefined
    try {
      if (beforePattern) beforeOk = new RegExp(beforePattern).test(testUrl)
    } catch { beforeOk = false }
    try {
      if (afterPattern) afterOk = new RegExp(afterPattern).test(after.url ?? '')
    } catch { afterOk = false }
    setTestResult({ before: beforeOk, after: afterOk })
  }

  return (
    <div className="space-y-4 rounded-lg border border-white/8 bg-white/[0.02] p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-zinc-300">URL State — {stepId}</p>
        {editedByUser ? (
          <Badge variant="outline" className="border-blue-500/30 bg-blue-500/10 text-blue-300 text-xs">
            edited by user
          </Badge>
        ) : null}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label className="text-xs text-zinc-400">Before pattern</Label>
          <Input
            value={beforePattern}
            onChange={(e) => { setBeforePattern(e.target.value); setTestResult(null) }}
            placeholder="^https://example\\.com/path$"
            className="font-mono text-xs border-white/10 bg-white/5 text-zinc-100"
          />
          {before.url ? (
            <p className="text-xs text-zinc-600 font-mono truncate">recorded: {before.url as string}</p>
          ) : null}
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-zinc-400">After pattern</Label>
          <Input
            value={afterPattern}
            onChange={(e) => { setAfterPattern(e.target.value); setTestResult(null) }}
            placeholder="^https://example\\.com/next$"
            className="font-mono text-xs border-white/10 bg-white/5 text-zinc-100"
          />
          {after.url ? (
            <p className="text-xs text-zinc-600 font-mono truncate">recorded: {after.url as string}</p>
          ) : null}
        </div>
      </div>

      {testResult ? (
        <div className="flex gap-4 text-xs">
          {testResult.before != null ? (
            <span className={testResult.before ? 'text-emerald-400' : 'text-red-400'}>
              before pattern: {testResult.before ? 'matches' : 'no match'}
            </span>
          ) : null}
          {testResult.after != null ? (
            <span className={testResult.after ? 'text-emerald-400' : 'text-red-400'}>
              after pattern: {testResult.after ? 'matches' : 'no match'}
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="flex gap-2">
        <Button
          size="sm"
          variant="outline"
          className="border-white/10 bg-white/5 text-zinc-300"
          onClick={testPattern}
          disabled={!beforePattern && !afterPattern}
        >
          Test patterns
        </Button>
        <Button
          size="sm"
          onClick={() => saveMut.mutate()}
          disabled={saveMut.isPending}
        >
          {saveMut.isPending ? <RefreshCw className="size-3.5 animate-spin" /> : <Edit2 className="size-3.5" />}
          Save
        </Button>
        {saveMut.isSuccess ? <span className="self-center text-xs text-emerald-400">Saved</span> : null}
        {saveMut.isError ? <span className="self-center text-xs text-red-400">{(saveMut.error as Error).message}</span> : null}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────
// Per-skill compiled files viewer
// ─────────────────────────────────────────────────

function SkillFilesViewer({
  pluginId,
  skillSlug,
}: {
  pluginId: string
  skillSlug: string
}) {
  const [activeFile, setActiveFile] = useState<SkillTab>('execution.json')
  const [editingStep, setEditingStep] = useState<string | null>(null)

  const q = useQuery({
    queryKey: ['compiled-skill', pluginId, skillSlug],
    queryFn: () => getCompiledSkill(pluginId, skillSlug),
    staleTime: 30_000,
  })

  const files = q.data?.files
  const activeData = files?.[activeFile]

  const steps: Array<{ id: string; url_state?: Record<string, unknown> }> =
    activeFile === 'execution.json' && activeData
      ? (Array.isArray(activeData)
          ? activeData
          : ((activeData as Record<string, unknown>).steps ??
              (activeData as Record<string, unknown>).execution_plan ??
              [])) as Array<{ id: string; url_state?: Record<string, unknown> }>
      : []

  const invalidate = () => q.refetch()

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
          {activeFile === 'execution.json' && steps.length > 0 ? (
            <div className="space-y-2">
              <p className="text-xs text-zinc-500">
                {steps.length} step{steps.length !== 1 ? 's' : ''} — click a step to edit its URL state
              </p>
              {steps.map((step, i) => {
                const sid = String(step.id ?? `step_${i + 1}`)
                const isEditing = editingStep === sid
                return (
                  <div key={sid} className="rounded-lg border border-white/6 bg-white/[0.015]">
                    <button
                      className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-white/[0.02]"
                      onClick={() => setEditingStep(isEditing ? null : sid)}
                    >
                      {isEditing ? <ChevronDown className="size-3.5 text-zinc-500 shrink-0" /> : <ChevronRight className="size-3.5 text-zinc-500 shrink-0" />}
                      <span className="text-xs font-mono text-zinc-300">{sid}</span>
                      <span className="text-xs text-zinc-500">{String((step as Record<string, unknown>).type ?? '')}</span>
                      {step.url_state ? (
                        (step.url_state as Record<string, unknown>).edited_by_user ? (
                          <Badge variant="outline" className="ml-auto text-xs border-blue-500/30 bg-blue-500/10 text-blue-300">edited</Badge>
                        ) : (
                          <Badge variant="outline" className="ml-auto text-xs border-white/10 bg-white/5 text-zinc-500">auto</Badge>
                        )
                      ) : null}
                    </button>
                    {isEditing && step.url_state ? (
                      <div className="border-t border-white/6 p-3">
                        <UrlStateEditor
                          pluginId={pluginId}
                          skillSlug={skillSlug}
                          stepId={sid}
                          urlState={step.url_state}
                          onSaved={invalidate}
                        />
                      </div>
                    ) : null}
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="overflow-auto max-h-[480px] rounded-lg border border-white/8 bg-black/30 p-4">
              <pre className="text-xs text-zinc-300 whitespace-pre-wrap break-words font-mono">
                {JSON.stringify(activeData, null, 2)}
              </pre>
            </div>
          )}
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

export function CompiledSkillsTab({ plugin }: { plugin: Plugin }) {
  const [expandedSkill, setExpandedSkill] = useState<string | null>(null)

  const skillSlugs = plugin.workflows
    .filter((w) => w.status === 'compiled' && w.skill_id)
    .map((w) => w.slug)

  if (plugin.build == null) {
    return (
      <Card className="border-white/8 bg-white/[0.03] shadow-none">
        <CardContent className="px-4 py-8 text-sm text-zinc-500">
          Plugin has not been built yet. Use the Build tab to compile.
        </CardContent>
      </Card>
    )
  }

  if (skillSlugs.length === 0) {
    return (
      <Card className="border-white/8 bg-white/[0.03] shadow-none">
        <CardContent className="px-4 py-8 text-sm text-zinc-500">
          No compiled skills found. Build the plugin first.
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
            {skillSlugs.length}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {skillSlugs.map((slug) => {
          const isOpen = expandedSkill === slug
          return (
            <div key={slug} className="border-t border-white/6 first:border-t-0">
              <button
                className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-white/[0.02]"
                onClick={() => setExpandedSkill(isOpen ? null : slug)}
              >
                {isOpen ? <ChevronDown className="size-4 text-zinc-500 shrink-0" /> : <ChevronRight className="size-4 text-zinc-500 shrink-0" />}
                <span className="text-sm font-mono text-white">{slug}</span>
                <ExternalLink className="size-3.5 text-zinc-600 ml-auto" />
              </button>
              {isOpen ? (
                <div className="border-t border-white/6 bg-white/[0.015] px-4 py-4">
                  <SkillFilesViewer pluginId={plugin.id} skillSlug={slug} />
                </div>
              ) : null}
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
