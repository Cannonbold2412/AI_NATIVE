'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CompiledSkillsTab } from '@/components/CompiledSkillsTab'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { Copy, FileJson, KeyRound, Loader2, MousePointer2, Play, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { usePluginWorkflowCompileTracker } from '@/hooks/usePluginWorkflowCompileTracker'

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
    <Card className="border-white/8 bg-white/[0.03] shadow-none">
      <CardHeader className="flex-row items-center justify-between border-b border-white/8 pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium text-white">
          <KeyRound className="size-4 text-amber-400" />
          Authentication
        </CardTitle>
        {plugin.auth ? (
          <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-300">
            Captured ✓
          </Badge>
        ) : (
          <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-amber-300">
            Required
          </Badge>
        )}
      </CardHeader>
      <CardContent className="space-y-3 pt-4">
        {plugin.auth ? (
          <div className="space-y-2 text-xs text-zinc-400">
            <p>
              Session captured{' '}
              {new Date(plugin.auth.captured_at * 1000).toLocaleString([], {
                month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
              })}
            </p>
            <p className="text-zinc-500">
              Re-record to refresh an expired session. Existing workflows are unaffected.
            </p>
            <Button
              size="sm"
              variant="outline"
              className="border-white/10 bg-white/5 text-zinc-300"
              onClick={() => reRecordMut.mutate()}
              disabled={reRecordMut.isPending}
            >
              <RefreshCw className="size-3.5" />
              Re-record Auth
            </Button>
          </div>
        ) : isRecording ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 rounded-lg border border-blue-500/20 bg-blue-500/5 px-3 py-2">
              <Loader2 className="size-4 animate-spin text-blue-400" />
              <p className="text-xs text-blue-300">
                {autoFinalizing ? 'Chromium closed, saving session…' : 'Browser is open — log in, navigate to the page where workflows should start, then close Chromium.'}
              </p>
            </div>
            {!autoFinalizing && (
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="flex-1 border-white/10 bg-white/5 text-zinc-300"
                  onClick={() => setActiveSession(null)}
                  disabled={finalizeMut.isPending}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  className="flex-1"
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
          <div className="space-y-2">
            <p className="text-xs text-zinc-500">
              A browser will open at <span className="font-mono text-zinc-300">{plugin.target_url}</span>.
              Log in, navigate to the page where workflows should start, then close Chromium.
            </p>
            <Button
              size="sm"
              className="w-full"
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
        {error ? <p className="text-xs text-red-400">{error}</p> : null}
      </CardContent>
    </Card>
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
  const router = useRouter()
  const [showJson, setShowJson] = useState(false)
  const [jsonData, setJsonData] = useState<unknown>(null)
  const [loadingJson, setLoadingJson] = useState(false)
  const compileCompletedRef = useRef(false)
  const { clearCompile, getCompile, isCompileActive } = usePluginWorkflowCompileTracker()
  const compileEntry = getCompile(pluginId, workflow.id)
  const isCompiling = isCompileActive(pluginId, workflow.id)
  const compileError = compileEntry?.error ?? ''

  const deleteMut = useMutation({
    mutationFn: () => deleteWorkflow(pluginId, workflow.id),
    onSuccess: onDelete,
  })

  useEffect(() => {
    if (isCompiling) {
      compileCompletedRef.current = true
      return
    }
    if (compileCompletedRef.current && workflow.skill_id) {
      compileCompletedRef.current = false
      onCompiled()
    }
  }, [isCompiling, onCompiled, workflow.skill_id])

  useEffect(() => {
    if (workflow.skill_id && compileEntry) {
      clearCompile(pluginId, workflow.id)
    }
  }, [clearCompile, compileEntry, pluginId, workflow.id, workflow.skill_id])

  const handleViewJson = async () => {
    setLoadingJson(true)
    try {
      const response = await fetch(`/api/v1/record/${workflow.session_id}/events`)
      if (!response.ok) throw new Error('Failed to fetch events')
      const data = await response.json()
      setJsonData(data)
      setShowJson(true)
    } catch (e) {
      console.error('Failed to load JSON:', e)
    } finally {
      setLoadingJson(false)
    }
  }

  const handleCompile = () => {
    router.push(`/plugins/${encodeURIComponent(pluginId)}/workflows/${encodeURIComponent(workflow.id)}/compile?start=1`)
  }

  const handleRecompile = () => {
    if (!workflow.skill_id) return
    router.push(
      `/plugins/${encodeURIComponent(pluginId)}/workflows/${encodeURIComponent(workflow.id)}/compile?start=1&mode=recompile`,
    )
  }

  return (
    <>
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
            <Button
              size="icon-sm"
              variant="ghost"
              className="text-zinc-500 hover:text-blue-400"
              onClick={handleViewJson}
              disabled={loadingJson}
              title="View JSON"
            >
              <FileJson className="size-4" />
            </Button>
            {!workflow.skill_id ? (
              <Button
                size="sm"
                variant="outline"
                className="border-amber-500/30 bg-amber-500/5 text-amber-300 hover:bg-amber-500/10"
                onClick={handleCompile}
                disabled={isCompiling}
              >
                {isCompiling ? (
                  <><Loader2 className="size-3.5 animate-spin" /> Compiling… (15–40s)</>
                ) : (
                  <><Play className="size-3.5" /> Compile</>
                )}
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
                      This rebuilds the skill package from the original raw recording. Saved editor changes to
                      selectors, validation, screenshots, and inputs will be replaced by the fresh compile.
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
        {compileError ? (
          <p className="text-xs text-red-400 px-0.5">{compileError}</p>
        ) : null}
      </div>

      {/* JSON Viewer Modal */}
      {showJson && (
        <Dialog open={showJson} onOpenChange={setShowJson}>
          <DialogContent className="border-white/10 bg-[#0d0f12] text-zinc-100 max-w-2xl max-h-[80vh]">
            <DialogHeader>
              <DialogTitle className="text-white">Workflow JSON - {workflow.name}</DialogTitle>
            </DialogHeader>
            <div className="overflow-y-auto max-h-[60vh] rounded-lg border border-white/10 bg-black/30 p-4">
              <pre className="text-xs text-zinc-300 whitespace-pre-wrap break-words font-mono">
                {JSON.stringify(jsonData, null, 2)}
              </pre>
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                className="border-white/10 bg-white/5 text-zinc-300"
                onClick={() => {
                  navigator.clipboard.writeText(JSON.stringify(jsonData, null, 2))
                }}
              >
                <Copy className="size-4 mr-2" />
                Copy JSON
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="flex-1 border-white/10 bg-white/5 text-zinc-300"
                onClick={() => setShowJson(false)}
              >
                Close
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
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

  // Extract variable names from protected_url (e.g., {{team_url}} → ['team_url'])
  const varPattern = /\{\{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*\}\}/g
  const requiredVars = Array.from(plugin.protected_url.matchAll(varPattern), (m) => m[1])
  const hasProtectedUrl = !!plugin.protected_url.trim()

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
      const workflowId = data.workflow_id

      // If the classifier detected a login recording, prompt to save as auth instead.
      if (data.workflow_kind === 'login') {
        setPromoteToAuth({ sessionId, workflowId })
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
          disabled={plugin.status !== 'ready' || !hasProtectedUrl}
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
            <div
              className="flex items-start gap-3 rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2.5"
            >
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
                      plugin.protected_url,
                    )
                  : plugin.protected_url}
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
                disabled={
                  !name ||
                  startMut.isPending ||
                  plugin.status !== 'ready' ||
                  !hasProtectedUrl
                }
              >
                {startMut.isPending ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    Launching browser…
                  </>
                ) : plugin.status !== 'ready' || !hasProtectedUrl ? (
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

        {/* Auth-promote dialog — shown when the classifier detects a login recording */}
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

export function PluginDetailPage({ pluginId }: { pluginId: string }) {
  const qc = useQueryClient()
  const [activeTab, setActiveTab] = useState<'auth' | 'workflows' | 'compiled'>('auth')
  const q = useQuery({
    queryKey: ['plugin', pluginId],
    queryFn: () => fetchPlugin(pluginId),
    staleTime: 5_000,
    refetchInterval: 10_000,
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

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title={plugin.name}
        description={<span className="truncate font-mono text-xs text-zinc-500">{plugin.target_url}</span>}
      />
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-6 sm:px-6">
        {/* Status bar */}
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3 text-xs text-zinc-400">
          <span>
            Auth:{' '}
            <span className={plugin.auth ? 'text-emerald-400' : 'text-amber-400'}>
              {plugin.auth ? 'captured' : 'required'}
            </span>
          </span>
          <span className="text-white/20">·</span>
          <span>{plugin.workflows.length} workflow{plugin.workflows.length !== 1 ? 's' : ''}</span>
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
          key={`${plugin.id}-${plugin.auth ? 'auth-captured' : 'needs-auth'}`}
          value={activeTab}
          onValueChange={(value) => setActiveTab(value as 'auth' | 'workflows' | 'compiled')}
        >
          <TabsList className="border border-white/10 bg-white/[0.03] text-zinc-400">
            <TabsTrigger value="auth">Auth</TabsTrigger>
            <TabsTrigger value="workflows">Workflows</TabsTrigger>
            <TabsTrigger value="compiled">Compiled Skills</TabsTrigger>
          </TabsList>

          <TabsContent value="auth" className="mt-4">
            <AuthPanel plugin={plugin} onRefresh={refresh} />
          </TabsContent>

          <TabsContent value="workflows" className="mt-4">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-medium text-zinc-300">Workflows</h2>
                <NewWorkflowDialog plugin={plugin} onCreated={refresh} />
              </div>
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
                        onCompiled={() => setActiveTab('compiled')}
                      />
                    ))}
                  </CardContent>
                )}
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="compiled" className="mt-4">
            <CompiledSkillsTab plugin={plugin} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
