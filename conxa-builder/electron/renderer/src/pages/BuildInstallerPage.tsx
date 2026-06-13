import { Fragment, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  buildInstaller,
  fetchPlugins,
  normalizePluginList,
  type InstallerBuildResult,
  type Plugin,
} from '@/api/pluginApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { EntitlementMeters } from '@/components/EntitlementMeters'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Check,
  CheckCircle2,
  Copy,
  Download,
  FileText,
  Globe,
  HardDrive,
  ImagePlus,
  Loader2,
  PackageCheck,
  X,
  XCircle,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const SEMVER_RE = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/

const ERROR_MESSAGES: Record<string, string> = {
  installer_upload_too_large: 'Installer too large for cloud hosting (max 250 MB). Reduce included assets and retry.',
  installer_not_found: 'Installer file not found. Re-run the build step.',
  cloud_auth_error: 'Cloud authentication failed. Sign in again and retry.',
}

function humanizeError(msg: string): string {
  for (const [code, human] of Object.entries(ERROR_MESSAGES)) {
    if (msg.includes(code)) return human
  }
  return msg
}

function packageNameFromOutputPath(outputPath?: string | null): string {
  if (!outputPath) return 'No package'
  const leaf = outputPath.split(/[\\/]+/).filter(Boolean).pop() ?? outputPath
  return leaf.endsWith('-plugin') ? leaf.slice(0, -'-plugin'.length) : leaf
}

function installerStatus(
  plugin: Plugin | null,
  result: InstallerBuildResult | null,
  activePluginId: string | null,
  building: boolean,
) {
  if (!plugin) return 'Select package'
  if (building && activePluginId === plugin.id) return 'Building'
  if (result?.plugin_id === plugin.id || plugin.installer) return 'Complete'
  return 'Not built'
}

function getLogLineStyle(line: string): string {
  const l = line.toLowerCase()
  if (l.includes('error') || l.includes('fail') || l.includes('exception') || l.includes('traceback'))
    return 'text-red-400'
  if (l.includes('warn')) return 'text-amber-400'
  if (
    l.includes('✓') ||
    l.includes('success') ||
    l.includes('complete') ||
    l.includes('done') ||
    l.includes('finished')
  )
    return 'text-emerald-400'
  if (l.includes('upload') || l.includes('publish') || l.includes('cloud')) return 'text-sky-400'
  if (l.includes('build') || l.includes('pack') || l.includes('compil')) return 'text-violet-300'
  return 'text-zinc-400'
}

const PIPELINE_STAGES = ['Build Installer', 'Upload to Cloud', 'Publish Release'] as const

function inferPipelineStage(logs: string[], done: boolean, hasError: boolean): number {
  if (done && !hasError) return 3
  const all = logs.join('\n').toLowerCase()
  if (all.includes('publish') || all.includes('release')) return 2
  if (all.includes('upload') || all.includes('uploading')) return 1
  if (logs.length > 0) return 0
  return -1
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  function handleCopy() {
    void navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button
      type="button"
      onClick={handleCopy}
      className="ml-2 shrink-0 rounded p-1 text-zinc-500 transition-colors hover:bg-white/8 hover:text-zinc-300"
      aria-label="Copy to clipboard"
    >
      {copied ? <Check className="size-3.5 text-emerald-400" /> : <Copy className="size-3.5" />}
    </button>
  )
}

function ResultCard({
  icon,
  label,
  value,
  href,
}: {
  icon: React.ReactNode
  label: string
  value: string
  href?: string
}) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2.5">
      <div className="mt-0.5 shrink-0 text-zinc-500">{icon}</div>
      <div className="min-w-0 flex-1">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">{label}</p>
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-0.5 block break-all font-mono text-[11px] text-sky-400 underline-offset-2 hover:underline"
          >
            {value}
          </a>
        ) : (
          <p className="mt-0.5 break-all font-mono text-[11px] text-zinc-300">{value}</p>
        )}
      </div>
      <CopyButton text={value} />
    </div>
  )
}

