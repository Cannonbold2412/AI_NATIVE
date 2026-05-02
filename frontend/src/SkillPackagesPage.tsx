import { useMemo, useState, type ComponentType, type ReactNode } from 'react'
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
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import {
  Copy,
  Download,
  FileCode2,
  FileJson,
  FileText,
  Folder,
  FolderKanban,
  FolderOpen,
  ImageIcon,
  Package,
  RefreshCw,
  Search,
  Trash2,
} from 'lucide-react'

const ROOT_FILE_ORDER = ['README.md', 'index.json']
const WORKFLOW_FILE_ORDER = ['skill.md', 'execution.json', 'recovery.json', 'inputs.json', 'manifest.json']
const WORKFLOW_KEYS = new Set(WORKFLOW_FILE_ORDER)
const ENGINE_FILES = [
  'execution.ts',
  'recovery.ts',
  'logging.ts',
  'config.ts',
]
const ENGINE_KEYS = ENGINE_FILES.map((f) => `engine/${f}`)
const ROW_TRANSITION = 'transition-colors duration-200 motion-reduce:transition-none'

function orderedSkillPackageKeys(keys: string[]): string[] {
  const prio = [...ROOT_FILE_ORDER, ...ENGINE_KEYS, ...WORKFLOW_FILE_ORDER]
  const set = new Set(keys)
  const head = prio.filter((k) => set.has(k))
  const tail = [...keys].filter((k) => !head.includes(k)).sort((a, b) => a.localeCompare(b))
  return [...head, ...tail]
}

function defaultSkillPackageActiveKey(keys: string[]): string | null {
  if (keys.length === 0) return null
  const ordered = orderedSkillPackageKeys(keys)
  for (const wf of WORKFLOW_FILE_ORDER) {
    if (ordered.includes(wf)) return wf
  }
  return ordered[0]
}

function previewPathForKey(packageName: string, key: string | null): string {
  if (!key) return 'Select a file to preview'
  if (key === 'README.md') return 'skill_package/README.md'
  if (key === 'index.json') return 'skill_package/index.json'
  if (key.startsWith('engine/')) return `skill_package/${key}`
  if (key.startsWith('visuals/')) return `skill_package/workflows/${packageName}/${key}`
  return `skill_package/workflows/${packageName}/${key}`
}

function isImageVisualKey(key: string): boolean {
  return (
    key.startsWith('visuals/') &&
    /\.(png|jpe?g|gif|webp)$/i.test(key.slice(key.lastIndexOf('/') + 1))
  )
}

function imageMimeFromKey(key: string): string {
  const base = key.slice(key.lastIndexOf('/') + 1).toLowerCase()
  if (base.endsWith('.png')) return 'image/png'
  if (base.endsWith('.jpg') || base.endsWith('.jpeg')) return 'image/jpeg'
  if (base.endsWith('.gif')) return 'image/gif'
  if (base.endsWith('.webp')) return 'image/webp'
  return 'application/octet-stream'
}

function base64DecodedBytes(b64: string): number {
  try {
    return atob(b64).length
  } catch {
    return 0
  }
}

