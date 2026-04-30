import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { deleteSkillPackage, type SkillSummary, fetchSkillList } from './api/workflowApi'
import { AppShell } from '@/components/layout/AppLayout'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { Boxes, Clock3, FileJson, Pencil, RefreshCw, Search, Trash2 } from 'lucide-react'

function formatModifiedAt(value: number) {
  return new Date(value * 1000).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

type Mode = 'packages' | 'skills'

export function SkillLibraryPage({ mode }: { mode: Mode }) {
  const [search, setSearch] = useState('')
  const [pendingDelete, setPendingDelete] = useState<SkillSummary | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['skillList'],
    queryFn: fetchSkillList,
    staleTime: 60_000,
  })

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    const items = q.data?.skills ?? []
    if (!term) return items
    return items.filter((skill) => {
      return (
        skill.skill_id.toLowerCase().includes(term) ||
        skill.title.toLowerCase().includes(term) ||
        String(skill.version).includes(term)
      )
    })
  }, [q.data?.skills, search])

  const totalSteps = filtered.reduce((sum, item) => sum + item.step_count, 0)
  const pageTitle = mode === 'packages' ? 'Skill Packages' : 'Skills'
  const pageDescription =
    mode === 'packages'
      ? 'Browse compiled packages with clear metadata and quick access into editing.'
      : 'Operational list view for saved skills, versions, and step counts.'

  const confirmDelete = async () => {
    if (!pendingDelete || isDeleting) return
    setIsDeleting(true)
    try {
      await deleteSkillPackage(pendingDelete.skill_id)
      toast.success(`${pendingDelete.title} deleted`)
      setPendingDelete(null)
      await qc.invalidateQueries({ queryKey: ['skillList'] })
    } catch (error) {
      const message = error instanceof Error && error.message ? error.message : 'Could not delete skill'
      toast.error(message)
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <AppShell
      title={pageTitle}
      description={pageDescription}
      mainClassName="overflow-y-auto"
      actions={
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08]"
          onClick={() => void q.refetch()}
          disabled={q.isFetching}
        >
          <RefreshCw className={cn('size-3.5', q.isFetching && 'animate-spin')} />
          Refresh
        </Button>
      }
    >
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6">
        <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <Card className="border-white/8 bg-white/[0.035] shadow-none">
            <CardHeader className="border-b border-white/8">
              <CardTitle className="text-white">{pageTitle}</CardTitle>
              <CardDescription className="text-zinc-500">
                Search by title or skill id, then open the stored JSON package or move into editing.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-4">
              <label className="relative block">
                <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-zinc-500" />
                <Input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={mode === 'packages' ? 'Search packages' : 'Search skills'}
                  className="border-white/10 bg-black/20 pl-9 text-zinc-100 placeholder:text-zinc-500"
                />
              </label>
            </CardContent>
          </Card>

          <Card className="border-white/8 bg-white/[0.035] shadow-none">
            <CardContent className="grid h-full gap-3 p-4">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-zinc-500">Saved</p>
                <p className="mt-1 text-2xl font-semibold text-white">{filtered.length}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-zinc-500">Total steps</p>
                <p className="mt-1 text-2xl font-semibold text-white">{totalSteps}</p>
              </div>
            </CardContent>
          </Card>
        </section>

        {q.isLoading ? (
          <div className={cn('grid gap-4', mode === 'packages' ? 'md:grid-cols-2 xl:grid-cols-3' : 'grid-cols-1')}>
            {Array.from({ length: mode === 'packages' ? 6 : 4 }).map((_, index) => (
              <Skeleton key={index} className="h-32 rounded-xl bg-white/8" />
            ))}
          </div>
        ) : null}

        {q.isError ? (
          <Card className="border-red-500/20 bg-red-500/5 shadow-none">
            <CardContent className="p-4 text-sm text-red-200">{(q.error as Error).message}</CardContent>
          </Card>
        ) : null}

        {!q.isLoading && !q.isError && filtered.length === 0 ? (
          <Card className="border-white/8 bg-white/[0.03] shadow-none">
            <CardContent className="p-8 text-center text-sm text-zinc-500">No saved skills match this filter.</CardContent>
          </Card>
        ) : null}

        {!q.isLoading && !q.isError && filtered.length > 0 && mode === 'packages' ? (
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {filtered.map((skill) => (
              <Card key={skill.skill_id} className="border-white/8 bg-white/[0.035] shadow-none">
                <CardHeader className="border-b border-white/8">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <CardTitle className="truncate text-white">{skill.title}</CardTitle>
                      <CardDescription className="mt-1 break-all font-mono text-xs text-zinc-500">
                        {skill.skill_id}
                      </CardDescription>
                    </div>
                    <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
                      v{skill.version}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4 pt-4">
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div className="rounded-lg border border-white/8 bg-black/20 p-3">
                      <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">Steps</p>
                      <p className="mt-1 font-medium text-white">{skill.step_count}</p>
                    </div>
                    <div className="rounded-lg border border-white/8 bg-black/20 p-3">
                      <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">Updated</p>
                      <p className="mt-1 text-white">{formatModifiedAt(skill.modified_at)}</p>
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2 text-xs text-zinc-500">
                      <Boxes className="size-3.5" />
                      Compiled package
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        type="button"
                        size="icon-sm"
                        variant="ghost"
                        className="text-red-300 hover:bg-red-500/10 hover:text-red-200"
                        title={`Delete ${skill.title}`}
                        onClick={() => setPendingDelete(skill)}
                        aria-label={`Delete ${skill.title}`}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                      <Button asChild size="sm" variant="secondary">
                        <Link to={`/edit/${skill.skill_id}`}>
                          <Pencil className="size-3.5" />
                          Edit
                        </Link>
                      </Button>
                      <Button asChild size="sm">
                        <Link to={`/skills/${skill.skill_id}/json`}>
                          <FileJson className="size-3.5" />
                          Open
                        </Link>
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </section>
        ) : null}

        {!q.isLoading && !q.isError && filtered.length > 0 && mode === 'skills' ? (
          <Card className="border-white/8 bg-white/[0.035] shadow-none">
            <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_7rem_8rem_11rem] gap-4 border-b border-white/8 px-4 py-3 text-xs uppercase tracking-[0.16em] text-zinc-500">
              <span>Title</span>
              <span>Skill ID</span>
              <span>Version</span>
              <span>Steps</span>
              <span className="text-right">Action</span>
            </div>
            <div>
              {filtered.map((skill) => (
                <div
                  key={skill.skill_id}
                  className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_7rem_8rem_11rem] items-center gap-4 border-b border-white/6 px-4 py-3 last:border-b-0"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-white">{skill.title}</p>
                    <div className="mt-1 flex items-center gap-1.5 text-xs text-zinc-500">
                      <Clock3 className="size-3.5" />
                      {formatModifiedAt(skill.modified_at)}
                    </div>
                  </div>
                  <p className="truncate font-mono text-xs text-zinc-400">{skill.skill_id}</p>
                  <p className="text-sm text-zinc-200">v{skill.version}</p>
                  <p className="text-sm text-zinc-200">{skill.step_count}</p>
                  <div className="flex justify-end gap-2">
                    <Button asChild size="sm" variant="secondary">
                      <Link to={`/edit/${skill.skill_id}`}>
                        <Pencil className="size-3.5" />
                        Edit
                      </Link>
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="text-red-300 hover:bg-red-500/10 hover:text-red-200"
                      title={`Delete ${skill.title}`}
                      onClick={() => setPendingDelete(skill)}
                      aria-label={`Delete ${skill.title}`}
                    >
                      <Trash2 className="size-3.5" />
                      Delete
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        ) : null}
      </div>
      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open && !isDeleting) setPendingDelete(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {mode === 'packages' ? 'package' : 'skill'}?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete
                ? `This will permanently delete ${pendingDelete.title} (${pendingDelete.skill_id}). This action cannot be undone.`
                : 'This action cannot be undone.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" disabled={isDeleting} onClick={confirmDelete}>
              {isDeleting ? 'Deleting...' : 'Delete'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AppShell>
  )
}
