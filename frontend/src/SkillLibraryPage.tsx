import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { deleteSkillPackage, fetchSkillList, renameSkill, type SkillSummary } from './api/workflowApi'
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
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
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
  const [pendingRename, setPendingRename] = useState<SkillSummary | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [isDeleting, setIsDeleting] = useState(false)
  const [isRenaming, setIsRenaming] = useState(false)
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

  const allSkills = q.data?.skills ?? []
  const totalSteps = filtered.reduce((sum, item) => sum + item.step_count, 0)
  const updatedThisWeek = allSkills.filter((item) => item.modified_at * 1000 >= Date.now() - 7 * 24 * 60 * 60 * 1000).length
  const pageTitle = mode === 'packages' ? 'Skill Packages' : 'Skills'
  const pageDescription =
    mode === 'packages'
      ? 'Compiled packages with quick access into editing and JSON review.'
      : 'Saved skills with compact operational metadata and direct edit access.'

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

  const openRename = (skill: SkillSummary) => {
    setPendingRename(skill)
    setRenameValue(skill.title)
  }

  const confirmRename = async () => {
    if (!pendingRename || isRenaming) return
    const nextTitle = renameValue.trim()
    if (!nextTitle) {
      toast.error('Skill Name is required.')
      return
    }
    setIsRenaming(true)
    try {
      await renameSkill(pendingRename.skill_id, nextTitle)
      toast.success(`Renamed to ${nextTitle}`)
      const skillId = pendingRename.skill_id
      setPendingRename(null)
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['skillList'] }),
        qc.invalidateQueries({ queryKey: ['workflow', skillId] }),
        qc.invalidateQueries({ queryKey: ['skillDocument', skillId] }),
      ])
    } catch (error) {
      const message = error instanceof Error && error.message ? error.message : 'Could not rename skill'
      toast.error(message)
    } finally {
      setIsRenaming(false)
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
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-4 sm:px-6 sm:py-5">
        <section className="overflow-hidden rounded-2xl border border-white/8 bg-[linear-gradient(180deg,rgba(255,255,255,0.05),rgba(255,255,255,0.02))] shadow-[0_20px_60px_rgba(0,0,0,0.22)]">
          <div className="grid gap-4 px-4 py-4 sm:px-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(19rem,0.9fr)] lg:items-end">
            <div className="space-y-4">
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className="border-white/10 bg-white/[0.05] text-zinc-300">
                    {filtered.length} visible
                  </Badge>
                  <Badge variant="outline" className="border-emerald-500/20 bg-emerald-500/10 text-emerald-200">
                    {updatedThisWeek} updated in 7d
                  </Badge>
                </div>
                <div>
                  <h2 className="text-lg font-semibold tracking-tight text-white sm:text-xl">{pageTitle}</h2>
                  <p className="mt-1 max-w-2xl text-sm leading-6 text-zinc-400">
                    Search by title, skill id, or version and move straight into edit or JSON review without extra navigation.
                  </p>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded-xl border border-white/8 bg-black/20 px-3.5 py-3">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-zinc-500">Saved</p>
                  <p className="mt-1 text-2xl font-semibold text-white">{allSkills.length}</p>
                </div>
                <div className="rounded-xl border border-white/8 bg-black/20 px-3.5 py-3">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-zinc-500">Visible</p>
                  <p className="mt-1 text-2xl font-semibold text-white">{filtered.length}</p>
                </div>
                <div className="rounded-xl border border-white/8 bg-black/20 px-3.5 py-3">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-zinc-500">Total steps</p>
                  <p className="mt-1 text-2xl font-semibold text-white">{totalSteps}</p>
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-white/8 bg-black/20 p-3.5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-white">Filter library</p>
                  <p className="text-xs text-zinc-500">Compact lookup for stored records and versions.</p>
                </div>
                <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-400">
                  Live
                </Badge>
              </div>
              <label className="relative mt-3 block">
                <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-zinc-500" />
                <Input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={mode === 'packages' ? 'Search packages' : 'Search skills'}
                  className="h-10 border-white/10 bg-white/[0.03] pl-9 text-zinc-100 placeholder:text-zinc-500"
                />
              </label>
              <p className="mt-2 text-xs text-zinc-500">Matches title, internal id, and version number.</p>
            </div>
          </div>
        </section>

        {q.isLoading ? (
          <div className={cn('grid gap-3', mode === 'packages' ? 'md:grid-cols-2 xl:grid-cols-3' : 'grid-cols-1')}>
            {Array.from({ length: mode === 'packages' ? 6 : 4 }).map((_, index) => (
              <Skeleton key={index} className="h-28 rounded-xl bg-white/8" />
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
            <CardContent className="p-6 text-center text-sm text-zinc-500">No saved skills match this filter.</CardContent>
          </Card>
        ) : null}

        {!q.isLoading && !q.isError && filtered.length > 0 && mode === 'packages' ? (
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {filtered.map((skill) => (
              <Card
                key={skill.skill_id}
                className="border-white/8 bg-white/[0.035] shadow-none transition-colors hover:border-white/14 hover:bg-white/[0.05]"
              >
                <CardHeader className="border-b border-white/8 px-4 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <CardTitle className="truncate text-base text-white">{skill.title}</CardTitle>
                      <CardDescription className="mt-1 break-all font-mono text-[11px] text-zinc-500">
                        {skill.skill_id}
                      </CardDescription>
                    </div>
                    <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
                      v{skill.version}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3 px-4 py-4">
                  <div className="grid grid-cols-2 gap-2.5 text-sm">
                    <div className="rounded-lg border border-white/8 bg-black/20 px-3 py-2.5">
                      <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-500">Steps</p>
                      <p className="mt-1 font-medium text-white">{skill.step_count}</p>
                    </div>
                    <div className="rounded-lg border border-white/8 bg-black/20 px-3 py-2.5">
                      <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-500">Updated</p>
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
                        className="cursor-pointer text-zinc-300 hover:bg-white/[0.08] hover:text-white"
                        title={`Rename ${skill.title}`}
                        onClick={() => openRename(skill)}
                        aria-label={`Rename ${skill.title}`}
                      >
                        <Pencil className="size-3.5" />
                      </Button>
                      <Button
                        type="button"
                        size="icon-sm"
                        variant="ghost"
                        className="cursor-pointer text-red-300 hover:bg-red-500/10 hover:text-red-200"
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
          <>
            <Card className="border-white/8 bg-white/[0.035] shadow-none md:hidden">
              <div className="border-b border-white/8 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">Saved skills</p>
              </div>
              <div className="divide-y divide-white/6">
                {filtered.map((skill) => (
                  <div key={skill.skill_id} className="space-y-3 px-4 py-3.5">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-white">{skill.title}</p>
                        <p className="mt-1 truncate font-mono text-[11px] text-zinc-500">{skill.skill_id}</p>
                      </div>
                      <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
                        v{skill.version}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-4 text-xs text-zinc-500">
                      <span>{skill.step_count} steps</span>
                      <span className="flex items-center gap-1.5">
                        <Clock3 className="size-3.5" />
                        {formatModifiedAt(skill.modified_at)}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button asChild size="sm">
                        <Link to={`/skills/${skill.skill_id}/json`}>
                          <FileJson className="size-3.5" />
                          Open
                        </Link>
                      </Button>
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
                        className="cursor-pointer text-zinc-300 hover:bg-white/[0.08] hover:text-white"
                        onClick={() => openRename(skill)}
                      >
                        <Pencil className="size-3.5" />
                        Rename
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="cursor-pointer text-red-300 hover:bg-red-500/10 hover:text-red-200"
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

            <Card className="hidden border-white/8 bg-white/[0.035] shadow-none md:block">
              <div className="grid grid-cols-[minmax(0,1.15fr)_minmax(0,0.95fr)_5rem_5rem_8rem_12.5rem] gap-4 border-b border-white/8 px-4 py-3 text-[11px] uppercase tracking-[0.16em] text-zinc-500">
                <span>Title</span>
                <span>Skill ID</span>
                <span>Ver</span>
                <span>Steps</span>
                <span>Updated</span>
                <span className="text-right">Actions</span>
              </div>
              <div>
                {filtered.map((skill) => (
                  <div
                    key={skill.skill_id}
                    className="grid grid-cols-[minmax(0,1.15fr)_minmax(0,0.95fr)_5rem_5rem_8rem_12.5rem] items-center gap-4 border-b border-white/6 px-4 py-2.5 transition-colors last:border-b-0 hover:bg-white/[0.03]"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-white">{skill.title}</p>
                    </div>
                    <p className="truncate font-mono text-xs text-zinc-400">{skill.skill_id}</p>
                    <p className="text-sm text-zinc-200">v{skill.version}</p>
                    <p className="text-sm text-zinc-200">{skill.step_count}</p>
                    <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                      <Clock3 className="size-3.5 shrink-0" />
                      <span className="truncate">{formatModifiedAt(skill.modified_at)}</span>
                    </div>
                    <div className="flex justify-end gap-1.5">
                      <Button asChild size="sm">
                        <Link to={`/skills/${skill.skill_id}/json`}>
                          <FileJson className="size-3.5" />
                          Open
                        </Link>
                      </Button>
                      <Button asChild size="sm" variant="secondary">
                        <Link to={`/edit/${skill.skill_id}`}>
                          <Pencil className="size-3.5" />
                          Edit
                        </Link>
                      </Button>
                      <Button
                        type="button"
                        size="icon-sm"
                        variant="ghost"
                        className="cursor-pointer text-zinc-300 hover:bg-white/[0.08] hover:text-white"
                        onClick={() => openRename(skill)}
                        title={`Rename ${skill.title}`}
                        aria-label={`Rename ${skill.title}`}
                      >
                        <Pencil className="size-3.5" />
                      </Button>
                      <Button
                        type="button"
                        size="icon-sm"
                        variant="ghost"
                        className="cursor-pointer text-red-300 hover:bg-red-500/10 hover:text-red-200"
                        title={`Delete ${skill.title}`}
                        onClick={() => setPendingDelete(skill)}
                        aria-label={`Delete ${skill.title}`}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </>
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
      <Dialog
        open={pendingRename !== null}
        onOpenChange={(open) => {
          if (!open && !isRenaming) {
            setPendingRename(null)
            setRenameValue('')
          }
        }}
      >
        <DialogContent className="border-white/10 bg-[#111418] text-zinc-100">
          <DialogHeader>
            <DialogTitle>Rename {mode === 'packages' ? 'package' : 'skill'}</DialogTitle>
            <DialogDescription className="text-zinc-400">
              {pendingRename ? `Update the display name for ${pendingRename.skill_id}.` : 'Update the saved skill title.'}
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault()
              void confirmRename()
            }}
          >
            <div className="space-y-2">
              <label className="text-xs uppercase tracking-[0.16em] text-zinc-500" htmlFor="rename-skill-title">
                Skill name
              </label>
              <Input
                id="rename-skill-title"
                value={renameValue}
                onChange={(event) => setRenameValue(event.target.value)}
                disabled={isRenaming}
                autoFocus
                className="border-white/10 bg-black/20 text-zinc-100"
              />
            </div>
            <DialogFooter className="border-white/8 bg-white/[0.03]">
              <Button
                type="button"
                variant="outline"
                className="border-white/10 bg-transparent text-zinc-200 hover:bg-white/[0.08]"
                onClick={() => {
                  if (!isRenaming) {
                    setPendingRename(null)
                    setRenameValue('')
                  }
                }}
                disabled={isRenaming}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={isRenaming}>
                {isRenaming ? 'Saving...' : 'Save'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </AppShell>
  )
}
