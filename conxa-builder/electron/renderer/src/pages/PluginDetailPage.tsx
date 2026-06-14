import { useEffect, useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { useNavigate, useParams } from 'react-router-dom'
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
import { fetchEntitlements } from '@/api/usageApi'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import {
  Check,
  ChevronRight,
  ExternalLink,
  Globe,
  KeyRound,
  ListChecks,
  Loader2,
  MousePointer2,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Zap,
} from 'lucide-react'

// ─────────────────────────────────────────────────
// Auth record dialog
// ─────────────────────────────────────────────────

function AuthRecordDialog({
  open,
  onOpenChange,
  plugin,
  onRefresh,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  plugin: Plugin
  onRefresh: () => void
}) {
  const [step, setStep] = useState<'guide' | 'record'>('guide')
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
    mutationFn: async () => finalizeAuth(plugin.id, activeSession!),
    onSuccess: () => {
      setActiveSession(null)
      setAutoFinalizing(false)
      onRefresh()
      onOpenChange(false)
    },
    onError: (e: Error) => {
      setError(e.message)
      setActiveSession(null)
      setAutoFinalizing(false)
    },
  })

  const reRecordMut = useMutation({
    mutationFn: () => reRecordAuth(plugin.id),
    onSuccess: () => { onRefresh(); onOpenChange(false) },
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

  function handleClose(v: boolean) {
    if (!v && isRecording && !autoFinalizing && !finalizeMut.isPending) return
    if (!v) { setStep('guide'); setError(''); setActiveSession(null); setAutoFinalizing(false) }
    onOpenChange(v)
  }

  const RECORD_STEPS = ['Open browser', 'Log in', 'Close to save']
  const recordStep = autoFinalizing ? 2 : 1

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="border-white/10 bg-[#0d0f12] text-zinc-100 sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-white">
            {plugin.auth ? 'Login Session' : 'Record Login'}
          </DialogTitle>
        </DialogHeader>

        {/* ── Already captured ── */}
        {plugin.auth ? (
          <div className="space-y-4 pt-1">
            <div className="flex items-center gap-4 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.04] p-4">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-emerald-500/20 bg-emerald-500/10">
                <ShieldCheck className="size-5 text-emerald-400" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-emerald-200">Login session active</p>
                <p className="mt-0.5 truncate text-xs text-emerald-100/50">
                  Captured{' '}
                  {new Date(plugin.auth.captured_at * 1000).toLocaleString([], {
                    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
                  })}
                </p>
              </div>
            </div>
            <p className="text-xs text-zinc-500">
              Re-recording will replace the existing session. The browser will open at your target URL — complete the full login flow, then close it.
            </p>
            {error ? <p className="rounded-xl border border-red-500/20 bg-red-500/[0.06] px-3 py-2 text-xs text-red-300">{error}</p> : null}
            <div className="flex gap-2">
              <Button variant="outline" className="flex-1 border-white/10 bg-white/[0.06] text-zinc-300" onClick={() => onOpenChange(false)}>
                Close
              </Button>
              <Button
                variant="outline"
                className="flex-1 border-amber-500/30 bg-amber-500/10 text-amber-200 hover:bg-amber-500/20"
                onClick={() => reRecordMut.mutate()}
                disabled={reRecordMut.isPending}
              >
                {reRecordMut.isPending
                  ? <><Loader2 className="size-4 animate-spin" />Re-recording…</>
                  : <><RefreshCw className="size-4" />Re-record Login</>}
              </Button>
            </div>
          </div>

        ) : isRecording ? (
          /* ── Recording in progress ── */
          <div className="space-y-5 pt-1">
            <div className="flex items-center">
              {RECORD_STEPS.map((s, i) => {
                const done = i < recordStep
                const current = i === recordStep
                return (
                  <div key={s} className="flex items-center" style={{ flex: i < RECORD_STEPS.length - 1 ? '1' : undefined }}>
                    <div className="flex flex-col items-center gap-1.5">
                      <div className={cn(
                        'flex size-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold transition-all',
                        done ? 'bg-emerald-500 text-white' : current ? 'bg-sky-500 text-white ring-2 ring-sky-500/30' : 'bg-white/8 text-zinc-600',
                      )}>
                        {done ? <Check className="size-3" /> : current && !autoFinalizing ? <Loader2 className="size-3 animate-spin" /> : i + 1}
                      </div>
                      <span className={cn('whitespace-nowrap text-[11px] font-medium', done ? 'text-emerald-300' : current ? 'text-sky-300' : 'text-zinc-600')}>
                        {s}
                      </span>
                    </div>
                    {i < RECORD_STEPS.length - 1 && (
                      <div className={cn('mb-4 mx-3 h-px flex-1 transition-colors duration-500', done ? 'bg-emerald-500/40' : 'bg-white/8')} />
                    )}
                  </div>
                )
              })}
            </div>
            <p className="text-xs leading-5 text-sky-100/70">
              {autoFinalizing
                ? 'Browser closed — saving your session…'
                : 'Browser is open. Log in, navigate to the page where workflows should start, then close the browser.'}
            </p>
            {!autoFinalizing && (
              <div className="flex gap-2">
                <Button size="sm" variant="outline" className="flex-1 border-white/10 bg-white/[0.06] text-zinc-300 hover:bg-white/10 hover:text-white" onClick={() => setActiveSession(null)} disabled={finalizeMut.isPending}>
                  Cancel
                </Button>
                <Button size="sm" className="flex-1 bg-sky-600 text-white hover:bg-sky-500" onClick={() => finalizeMut.mutate()} disabled={finalizeMut.isPending}>
                  {finalizeMut.isPending ? <><Loader2 className="size-4 animate-spin" />Saving session…</> : 'Save Session Now'}
                </Button>
              </div>
            )}
            {error ? <p className="rounded-xl border border-red-500/20 bg-red-500/[0.06] px-3 py-2 text-xs text-red-300">{error}</p> : null}
          </div>

        ) : step === 'guide' ? (
          /* ── Guide: how it works ── */
          <div className="space-y-5 pt-1">
            <div className="space-y-3">
              <p className="text-xs font-semibold text-zinc-300">How it works</p>
              {[
                'A browser opens at your target URL.',
                'Complete the full login flow, including 2FA or SSO.',
                'Navigate to the page where workflows should begin.',
                'Close the browser — the session is saved automatically.',
              ].map((text, i) => (
                <div key={i} className="flex items-start gap-3">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-white/8 text-[11px] font-bold text-zinc-400">{i + 1}</span>
                  <p className="text-xs leading-5 text-zinc-400">{text}</p>
                </div>
              ))}
            </div>
            <div className="border-t border-white/8" />
            <div className="space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Best practices</p>
              {[
                "Complete the full flow before closing — partial sessions won't work.",
                "Land on your app's actual starting page, not the login page.",
                'Re-record whenever credentials or cookies change.',
              ].map((tip) => (
                <p key={tip} className="text-xs leading-5 text-zinc-500"><span className="mr-1.5 text-zinc-600">·</span>{tip}</p>
              ))}
            </div>
            <Button className="w-full bg-amber-500 font-medium text-zinc-950 hover:bg-amber-400" onClick={() => setStep('record')}>
              Continue →
            </Button>
          </div>

        ) : (
          /* ── Record: target URL + launch ── */
          <div className="space-y-4 pt-1">
            <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
              <div className="flex items-center gap-1.5 mb-1.5">
                <Globe className="size-3.5 text-zinc-500" />
                <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Target URL</p>
              </div>
              <p className="truncate font-mono text-sm text-zinc-200">{plugin.target_url}</p>
              <p className="mt-2 text-xs text-zinc-500">Log in, navigate to the starting page, then close the browser.</p>
            </div>
            {error ? <p className="rounded-xl border border-red-500/20 bg-red-500/[0.06] px-3 py-2 text-xs text-red-300">{error}</p> : null}
            <div className="flex flex-col gap-2">
              <Button
                className="h-10 w-full bg-amber-500 font-medium text-zinc-950 hover:bg-amber-400"
                onClick={() => startMut.mutate()}
                disabled={startMut.isPending}
              >
                {startMut.isPending ? <><Loader2 className="size-4 animate-spin" />Launching browser…</> : <><Play className="size-4" />Record Login</>}
              </Button>
              <button type="button" onClick={() => setStep('guide')} className="text-center text-xs text-zinc-500 transition-colors hover:text-zinc-300">
                ← Back to guide
              </button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
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

  const isCompiled = workflow.status === 'compiled' && !!workflow.skill_id
  const isTested = workflow.last_test_status === 'passed'

  const PIPELINE = [
    { label: 'Recorded', done: true },
    { label: 'Compiled', done: isCompiled },
    { label: 'Tested', done: isTested },
    { label: 'Installed', done: false },
  ]

  return (
    <div className="group border-t border-white/6 px-5 py-4 first:border-t-0 transition-colors hover:bg-white/[0.02]">
      {/* Top row */}
      <div className="flex items-center gap-4">
        <div className={cn('size-2 shrink-0 rounded-full', isCompiled ? 'bg-emerald-400' : 'bg-zinc-600')} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium leading-snug text-white">{workflow.name}</p>
          <p className="mt-0.5 text-[11px] text-zinc-500">
            Recorded{' '}
            {new Date(workflow.recorded_at * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
          </p>
        </div>
        <Badge
          variant="outline"
          className={cn('shrink-0 text-[10px] font-medium', isCompiled ? 'border-emerald-500/30 bg-emerald-500/[0.08] text-emerald-300' : 'border-white/10 bg-white/[0.04] text-zinc-400')}
        >
          {isCompiled ? 'compiled' : 'recorded'}
        </Badge>
        <div className="flex shrink-0 items-center gap-1.5">
          {!workflow.skill_id ? (
            <Button size="sm" variant="outline" className="border-amber-500/30 bg-amber-500/[0.06] text-amber-300 hover:bg-amber-500/10" onClick={handleCompile}>
              <Play className="size-3.5" /> Compile
            </Button>
          ) : (
            <>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button size="sm" variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300 hover:border-amber-500/30 hover:bg-amber-500/[0.06] hover:text-amber-300">
                    <RefreshCw className="size-3.5" /> Recompile
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent className="border-white/10 bg-[#0d0f12] text-zinc-100">
                  <AlertDialogHeader>
                    <AlertDialogTitle className="text-white">Recompile &ldquo;{workflow.name}&rdquo;?</AlertDialogTitle>
                    <AlertDialogDescription className="text-zinc-400">
                      This rebuilds the skill package from the original raw recording and uses the Human Edit pool. Saved editor changes will be replaced.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel className="border-white/10 bg-white/5 text-zinc-200">Cancel</AlertDialogCancel>
                    <AlertDialogAction className="bg-amber-600 text-white hover:bg-amber-700" onClick={handleRecompile}>Recompile</AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
              <Button size="sm" variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300 hover:text-white" onClick={() => navigate(`/edit/${encodeURIComponent(workflow.skill_id!)}?from=/plugins/${encodeURIComponent(pluginId)}`)}>
                Edit
              </Button>
            </>
          )}
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button size="icon-sm" variant="ghost" className="text-zinc-600 hover:text-red-400">
                <Trash2 className="size-4" />
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent className="border-white/10 bg-[#0d0f12] text-zinc-100">
              <AlertDialogHeader>
                <AlertDialogTitle className="text-white">Delete &ldquo;{workflow.name}&rdquo;?</AlertDialogTitle>
                <AlertDialogDescription className="text-zinc-400">This removes the workflow recording from this plugin.</AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel className="border-white/10 bg-white/5 text-zinc-200">Cancel</AlertDialogCancel>
                <AlertDialogAction className="bg-red-600 text-white hover:bg-red-700" onClick={() => deleteMut.mutate()}>Delete</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      {/* Pipeline bar */}
      <div className="ml-6 mt-3 flex items-center">
        {PIPELINE.map((stage, i) => (
          <div key={stage.label} className="flex items-center" style={{ flex: i < PIPELINE.length - 1 ? '1' : undefined }}>
            <div className="flex flex-col items-center gap-1">
              <div className={cn(
                'flex size-3.5 shrink-0 items-center justify-center rounded-full',
                stage.done ? 'bg-emerald-500' : 'border border-white/20 bg-transparent',
              )}>
                {stage.done && <Check className="size-2 text-white" />}
              </div>
              <span className={cn('whitespace-nowrap text-[10px] font-medium', stage.done ? 'text-emerald-400' : 'text-zinc-600')}>
                {stage.label}
              </span>
            </div>
            {i < PIPELINE.length - 1 && (
              <div className={cn(
                'mb-3.5 mx-2 h-px flex-1',
                stage.done && PIPELINE[i + 1].done ? 'bg-emerald-500/50' : stage.done ? 'bg-emerald-500/30' : 'bg-white/8',
              )} />
            )}
          </div>
        ))}
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
  triggerElement,
}: {
  plugin: Plugin
  onCreated: () => void
  triggerElement?: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<1 | 2>(1)
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
    mutationFn: () => finalizeWorkflow(plugin.id, activeSession!.workflowId, activeSession!.sessionId),
    onSuccess: async (data) => {
      if (data.workflow_kind === 'login') {
        setPromoteToAuth({ sessionId: data.session_id, workflowId: data.workflow_id })
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

  const defaultTrigger = (
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
  )

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && activeSession && !workflowBrowserClosed && !finalizeMut.isPending) return
        if (!nextOpen) setStep(1)
        setOpen(nextOpen)
      }}
    >
      <DialogTrigger asChild>
        {triggerElement ?? defaultTrigger}
      </DialogTrigger>

      <DialogContent className="border-white/10 bg-[#0d0f12] text-zinc-100">
        <DialogHeader>
          <DialogTitle className="text-white">Record Workflow</DialogTitle>
        </DialogHeader>

        {!isRecording && step === 1 ? (
          <div className="space-y-5 pt-1">
            <div className="space-y-3">
              <p className="text-xs font-semibold text-zinc-300">How it works</p>
              {[
                'Name your workflow on the next screen, then click "Start Recording".',
                'Perform the workflow naturally in the browser — every action is captured.',
                'Close the browser when done to finalize the recording.',
              ].map((text, i) => (
                <div key={i} className="flex items-start gap-3">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-white/8 text-[11px] font-bold text-zinc-400">{i + 1}</span>
                  <p className="text-xs leading-5 text-zinc-400">{text}</p>
                </div>
              ))}
            </div>
            <div className="border-t border-white/8" />
            <div className="space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Best practices</p>
              {[
                'Keep each workflow focused on a single task.',
                <span key="var">Use <code className="font-mono text-zinc-300">{'{{variable}}'}</code> placeholders for dynamic values.</span>,
                'Never record passwords — use template variables instead.',
                'One clean pass only — no backtracking.',
              ].map((tip, i) => (
                <p key={i} className="text-xs leading-5 text-zinc-500"><span className="mr-1.5 text-zinc-600">·</span>{tip}</p>
              ))}
            </div>
            <Button className="w-full" onClick={() => setStep(2)}>Next →</Button>
          </div>

        ) : !isRecording ? (
          <div className="space-y-4 pt-1">
            <div className="space-y-1.5">
              <Label className="text-zinc-300">Workflow name</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Create new service" className="border-white/10 bg-white/5 text-zinc-100" />
            </div>
            {requiredVars.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-zinc-400">URL variables <span className="text-zinc-600">(optional)</span></p>
                {requiredVars.map((varName) => (
                  <div key={varName} className="space-y-1">
                    <Label className="text-xs text-zinc-400">{varName}</Label>
                    <Input value={urlVariables[varName] || ''} onChange={(e) => setUrlVariables((prev) => ({ ...prev, [varName]: e.target.value }))} placeholder={`Enter ${varName} (optional)`} className="border-white/10 bg-white/5 text-zinc-100 h-8" />
                  </div>
                ))}
              </div>
            )}
            <div className="flex items-start gap-3 rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2.5">
              <Checkbox id="workflowCaptureHover" checked={captureHover} disabled={startMut.isPending} onCheckedChange={(checked) => setCaptureHover(checked === true)} className="mt-0.5" />
              <Label htmlFor="workflowCaptureHover" className="grid min-w-0 cursor-pointer gap-1">
                <span className="flex items-center gap-2 text-sm font-medium text-zinc-200"><MousePointer2 className="size-3.5 text-zinc-400" />Workflow contains hover-only elements</span>
                <span className="text-xs leading-5 text-zinc-500">Turn this on when menus, tooltips, or drawers only appear after hovering.</span>
              </Label>
            </div>
            <p className="text-xs text-zinc-500">
              The browser will open pre-authenticated at{' '}
              <span className="font-mono text-zinc-300">
                {requiredVars.some((v) => urlVariables[v])
                  ? requiredVars.reduce((url, varName) => url.replace(new RegExp(`{{\\s*${varName}\\s*}}`), urlVariables[varName] || `{{${varName}}}`), workflowStartUrl)
                  : workflowStartUrl}
              </span>.
            </p>
            {error ? <p className="text-sm text-red-400">{error}</p> : null}
            <div className="flex gap-2">
              <Button size="sm" variant="outline" className="flex-1 border-white/10 bg-white/5 text-zinc-300" onClick={() => { setName(''); setUrlVariables({}); setCaptureHover(false); setError('') }}>Clear</Button>
              <Button className="flex-1" onClick={() => startMut.mutate()} disabled={!name || startMut.isPending || !canRecordWorkflow}>
                {startMut.isPending ? <><Loader2 className="size-4 animate-spin" />Launching browser…</> : !canRecordWorkflow ? 'Record auth first' : <><Play className="size-4" />Start Recording</>}
              </Button>
            </div>
          </div>

        ) : (
          <div className="space-y-4 pt-1">
            <div className="flex items-center gap-2 rounded-lg border border-blue-500/20 bg-blue-500/5 px-3 py-2">
              <Loader2 className="size-4 animate-spin text-blue-400" />
              <p className="text-xs text-blue-300">
                {finalizeMut.isPending ? 'Saving workflow…' : workflowBrowserClosed ? 'Browser closed — saving the workflow…' : 'Browser is open — perform your workflow, then close it when done.'}
              </p>
            </div>
            {error ? <p className="text-sm text-red-400">{error}</p> : null}
          </div>
        )}

        {promoteToAuth ? (
          <div className="mt-4 rounded-lg border border-amber-500/20 bg-amber-500/5 p-4 space-y-3">
            <p className="text-sm font-medium text-amber-300">This looks like a login recording</p>
            <p className="text-xs text-zinc-400">We detected a password field. Would you like to save this as the plugin&apos;s authentication session instead of a workflow?</p>
            {error ? <p className="text-xs text-red-400">{error}</p> : null}
            <div className="flex gap-2">
              <Button size="sm" variant="outline" className="flex-1 border-white/10 bg-white/5 text-zinc-300" onClick={() => { setPromoteToAuth(null); setOpen(false); setName(''); setCaptureHover(false); setActiveSession(null); onCreated() }} disabled={promoteAuthMut.isPending}>Keep as workflow</Button>
              <Button size="sm" className="flex-1 bg-amber-600 text-white hover:bg-amber-700" onClick={() => promoteAuthMut.mutate({ sessionId: promoteToAuth.sessionId })} disabled={promoteAuthMut.isPending}>
                {promoteAuthMut.isPending ? <><Loader2 className="size-4 animate-spin" />Saving auth…</> : 'Save as auth'}
              </Button>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function fmtTokens(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`
  return String(n)
}

// ─────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────

export function PluginDetailPage() {
  const { pluginId } = useParams<{ pluginId: string }>()
  const qc = useQueryClient()
  const [authDialogOpen, setAuthDialogOpen] = useState(false)

  const q = useQuery({
    queryKey: ['plugin', pluginId],
    queryFn: () => fetchPlugin(pluginId!),
    staleTime: 5_000,
    refetchInterval: 10_000,
    enabled: !!pluginId,
  })
  const entitlementsQ = useQuery({
    queryKey: ['entitlements'],
    queryFn: fetchEntitlements,
    staleTime: 30_000,
    retry: 1,
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['plugin', pluginId] })

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
  const compiledCount = plugin.workflows.filter((wf) => wf.status === 'compiled' && wf.skill_id).length
  const compileMeter = entitlementsQ.data?.meters?.compile_credits
  const editMeter = entitlementsQ.data?.meters?.human_edit_tokens
  const canRecordWorkflow = plugin.status === 'ready' && !!plugin.auth

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title={plugin.name}
        description={
          <a
            href={plugin.target_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 truncate font-mono text-xs text-sky-400 transition-colors hover:text-sky-300"
          >
            {plugin.target_url}
            <ExternalLink className="size-3 shrink-0" />
          </a>
        }
      />

      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">

        {/* ── 4 stat cards ── */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="flex items-center gap-3 rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3">
            <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg border', plugin.auth ? 'border-emerald-500/20 bg-emerald-500/[0.08]' : 'border-amber-500/20 bg-amber-500/[0.08]')}>
              <KeyRound className={cn('size-4', plugin.auth ? 'text-emerald-400' : 'text-amber-400')} />
            </span>
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Auth</p>
              <p className={cn('text-xs font-semibold', plugin.auth ? 'text-emerald-300' : 'text-amber-300')}>{plugin.auth ? 'Connected' : 'Required'}</p>
              <p className="text-[10px] text-zinc-600">{plugin.auth ? `Recorded ${new Date(plugin.auth.captured_at * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' })}` : 'Not recorded'}</p>
            </div>
          </div>

          <div className="flex items-center gap-3 rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-sky-500/20 bg-sky-500/[0.08]">
              <ListChecks className="size-4 text-sky-400" />
            </span>
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Workflows</p>
              <p className="text-xs font-semibold text-sky-300">{compiledCount} / {workflowCount} compiled</p>
              <p className="text-[10px] text-zinc-600">Active workflows</p>
            </div>
          </div>

          <div className="flex items-center gap-3 rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-violet-500/20 bg-violet-500/[0.08]">
              <Zap className="size-4 text-violet-400" />
            </span>
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Compile</p>
              <p className="text-xs font-semibold text-zinc-200">
                {compileMeter ? (compileMeter.unlimited ? `${compileMeter.used} used` : `${compileMeter.used} / ${compileMeter.limit}`) : '—'}
              </p>
              <p className="text-[10px] text-zinc-600">Compiles used</p>
            </div>
          </div>

          <div className="flex items-center gap-3 rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-rose-500/20 bg-rose-500/[0.08]">
              <Pencil className="size-4 text-rose-400" />
            </span>
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Human Edit</p>
              <p className="text-xs font-semibold text-zinc-200">
                {editMeter ? (editMeter.unlimited ? `${fmtTokens(editMeter.used)} used` : `${fmtTokens(editMeter.used)} / ${editMeter.limit ? fmtTokens(editMeter.limit) : '∞'}`) : '—'}
              </p>
              <p className="text-[10px] text-zinc-600">Edits used</p>
            </div>
          </div>
        </div>

        {/* ── Action cards ── */}
        <div className="grid grid-cols-2 gap-4">
          {/* Record Login */}
          <button
            type="button"
            onClick={() => setAuthDialogOpen(true)}
            className="flex items-center gap-4 rounded-xl border border-white/8 bg-white/[0.03] p-5 text-left transition-all hover:border-white/15 hover:bg-white/[0.05]"
          >
            <span className={cn(
              'flex size-11 shrink-0 items-center justify-center rounded-xl border',
              plugin.auth ? 'border-emerald-500/20 bg-emerald-500/[0.1]' : 'border-amber-500/20 bg-amber-500/[0.1]',
            )}>
              {plugin.auth ? <ShieldCheck className="size-5 text-emerald-400" /> : <KeyRound className="size-5 text-amber-400" />}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <p className="text-sm font-semibold text-white">Record Login</p>
                <span className={cn(
                  'rounded-md px-1.5 py-0.5 text-[10px] font-semibold',
                  plugin.auth ? 'bg-emerald-500/10 text-emerald-300' : 'bg-amber-500/10 text-amber-300',
                )}>
                  {plugin.auth ? 'Session active' : 'Required'}
                </span>
              </div>
              <p className="mt-0.5 text-xs text-zinc-500">Record your login/authentication steps to connect to your application.</p>
            </div>
            <ChevronRight className="size-4 shrink-0 text-zinc-600" />
          </button>

          {/* Create Workflow */}
          <NewWorkflowDialog
            plugin={plugin}
            onCreated={refresh}
            triggerElement={
              <button
                type="button"
                disabled={!canRecordWorkflow}
                className={cn(
                  'flex w-full items-center gap-4 rounded-xl border p-5 text-left transition-all',
                  canRecordWorkflow
                    ? 'border-white/8 bg-white/[0.03] hover:border-white/15 hover:bg-white/[0.05]'
                    : 'cursor-not-allowed border-white/5 bg-white/[0.015] opacity-60',
                )}
              >
                <span className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-violet-500/20 bg-violet-500/[0.1]">
                  <Plus className="size-5 text-violet-400" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-white">Create Workflow</p>
                  <p className="mt-0.5 text-xs text-zinc-500">
                    {canRecordWorkflow ? 'Record and compile a new workflow to automate your tasks.' : 'Record login first to unlock workflow recording.'}
                  </p>
                </div>
                <ChevronRight className="size-4 shrink-0 text-zinc-600" />
              </button>
            }
          />
        </div>

        {/* ── Workflows section ── */}
        <section>
          <div className="mb-4 flex items-center justify-between gap-4">
            <div>
              <h2 className="text-sm font-semibold text-white">Workflows</h2>
              <p className="mt-0.5 text-xs text-zinc-500">Record and compile the automations this plugin exposes.</p>
            </div>
            <div className="flex items-center gap-2">
              {workflowCount > 0 && (
                <span className="rounded-md border border-white/8 bg-white/[0.04] px-2 py-0.5 text-[11px] font-medium text-zinc-400">{workflowCount}</span>
              )}
              <NewWorkflowDialog plugin={plugin} onCreated={refresh} />
            </div>
          </div>

          {plugin.workflows.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-white/8 py-16 text-center">
              <div className="rounded-full border border-white/8 bg-white/[0.03] p-4">
                <ListChecks className="size-7 text-zinc-700" />
              </div>
              <div>
                <p className="text-sm font-medium text-zinc-400">No workflows yet</p>
                <p className="mt-1 max-w-xs text-xs text-zinc-600">
                  {plugin.status !== 'ready' ? 'Record login first, then add workflows.' : 'Create your first workflow to start automating.'}
                </p>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-white/8 bg-white/[0.02]">
              {plugin.workflows.map((wf) => (
                <WorkflowRow key={wf.id} workflow={wf} pluginId={plugin.id} onDelete={refresh} onCompiled={refresh} />
              ))}
            </div>
          )}
        </section>
      </div>

      <AuthRecordDialog
        open={authDialogOpen}
        onOpenChange={setAuthDialogOpen}
        plugin={plugin}
        onRefresh={refresh}
      />
    </div>
  )
}
