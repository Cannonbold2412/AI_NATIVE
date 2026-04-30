import { type ChangeEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useRecordingSession } from './hooks/useRecordingSession'
import { AppShell } from '@/components/layout/AppLayout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Activity,
  ArrowRight,
  CircleDot,
  ClipboardList,
  Gauge,
  Pencil,
  Play,
  Sparkles,
} from 'lucide-react'

function FlowStatusBadge({
  isRecording,
  isCompiling,
}: {
  isRecording: boolean
  isCompiling: boolean
}) {
  if (isCompiling) {
    return <Badge className="border-emerald-400/20 bg-emerald-400/12 text-emerald-200">Compiling</Badge>
  }
  if (isRecording) {
    return <Badge className="border-sky-400/20 bg-sky-400/12 text-sky-200">Recording</Badge>
  }
  return <Badge variant="secondary">Ready</Badge>
}

function metricPreviewValue(value: unknown) {
  if (typeof value === 'number') return value.toLocaleString()
  if (typeof value === 'string' && value.trim().length > 0) return value
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (Array.isArray(value)) return `${value.length} items`
  if (value && typeof value === 'object') return 'Object'
  return 'n/a'
}

const workflowNotes = [
  'Launch a headed browser from the target URL.',
  'Close the browser when the capture is complete.',
  'Open the compiled package directly in Human edit.',
]

