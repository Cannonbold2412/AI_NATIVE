import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Download, FileJson, Pencil } from 'lucide-react'
import { fetchSkillDocument } from './api/workflowApi'
import { AppShell } from '@/components/layout/AppLayout'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

function triggerJsonDownload(skillId: string, payload: Record<string, unknown>) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${skillId}.json`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function SkillJsonPage() {
  const { skillId: rawSkillId } = useParams<{ skillId: string }>()
  const skillId = rawSkillId?.trim() ?? ''

  const q = useQuery({
    queryKey: ['skillDocument', skillId],
    queryFn: () => fetchSkillDocument(skillId),
    enabled: Boolean(skillId),
  })

  const formattedJson = useMemo(() => {
    if (!q.data) return ''
    return JSON.stringify(q.data, null, 2)
  }, [q.data])

  const skillTitle = useMemo(() => {
    const meta = q.data?.meta
    if (meta && typeof meta === 'object') {
      const raw = (meta as { title?: unknown }).title
      if (typeof raw === 'string' && raw.trim()) return raw.trim()
    }
    return skillId || 'Unknown skill'
  }, [q.data, skillId])

  return (
    <AppShell
      title={skillTitle}
      description={`Skill JSON - ${skillId || 'unknown id'}`}
      mainClassName="overflow-y-auto"
      actions={
        <>
          <Button variant="outline" size="sm" asChild className="border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08]">
            <Link to="/skills">Back to library</Link>
          </Button>
          {skillId ? (
            <Button variant="outline" size="sm" asChild className="border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08]">
              <Link to={`/edit/${skillId}`}>
                <Pencil className="size-3.5" />
                Edit
              </Link>
            </Button>
          ) : null}
          <Button
            type="button"
            size="sm"
            disabled={!q.data}
            onClick={() => q.data && triggerJsonDownload(skillId, q.data)}
            className="bg-white text-black hover:bg-zinc-200"
          >
            <Download className="size-3.5" />
            Download JSON
          </Button>
        </>
      }
    >
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
        <Card className="border-white/8 bg-white/[0.035] shadow-none">
          <CardHeader className="border-b border-white/8">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <CardTitle className="flex items-center gap-2 text-white">
                  <FileJson className="size-4" />
                  {skillTitle}
                </CardTitle>
                <CardDescription className="mt-1 break-all font-mono text-xs text-zinc-500">
                  {skillId || 'Unknown skill'}
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="pt-4">
            {q.isLoading ? <Skeleton className="h-[28rem] rounded-xl bg-white/8" /> : null}
            {q.isError ? (
              <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4 text-sm text-red-200">
                {(q.error as Error).message}
              </div>
            ) : null}
            {!q.isLoading && !q.isError ? (
              <pre className="overflow-x-auto rounded-xl border border-white/8 bg-black/30 p-4 text-xs leading-6 text-zinc-200">
                <code>{formattedJson}</code>
              </pre>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
