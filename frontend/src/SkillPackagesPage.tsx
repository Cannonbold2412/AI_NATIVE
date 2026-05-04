'use client'

import { Fragment, useMemo, useState, type ComponentType, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiUrl } from '@/lib/apiBase'
import {
  deleteStoredSkillPackage,
  errorMessage,
  fetchSkillPackageFiles,
  fetchSkillPackageList,
  renameStoredSkillPackage,
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
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
  FolderKanban,
  FolderOpen,
  ImageIcon,
  Package,
  Pencil,
  RefreshCw,
  Search,
  Trash2,
} from 'lucide-react'

const ROOT_FILE_ORDER = ['package.json', 'index.js', 'skill.json', 'README.md', 'index.json']
const WORKFLOW_FILE_ORDER = ['skill.md', 'execution.json', 'recovery.json', 'inputs.json', 'manifest.json']
const ENGINE_FILES = [
  'execution.ts',
  'recovery.ts',
  'logging.ts',
  'config.ts',
]
const ENGINE_KEYS = ENGINE_FILES.map((f) => `engine/${f}`)
const ROW_TRANSITION = 'transition-colors duration-200 motion-reduce:transition-none'

const AGENT_PLUGIN_PREFIXES = ['.opencode/', '.claude/', '.codex/'] as const

function orderedSkillPackageKeys(keys: string[]): string[] {
  const set = new Set(keys)
  const head: string[] = []
  for (const k of ROOT_FILE_ORDER) if (set.has(k)) head.push(k)
  for (const k of ENGINE_KEYS) if (set.has(k)) head.push(k)

  const agentMid = [...keys]
    .filter((k) => AGENT_PLUGIN_PREFIXES.some((p) => k.startsWith(p)))
    .sort((a, b) => a.localeCompare(b))

  const workflowSlugs = [
    ...new Set(
      keys
        .map((k) => {
          const m = /^workflows\/([^/]+)\//.exec(k)
          return m ? m[1] : ''
        })
        .filter(Boolean),
    ),
  ].sort((a, b) => a.localeCompare(b))

  const mid: string[] = []
  for (const wf of workflowSlugs) {
    const prefix = `workflows/${wf}/`
    for (const wfFile of WORKFLOW_FILE_ORDER) {
      const kk = `${prefix}${wfFile}`
      if (set.has(kk)) mid.push(kk)
    }
    const visuals = [...keys].filter((k) => k.startsWith(`${prefix}visuals/`)).sort((a, b) => a.localeCompare(b))
    mid.push(...visuals)
  }

  const used = new Set([...head, ...agentMid, ...mid])
  const tail = [...keys].filter((k) => !used.has(k)).sort((a, b) => a.localeCompare(b))
  return [...head, ...agentMid, ...mid, ...tail]
}

type PathTrieNode = {
  segment: string
  /** Full relative path inside the package when this node is an on-disk leaf file key. */
  fileKey: string | null
  children: PathTrieNode[]
}

function getOrCreateTrieChild(parent: PathTrieNode, segment: string): PathTrieNode {
  let child = parent.children.find((c) => c.segment === segment)
  if (!child) {
    child = { segment, fileKey: null, children: [] }
    parent.children.push(child)
  }
  return child
}

/** Trie over relative paths — sibling order matches `orderedPaths` insertion order for stable UI. */
function buildPathTrie(orderedPaths: readonly string[]): PathTrieNode {
  const root: PathTrieNode = { segment: '', fileKey: null, children: [] }
  for (const key of orderedPaths) {
    const parts = key.split('/').filter((p) => p.length > 0)
    if (parts.length === 0) continue
    let cur = root
    for (let i = 0; i < parts.length; i++) {
      const segment = parts[i]!
      const child = getOrCreateTrieChild(cur, segment)
      cur = child
      if (i === parts.length - 1) {
        cur.fileKey = key
      }
    }
  }
  return root
}

function defaultSkillPackageActiveKey(keys: string[]): string | null {
  if (keys.length === 0) return null
  const ordered = orderedSkillPackageKeys(keys)
  const wfSkill =
    ordered.find((k) => k.endsWith('/skill.md')) ?? (ordered.includes('skill.md') ? 'skill.md' : null)
  return wfSkill ?? ordered[0] ?? null
}

function previewPathForKey(bundleRoot: string, bundleName: string, key: string | null): string {
  const base = `root/${bundleRoot}/${bundleName}`
  if (!key) return 'Select a file to preview'
  return `${base}/${key}`
}

