import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiUrl } from '@/lib/apiBase'
import {
  deleteStoredSkillPackage,
  errorMessage,
  fetchSkillPackageFiles,
  fetchSkillPackageList,
  type SkillPackageSummary,
} from '@/api/workflowApi'
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
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import { Copy, Download, FileJson, FileText, FolderKanban, RefreshCw, Trash2 } from 'lucide-react'

const FILE_ORDER = ['skill.md', 'skill.json', 'inputs.json', 'manifest.json', 'input.json']

function formatModifiedAt(value: number) {
  return new Date(value * 1000).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function iconForFile(filename: string) {
  return filename.endsWith('.md') ? FileText : FileJson
}

function orderedPackageFiles(files: string[]) {
  return [...files].sort((a, b) => {
    const aIndex = FILE_ORDER.indexOf(a)
    const bIndex = FILE_ORDER.indexOf(b)
    if (aIndex !== -1 || bIndex !== -1) {
      return (aIndex === -1 ? Number.MAX_SAFE_INTEGER : aIndex) - (bIndex === -1 ? Number.MAX_SAFE_INTEGER : bIndex)
    }
    return a.localeCompare(b)
  })
}

async function downloadPackageFolder(packageName: string) {
  const response = await fetch(apiUrl(`/skill-pack/${encodeURIComponent(packageName)}/download`))
  if (!response.ok) {
    const raw = (await response.text()).trim()
    throw new Error(raw || 'Could not download package folder.')
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${packageName}.zip`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function SkillPackagesPage() {
  const qc = useQueryClient()
  const [pendingDelete, setPendingDelete] = useState<SkillPackageSummary | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [downloadingName, setDownloadingName] = useState<string | null>(null)
  const [selectedPackageName, setSelectedPackageName] = useState<string | null>(null)
  const [activeFile, setActiveFile] = useState<string | null>(null)

  const q = useQuery({
    queryKey: ['skillPackages'],
    queryFn: fetchSkillPackageList,
    staleTime: 30_000,
  })
  const filesQ = useQuery({
    queryKey: ['skillPackageFiles', selectedPackageName],
    queryFn: () => fetchSkillPackageFiles(selectedPackageName ?? ''),
    enabled: selectedPackageName !== null,
    staleTime: 30_000,
  })

  const selectedPackage = useMemo(
    () => q.data?.packages.find((pkg) => pkg.package_name === selectedPackageName) ?? null,
    [q.data?.packages, selectedPackageName],
  )
  const visibleFiles = useMemo(() => {
    if (filesQ.data) return orderedPackageFiles(Object.keys(filesQ.data.files))
    if (selectedPackage) return orderedPackageFiles(selectedPackage.files)
    return []
  }, [filesQ.data, selectedPackage])
  const activeContent = activeFile && filesQ.data ? filesQ.data.files[activeFile] : ''

  useEffect(() => {
    const packages = q.data?.packages ?? []
    if (packages.length === 0) {
      setSelectedPackageName(null)
      setActiveFile(null)
      return
    }
    if (!selectedPackageName || !packages.some((pkg) => pkg.package_name === selectedPackageName)) {
      setSelectedPackageName(packages[0].package_name)
    }
  }, [q.data?.packages, selectedPackageName])

  useEffect(() => {
    if (visibleFiles.length === 0) {
      setActiveFile(null)
      return
    }
    if (!activeFile || !visibleFiles.includes(activeFile)) {
      setActiveFile(visibleFiles[0])
    }
  }, [activeFile, visibleFiles])

  async function handleDownload(packageName: string) {
    setDownloadingName(packageName)
    try {
      await downloadPackageFolder(packageName)
      toast.success(`${packageName}.zip downloaded`)
    } catch (err) {
      toast.error(errorMessage(err, 'Could not download package folder.'))
    } finally {
      setDownloadingName(null)
    }
  }

  async function handleCopyFile() {
    if (!activeFile || !activeContent) return
    try {
      await navigator.clipboard.writeText(activeContent)
      toast.success(`${activeFile} copied`)
    } catch {
      toast.error(`Could not copy ${activeFile}`)
    }
  }

  async function confirmDelete() {
    if (!pendingDelete || isDeleting) return
    setIsDeleting(true)
    try {
      await deleteStoredSkillPackage(pendingDelete.package_name)
      toast.success(`${pendingDelete.package_name} deleted`)
      setPendingDelete(null)
      await qc.invalidateQueries({ queryKey: ['skillPackages'] })
      await qc.invalidateQueries({ queryKey: ['skillPackageFiles', pendingDelete.package_name] })
    } catch (err) {
      toast.error(errorMessage(err, 'Could not delete package folder.'))
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <AppShell
      title="Skill Packages"
      description="Generated package folders saved from Skill Pack Builder."
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
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-4 sm:px-6 sm:py-5">
        {q.isLoading ? (
          <div className="grid gap-4 lg:grid-cols-[minmax(18rem,24rem)_minmax(0,1fr)]">
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, index) => (
                <Skeleton key={index} className="h-36 rounded-xl bg-white/8" />
              ))}
            </div>
            <Skeleton className="h-[42rem] rounded-xl bg-white/8" />
          </div>
        ) : null}

        {q.isError ? (
          <Card className="border-red-500/20 bg-red-500/5 shadow-none">
            <CardContent className="p-4 text-sm text-red-200">{errorMessage(q.error, 'Could not load skill packages.')}</CardContent>
          </Card>
        ) : null}

        {!q.isLoading && !q.isError && (q.data?.packages.length ?? 0) === 0 ? (
          <Card className="border-white/8 bg-white/[0.03] shadow-none">
            <CardContent className="flex min-h-52 flex-col items-center justify-center gap-3 p-6 text-center">
              <div className="rounded-2xl border border-white/8 bg-white/[0.04] p-4">
                <FolderKanban className="size-8 text-zinc-300" />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-medium text-white">No saved package folders yet.</p>
                <p className="text-sm text-zinc-500">Generate a package from Skill Pack Builder to create one here.</p>
              </div>
            </CardContent>
          </Card>
        ) : null}

        {!q.isLoading && !q.isError && (q.data?.packages.length ?? 0) > 0 ? (
          <section className="grid min-h-0 gap-4 lg:grid-cols-[minmax(18rem,24rem)_minmax(0,1fr)]">
            <div className="space-y-3">
              {q.data?.packages.map((pkg) => {
                const selected = pkg.package_name === selectedPackageName
                return (
                  <Card key={pkg.package_name} className={cn('border-white/8 bg-white/[0.035] shadow-none', selected && 'border-sky-400/40 bg-sky-500/10')}>
                    <CardHeader className="border-b border-white/8 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <button type="button" className="min-w-0 text-left" onClick={() => setSelectedPackageName(pkg.package_name)}>
                          <CardTitle className="truncate text-base text-white">{pkg.package_name}</CardTitle>
                          <CardDescription className="mt-1 text-zinc-500">Updated {formatModifiedAt(pkg.modified_at)}</CardDescription>
                        </button>
                        <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
                          {pkg.files.length} files
                        </Badge>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-4 p-4">
                      <button
                        type="button"
                        className="w-full rounded-lg border border-white/8 bg-black/20 p-3 text-left transition-colors hover:border-white/15 hover:bg-white/[0.04]"
                        onClick={() => setSelectedPackageName(pkg.package_name)}
                      >
                        <p className="mb-2 text-[11px] uppercase tracking-[0.16em] text-zinc-500">Files</p>
                        <div className="flex flex-wrap gap-2">
                          {orderedPackageFiles(pkg.files).map((filename) => {
                            const Icon = iconForFile(filename)
                            return (
                              <span key={filename} className="inline-flex items-center gap-1.5 rounded-md border border-white/8 bg-white/[0.03] px-2 py-1 text-xs text-zinc-200">
                                <Icon className="size-3 text-zinc-400" />
                                {filename}
                              </span>
                            )
                          })}
                        </div>
                      </button>
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="border-white/10 bg-white/[0.04] text-zinc-200"
                          onClick={() => void handleDownload(pkg.package_name)}
                          disabled={downloadingName === pkg.package_name}
                        >
                          <Download className="size-3.5" />
                          {downloadingName === pkg.package_name ? 'Downloading...' : 'Download'}
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="text-red-300 hover:bg-red-500/10 hover:text-red-200"
                          onClick={() => setPendingDelete(pkg)}
                        >
                          <Trash2 className="size-3.5" />
                          Delete
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>

            <Card className="min-w-0 border-white/8 bg-white/[0.035] shadow-none">
              <CardHeader className="border-b border-white/8">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <CardTitle className="truncate text-base text-white">{selectedPackageName ?? 'Package files'}</CardTitle>
                    <CardDescription className="mt-1 text-zinc-500">
                      {selectedPackage ? `Saved folder updated ${formatModifiedAt(selectedPackage.modified_at)}` : 'Select a package to inspect its files.'}
                    </CardDescription>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="border-white/10 bg-white/[0.04] text-zinc-200"
                      onClick={() => void handleCopyFile()}
                      disabled={!activeContent}
                    >
                      <Copy className="size-3.5" />
                      Copy
                    </Button>
                    {selectedPackageName ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="border-white/10 bg-white/[0.04] text-zinc-200"
                        onClick={() => void handleDownload(selectedPackageName)}
                        disabled={downloadingName === selectedPackageName}
                      >
                        <Download className="size-3.5" />
                        ZIP
                      </Button>
                    ) : null}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="min-w-0 p-4">
                {filesQ.isError ? (
                  <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-4 text-sm text-red-200">
                    {errorMessage(filesQ.error, 'Could not load package files.')}
                  </div>
                ) : null}

                {!filesQ.isError && visibleFiles.length > 0 ? (
                  <div className="space-y-4">
                    <Tabs value={activeFile ?? visibleFiles[0]} onValueChange={setActiveFile}>
                      <TabsList variant="line" className="h-auto flex-wrap justify-start bg-transparent p-0">
                        {visibleFiles.map((filename) => {
                          const Icon = iconForFile(filename)
                          return (
                            <TabsTrigger
                              key={filename}
                              value={filename}
                              className="rounded-lg border border-white/10 bg-white/[0.03] px-3 text-zinc-300 data-active:bg-white/[0.08] data-active:text-white"
                            >
                              <Icon className="size-3.5" />
                              {filename}
                            </TabsTrigger>
                          )
                        })}
                      </TabsList>
                    </Tabs>

                    <div className="min-h-[34rem] overflow-auto rounded-xl border border-white/8 bg-black/30">
                      {filesQ.isLoading || !filesQ.data ? (
                        <div className="flex min-h-[34rem] items-center justify-center text-sm text-zinc-500">Loading file contents...</div>
                      ) : (
                        <pre className="min-w-full whitespace-pre-wrap break-words p-4 font-mono text-xs leading-6 text-zinc-100">{activeContent}</pre>
                      )}
                    </div>
                  </div>
                ) : null}

                {!filesQ.isLoading && !filesQ.isError && visibleFiles.length === 0 ? (
                  <div className="flex min-h-[34rem] items-center justify-center rounded-xl border border-dashed border-white/10 bg-black/15 px-6 text-center text-sm text-zinc-500">
                    Select a package to view `skill.md`, `skill.json`, `inputs.json`, and `manifest.json`.
                  </div>
                ) : null}
              </CardContent>
            </Card>
          </section>
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
            <AlertDialogTitle>Delete package folder?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete
                ? `This will permanently delete ${pendingDelete.package_name} and its generated files.`
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
