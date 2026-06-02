import { useMemo, useRef, useState } from 'react'
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
import { CheckCircle2, Download, ImagePlus, Loader2, PackageCheck, X, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

const SEMVER_RE = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/

function packageNameFromOutputPath(outputPath?: string | null): string {
  if (!outputPath) return 'No package'
  const leaf = outputPath.split(/[\\/]+/).filter(Boolean).pop() ?? outputPath
  return leaf.endsWith('-plugin') ? leaf.slice(0, -'-plugin'.length) : leaf
}

function installerStatus(plugin: Plugin | null, result: InstallerBuildResult | null, activePluginId: string | null, building: boolean) {
  if (!plugin) return 'Select package'
  if (building && activePluginId === plugin.id) return 'Building'
  if (result?.plugin_id === plugin.id || plugin.installer) return 'Complete'
  return 'Not built'
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
  const builtPlugins = useMemo(() => plugins.filter((plugin) => plugin.build), [plugins])
  const allTestsPassed = (plugin: { workflows: { last_test_status: string }[] }) =>
    plugin.workflows.length > 0 && plugin.workflows.every((w) => w.last_test_status === 'passed')
  const readyPlugins = useMemo(() => builtPlugins.filter(allTestsPassed), [builtPlugins])
  const selectedPlugin = useMemo(() => {
    if (builtPlugins.length === 0) return null
    if (selectedId) {
      const selected = builtPlugins.find((plugin) => plugin.id === selectedId)
      if (selected) return selected
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
    setReleaseVersion(selectedPlugin.build?.version || selectedPlugin.installer?.version || '0.1.0')
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
        <div className="min-h-0 flex-1 overflow-hidden">
          <p className="p-6 text-sm text-zinc-500">Loading...</p>
        </div>
      </div>
    )
  }

  if (pluginsQ.isError || !pluginsQ.data) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <PageHeader title="Build Installer" />
        <div className="min-h-0 flex-1 overflow-hidden">
          <p className="p-6 text-sm text-red-400">{(pluginsQ.error as Error)?.message ?? 'Failed to load plugins'}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader title="Build Installer" description="Turn a built plugin package into a Windows installer." />
      <div className="flex min-h-0 flex-1 gap-4 p-6">
        <div className="flex min-h-0 w-80 flex-col gap-3 rounded-lg border border-white/8 bg-white/[0.03]">
          <div className="border-b border-white/8 px-4 py-3">
            <h2 className="text-sm font-medium text-white">Built Packages</h2>
            <p className="mt-0.5 text-xs text-zinc-500">{readyPlugins.length} of {builtPlugins.length} ready for installer</p>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
            {builtPlugins.length === 0 ? (
              <p className="px-2 py-4 text-xs text-zinc-500">No built packages yet. Build a plugin first.</p>
            ) : (
              <div className="space-y-1">
                {builtPlugins.map((plugin) => {
                  const selected = selectedPlugin?.id === plugin.id
                  const tested = allTestsPassed(plugin)
                  const untested = plugin.workflows.filter((w) => w.last_test_status !== 'passed').length
                  return (
                    <button
                      key={plugin.id}
                      type="button"
                      onClick={() => selectPlugin(plugin.id)}
                      className={cn(
                        'w-full cursor-pointer rounded-lg border border-transparent px-3 py-2.5 text-left text-sm transition-colors',
                        'hover:border-white/8 hover:bg-white/[0.07] hover:text-white',
                        selected ? 'border-white/10 bg-white/[0.10] text-white' : 'text-zinc-300',
                        !tested && 'opacity-60',
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate font-medium">{packageNameFromOutputPath(plugin.build?.output_path)}</p>
                          <p className="mt-0.5 truncate text-xs text-zinc-500">{plugin.name}</p>
                        </div>
                        <Badge
                          variant="outline"
                          className={cn(
                            'shrink-0 text-[10px]',
                            plugin.installer
                              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                              : tested
                                ? 'border-sky-500/30 bg-sky-500/10 text-sky-300'
                                : 'border-amber-500/30 bg-amber-500/10 text-amber-300',
                          )}
                        >
                          {plugin.installer ? 'installer' : tested ? 'ready' : `${untested} untested`}
                        </Badge>
                      </div>
                      <p className="mt-1 truncate text-xs text-zinc-500">{plugin.build?.output_path}</p>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 rounded-lg border border-white/8 bg-white/[0.03]">
          {selectedPlugin ? (
            <>
              <div className="border-b border-white/8 px-4 py-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-sm font-medium text-white">{selectedPlugin.name}</h3>
                    <p className="mt-0.5 break-all text-xs text-zinc-500">{selectedPlugin.build?.output_path}</p>
                  </div>
                  <Badge
                    variant="outline"
                    className={cn(
                      'border-white/10 bg-white/[0.04] text-xs text-zinc-300',
                      installerReady && 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200',
                      buildingSelected && 'border-sky-500/25 bg-sky-500/10 text-sky-200',
                    )}
                  >
                    {selectedStatus}
                  </Badge>
                </div>
              </div>

              {!selectedPluginTestsOk && (
                <div className="mx-4 mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-300">
                  {untestedCount} workflow{untestedCount !== 1 ? 's' : ''} must pass{' '}
                  <Link to="/test" className="underline">Test Plugin</Link> before building the installer.
                </div>
              )}

              {/* Logo picker */}
              <div className="mx-4 mt-1 flex items-center gap-3">
                {logoPath ? (
                  <div className="flex items-center gap-2">
                    <div className="flex flex-col">
                      <span className="text-xs text-zinc-300 truncate max-w-[200px]">
                        {logoPath.split(/[\\/]/).pop()}
                      </span>
                      <span className="text-[10px] text-zinc-500">Installer logo</span>
                    </div>
                    <button
                      type="button"
                      onClick={handleClearLogo}
                      className="ml-1 rounded p-0.5 text-zinc-500 hover:text-zinc-300 hover:bg-white/10 transition-colors"
                      title="Remove logo"
                    >
                      <X className="size-3.5" />
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={handlePickLogo}
                    className="flex items-center gap-1.5 rounded-md border border-dashed border-amber-500/40 px-2.5 py-1.5 text-xs text-amber-400 hover:border-amber-400/70 hover:text-amber-300 transition-colors"
                  >
                    <ImagePlus className="size-3.5" />
                    Add installer logo (required)
                  </button>
                )}
              </div>

              <div className="flex flex-wrap gap-2 px-4">
                <Button size="sm" onClick={handleOpenReleaseDialog} disabled={!canBuild}>
                  {buildingSelected ? (
                    <>
                      <Loader2 className="size-4 animate-spin" />
                      Building...
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

              <div className="flex min-h-0 flex-1 flex-col gap-2 px-4 pb-4">
                {activeDone ? (
                  <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="size-4 shrink-0 text-emerald-400" />
                      <p className="text-xs font-medium text-emerald-300">Installer build complete</p>
                    </div>
                    {installerOutputPath ? (
                      <p className="mt-1 break-all pl-6 font-mono text-[11px] text-emerald-100/60">{installerOutputPath}</p>
                    ) : null}
                    {currentResult?.cloud_download_url ? (
                      <p className="mt-1 break-all pl-6 font-mono text-[11px] text-emerald-100/60">{currentResult.cloud_download_url}</p>
                    ) : null}
                    {currentResult?.cloud_version_download_url ? (
                      <p className="mt-1 break-all pl-6 font-mono text-[11px] text-emerald-100/60">{currentResult.cloud_version_download_url}</p>
                    ) : null}
                    {currentResult?.cloud_workspace_id ? (
                      <p className="mt-1 break-all pl-6 font-mono text-[11px] text-emerald-100/60">Workspace: {currentResult.cloud_workspace_id}</p>
                    ) : null}
                    {currentResult?.cloud_tracking_url ? (
                      <p className="mt-1 break-all pl-6 font-mono text-[11px] text-emerald-100/60">Tracking: {currentResult.cloud_tracking_url}</p>
                    ) : null}
                    {currentResult?.installed_runtime_path ? (
                      <p className="mt-1 break-all pl-6 font-mono text-[11px] text-emerald-100/60">Runtime: {currentResult.installed_runtime_path}</p>
                    ) : null}
                  </div>
                ) : null}
                {activeError ? (
                  <div className="flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2">
                    <XCircle className="size-4 shrink-0 text-red-400" />
                    <p className="text-xs text-red-300">{activeError}</p>
                  </div>
                ) : null}
                <div
                  ref={logRef}
                  className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-white/8 bg-black/30 p-3 font-mono text-[11px] text-zinc-400"
                >
                  {activeLogs.length === 0 ? (
                    <p className="text-zinc-600">Installer logs will appear here...</p>
                  ) : (
                    activeLogs.map((line, index) => <div key={index}>{line}</div>)
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center px-6 text-center">
              <p className="text-sm text-zinc-500">Build a plugin first, then return here to create its installer.</p>
            </div>
          )}
        </div>
      </div>
      <Dialog open={releaseDialogOpen} onOpenChange={setReleaseDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <form
            className="grid gap-4"
            onSubmit={(event) => {
              event.preventDefault()
              if (canConfirmReleaseBuild) void handleBuildInstaller()
            }}
          >
            <DialogHeader>
              <DialogTitle>Installer Release</DialogTitle>
              <DialogDescription>{selectedPlugin?.name ?? 'Selected plugin'}</DialogDescription>
            </DialogHeader>
            <div className="grid gap-3">
              <label className="grid gap-1.5 text-xs font-medium text-zinc-300">
                Version
                <Input
                  value={releaseVersion}
                  onChange={(event) => setReleaseVersion(event.target.value)}
                  placeholder="1.2.3"
                  aria-invalid={releaseVersion.length > 0 && !releaseVersionValid}
                  disabled={buildingSelected}
                />
              </label>
              {releaseVersion.length > 0 && !releaseVersionValid ? (
                <p className="text-xs text-red-300">Use 1.2.3 or 1.2.3-beta.1.</p>
              ) : null}
              <label className="grid gap-1.5 text-xs font-medium text-zinc-300">
                Release message
                <Textarea
                  value={releaseNotes}
                  onChange={(event) => setReleaseNotes(event.target.value)}
                  maxLength={2000}
                  rows={5}
                  aria-invalid={releaseNotes.length > 2000}
                  disabled={buildingSelected}
                  className="resize-none"
                />
              </label>
              <p className={cn('text-xs', releaseNotes.length > 2000 ? 'text-red-300' : 'text-zinc-500')}>
                {releaseNotes.length}/2000
              </p>
            </div>
            <DialogFooter className="bg-transparent">
              <Button type="button" variant="outline" onClick={() => setReleaseDialogOpen(false)} disabled={buildingSelected}>
                Cancel
              </Button>
              <Button type="submit" disabled={!canConfirmReleaseBuild}>
                {buildingSelected ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    Building...
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