function formatModifiedAt(value: number) {
  return new Date(value * 1000).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

function iconForFile(filename: string): ComponentType<{ className?: string }> {
  if (filename.startsWith('visuals/')) return ImageIcon
  if (filename.endsWith('.ts')) return FileCode2
  if (filename.endsWith('.md')) return FileText
  return FileJson
}

function labelForFile(filename: string) {
  if (filename.startsWith('visuals/')) return 'Visual'
  if (filename.endsWith('.ts')) return 'TypeScript'
  if (filename.endsWith('.md')) return 'Markdown'
  if (filename.endsWith('.json')) return 'JSON'
  return 'File'
}

function isWorkflowScopedKey(key: string): boolean {
  if (key.startsWith('visuals/')) return true
  return WORKFLOW_KEYS.has(key)
}

function TreeItem({
  active = false,
  depth,
  icon: Icon,
  label,
  muted = false,
  onClick,
  suffix,
}: {
  active?: boolean
  depth: number
  icon: ComponentType<{ className?: string }>
  label: string
  muted?: boolean
  onClick?: () => void
  suffix?: string
}) {
  const className = cn(
    'flex w-full items-center gap-2 rounded-xl py-2 pr-2 text-left text-xs',
    ROW_TRANSITION,
    active && 'bg-emerald-500/12 text-emerald-50',
    !active && !muted && 'text-zinc-200',
    muted && 'text-zinc-500',
    onClick && 'cursor-pointer hover:bg-white/[0.05] hover:text-white',
    !onClick && 'cursor-default',
  )
  const content = (
    <>
      <Icon
        className={cn(
          'size-3.5 shrink-0',
          active ? 'text-emerald-300' : muted ? 'text-zinc-600' : 'text-zinc-400',
        )}
      />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {suffix ? (
        <span className="shrink-0 text-[10px] uppercase tracking-[0.14em] text-zinc-600">{suffix}</span>
      ) : null}
    </>
  )
  const style = { paddingLeft: `${0.8 + depth * 1.05}rem` }

  if (onClick) {
    return (
      <button type="button" className={className} style={style} onClick={onClick}>
        {content}
      </button>
    )
  }

  return (
    <div className={className} style={style}>
      {content}
    </div>
  )
}

function PanelChrome({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        'flex min-h-0 min-w-0 flex-col rounded-[1.5rem] border border-white/10 bg-[linear-gradient(180deg,rgba(17,24,39,0.94),rgba(7,10,16,0.98))] shadow-[0_20px_60px_rgba(0,0,0,0.28)] ring-1 ring-white/[0.04]',
        className,
      )}
    >
      {children}
    </div>
  )
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
  anchor.download = `skill_package_${packageName}.zip`
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
  const [searchValue, setSearchValue] = useState('')

  const q = useQuery({
    queryKey: ['skillPackages'],
    queryFn: fetchSkillPackageList,
    staleTime: 30_000,
  })

  const packages = useMemo(() => q.data?.packages ?? [], [q.data?.packages])
  const searchNeedle = searchValue.trim().toLowerCase()
  const filteredPackages = useMemo(() => {
    if (!searchNeedle) return packages
    return packages.filter((pkg) => {
      const haystack = [pkg.package_name, ...pkg.files].join(' ').toLowerCase()
      return haystack.includes(searchNeedle)
    })
  }, [packages, searchNeedle])
  const resolvedSelectedPackageName = useMemo(() => {
    if (filteredPackages.length === 0) return null
    if (selectedPackageName && filteredPackages.some((pkg) => pkg.package_name === selectedPackageName)) {
      return selectedPackageName
    }
    return filteredPackages[0].package_name
  }, [filteredPackages, selectedPackageName])
  const filesQ = useQuery({
    queryKey: ['skillPackageFiles', resolvedSelectedPackageName],
    queryFn: () => fetchSkillPackageFiles(resolvedSelectedPackageName ?? ''),
    enabled: resolvedSelectedPackageName !== null,
    staleTime: 30_000,
  })

  const selectedPackage = useMemo(
    () => packages.find((pkg) => pkg.package_name === resolvedSelectedPackageName) ?? null,
    [packages, resolvedSelectedPackageName],
  )
  const visibleFiles = useMemo(() => {
    if (filesQ.data) return orderedSkillPackageKeys(Object.keys(filesQ.data.files))
    if (selectedPackage) return orderedSkillPackageKeys(selectedPackage.files)
    return []
  }, [filesQ.data, selectedPackage])
  const resolvedActiveFile = useMemo(() => {
    if (visibleFiles.length === 0) return null
    if (activeFile && visibleFiles.includes(activeFile)) return activeFile
    return defaultSkillPackageActiveKey(visibleFiles)
  }, [activeFile, visibleFiles])
  const activeSource =
    resolvedActiveFile && filesQ.data ? filesQ.data.files[resolvedActiveFile] ?? '' : ''
  const activeIsImage = resolvedActiveFile ? isImageVisualKey(resolvedActiveFile) : false
  const activeContent = activeIsImage ? '' : activeSource
  const activeLineCount = activeContent ? activeContent.split('\n').length : 0
  const activeSize = activeSource
    ? activeIsImage
      ? base64DecodedBytes(activeSource)
      : new Blob([activeSource]).size
    : 0
  async function handleDownload(packageName: string) {
    setDownloadingName(packageName)
    try {
      await downloadPackageFolder(packageName)
      toast.success(`skill_package_${packageName}.zip downloaded`)
    } catch (err) {
      toast.error(errorMessage(err, 'Could not download package folder.'))
    } finally {
      setDownloadingName(null)
    }
  }

  async function handleCopyFile() {
    if (!resolvedActiveFile || !activeSource || activeIsImage) return
    try {
      await navigator.clipboard.writeText(activeSource)
      toast.success(`${resolvedActiveFile} copied`)
    } catch {
      toast.error(`Could not copy ${resolvedActiveFile}`)
    }
  }

  async function confirmDelete() {
    if (!pendingDelete || isDeleting) return
    const name = pendingDelete.package_name
    setIsDeleting(true)
    try {
      await deleteStoredSkillPackage(name)
      toast.success(`${name} deleted`)
      setPendingDelete(null)
      await qc.invalidateQueries({ queryKey: ['skillPackages'] })
      await qc.invalidateQueries({ queryKey: ['skillPackageFiles', name] })
    } catch (err) {
      toast.error(errorMessage(err, 'Could not delete package folder.'))
    } finally {
      setIsDeleting(false)
    }
  }

  const pkgCount = packages.length

  return (
    <AppShell
      title="Skill packages"
      description="Review generated workflow bundles, inspect the file set, and export ZIP archives from one production-ready workspace."
      mainClassName="min-w-0 overflow-x-hidden overflow-y-auto"
      actions={
        <Button
          type="button"
          variant="outline"
          size="sm"
          className={cn(
            'cursor-pointer border-white/10 bg-white/[0.04] text-zinc-200',
            ROW_TRANSITION,
            'hover:bg-white/[0.08]',
          )}
          onClick={() => void q.refetch()}
          disabled={q.isFetching}
        >
          <RefreshCw className={cn('size-3.5', q.isFetching && 'animate-spin motion-reduce:animate-none')} />
          Refresh
        </Button>
      }
    >
      <div className="mx-auto flex w-full min-w-0 max-w-7xl flex-col gap-3 px-3 py-3 sm:px-4 sm:py-4">
        {q.isLoading ? (
          <div className="flex min-h-[min(640px,calc(100vh-9rem))] min-w-0 flex-col gap-3 md:flex-row md:items-stretch">
            <PanelChrome className="w-full shrink-0 p-3 md:w-[15rem] lg:w-[18rem]">
              <Skeleton className="h-9 rounded-lg bg-white/[0.06]" />
              <div className="mt-3 space-y-2">
                {Array.from({ length: 5 }).map((_, index) => (
                  <Skeleton key={index} className="h-14 rounded-xl bg-white/[0.06]" />
                ))}
              </div>
            </PanelChrome>
            <PanelChrome className="min-h-0 min-w-0 flex-1 overflow-hidden p-3">
              <Skeleton className="h-7 w-48 rounded bg-white/[0.08]" />
              <Skeleton className="mt-3 h-2 w-full rounded bg-white/[0.06]" />
              <div className="mt-3 grid gap-2 2xl:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
                <Skeleton className="min-h-[14rem] rounded-xl bg-white/[0.05]" />
                <Skeleton className="min-h-[20rem] rounded-xl bg-white/[0.05]" />
              </div>
            </PanelChrome>
          </div>
        ) : null}

        {q.isError ? (
          <Card className="rounded-[1.5rem] border-red-500/25 bg-red-500/[0.06] shadow-none">
            <CardContent className="p-5 text-sm text-red-100">
              {errorMessage(q.error, 'Could not load skill packages.')}
            </CardContent>
          </Card>
        ) : null}

        {!q.isLoading && !q.isError && pkgCount === 0 ? (
          <PanelChrome className="items-center justify-center py-18 text-center">
            <div className="flex max-w-md flex-col items-center gap-4 px-6">
              <div className="rounded-[1.4rem] border border-white/10 bg-white/[0.04] p-5">
                <FolderKanban className="mx-auto size-10 text-zinc-300" aria-hidden />
              </div>
              <div className="space-y-2">
                <p className="text-lg font-semibold tracking-tight text-white">No packages yet</p>
                <p className="text-sm leading-relaxed text-zinc-500">
                  Generate a package in Skill Pack Builder. Saved workflow bundles appear here for review, validation, and ZIP export.
                </p>
              </div>
            </div>
          </PanelChrome>
        ) : null}

        {!q.isLoading && !q.isError && pkgCount > 0 ? (
          <section className="flex min-h-[min(640px,calc(100vh-9rem))] min-w-0 flex-col gap-3 md:flex-row md:items-stretch">
            <PanelChrome className="w-full shrink-0 overflow-hidden md:max-w-[15rem] md:w-[min(100%,15rem)] lg:max-w-[18rem] lg:w-[min(100%,18rem)]">
              <div className="border-b border-white/10 px-3 py-2.5">
                <div className="flex items-center gap-2">
                  <div className="relative min-w-0 flex-1">
                    <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-zinc-500" />
                    <Input
                      value={searchValue}
                      onChange={(event) => setSearchValue(event.target.value)}
                      placeholder="Search…"
                      className="h-9 border-white/10 bg-white/[0.05] py-2 pl-8 text-sm text-zinc-100 placeholder:text-zinc-500"
                      aria-label="Search packages or files"
                    />
                  </div>
                  {searchNeedle ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-9 shrink-0 cursor-pointer px-2 text-xs text-zinc-400 hover:bg-white/[0.06] hover:text-white"
                      onClick={() => setSearchValue('')}
                    >
                      Clear
                    </Button>
                  ) : null}
                </div>
              </div>

              <ScrollArea className="min-h-0 min-w-0 max-w-full flex-1 [&_[data-slot=scroll-area-viewport]]:max-w-full [&_[data-slot=scroll-area-viewport]]:!overflow-x-hidden [&_[data-slot=scroll-area-viewport]]:!overflow-y-auto">
                {filteredPackages.length === 0 ? (
                  <div className="flex h-full min-h-[16rem] flex-col items-center justify-center px-3 text-center">
                    <div className="rounded-xl border border-white/10 bg-white/[0.04] p-3">
                      <Search className="size-4 text-zinc-300" />
                    </div>
                    <p className="mt-3 text-sm font-medium text-white">No matching packages</p>
                    <p className="mt-1.5 max-w-xs text-xs leading-relaxed text-zinc-500">
                      Try a different term — search includes file names inside each package.
                    </p>
                  </div>
                ) : (
                  <nav className="box-border w-full min-w-0 max-w-full p-2" aria-label="Saved skill packages">
                    <ul className="flex w-full min-w-0 max-w-full flex-col gap-1.5">
                      {filteredPackages.map((pkg) => {
                        const selected = pkg.package_name === resolvedSelectedPackageName
                        const busy = downloadingName === pkg.package_name
                        return (
                          <li key={pkg.package_name} className="w-full min-w-0 max-w-full">
                            <div
                              className={cn(
                                'group box-border w-full min-w-0 max-w-full overflow-hidden rounded-xl border p-1',
                                ROW_TRANSITION,
                                selected
                                  ? 'border-emerald-500/25 bg-emerald-500/[0.08] shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]'
                                  : 'border-white/8 bg-white/[0.02] hover:border-white/12 hover:bg-white/[0.04]',
                              )}
                            >
                              <div className="flex max-w-full min-w-0 items-start gap-1">
                                <button
                                  type="button"
                                  onClick={() => setSelectedPackageName(pkg.package_name)}
                                  className={cn(
                                    'flex min-h-0 min-w-0 max-w-full flex-1 cursor-pointer items-start gap-1.5 rounded-lg px-1.5 py-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50',
                                    ROW_TRANSITION,
                                  )}
                                  aria-current={selected ? 'true' : undefined}
                                >
                                  <div
                                    className={cn(
                                      'mt-0.5 rounded-lg border p-1.5',
                                      selected ? 'border-emerald-500/25 bg-emerald-500/10' : 'border-white/10 bg-black/20',
                                    )}
                                  >
                                    <Package
                                      className={cn(
                                        'size-3.5 shrink-0',
                                        selected ? 'text-emerald-300' : 'text-zinc-400 group-hover:text-zinc-200',
                                      )}
                                      aria-hidden
                                    />
                                  </div>
                                  <span className="min-w-0 flex-1 overflow-hidden">
                                    <span className="block break-words text-sm font-medium leading-snug text-white [overflow-wrap:anywhere]">
                                      {pkg.package_name}
                                    </span>
                                    <span className="mt-0.5 block text-[11px] text-zinc-500">
                                      {formatModifiedAt(pkg.modified_at)}
                                    </span>
                                    <span className="mt-1.5 flex flex-wrap gap-1.5">
                                      <Badge
                                        variant="outline"
                                        className="border-white/10 bg-white/[0.04] text-[11px] text-zinc-300"
                                      >
                                        {pkg.files.length} file{pkg.files.length === 1 ? '' : 's'}
                                      </Badge>
                                    </span>
                                  </span>
                                </button>

                                <div className="flex shrink-0 flex-col justify-center gap-0.5 pt-0.5">
                                  <Button
                                    type="button"
                                    size="icon-sm"
                                    variant="ghost"
                                    aria-label={`Download ${pkg.package_name}`}
                                    className="cursor-pointer text-zinc-400 hover:bg-white/[0.08] hover:text-white"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      void handleDownload(pkg.package_name)
                                    }}
                                    disabled={busy}
                                  >
                                    <Download className="size-3.5" />
                                  </Button>
                                  <Button
                                    type="button"
                                    size="icon-sm"
                                    variant="ghost"
                                    aria-label={`Delete ${pkg.package_name}`}
                                    className="cursor-pointer text-zinc-500 hover:bg-red-500/15 hover:text-red-300"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      setPendingDelete(pkg)
                                    }}
                                  >
                                    <Trash2 className="size-3.5" />
                                  </Button>
                                </div>
                              </div>
                            </div>
                          </li>
                        )
                      })}
                    </ul>
                  </nav>
                )}
              </ScrollArea>
            </PanelChrome>

            <PanelChrome className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
              <div className="shrink-0 border-b border-white/10 px-3 py-2.5 sm:px-4">
                <div className="flex flex-wrap items-start justify-between gap-2 gap-y-2">
                  <div className="min-w-0 flex flex-wrap items-center gap-2">
                    <p className="max-w-full break-words text-base font-semibold leading-snug tracking-tight text-white [overflow-wrap:anywhere]">
                      {resolvedSelectedPackageName ?? 'Inspector'}
                    </p>
                    {resolvedActiveFile ? (
                      <Badge variant="outline" className="border-white/10 bg-white/[0.05] text-xs text-zinc-300">
                        {labelForFile(resolvedActiveFile)}
                      </Badge>
                    ) : null}
                    {selectedPackage ? (
                      <span className="text-[11px] text-zinc-500">
                        {formatModifiedAt(selectedPackage.modified_at)}
                        {resolvedActiveFile
                          ? activeIsImage
                            ? ` · ${formatBytes(activeSize)}`
                            : ` · ${activeLineCount} lines · ${formatBytes(activeSize)}`
                          : ''}
                      </span>
                    ) : null}
                  </div>

                  <div className="flex shrink-0 flex-wrap gap-1.5">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className={cn(
                        'h-8 cursor-pointer border-white/10 bg-white/[0.04] px-2.5 text-xs text-zinc-200',
                        ROW_TRANSITION,
                        'hover:bg-white/[0.08]',
                      )}
                      onClick={() => void handleCopyFile()}
                      disabled={!activeSource || activeIsImage}
                    >
                      <Copy className="size-3" />
                      Copy
                    </Button>
                    {resolvedSelectedPackageName ? (
                      <Button
                        type="button"
                        size="sm"
                        className={cn(
                          'h-8 cursor-pointer border-emerald-500/35 bg-emerald-600/[0.2] px-2.5 text-xs text-emerald-50',
                          ROW_TRANSITION,
                          'hover:bg-emerald-600/30',
                        )}
                        disabled={downloadingName === resolvedSelectedPackageName}
                        onClick={() => void handleDownload(resolvedSelectedPackageName)}
                      >
                        <Download className="size-3" />
                        {downloadingName === resolvedSelectedPackageName ? 'ZIP…' : 'ZIP'}
                      </Button>
                    ) : null}
                  </div>
                </div>
              </div>

              <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-2 sm:p-3">
                {filesQ.isError ? (
                  <div className="rounded-2xl border border-red-500/25 bg-red-500/[0.06] p-4 text-sm text-red-100">
                    {errorMessage(filesQ.error, 'Could not load package files.')}
                  </div>
                ) : null}

                {!filesQ.isError && selectedPackage && visibleFiles.length > 0 ? (
                  <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                    <div
                      className={cn(
                        'grid min-h-0 flex-1 gap-2 overflow-hidden',
                        'grid-cols-1 grid-rows-[auto_minmax(0,1fr)]',
                        '2xl:grid-cols-[minmax(0,15rem)_minmax(0,1fr)] 2xl:grid-rows-none 2xl:min-h-[14rem]',
                      )}
                    >
                      <div className="flex min-h-[8rem] max-h-[min(38vh,15rem)] min-w-0 flex-col overflow-hidden rounded-xl border border-white/10 bg-black/20 p-2 2xl:max-h-none 2xl:min-h-0">
                        <div className="mb-2 flex shrink-0 items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="text-xs font-medium text-white">Structure</p>
                            <p className="mt-0.5 text-[10px] leading-relaxed text-zinc-500">Engine + workflow files.</p>
                          </div>
                          <Badge variant="outline" className="shrink-0 border-white/10 bg-white/[0.04] px-1.5 py-0 text-[10px] text-zinc-300">
                            skill_package/
                          </Badge>
                        </div>

                        <ScrollArea className="min-h-0 flex-1">
                          <div className="space-y-0.5 rounded-lg border border-white/[0.06] bg-[#06080d] p-1.5 font-mono pb-3">
                          <TreeItem depth={0} icon={FolderOpen} label="skill_package/" />
                          {visibleFiles.includes('README.md') ? (
                            <TreeItem
                              depth={1}
                              icon={FileText}
                              label="README.md"
                              active={resolvedActiveFile === 'README.md'}
                              onClick={() => setActiveFile('README.md')}
                              suffix="root"
                            />
                          ) : null}
                          {visibleFiles.includes('index.json') ? (
                            <TreeItem
                              depth={1}
                              icon={FileJson}
                              label="index.json"
                              active={resolvedActiveFile === 'index.json'}
                              onClick={() => setActiveFile('index.json')}
                              suffix="root"
                            />
                          ) : null}
                          <TreeItem depth={1} icon={FolderOpen} label="engine/" />
                          {ENGINE_KEYS.filter((engineKey) => visibleFiles.includes(engineKey)).map((engineKey) => {
                            const base = engineKey.slice('engine/'.length)
                            return (
                              <TreeItem
                                key={engineKey}
                                depth={2}
                                icon={FileCode2}
                                label={base}
                                active={resolvedActiveFile === engineKey}
                                onClick={() => setActiveFile(engineKey)}
                                suffix="engine"
                              />
                            )
                          })}
                          <TreeItem depth={1} icon={FolderOpen} label="workflows/" />
                          {filteredPackages.map((pkg) => {
                            const isSelected = pkg.package_name === resolvedSelectedPackageName
                            if (!isSelected) {
                              return (
                                <TreeItem
                                  key={pkg.package_name}
                                  depth={2}
                                  icon={Folder}
                                  label={`${pkg.package_name}/`}
                                  onClick={() => setSelectedPackageName(pkg.package_name)}
                                  suffix="workflow"
                                />
                              )
                            }
                            const workflowKeys = orderedSkillPackageKeys(visibleFiles.filter(isWorkflowScopedKey))
                            const defs = workflowKeys.filter((k) => !k.startsWith('visuals/'))
                            const visualKeys = workflowKeys.filter((k) => k.startsWith('visuals/'))
                            return (
                              <div key={pkg.package_name}>
                                <TreeItem depth={2} icon={FolderOpen} label={`${pkg.package_name}/`} />
                                {defs.map((filename) => {
                                  const Icon = iconForFile(filename)
                                  return (
                                    <TreeItem
                                      key={filename}
                                      active={resolvedActiveFile === filename}
                                      depth={3}
                                      icon={Icon}
                                      label={filename}
                                      onClick={() => setActiveFile(filename)}
                                      suffix="open"
                                    />
                                  )
                                })}
                                {visualKeys.length > 0 ? (
                                  <>
                                    <TreeItem depth={3} icon={Folder} label="visuals/" />
                                    {visualKeys.map((key) => {
                                      const name = key.slice('visuals/'.length)
                                      const Icon = iconForFile(key)
                                      return (
                                        <TreeItem
                                          key={key}
                                          depth={4}
                                          active={resolvedActiveFile === key}
                                          icon={Icon}
                                          label={name}
                                          onClick={() => setActiveFile(key)}
                                          suffix="visual"
                                        />
                                      )
                                    })}
                                  </>
                                ) : null}
                              </div>
                            )
                          })}
                          </div>
                        </ScrollArea>
                      </div>

                      <div className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border border-white/10 bg-[#05070c]">
                        <div className="shrink-0 border-b border-white/10 px-2.5 py-2">
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium text-white">{resolvedActiveFile ?? 'File preview'}</p>
                              <p className="mt-1 text-xs text-zinc-500">
                                {resolvedSelectedPackageName
                                  ? previewPathForKey(resolvedSelectedPackageName, resolvedActiveFile)
                                  : 'Select a file to preview'}
                              </p>
                            </div>
                            {resolvedActiveFile ? (
                              <div className="flex flex-wrap gap-2">
                                <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
                                  {labelForFile(resolvedActiveFile)}
                                </Badge>
                                {activeIsImage ? null : (
                                  <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
                                    {activeLineCount} lines
                                  </Badge>
                                )}
                                <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
                                  {formatBytes(activeSize)}
                                </Badge>
                              </div>
                            ) : null}
                          </div>
                        </div>

                        {filesQ.isLoading || !filesQ.data ? (
                          <div className="flex min-h-[12rem] flex-1 items-center justify-center text-sm text-zinc-500">
                            Loading contents...
                          </div>
                        ) : (
                          <ScrollArea className="min-h-0 flex-1">
                            {activeIsImage && resolvedActiveFile ? (
                              <div className="flex justify-center p-3 sm:p-4">
                                <img
                                  src={`data:${imageMimeFromKey(resolvedActiveFile)};base64,${activeSource}`}
                                  alt=""
                                  className="max-h-[min(60vh,32rem)] max-w-full rounded-lg border border-white/10 object-contain shadow-lg"
                                />
                              </div>
                            ) : (
                              <pre className="min-w-full whitespace-pre-wrap break-words p-2.5 font-mono text-xs leading-relaxed text-zinc-100 sm:p-3">
                                {activeContent}
                              </pre>
                            )}
                          </ScrollArea>
                        )}
                      </div>
                    </div>
                  </div>
                ) : null}

                {!filesQ.isLoading && !filesQ.isError && pkgCount > 0 && filteredPackages.length === 0 ? (
                  <div className="flex min-h-[20rem] items-center justify-center rounded-2xl border border-dashed border-white/10 bg-black/20 px-6 text-center text-sm text-zinc-500">
                    No package matches the current search query.
                  </div>
                ) : null}

                {!filesQ.isLoading && !filesQ.isError && filteredPackages.length > 0 && visibleFiles.length === 0 ? (
                  <div className="flex min-h-[20rem] items-center justify-center rounded-2xl border border-dashed border-white/10 bg-black/20 px-6 text-center text-sm text-zinc-500">
                    Select a package to browse `index.json`, `skill.md`, `execution.json`, `recovery.json`, `inputs.json`, and `manifest.json`.
                  </div>
                ) : null}
              </div>
            </PanelChrome>
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
            <AlertDialogTitle>Delete this package?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete
                ? `This permanently removes "${pendingDelete.package_name}" and its generated workflow files from storage.`
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