function isImageVisualKey(key: string): boolean {
  return /\/visuals\/[^/]+\.(png|jpe?g|gif|webp)$/i.test(key)
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

function leafFileName(filename: string): string {
  return filename.includes('/') ? filename.slice(filename.lastIndexOf('/') + 1) : filename
}

function iconForFile(key: string): ComponentType<{ className?: string }> {
  if (key.includes('/visuals/')) return ImageIcon
  if (key.endsWith('.ts')) return FileCode2
  if (key.endsWith('.js')) return FileCode2
  if (key.endsWith('.md')) return FileText
  return FileJson
}

function labelForFile(filename: string) {
  const leaf = leafFileName(filename)
  if (filename.includes('/visuals/')) return 'Visual'
  if (leaf.endsWith('.ts')) return 'TypeScript'
  if (leaf.endsWith('.js')) return 'JavaScript'
  if (leaf.endsWith('.md')) return 'Markdown'
  if (leaf.endsWith('.json')) return 'JSON'
  return 'File'
}

function TreeItem({
  active = false,
  depth,
  icon: Icon,
  label,
  onClick,
}: {
  active?: boolean
  depth: number
  icon: ComponentType<{ className?: string }>
  label: string
  onClick?: () => void
}) {
  const className = cn(
    'flex w-full items-center gap-2 rounded-xl py-2 pr-2 text-left text-xs font-mono text-white',
    ROW_TRANSITION,
    active && 'bg-emerald-500/12 text-emerald-50',
    !active && 'text-white',
    onClick && 'cursor-pointer hover:bg-white/[0.05]',
    !onClick && 'cursor-default',
  )
  const content = (
    <>
      <Icon
        className={cn(
          'size-3.5 shrink-0',
          active ? 'text-emerald-300' : 'text-white/85',
        )}
      />
      <span className="min-w-0 flex-1 truncate">{label}</span>
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

function StructureTrieRows({
  nodes,
  depth,
  pathPrefix,
  activeFile,
  onPick,
}: {
  nodes: PathTrieNode[]
  depth: number
  pathPrefix: string
  activeFile: string | null
  onPick: (key: string) => void
}): ReactNode {
  return (
    <>
      {nodes.map((child) => {
        const childPath = pathPrefix ? `${pathPrefix}/${child.segment}` : child.segment
        const hasKids = child.children.length > 0
        const fileKey = child.fileKey

        if (hasKids && fileKey) {
          return (
            <Fragment key={childPath}>
              <TreeItem
                depth={depth}
                icon={iconForFile(fileKey)}
                label={child.segment}
                active={activeFile === fileKey}
                onClick={() => onPick(fileKey)}
              />
              <TreeItem depth={depth} icon={FolderOpen} label={`${child.segment}/`} />
              <StructureTrieRows
                nodes={child.children}
                depth={depth + 1}
                pathPrefix={childPath}
                activeFile={activeFile}
                onPick={onPick}
              />
            </Fragment>
          )
        }

        if (hasKids) {
          return (
            <Fragment key={`dir:${childPath}`}>
              <TreeItem depth={depth} icon={FolderOpen} label={`${child.segment}/`} />
              <StructureTrieRows
                nodes={child.children}
                depth={depth + 1}
                pathPrefix={childPath}
                activeFile={activeFile}
                onPick={onPick}
              />
            </Fragment>
          )
        }

        if (fileKey) {
          return (
            <TreeItem
              key={fileKey}
              depth={depth}
              icon={iconForFile(fileKey)}
              label={child.segment}
              active={activeFile === fileKey}
              onClick={() => onPick(fileKey)}
            />
          )
        }

        return null
      })}
    </>
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

function filenameFromContentDisposition(header: string | null): string | null {
  if (!header) return null
  const utf8 = /filename\*=UTF-8''([^;\s]+)/i.exec(header)
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1].trim())
    } catch {
      /* ignore */
    }
  }
  const quoted = /filename="([^"]+)"/i.exec(header)
  if (quoted?.[1]) return quoted[1]
  const plain = /filename=([^;\s]+)/i.exec(header)
  if (plain?.[1]) return plain[1].replace(/^"+|"+$/g, '')
  return null
}

async function downloadPackageFolder(packageName: string): Promise<string> {
  const response = await fetch(apiUrl(`/skill-pack/bundles/${encodeURIComponent(packageName)}/download`))
  if (!response.ok) {
    const raw = (await response.text()).trim()
    throw new Error(raw || 'Could not download package folder.')
  }
  const fallback = `${packageName}.zip`
  const filename =
    filenameFromContentDisposition(response.headers.get('Content-Disposition')) ?? fallback
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
  return filename
}