export function HomePage() {
  const navigate = useNavigate()
  const {
    startUrl,
    setStartUrl,
    skillTitle,
    setSkillTitle,
    flowStatus,
    logLines,
    isRecording,
    isCompiling,
    metrics,
    sessionId,
    startFlow,
  } = useRecordingSession({
    onCompileSuccess: (id) => navigate(`/edit/${id}`),
  })

  const metricEntries = Object.entries(metrics ?? {})
  const metricHighlights = metricEntries.slice(0, 3)

  return (
    <AppShell
      title="Home"
      description="Record a browser workflow, compile it into a package, and move into review without leaving the workspace."
      mainClassName="overflow-y-auto"
      actions={
        <>
          <Button
            variant="outline"
            size="sm"
            asChild
            className="border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08]"
          >
            <Link to="/edit">
              <Pencil className="size-3.5" />
              Edit Skill
            </Link>
          </Button>
          <FlowStatusBadge isCompiling={isCompiling} isRecording={isRecording} />
        </>
      }
    >
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-4 sm:px-6 sm:py-5">
        <section className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_20rem]">
          <Card className="overflow-hidden border border-white/8 bg-[linear-gradient(180deg,rgba(255,255,255,0.06),rgba(255,255,255,0.03))] shadow-none">
            <CardHeader className="border-b border-white/8 pb-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.22em] text-zinc-500">
                    <Sparkles className="size-3.5" />
                    Capture Workspace
                  </div>
                  <CardTitle className="max-w-3xl text-[1.9rem] font-semibold tracking-[-0.03em] text-white sm:text-[2.35rem]">
                    Build reusable skills from live browser workflows.
                  </CardTitle>
                  <CardDescription className="max-w-2xl text-sm leading-6 text-zinc-400">
                    Start a session from any URL, capture the flow in a headed browser, and hand the compiled result directly to the editor for refinement.
                  </CardDescription>
                </div>
              </div>
            </CardHeader>

            <CardContent className="grid gap-4 pt-4">
              <div className="grid gap-3 md:grid-cols-2">
                <div className="grid gap-1.5">
                  <Label className="text-zinc-200" htmlFor="startUrl">
                    Start URL
                  </Label>
                  <Input
                    id="startUrl"
                    type="url"
                    placeholder="https://example.com"
                    value={startUrl}
                    onChange={(e: ChangeEvent<HTMLInputElement>) => setStartUrl(e.target.value)}
                    className="h-10 border-white/10 bg-black/20 text-zinc-100 placeholder:text-zinc-500"
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-zinc-200" htmlFor="skillName">
                    Skill name
                  </Label>
                  <Input
                    id="skillName"
                    type="text"
                    placeholder="Checkout flow"
                    value={skillTitle}
                    onChange={(e: ChangeEvent<HTMLInputElement>) => setSkillTitle(e.target.value)}
                    className="h-10 border-white/10 bg-black/20 text-zinc-100 placeholder:text-zinc-500"
                  />
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2.5">
                <Button
                  type="button"
                  size="lg"
                  disabled={isRecording || isCompiling}
                  onClick={() => void startFlow()}
                  className="h-10 min-w-44 bg-white text-black hover:bg-zinc-200"
                >
                  <Play className="size-4" />
                  Start recording
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="lg"
                  asChild
                  className="h-10 border-white/10 bg-white/[0.04] text-zinc-200 hover:bg-white/[0.08]"
                >
                  <Link to="/skills">
                    Open library
                    <ArrowRight className="size-4" />
                  </Link>
                </Button>
                <p className="text-sm text-zinc-400" id="flow-status" role="status" aria-live="polite">
                  {flowStatus}
                </p>
              </div>

              <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_16rem]">
                <div className="grid gap-2 rounded-xl border border-white/8 bg-black/20 p-3">
                  <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-zinc-500">
                    Workflow
                  </p>
                  <div className="grid gap-2 sm:grid-cols-3">
                    {workflowNotes.map((note, index) => (
                      <div key={note} className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
                        <div className="mb-1 flex items-center gap-2 text-xs font-medium text-zinc-300">
                          <CircleDot className="size-3 text-emerald-300" />
                          Step {index + 1}
                        </div>
                        <p className="text-sm leading-5 text-zinc-400">{note}</p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="grid gap-2 rounded-xl border border-white/8 bg-black/20 p-3">
                  <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-zinc-500">
                    Session
                  </p>
                  <div className="space-y-1">
                    <p className="text-xs text-zinc-500">Recorder id</p>
                    <p className="truncate text-sm font-medium text-white">
                      {sessionId ?? 'No active session'}
                    </p>
                  </div>
                  <div className="space-y-1">
                    <p className="text-xs text-zinc-500">Captured events</p>
                    <p className="text-2xl font-semibold tracking-[-0.03em] text-white">{logLines.length}</p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-4">
            <Card size="sm" className="border-white/8 bg-white/[0.035] shadow-none">
              <CardHeader className="border-b border-white/8">
                <div className="flex items-center gap-2">
                  <Gauge className="size-4 text-zinc-400" />
                  <CardTitle className="text-white">Operational summary</CardTitle>
                </div>
                <CardDescription className="text-zinc-500">
                  Immediate visibility into the current run.
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-2 pt-3">
                <div className="rounded-lg border border-white/8 bg-black/20 p-3">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-zinc-500">Status</p>
                  <div className="mt-2">
                    <FlowStatusBadge isCompiling={isCompiling} isRecording={isRecording} />
                  </div>
                </div>
                <div className="rounded-lg border border-white/8 bg-black/20 p-3">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-zinc-500">Flow message</p>
                  <p className="mt-2 text-sm leading-5 text-zinc-300">{flowStatus}</p>
                </div>
              </CardContent>
            </Card>

            <Card size="sm" className="border-white/8 bg-white/[0.035] shadow-none">
              <CardHeader className="border-b border-white/8">
                <div className="flex items-center gap-2">
                  <ClipboardList className="size-4 text-zinc-400" />
                  <CardTitle className="text-white">Metric highlights</CardTitle>
                </div>
                <CardDescription className="text-zinc-500">
                  Top-level counters from the backend metrics endpoint.
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-2 pt-3">
                {metricHighlights.length > 0 ? (
                  metricHighlights.map(([key, value]) => (
                    <div
                      key={key}
                      className="flex items-center justify-between gap-3 rounded-lg border border-white/8 bg-black/20 p-3"
                    >
                      <span className="truncate text-sm text-zinc-400">{key}</span>
                      <span className="shrink-0 text-sm font-medium text-white">
                        {metricPreviewValue(value)}
                      </span>
                    </div>
                  ))
                ) : (
                  <div className="rounded-lg border border-white/8 bg-black/20 p-3 text-sm text-zinc-400">
                    No metrics available yet.
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
          <Card className="border-white/8 bg-white/[0.03] shadow-none">
            <CardHeader className="border-b border-white/8">
              <div className="flex items-center gap-2">
                <Activity className="size-4 text-zinc-400" />
                <CardTitle className="text-white">Activity log</CardTitle>
              </div>
              <CardDescription className="text-zinc-500">
                Live recorder and compiler events for the active workspace.
              </CardDescription>
            </CardHeader>
            <CardContent className="min-h-0 pt-3">
              <ScrollArea
                className="h-[20rem] rounded-lg border border-white/8 bg-black/20 p-3 xl:h-full"
                aria-labelledby="log-heading"
                role="log"
              >
                <p id="log-heading" className="sr-only">
                  Session activity log
                </p>
                <pre className="font-mono text-xs leading-5 break-words whitespace-pre-wrap text-zinc-400">
                  {logLines.length > 0 ? logLines.join('\n') : 'Events from this run will appear here.'}
                </pre>
              </ScrollArea>
            </CardContent>
          </Card>

          <Card className="border-white/8 bg-white/[0.03] shadow-none">
            <CardHeader className="border-b border-white/8">
              <CardTitle className="text-white">Session metrics</CardTitle>
              <CardDescription className="text-zinc-500">
                Full backend metrics payload for debugging and validation.
              </CardDescription>
            </CardHeader>
            <CardContent className="min-h-0 pt-3">
              <ScrollArea className="h-[20rem] rounded-lg border border-white/8 bg-black/20 p-3 xl:h-full" aria-label="Session metrics in JSON">
                <pre className="font-mono text-xs leading-5 break-words whitespace-pre-wrap text-zinc-400">
                  {JSON.stringify(metrics ?? { info: 'No metrics yet' }, null, 2)}
                </pre>
              </ScrollArea>
            </CardContent>
          </Card>
        </section>
      </div>
    </AppShell>
  )
}
