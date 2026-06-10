import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  deleteWorkflow,
  fetchPlugin,
  finalizeAuth,
  finalizeWorkflow,
  getPluginRecordingStatus,
  reRecordAuth,
  startAuthRecord,
  startWorkflowRecord,
  type Plugin,
} from '@/api/pluginApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CompiledSkillsTab } from '@/components/CompiledSkillsTab'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { KeyRound, ListChecks, Loader2, MousePointer2, PackageCheck, Play, Plus, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react'

// ─────────────────────────────────────────────────
// Auth panel
// ─────────────────────────────────────────────────

function AuthPanel({ plugin, onRefresh }: { plugin: Plugin; onRefresh: () => void }) {
  const [activeSession, setActiveSession] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [autoFinalizing, setAutoFinalizing] = useState(false)

  const startMut = useMutation({
    mutationFn: () => startAuthRecord(plugin.id),
    onSuccess: (data) => {
      setActiveSession(data.session_id)
      setError('')
      setAutoFinalizing(false)
    },
    onError: (e: Error) => setError(e.message),
  })

  const finalizeMut = useMutation({
    mutationFn: async () => {
      const result = await finalizeAuth(plugin.id, activeSession!)
      return result
    },
    onSuccess: () => {
      setActiveSession(null)
      setAutoFinalizing(false)
      onRefresh()
    },
    onError: (e: Error) => {
      setError(e.message)
      setActiveSession(null)
      setAutoFinalizing(false)
    },
  })

  const reRecordMut = useMutation({
    mutationFn: () => reRecordAuth(plugin.id),
    onSuccess: onRefresh,
    onError: (e: Error) => setError(e.message),
  })

  const isRecording = !!activeSession
  const statusQ = useQuery({
    queryKey: ['plugin-auth-recording-status', plugin.id, activeSession],
    queryFn: () => getPluginRecordingStatus(activeSession!),
    enabled: isRecording && !finalizeMut.isPending && !autoFinalizing,
    refetchInterval: 1000,
    retry: false,
  })

  useEffect(() => {
    if (!isRecording || autoFinalizing || finalizeMut.isPending) return
    if (statusQ.data?.browser_open === false) {
      setAutoFinalizing(true)
      finalizeMut.mutate()
    }
  }, [isRecording, autoFinalizing, finalizeMut, statusQ.data?.browser_open])

  return (
    <section>
      <div className="flex items-start justify-between gap-3 border-b border-white/8 px-5 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-amber-500/20 bg-amber-500/10">
            <KeyRound className="size-4 text-amber-300" />
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-white">Authentication workflow</h2>
            <p className="mt-1 text-xs text-zinc-500">Capture the login session before recording workflows.</p>
          </div>
        </div>
        {plugin.auth ? (
          <Badge variant="outline" className="shrink-0 border-emerald-500/30 bg-emerald-500/10 text-emerald-300">
            Captured
          </Badge>
        ) : (
          <Badge variant="outline" className="shrink-0 border-amber-500/30 bg-amber-500/10 text-amber-300">
            Required
          </Badge>
        )}
      </div>
      <div className="max-w-3xl space-y-4 p-5">
        {plugin.auth ? (
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/[0.06] px-3 py-3">
              <div className="flex items-center gap-2 text-sm font-medium text-emerald-200">
                <ShieldCheck className="size-4" />
                Session ready
              </div>
              <p className="mt-1 text-xs text-emerald-100/70">
                Captured{' '}
                {new Date(plugin.auth.captured_at * 1000).toLocaleString([], {
                  month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
                })}
              </p>
            </div>
            <Button
              size="sm"
              variant="outline"
              className="h-9 border-white/10 bg-white/[0.06] px-3 text-zinc-200 hover:border-amber-500/30 hover:bg-amber-500/10 hover:text-amber-100"
              onClick={() => reRecordMut.mutate()}
              disabled={reRecordMut.isPending}
            >
              <RefreshCw className="size-3.5" />
              Re-record Auth
            </Button>
          </div>
        ) : isRecording ? (
          <div className="space-y-3">
            <div className="flex items-start gap-3 rounded-lg border border-blue-500/20 bg-blue-500/[0.07] px-3 py-3">
              <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-blue-300" />
              <p className="text-xs leading-5 text-blue-100/80">
                {autoFinalizing ? 'Chromium closed, saving session…' : 'Browser is open. Log in, navigate to the page where workflows should start, then close Chromium.'}
              </p>
            </div>
            {!autoFinalizing && (
              <div className="grid gap-2 sm:grid-cols-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="h-9 border-white/10 bg-white/[0.06] text-zinc-300 hover:bg-white/10 hover:text-white"
                  onClick={() => setActiveSession(null)}
                  disabled={finalizeMut.isPending}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  className="h-9 bg-blue-600 text-white hover:bg-blue-500"
                  onClick={() => finalizeMut.mutate()}
                  disabled={finalizeMut.isPending}
                >
                  {finalizeMut.isPending ? (
                    <>
                      <Loader2 className="size-4 animate-spin" />
                      Saving session…
                    </>
                  ) : (
                    'Save Session Now'
                  )}
                </Button>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="rounded-lg border border-white/8 bg-black/20 px-3 py-3">
              <p className="text-[11px] font-medium text-zinc-500">Target URL</p>
              <p className="mt-1 truncate font-mono text-xs text-zinc-300">{plugin.target_url}</p>
              <p className="mt-2 text-xs leading-5 text-zinc-500">
                Log in, navigate to the page where workflows should start, then close Chromium.
              </p>
            </div>
            <Button
              size="sm"
              className="h-9 w-full bg-amber-500 text-zinc-950 hover:bg-amber-400"
              onClick={() => startMut.mutate()}
              disabled={startMut.isPending}
            >
              {startMut.isPending ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  Launching browser…
                </>
              ) : (
                <>
                  <Play className="size-4" />
                  Record Auth
                </>
              )}
            </Button>
          </div>
        )}
        {error ? <p className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</p> : null}
      </div>
    </section>
  )
}

// ─────────────────────────────────────────────────
// Workflow row
// ─────────────────────────────────────────────────

function WorkflowRow({
  workflow,
  pluginId,
  onDelete,
  onCompiled,
}: {
  workflow: Plugin['workflows'][number]
  pluginId: string
  onDelete: () => void
  onCompiled: () => void
}) {
  const navigate = useNavigate()

  const deleteMut = useMutation({
    mutationFn: () => deleteWorkflow(pluginId, workflow.id),
    onSuccess: onDelete,
  })

  const handleCompile = () => {
    navigate(`/plugins/${encodeURIComponent(pluginId)}/compile/${encodeURIComponent(workflow.session_id)}`)
  }

  const handleRecompile = () => {
    if (!workflow.skill_id) return
    navigate(`/plugins/${encodeURIComponent(pluginId)}/compile/${encodeURIComponent(workflow.session_id)}?mode=recompile`)
  }

  return (
    <div className="flex flex-col gap-1 border-t border-white/6 px-4 py-3 first:border-t-0">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-white">{workflow.name}</p>
          <p className="mt-0.5 text-xs text-zinc-500">
            {new Date(workflow.recorded_at * 1000).toLocaleString([], {
              month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
            })}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge
            variant="outline"
            className={
              workflow.status === 'compiled'
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                : 'border-white/10 bg-white/5 text-zinc-400'
            }
          >
            {workflow.status}
          </Badge>
          {!workflow.skill_id ? (
            <Button
              size="sm"
              variant="outline"
              className="border-amber-500/30 bg-amber-500/5 text-amber-300 hover:bg-amber-500/10"
              onClick={handleCompile}
            >
              <Play className="size-3.5" /> Compile
            </Button>
          ) : (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  size="sm"
                  variant="outline"
                  className="border-amber-500/30 bg-amber-500/5 text-amber-300 hover:bg-amber-500/10"
                  title="Recompile"
                >
                  <><RefreshCw className="size-3.5" /> Recompile</>
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent className="border-white/10 bg-[#0d0f12] text-zinc-100">
                <AlertDialogHeader>
                  <AlertDialogTitle className="text-white">Recompile &ldquo;{workflow.name}&rdquo;?</AlertDialogTitle>
                  <AlertDialogDescription className="text-zinc-400">
                    This rebuilds the skill package from the original raw recording and uses the Human Edit pool.
                    Saved editor changes to selectors, validation, screenshots, and inputs will be replaced by the fresh compile.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel className="border-white/10 bg-white/5 text-zinc-200">Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    className="bg-amber-600 text-white hover:bg-amber-700"
                    onClick={handleRecompile}
                  >
                    Recompile
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
          {workflow.skill_id && (
            <Button
              size="sm"
              variant="outline"
              className="border-white/10 bg-white/5 text-zinc-300 hover:text-white"
              onClick={() => navigate(`/edit/${encodeURIComponent(workflow.skill_id!)}?from=/plugins/${encodeURIComponent(pluginId)}`)}
            >
              Edit
            </Button>
          )}
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button size="icon-sm" variant="ghost" className="text-zinc-500 hover:text-red-400">
                <Trash2 className="size-4" />
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent className="border-white/10 bg-[#0d0f12] text-zinc-100">
              <AlertDialogHeader>
                <AlertDialogTitle className="text-white">Delete &ldquo;{workflow.name}&rdquo;?</AlertDialogTitle>
                <AlertDialogDescription className="text-zinc-400">
                  This removes the workflow recording from this plugin.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel className="border-white/10 bg-white/5 text-zinc-200">Cancel</AlertDialogCancel>
                <AlertDialogAction
                  className="bg-red-600 text-white hover:bg-red-700"
                  onClick={() => deleteMut.mutate()}
                >
                  Delete
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────
// New workflow dialog
// ─────────────────────────────────────────────────

function NewWorkflowDialog({
  plugin,
  onCreated,
}: {
  plugin: Plugin
  onCreated: () => void
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [urlVariables, setUrlVariables] = useState<Record<string, string>>({})
  const [captureHover, setCaptureHover] = useState(false)
  const [activeSession, setActiveSession] = useState<{ sessionId: string; workflowId: string } | null>(null)
  const [error, setError] = useState('')
  const [workflowFinalizeRequested, setWorkflowFinalizeRequested] = useState(false)
  const [promoteToAuth, setPromoteToAuth] = useState<{ sessionId: string; workflowId: string } | null>(null)

  const workflowStartUrl = (plugin.protected_url || plugin.target_url).trim()
  const varPattern = /\{\{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*\}\}/g
  const requiredVars = Array.from(workflowStartUrl.matchAll(varPattern), (m) => m[1])
  const canRecordWorkflow = plugin.status === 'ready' && !!plugin.auth

  const startMut = useMutation({
    mutationFn: () => startWorkflowRecord(plugin.id, name, requiredVars.length > 0 ? urlVariables : undefined, captureHover),
    onSuccess: (data) => {
      setActiveSession({ sessionId: data.session_id, workflowId: data.workflow_id })
      setError('')
      setWorkflowFinalizeRequested(false)
    },
    onError: (e: Error) => setError(e.message),
  })

  const promoteAuthMut = useMutation({
    mutationFn: ({ sessionId }: { sessionId: string }) => finalizeAuth(plugin.id, sessionId),
    onSuccess: () => {
      setPromoteToAuth(null)
      setOpen(false)
      setName('')
      setCaptureHover(false)
      setActiveSession(null)
      onCreated()
    },
    onError: (e: Error) => setError(e.message),
  })

  const finalizeMut = useMutation({
    mutationFn: () =>
      finalizeWorkflow(plugin.id, activeSession!.workflowId, activeSession!.sessionId),
    onSuccess: async (data) => {
      const sessionId = data.session_id
      if (data.workflow_kind === 'login') {
        setPromoteToAuth({ sessionId, workflowId: data.workflow_id })
        return
      }
      setOpen(false)
      setName('')
      setCaptureHover(false)
      setActiveSession(null)
      setWorkflowFinalizeRequested(false)
      onCreated()
    },
    onError: (e: Error) => {
      const message = e.message
      setError(message)
      if (message.toLowerCase().startsWith('no workflow actions were recorded')) {
        setActiveSession(null)
        setWorkflowFinalizeRequested(false)
        onCreated()
      }
    },
  })

  const isRecording = !!activeSession
  const statusQ = useQuery({
    queryKey: ['plugin-workflow-recording-status', plugin.id, activeSession?.workflowId, activeSession?.sessionId],
    queryFn: () => getPluginRecordingStatus(activeSession!.sessionId),
    enabled: isRecording && !finalizeMut.isPending,
    refetchInterval: 1000,
    retry: false,
  })
  const workflowBrowserClosed = statusQ.data?.browser_open === false

  useEffect(() => {
    if (!isRecording || !workflowBrowserClosed || workflowFinalizeRequested || finalizeMut.isPending) return
    setWorkflowFinalizeRequested(true)
    finalizeMut.mutate()
  }, [isRecording, workflowBrowserClosed, workflowFinalizeRequested, finalizeMut])

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && activeSession && !workflowBrowserClosed && !finalizeMut.isPending) return
        setOpen(nextOpen)
      }}
    >
      <DialogTrigger asChild>
        <Button
          size="sm"
          variant="outline"
          className="border-white/10 bg-white/[0.04] text-zinc-200"
          disabled={!canRecordWorkflow}
          title={canRecordWorkflow ? 'Create a Workflow' : 'Record auth first'}
        >
          <Plus className="size-4" />
          Create a Workflow
        </Button>
      </DialogTrigger>
      <DialogContent className="border-white/10 bg-[#0d0f12] text-zinc-100">
        <DialogHeader>
          <DialogTitle className="text-white">Record Workflow</DialogTitle>
        </DialogHeader>
        {!isRecording ? (
          <div className="space-y-4 pt-2">
            <div className="space-y-1.5">
              <Label className="text-zinc-300">Workflow name</Label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Create new service"
                className="border-white/10 bg-white/5 text-zinc-100"
              />
            </div>
            {requiredVars.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-zinc-400">
                  URL variables <span className="text-zinc-600">(optional — leave blank to open at login URL)</span>
                </p>
                {requiredVars.map((varName) => (
                  <div key={varName} className="space-y-1">
                    <Label className="text-xs text-zinc-400">{varName}</Label>
                    <Input
                      value={urlVariables[varName] || ''}
                      onChange={(e) =>
                        setUrlVariables((prev) => ({ ...prev, [varName]: e.target.value }))
                      }
                      placeholder={`Enter ${varName} (optional)`}
                      className="border-white/10 bg-white/5 text-zinc-100 h-8"
                    />
                  </div>
                ))}
              </div>
            )}
            <div className="flex items-start gap-3 rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2.5">
              <Checkbox
                id="workflowCaptureHover"
                checked={captureHover}
                disabled={startMut.isPending}
                onCheckedChange={(checked) => setCaptureHover(checked === true)}
                className="mt-0.5"
              />
              <Label htmlFor="workflowCaptureHover" className="grid min-w-0 cursor-pointer gap-1">
                <span className="flex items-center gap-2 text-sm font-medium text-zinc-200">
                  <MousePointer2 className="size-3.5 text-zinc-400" />
                  Workflow contains hover-only elements
                </span>
                <span className="text-xs leading-5 text-zinc-500">
                  Turn this on when menus, tooltips, or drawers only appear after hovering.
                </span>
              </Label>
            </div>
            <p className="text-xs text-zinc-500">
              The browser will open pre-authenticated at{' '}
              <span className="font-mono text-zinc-300">
                {requiredVars.some((v) => urlVariables[v])
                  ? requiredVars.reduce(
                      (url, varName) =>
                        url.replace(new RegExp(`{{\\s*${varName}\\s*}}`), urlVariables[varName] || `{{${varName}}}`),
                      workflowStartUrl,
                    )
                  : workflowStartUrl}
              </span>
              . Record your workflow without needing to log in again.
            </p>
            {error ? <p className="text-sm text-red-400">{error}</p> : null}
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                className="flex-1 border-white/10 bg-white/5 text-zinc-300"
                onClick={() => {
                  setName('')
                  setUrlVariables({})
                  setCaptureHover(false)
                  setError('')
                }}
              >
                Clear
              </Button>
              <Button
                className="flex-1"
                onClick={() => startMut.mutate()}
                disabled={!name || startMut.isPending || !canRecordWorkflow}
              >
                {startMut.isPending ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    Launching browser…
                  </>
                ) : !canRecordWorkflow ? (
                  'Record auth first'
                ) : (
                  <>
                    <Play className="size-4" />
                    Start Recording
                  </>
                )}
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4 pt-2">
            <div className="flex items-center gap-2 rounded-lg border border-blue-500/20 bg-blue-500/5 px-3 py-2">
              <Loader2 className="size-4 animate-spin text-blue-400" />
              <p className="text-xs text-blue-300">
                {finalizeMut.isPending
                  ? 'Saving workflow…'
                  : workflowBrowserClosed
                  ? 'Chromium is closed — saving the workflow…'
                  : 'Browser is open — perform your workflow, then close it when done.'}
              </p>
            </div>
            {error ? <p className="text-sm text-red-400">{error}</p> : null}
          </div>
        )}

        {promoteToAuth ? (
          <div className="mt-4 rounded-lg border border-amber-500/20 bg-amber-500/5 p-4 space-y-3">
            <p className="text-sm font-medium text-amber-300">This looks like a login recording</p>
            <p className="text-xs text-zinc-400">
              We detected a password field in your recording. Would you like to save this as the plugin&apos;s
              authentication session instead of a regular workflow?
            </p>
            {error ? <p className="text-xs text-red-400">{error}</p> : null}
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                className="flex-1 border-white/10 bg-white/5 text-zinc-300"
                onClick={() => {
                  setPromoteToAuth(null)
                  setOpen(false)
                  setName('')
                  setCaptureHover(false)
                  setActiveSession(null)
                  onCreated()
                }}
                disabled={promoteAuthMut.isPending}
              >
                Keep as workflow
              </Button>
              <Button
                size="sm"
                className="flex-1 bg-amber-600 text-white hover:bg-amber-700"
                onClick={() => promoteAuthMut.mutate({ sessionId: promoteToAuth.sessionId })}
                disabled={promoteAuthMut.isPending}
              >
                {promoteAuthMut.isPending ? (
                  <><Loader2 className="size-4 animate-spin" /> Saving auth…</>
                ) : (
                  'Save as auth'
                )}
              </Button>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

// ─────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────

export function PluginDetailPage() {
  const { pluginId } = useParams<{ pluginId: string }>()
  const qc = useQueryClient()
  const [activeTab, setActiveTab] = useState<'auth' | 'workflows' | 'compiled'>('auth')
  const q = useQuery({
    queryKey: ['plugin', pluginId],
    queryFn: () => fetchPlugin(pluginId!),
    staleTime: 5_000,
    refetchInterval: 10_000,
    enabled: !!pluginId,
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['plugin', pluginId] })

  useEffect(() => {
    const hasAuth = q.data?.plugin.auth
    if (hasAuth === undefined) return
    setActiveTab((current) => {
      if (!hasAuth) return 'auth'
      return current === 'auth' ? 'workflows' : current
    })
  }, [q.data?.plugin.auth])

  if (q.isLoading) {
    return (
      <div className="h-full overflow-y-auto">
        <PageHeader title="Plugin" />
        <p className="px-6 py-6 text-sm text-zinc-500">Loading…</p>
      </div>
    )
  }

  if (q.isError || !q.data) {
    return (
      <div className="h-full overflow-y-auto">
        <PageHeader title="Plugin" />
        <p className="px-6 py-6 text-sm text-red-400">{(q.error as Error)?.message ?? 'Not found'}</p>
      </div>
    )
  }

  const plugin = q.data.plugin
  const workflowCount = plugin.workflows.length
  const compiledCount = plugin.workflows.filter((workflow) => workflow.status === 'compiled' && workflow.skill_id).length
  const tabLabelClass = (tab: 'auth' | 'workflows' | 'compiled') =>
    activeTab === tab ? 'truncate font-bold text-white' : 'truncate font-medium'
  const tabMetaClass = (tab: 'auth' | 'workflows' | 'compiled', activeColor: string) =>
    activeTab === tab ? `text-[11px] font-semibold ${activeColor}` : 'text-[11px] text-zinc-500'

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title={plugin.name}
        description={<span className="truncate font-mono text-xs text-zinc-500">{plugin.target_url}</span>}
      />
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3 text-xs text-zinc-400">
          <span>
            Auth:{' '}
            <span className={plugin.auth ? 'text-emerald-400' : 'text-amber-400'}>
              {plugin.auth ? 'captured' : 'required'}
            </span>
          </span>
          <span className="text-white/20">·</span>
          <span>{workflowCount} workflow{workflowCount !== 1 ? 's' : ''}</span>
          {plugin.build ? (
            <>
              <span className="text-white/20">·</span>
              <span>
                Last built{' '}
                {new Date(plugin.build.last_built_at * 1000).toLocaleString([], {
                  month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
                })}
              </span>
            </>
          ) : null}
        </div>

        <Tabs
          className="!w-full !flex-col gap-0"
          key={`${plugin.id}-${plugin.auth ? 'auth-captured' : 'needs-auth'}`}
          value={activeTab}
          onValueChange={(value) => setActiveTab(value as 'auth' | 'workflows' | 'compiled')}
        >
          <div className="w-full overflow-hidden rounded-xl border border-white/10 bg-[#101317]/95">
            <div className="border-b border-white/8 bg-black/20 px-4 pt-3">
              <TabsList className="!inline-flex h-auto !w-auto max-w-full gap-1 overflow-x-auto rounded-none border-0 bg-transparent p-0 text-zinc-400">
                <TabsTrigger
                  value="auth"
                  className="h-10 min-w-[8.5rem] flex-none cursor-pointer rounded-t-lg border border-b-0 border-transparent bg-transparent px-3 text-left text-xs data-active:border-white/10 data-active:bg-[#101317] data-active:text-amber-100"
                >
                  <KeyRound className="size-4" />
                  <span className={tabLabelClass('auth')}>Auth</span>
                  <span className={tabMetaClass('auth', plugin.auth ? 'text-emerald-300' : 'text-amber-300')}>
                    {plugin.auth ? 'Ready' : 'Required'}
                  </span>
                </TabsTrigger>
                <TabsTrigger
                  value="workflows"
                  className="h-10 min-w-[9rem] flex-none cursor-pointer rounded-t-lg border border-b-0 border-transparent bg-transparent px-3 text-left text-xs data-active:border-white/10 data-active:bg-[#101317] data-active:text-blue-100"
                >
                  <ListChecks className="size-4" />
                  <span className={tabLabelClass('workflows')}>Workflows</span>
                  <span className={tabMetaClass('workflows', 'text-blue-300')}>{workflowCount}</span>
                </TabsTrigger>
                <TabsTrigger
                  value="compiled"
                  className="h-10 min-w-[11rem] flex-none cursor-pointer rounded-t-lg border border-b-0 border-transparent bg-transparent px-3 text-left text-xs data-active:border-white/10 data-active:bg-[#101317] data-active:text-emerald-100"
                >
                  <PackageCheck className="size-4" />
                  <span className={tabLabelClass('compiled')}>Compiled Skills</span>
                  <span className={tabMetaClass('compiled', 'text-emerald-300')}>{compiledCount}/{workflowCount}</span>
                </TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="auth" className="mt-0">
              <AuthPanel plugin={plugin} onRefresh={refresh} />
            </TabsContent>

            <TabsContent value="workflows" className="mt-0">
              <section>
                <div className="flex flex-col gap-3 border-b border-white/8 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <h2 className="text-sm font-semibold text-white">Workflows</h2>
                    <p className="mt-1 text-xs text-zinc-500">Record and compile the automations this plugin exposes.</p>
                  </div>
                  <NewWorkflowDialog plugin={plugin} onCreated={refresh} />
                </div>
                <div className="p-5">
                  <Card className="border-white/8 bg-white/[0.03] shadow-none">
                    {plugin.workflows.length === 0 ? (
                      <CardContent className="flex flex-col items-center gap-2 py-10 text-center">
                        <p className="text-sm text-zinc-400">No workflows yet</p>
                        <p className="max-w-xs text-xs text-zinc-600">
                          {plugin.status !== 'ready'
                            ? 'Record login first, then add workflows.'
                            : 'Click "Create a Workflow" to record the first one.'}
                        </p>
                      </CardContent>
                    ) : (
                      <CardContent className="p-0">
                        {plugin.workflows.map((wf) => (
                          <WorkflowRow
                            key={wf.id}
                            workflow={wf}
                            pluginId={plugin.id}
                            onDelete={refresh}
                            onCompiled={() => {
                              refresh()
                              setActiveTab('compiled')
                            }}
                          />
                        ))}
                      </CardContent>
                    )}
                  </Card>
                </div>
              </section>
            </TabsContent>

            <TabsContent value="compiled" className="mt-0">
              <CompiledSkillsTab plugin={plugin} />
            </TabsContent>
          </div>
        </Tabs>
      </div>
    </div>
  )
}