export function SkillPackagesPage() {
  const qc = useQueryClient()

  const [pendingRename, setPendingRename] = useState<SkillPackageSummary | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [isRenaming, setIsRenaming] = useState(false)
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
  const bundleRoot = q.data?.bundle_root ?? 'output/skill_package'
  const bundleRootDisplay = `root/${bundleRoot}`
  const searchNeedle = searchValue.trim().toLowerCase()
  const filteredPackages = useMemo(() => {
    if (!searchNeedle) return packages
    return packages.filter((pkg) => {
      const haystack = [
        pkg.package_name,
        ...pkg.workflows.flatMap((w) => [w.workflow_slug, w.display_label ?? '']),
        ...pkg.files,
      ]
        .join(' ')
        .toLowerCase()
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
  const packagePathTrie = useMemo(() => buildPathTrie(visibleFiles), [visibleFiles])
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
      const savedAs = await downloadPackageFolder(packageName)
      toast.success(`${savedAs} downloaded`)
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

  async function confirmRename() {
    if (!pendingRename || isRenaming) return
    const trimmed = renameValue.trim()
    if (!trimmed) {
      toast.error('Enter a package name.')
      return
    }
    const previous = pendingRename.package_name
    setIsRenaming(true)
    try {
      const { package_name: nextSlug } = await renameStoredSkillPackage(previous, trimmed)
      toast.success(`Renamed to ${nextSlug}`)
      setPendingRename(null)
      setRenameValue('')
      setSelectedPackageName(nextSlug)
      await qc.invalidateQueries({ queryKey: ['skillPackages'] })
      await qc.invalidateQueries({ queryKey: ['skillPackageFiles', previous] })
      await qc.invalidateQueries({ queryKey: ['skillPackageFiles', nextSlug] })
    } catch (err) {
      toast.error(errorMessage(err, 'Could not rename package.'))
    } finally {
      setIsRenaming(false)
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
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
            {bundleRootDisplay}/
          </Badge>
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
        </div>
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
                  <nav className="box-border w-full min-w-0 max-w-full px-2 pb-2 pt-2" aria-label="Skill package bundles">
                    <ul className="flex w-full min-w-0 max-w-full flex-col gap-1.5">
                      {filteredPackages.map((pkg) => {
                        const selected = pkg.package_name === resolvedSelectedPackageName
                        const busy = downloadingName === pkg.package_name
                        const wfCount = pkg.workflows.length
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
                                      {wfCount} workflow folder{wfCount === 1 ? '' : 's'} ·{' '}
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
                                    aria-label={`Rename ${pkg.package_name}`}
                                    className="cursor-pointer text-zinc-400 hover:bg-white/[0.08] hover:text-white"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      setPendingRename(pkg)
                                      setRenameValue(pkg.package_name)
                                    }}
                                  >
                                    <Pencil className="size-3.5" />
                                  </Button>
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
                    <div className="min-w-0 max-w-full">
                      <p className="max-w-full break-words text-base font-semibold leading-snug tracking-tight text-white [overflow-wrap:anywhere]">
                        {selectedPackage ? selectedPackage.package_name : resolvedSelectedPackageName ?? 'Inspector'}
                      </p>
                      {selectedPackage ? (
                        <>
                          <p className="mt-0.5 font-mono text-[11px] leading-snug text-zinc-400 [overflow-wrap:anywhere]">
                            {bundleRoot}/{selectedPackage.package_name}
                          </p>
                          <p className="mt-0.5 text-[11px] leading-snug text-zinc-500">
                            {selectedPackage.workflows.length} workflow folder
                            {selectedPackage.workflows.length === 1 ? '' : 's'}
                          </p>
                        </>
                      ) : null}
                    </div>
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
                          <div className="min-w-0 font-mono text-white">
                            <p className="text-xs font-medium">Structure</p>
                            <p className="mt-0.5 text-[10px] leading-relaxed text-white/70">
                              {visibleFiles.length} file{visibleFiles.length === 1 ? '' : 's'} under{' '}
                              <span className="text-white">{selectedPackage.package_name}/</span>
                            </p>
                          </div>
                          <div className="flex shrink-0 items-center gap-0.5">
                            <Badge
                              variant="outline"
                              className="border-white/10 bg-white/[0.04] px-1.5 py-0 text-[10px] text-white/80"
                              title="Named packages live under output/skill_package/<name>/."
                            >
                              {bundleRootDisplay}/
                            </Badge>
                          </div>
                        </div>

                        <ScrollArea className="min-h-0 flex-1">
                          <div className="space-y-0.5 rounded-lg border border-white/[0.06] bg-[#06080d] p-1.5 pb-3">
                            <TreeItem depth={0} icon={FolderOpen} label={`${selectedPackage.package_name}/`} />
                            <StructureTrieRows
                              nodes={packagePathTrie.children}
                              depth={1}
                              pathPrefix=""
                              activeFile={resolvedActiveFile}
                              onPick={setActiveFile}
                            />
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
                                  ? previewPathForKey(bundleRoot, resolvedSelectedPackageName, resolvedActiveFile)
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
            <DialogTitle>Rename package</DialogTitle>
            <DialogDescription className="text-zinc-400">
              {pendingRename
                ? `Renames ${bundleRoot}/${pendingRename.package_name} — slug is derived from the new name (e.g. spaces → underscores).`
                : ''}
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
              <label className="text-xs uppercase tracking-[0.16em] text-zinc-500" htmlFor="rename-skill-package-slug">
                Package name
              </label>
              <Input
                id="rename-skill-package-slug"
                value={renameValue}
                onChange={(event) => setRenameValue(event.target.value)}
                disabled={isRenaming}
                autoFocus
                placeholder={pendingRename?.package_name ?? ''}
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