export function BuildInstallerPage() {
  const pluginsQ = useQuery({
    queryKey: ['plugins'],
    queryFn: fetchPlugins,
    staleTime: 30_000,
  })

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [activePluginId, setActivePluginId] = useState<string | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [building, setBuilding] = useState(false)
  const [installerError, setInstallerError] = useState('')
  const [installerDone, setInstallerDone] = useState(false)
  const [installerResult, setInstallerResult] = useState<InstallerBuildResult | null>(null)
  const [logoPath, setLogoPath] = useState<string | null>(null)
  const [releaseDialogOpen, setReleaseDialogOpen] = useState(false)
  const [releaseVersion, setReleaseVersion] = useState('')
  const [releaseNotes, setReleaseNotes] = useState('')
  const logRef = useRef<HTMLDivElement>(null)

  const plugins = useMemo(() => normalizePluginList(pluginsQ.data), [pluginsQ.data])
  const builtPlugins = useMemo(() => plugins.filter((p) => p.build), [plugins])
  const allTestsPassed = (plugin: { workflows: { last_test_status: string }[] }) =>
    plugin.workflows.length > 0 && plugin.workflows.every((w) => w.last_test_status === 'passed')
  const readyPlugins = useMemo(() => builtPlugins.filter(allTestsPassed), [builtPlugins])
  const selectedPlugin = useMemo(() => {
    if (builtPlugins.length === 0) return null
    if (selectedId) {
      const found = builtPlugins.find((p) => p.id === selectedId)
      if (found) return found
    }
    return readyPlugins[0] ?? builtPlugins[0] ?? null
  }, [builtPlugins, readyPlugins, selectedId])

  const currentResult = installerResult?.plugin_id === selectedPlugin?.id ? installerResult : null
  const selectedStatus = installerStatus(selectedPlugin, currentResult, activePluginId, building)
  const installerReady = Boolean(currentResult || selectedPlugin?.installer)
  const selectedPluginTestsOk = selectedPlugin ? allTestsPassed(selectedPlugin) : false
  const untestedCount = selectedPlugin
    ? selectedPlugin.workflows.filter((w) => w.last_test_status !== 'passed').length
    : 0
  const installerOutputPath = currentResult?.installer_path ?? selectedPlugin?.installer?.installer_path
  const activeLogs = activePluginId === selectedPlugin?.id ? logs : []
  const activeError = activePluginId === selectedPlugin?.id ? installerError : ''
  const activeDone = activePluginId === selectedPlugin?.id ? installerDone : false
  const buildingSelected = building && activePluginId === selectedPlugin?.id
  const canBuild = selectedPluginTestsOk && Boolean(logoPath) && !buildingSelected
  const releaseVersionValue = releaseVersion.trim()
  const releaseNotesValue = releaseNotes.trim()
  const releaseVersionValid = SEMVER_RE.test(releaseVersionValue)
  const releaseNotesValid = releaseNotesValue.length > 0 && releaseNotesValue.length <= 2000
  const canConfirmReleaseBuild = canBuild && releaseVersionValid && releaseNotesValid

  const pipelineStage = inferPipelineStage(activeLogs, activeDone, Boolean(activeError))
  const showPipeline = buildingSelected || activeDone || Boolean(activeError)

  function selectPlugin(pluginId: string) {
    setSelectedId(pluginId)
    setInstallerError('')
    setInstallerDone(false)
    setInstallerResult(null)
    setLogs([])
    setActivePluginId(null)
    setReleaseDialogOpen(false)
  }

  async function handlePickLogo() {
    const picked = await window.conxa.pickFile([
      { name: 'Images', extensions: ['png', 'jpg', 'jpeg', 'ico'] },
    ])
    if (picked) setLogoPath(picked)
  }

  function handleClearLogo() {
    setLogoPath(null)
  }

  function handleOpenReleaseDialog() {
    if (!selectedPlugin || !canBuild) return
    setReleaseVersion(
      selectedPlugin.build?.version || selectedPlugin.installer?.version || '0.1.0',
    )
    setReleaseNotes('')
    setReleaseDialogOpen(true)
  }

  async function handleBuildInstaller() {
    if (!selectedPlugin) return
    const version = releaseVersionValue
    const notes = releaseNotesValue
    if (!SEMVER_RE.test(version) || !notes || notes.length > 2000) return
    setReleaseDialogOpen(false)
    setActivePluginId(selectedPlugin.id)
    setLogs([])
    setInstallerError('')
    setInstallerDone(false)
    setInstallerResult(null)
    setBuilding(true)

    try {
      const result = await buildInstaller(
        selectedPlugin.id,
        (message) => {
          setLogs((prev) => [...prev, message])
          setTimeout(() => logRef.current?.scrollTo(0, logRef.current.scrollHeight), 0)
        },
        logoPath,
        version,
        notes,
      )
      setInstallerResult(result)
      setInstallerDone(true)
      void pluginsQ.refetch()
    } catch (err) {
      setInstallerError(err instanceof Error ? err.message : 'Installer build failed')
    } finally {
      setBuilding(false)
    }
  }

  function handleOpenInstaller() {
    if (!installerOutputPath || !installerReady) return
    void window.conxa.openExternal(`file://${installerOutputPath}`)
  }

  if (pluginsQ.isLoading) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <PageHeader title="Build Installer" />
        <div className="flex flex-1 items-center justify-center">
          <div className="flex items-center gap-2 text-zinc-500">
            <Loader2 className="size-4 animate-spin" />
            <span className="text-sm">Loading packages…</span>
          </div>
        </div>
      </div>
    )
  }

  if (pluginsQ.isError || !pluginsQ.data) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <PageHeader title="Build Installer" />
        <div className="mx-6 mt-6 flex items-start gap-2.5 rounded-lg border border-red-500/20 bg-red-500/[0.06] px-4 py-3">
          <XCircle className="mt-0.5 size-4 shrink-0 text-red-400" />
          <p className="text-sm text-red-300">
            {(pluginsQ.error as Error)?.message ?? 'Failed to load plugins'}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        title="Build Installer"
        description="Package a built plugin into a distributable Windows .exe installer."
      />

      {/* Entitlement meters strip */}
      <div className="border-b border-white/8 px-6 py-3">
        <EntitlementMeters meters={['installer_slots']} compact />
      </div>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* Left sidebar — package list */}
        <div className="flex w-72 shrink-0 flex-col border-r border-white/8">
          <div className="border-b border-white/8 px-4 py-3">
            <div className="flex items-center justify-between">
              <h2 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                Built Packages
              </h2>
              <span className="rounded-full bg-white/8 px-2 py-0.5 text-[10px] font-medium text-zinc-400">
                {builtPlugins.length}
              </span>
            </div>
            <p className="mt-0.5 text-[11px] text-zinc-600">
              {readyPlugins.length} of {builtPlugins.length} ready for installer
            </p>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
            {builtPlugins.length === 0 ? (
              <div className="flex flex-col items-center justify-center px-4 py-12 text-center">
                <div className="mb-3 rounded-full border border-white/8 bg-white/[0.03] p-3">
                  <PackageCheck className="size-6 text-zinc-700" />
                </div>
                <p className="text-xs font-medium text-zinc-500">No built packages</p>
                <p className="mt-1 text-[11px] text-zinc-600">
                  Build a plugin first, then return here.
                </p>
              </div>
            ) : (
              <div className="space-y-1">
                {builtPlugins.map((plugin) => {
                  const selected = selectedPlugin?.id === plugin.id
                  const tested = allTestsPassed(plugin)
                  const untested = plugin.workflows.filter(
                    (w) => w.last_test_status !== 'passed',
                  ).length
                  return (
                    <button
                      key={plugin.id}
                      type="button"
                      onClick={() => selectPlugin(plugin.id)}
                      className={cn(
                        'group w-full cursor-pointer rounded-lg border px-3 py-2.5 text-left transition-all duration-150',
                        selected
                          ? 'border-sky-500/25 bg-sky-500/[0.08] text-white'
                          : 'border-transparent text-zinc-300 hover:border-white/8 hover:bg-white/[0.04] hover:text-white',
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate text-[13px] font-medium leading-snug">
                            {packageNameFromOutputPath(plugin.build?.output_path)}
                          </p>
                          <p className="mt-0.5 truncate text-[11px] text-zinc-500">{plugin.name}</p>
                        </div>
                        <Badge
                          variant="outline"
                          className={cn(
                            'shrink-0 text-[10px] font-medium',
                            plugin.installer
                              ? 'border-emerald-500/30 bg-emerald-500/[0.08] text-emerald-300'
                              : tested
                                ? 'border-sky-500/30 bg-sky-500/[0.08] text-sky-300'
                                : 'border-amber-500/30 bg-amber-500/[0.08] text-amber-300',
                          )}
                        >
                          {plugin.installer ? 'installer' : tested ? 'ready' : `${untested} untested`}
                        </Badge>
                      </div>
                      {/* Readiness bar */}
                      <div className="mt-2 flex items-center gap-1.5">
                        <div
                          className={cn(
                            'h-0.5 flex-1 rounded-full',
                            plugin.installer
                              ? 'bg-emerald-500/50'
                              : tested
                                ? 'bg-sky-500/40'
                                : 'bg-amber-500/30',
                          )}
                        />
                        <span className="text-[10px] text-zinc-600">
                          {plugin.workflows.length}w
                        </span>
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right panel */}
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          {selectedPlugin ? (
            <div className="flex flex-col gap-0">
              {/* Plugin header */}
              <div className="border-b border-white/8 px-6 py-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <h3 className="text-base font-semibold leading-snug text-white">
                      {selectedPlugin.name}
                    </h3>
                    <p className="mt-0.5 break-all font-mono text-xs text-zinc-500">
                      {selectedPlugin.build?.output_path}
                    </p>
                    <p className="mt-1 text-[11px] text-zinc-600">
                      {selectedPlugin.installer
                        ? 'Uploading a new version will update the existing installer slot.'
                        : 'Publishing this installer will consume one installer slot.'}
                    </p>
                  </div>
                  <Badge
                    variant="outline"
                    className={cn(
                      'shrink-0 px-2.5 py-1 text-xs',
                      installerReady
                        ? 'border-emerald-500/25 bg-emerald-500/[0.08] text-emerald-200'
                        : buildingSelected
                          ? 'border-sky-500/25 bg-sky-500/[0.08] text-sky-200'
                          : 'border-white/10 bg-white/[0.04] text-zinc-300',
                    )}
                  >
                    {selectedStatus}
                  </Badge>
                </div>
              </div>

              {/* Test warning */}
              {!selectedPluginTestsOk && (
                <div className="mx-6 mt-4 flex items-start gap-2.5 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] px-4 py-3">
                  <XCircle className="mt-0.5 size-4 shrink-0 text-amber-400" />
                  <div>
                    <p className="text-sm font-medium text-amber-300">Tests required before build</p>
                    <p className="mt-0.5 text-xs text-amber-400/80">
                      {untestedCount} workflow{untestedCount !== 1 ? 's' : ''} must pass{' '}
                      <Link
                        to="/test"
                        className="font-medium underline underline-offset-2 hover:text-amber-300 transition-colors"
                      >
                        Test Plugin
                      </Link>{' '}
                      before this installer can be built.
                    </p>
                  </div>
                </div>
              )}

              {/* Configuration grid */}
              <div className="mx-6 mt-4 grid gap-3 sm:grid-cols-2">
                {/* Logo upload zone */}
                <div className="rounded-lg border border-white/8 bg-white/[0.02] p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                      Installer Logo
                    </p>
                    {!logoPath && (
                      <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400">
                        Required
                      </span>
                    )}
                  </div>
                  {logoPath ? (
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04]">
                        <ImagePlus className="size-5 text-zinc-400" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium text-zinc-200">
                          {logoPath.split(/[\\/]/).pop()}
                        </p>
                        <p className="text-[11px] text-zinc-500">Logo ready</p>
                      </div>
                      <button
                        type="button"
                        onClick={handleClearLogo}
                        className="shrink-0 rounded p-1 text-zinc-500 transition-colors hover:bg-white/8 hover:text-zinc-300"
                        aria-label="Remove logo"
                      >
                        <X className="size-3.5" />
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={handlePickLogo}
                      className="flex w-full cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-white/12 py-5 text-center transition-colors hover:border-white/20 hover:bg-white/[0.03]"
                    >
                      <ImagePlus className="size-6 text-zinc-600" />
                      <div>
                        <p className="text-xs font-medium text-zinc-400">Click to select logo</p>
                        <p className="mt-0.5 text-[11px] text-zinc-600">PNG, JPG, or ICO</p>
                      </div>
                    </button>
                  )}
                </div>

                {/* Release details */}
                <div className="rounded-lg border border-white/8 bg-white/[0.02] p-4">
                  <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                    Release Details
                  </p>
                  {releaseVersionValid && releaseNotesValid ? (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-sky-500/10 px-2 py-0.5 font-mono text-xs font-medium text-sky-300">
                          v{releaseVersionValue}
                        </span>
                        <CheckCircle2 className="size-3.5 text-emerald-400" />
                      </div>
                      <p className="line-clamp-3 text-[11px] leading-relaxed text-zinc-400">
                        {releaseNotesValue}
                      </p>
                      <button
                        type="button"
                        onClick={handleOpenReleaseDialog}
                        className="text-[11px] font-medium text-sky-400 transition-colors hover:text-sky-300"
                      >
                        Edit release details →
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={handleOpenReleaseDialog}
                      disabled={!canBuild}
                      className={cn(
                        'flex w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed py-5 text-center transition-colors',
                        canBuild
                          ? 'cursor-pointer border-white/12 hover:border-white/20 hover:bg-white/[0.03]'
                          : 'cursor-not-allowed border-white/6 opacity-40',
                      )}
                    >
                      <FileText className="size-6 text-zinc-600" />
                      <div>
                        <p className="text-xs font-medium text-zinc-400">Set version & release notes</p>
                        <p className="mt-0.5 text-[11px] text-zinc-600">
                          {!selectedPluginTestsOk
                            ? 'Tests must pass first'
                            : !logoPath
                              ? 'Add logo first'
                              : 'Required before build'}
                        </p>
                      </div>
                    </button>
                  )}
                </div>
              </div>

              {/* Action bar */}
              <div className="mx-6 mt-4 flex flex-wrap items-center gap-2">
                <Button size="sm" onClick={handleOpenReleaseDialog} disabled={!canBuild}>
                  {buildingSelected ? (
                    <>
                      <Loader2 className="size-4 animate-spin" />
                      Building installer…
                    </>
                  ) : (
                    <>
                      <PackageCheck className="size-4" />
                      Build Installer
                    </>
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleOpenInstaller}
                  disabled={!installerReady || buildingSelected}
                >
                  <Download className="size-4" />
                  Open Installer
                </Button>
              </div>

              {/* Pipeline stepper */}
              {showPipeline && (
                <div className="mx-6 mt-4 rounded-lg border border-white/8 bg-white/[0.02] px-5 py-4">
                  <p className="mb-4 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                    Pipeline
                  </p>
                  <div className="flex items-center">
                    {PIPELINE_STAGES.map((stage, i) => {
                      const isComplete = pipelineStage > i
                      const isCurrent = !activeDone && !activeError && pipelineStage === i
                      const isErrored = Boolean(activeError) && pipelineStage === i
                      return (
                        <Fragment key={stage}>
                          <div className="flex flex-col items-center gap-1.5">
                            <div
                              className={cn(
                                'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold transition-all duration-300',
                                isComplete
                                  ? 'bg-emerald-500 text-white'
                                  : isCurrent
                                    ? 'bg-sky-500 text-white ring-2 ring-sky-500/30'
                                    : isErrored
                                      ? 'bg-red-500 text-white'
                                      : 'bg-white/8 text-zinc-600',
                              )}
                            >
                              {isComplete ? (
                                <Check className="size-3" />
                              ) : isCurrent ? (
                                <Loader2 className="size-3 animate-spin" />
                              ) : isErrored ? (
                                <X className="size-3" />
                              ) : (
                                i + 1
                              )}
                            </div>
                            <span
                              className={cn(
                                'whitespace-nowrap text-[11px] font-medium',
                                isComplete
                                  ? 'text-emerald-300'
                                  : isCurrent
                                    ? 'text-sky-300'
                                    : isErrored
                                      ? 'text-red-300'
                                      : 'text-zinc-600',
                              )}
                            >
                              {stage}
                            </span>
                          </div>
                          {i < PIPELINE_STAGES.length - 1 && (
                            <div
                              className={cn(
                                'mx-3 mb-4 h-px flex-1 transition-colors duration-500',
                                pipelineStage > i ? 'bg-emerald-500/40' : 'bg-white/8',
                              )}
                            />
                          )}
                        </Fragment>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Build error */}
              {activeError && (
                <div className="mx-6 mt-3 flex items-start gap-2.5 rounded-lg border border-red-500/20 bg-red-500/[0.06] px-4 py-3">
                  <XCircle className="mt-0.5 size-4 shrink-0 text-red-400" />
                  <div>
                    <p className="text-sm font-medium text-red-300">Build failed</p>
                    <p className="mt-0.5 text-xs text-red-400/80">{humanizeError(activeError)}</p>
                  </div>
                </div>
              )}

              {/* Success results */}
              {activeDone && (
                <div className="mx-6 mt-3">
                  <div className="mb-3 flex items-center gap-2">
                    <CheckCircle2 className="size-4 text-emerald-400" />
                    <p className="text-sm font-semibold text-emerald-300">
                      Installer built and published
                    </p>
                  </div>
                  <div className="space-y-2">
                    {installerOutputPath && (
                      <ResultCard
                        icon={<HardDrive className="size-4" />}
                        label="Local installer"
                        value={installerOutputPath}
                      />
                    )}
                    {currentResult?.cloud_download_url && (
                      <ResultCard
                        icon={<Globe className="size-4" />}
                        label="Cloud download URL"
                        value={currentResult.cloud_download_url}
                        href={currentResult.cloud_download_url}
                      />
                    )}
                    {currentResult?.cloud_version_download_url && (
                      <ResultCard
                        icon={<Globe className="size-4" />}
                        label="Version download URL"
                        value={currentResult.cloud_version_download_url}
                        href={currentResult.cloud_version_download_url}
                      />
                    )}
                    {currentResult?.cloud_tracking_url && (
                      <ResultCard
                        icon={<Globe className="size-4" />}
                        label="Tracking URL"
                        value={currentResult.cloud_tracking_url}
                        href={currentResult.cloud_tracking_url}
                      />
                    )}
                    {currentResult?.cloud_workspace_id && (
                      <ResultCard
                        icon={<FileText className="size-4" />}
                        label="Workspace ID"
                        value={currentResult.cloud_workspace_id}
                      />
                    )}
                    {currentResult?.installed_runtime_path && (
                      <ResultCard
                        icon={<HardDrive className="size-4" />}
                        label="Runtime path"
                        value={currentResult.installed_runtime_path}
                      />
                    )}
                  </div>
                </div>
              )}

              {/* Build log */}
              <div className="mx-6 mb-6 mt-4 flex flex-col">
                <div className="mb-1.5 flex items-center justify-between">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-600">
                    Build Log
                  </p>
                  {activeLogs.length > 0 && (
                    <span className="text-[10px] text-zinc-600">{activeLogs.length} lines</span>
                  )}
                </div>
                <div
                  ref={logRef}
                  className="min-h-[140px] overflow-y-auto rounded-lg border border-white/8 bg-black/40 p-3 font-mono text-[11px]"
                >
                  {activeLogs.length === 0 ? (
                    <p className="text-zinc-700">Installer logs will appear here when build starts…</p>
                  ) : (
                    <div className="space-y-px">
                      {activeLogs.map((line, index) => (
                        <div key={index} className={cn('leading-5', getLogLineStyle(line))}>
                          <span className="mr-2 select-none text-zinc-700">
                            {String(index + 1).padStart(3, ' ')}
                          </span>
                          {line}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-4 px-8 text-center">
              <div className="rounded-full border border-white/8 bg-white/[0.03] p-5">
                <PackageCheck className="size-9 text-zinc-700" />
              </div>
              <div>
                <p className="text-sm font-semibold text-zinc-400">No package selected</p>
                <p className="mt-1 text-xs text-zinc-600">
                  Build a plugin package first, then return here to create its installer.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Release dialog */}
      <Dialog open={releaseDialogOpen} onOpenChange={setReleaseDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (canConfirmReleaseBuild) void handleBuildInstaller()
            }}
          >
            <DialogHeader>
              <DialogTitle>Configure Release</DialogTitle>
              <DialogDescription className="mt-0.5">
                {selectedPlugin?.name ?? 'Selected plugin'} — builds installer and publishes to cloud
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-3">
              <label className="grid gap-1.5">
                <span className="text-xs font-medium text-zinc-300">Version</span>
                <Input
                  value={releaseVersion}
                  onChange={(e) => setReleaseVersion(e.target.value)}
                  placeholder="1.2.3"
                  aria-invalid={releaseVersion.length > 0 && !releaseVersionValid}
                  disabled={buildingSelected}
                  className="font-mono"
                />
                {releaseVersion.length > 0 && !releaseVersionValid ? (
                  <p className="text-xs text-red-300">Must be semver: 1.2.3 or 1.2.3-beta.1</p>
                ) : (
                  <p className="text-[11px] text-zinc-600">Format: 1.2.3 or 1.2.3-beta.1</p>
                )}
              </label>
              <label className="grid gap-1.5">
                <span className="text-xs font-medium text-zinc-300">Release notes</span>
                <Textarea
                  value={releaseNotes}
                  onChange={(e) => setReleaseNotes(e.target.value)}
                  maxLength={2000}
                  rows={5}
                  placeholder="Describe what changed in this release…"
                  aria-invalid={releaseNotes.length > 2000}
                  disabled={buildingSelected}
                  className="resize-none"
                />
                <p
                  className={cn(
                    'text-[11px]',
                    releaseNotes.length > 2000 ? 'text-red-300' : 'text-zinc-600',
                  )}
                >
                  {releaseNotes.length} / 2000 characters
                </p>
              </label>
            </div>
            <DialogFooter className="bg-transparent">
              <Button
                type="button"
                variant="outline"
                onClick={() => setReleaseDialogOpen(false)}
                disabled={buildingSelected}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={!canConfirmReleaseBuild}>
                {buildingSelected ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    Building…
                  </>
                ) : (
                  <>
                    <PackageCheck className="size-4" />
                    Build Installer
                  </>
                )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
