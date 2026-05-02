import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { errorMessage, fetchSkillList, fetchWorkflow } from '@/api/workflowApi'
import { AppShell } from '@/components/layout/AppLayout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import {
  buildSkillPackage,
  downloadSkillPackZip,
  estimateSkillPackBuildSeconds,
  parseInputs,
  type SkillPackBuildResult,
} from '@/services/skillPackBuilder'
import { Boxes, CheckCircle2, Download, LoaderCircle, Package } from 'lucide-react'

/** Radix Select needs a sentinel item for the empty selection label. */
const NO_SKILL_SENTINEL = '__no_skill_selected__'

const GENERATION_PROGRESS_INTERVAL_MS = 250

function formatDurationLabel(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  if (remainder === 0) return `${minutes}m`
  return `${minutes}m ${remainder}s`
}

export function SkillPackBuilderPage() {
  const [jsonText, setJsonText] = useState('')
  const [selectedSkillId, setSelectedSkillId] = useState('')
  const [workflowLoadError, setWorkflowLoadError] = useState<string | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<SkillPackBuildResult | null>(null)
  const [generationStartedAt, setGenerationStartedAt] = useState<number | null>(null)
  const [generationNow, setGenerationNow] = useState<number | null>(null)

  const skillsQ = useQuery({
    queryKey: ['skillList'],
    queryFn: fetchSkillList,
    staleTime: 60_000,
  })

  const sortedSkills = useMemo(() => {
    const skills = [...(skillsQ.data?.skills ?? [])]
    skills.sort((a, b) => b.modified_at - a.modified_at)
    return skills
  }, [skillsQ.data?.skills])

  const detectedInputs = useMemo(() => {
    if (!jsonText.trim()) return []
    try {
      return parseInputs(jsonText)
    } catch {
      return []
    }
  }, [jsonText])

  const estimatedGenerationSeconds = useMemo(() => {
    if (!jsonText.trim()) return null
    try {
      return estimateSkillPackBuildSeconds(jsonText)
    } catch {
      return null
    }
  }, [jsonText])

  const generationElapsedSeconds = useMemo(() => {
    if (!isGenerating || generationStartedAt == null || generationNow == null) return 0
    return Math.max(0, (generationNow - generationStartedAt) / 1000)
  }, [generationNow, generationStartedAt, isGenerating])

  const generationProgressValue = useMemo(() => {
    const estimate = estimatedGenerationSeconds ?? 20
    if (!isGenerating) return 0
    if (estimate <= 0) return 12
    const ratio = generationElapsedSeconds / estimate
    if (ratio >= 1) return 96
    return Math.max(8, Math.min(96, Math.round((ratio ** 0.82) * 92)))
  }, [estimatedGenerationSeconds, generationElapsedSeconds, isGenerating])

  const generationStatusLabel = useMemo(() => {
    if (!isGenerating) return null
    if (estimatedGenerationSeconds == null) return 'Preparing package build…'
    const remaining = Math.max(0, Math.ceil(estimatedGenerationSeconds - generationElapsedSeconds))
    if (remaining === 0) return 'Finalizing package files…'
    return `About ${formatDurationLabel(remaining)} remaining`
  }, [estimatedGenerationSeconds, generationElapsedSeconds, isGenerating])

  const generationCaption = useMemo(() => {
    if (!isGenerating) return null
    const elapsed = formatDurationLabel(Math.max(1, Math.floor(generationElapsedSeconds)))
    if (estimatedGenerationSeconds == null) return `Elapsed ${elapsed}`
    return `Elapsed ${elapsed} of about ${formatDurationLabel(estimatedGenerationSeconds)}`
  }, [estimatedGenerationSeconds, generationElapsedSeconds, isGenerating])

  useEffect(() => {
    if (!isGenerating || generationStartedAt == null) {
      setGenerationNow(null)
      return
    }
    setGenerationNow(Date.now())
    const timer = window.setInterval(() => setGenerationNow(Date.now()), GENERATION_PROGRESS_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [generationStartedAt, isGenerating])

  const skillSelectValue = useMemo(() => {
    if (!selectedSkillId) return NO_SKILL_SENTINEL
    if (!sortedSkills.some((s) => s.skill_id === selectedSkillId)) return NO_SKILL_SENTINEL
    return selectedSkillId
  }, [selectedSkillId, sortedSkills])

  async function loadWorkflowForSkill(skillId: string) {
    setSelectedSkillId(skillId)
    setWorkflowLoadError(null)
    setError(null)
    try {
      const workflow = await fetchWorkflow(skillId)
      setJsonText(JSON.stringify(workflow, null, 2))
      const meta = sortedSkills.find((s) => s.skill_id === skillId)
      toast.success(meta ? `"${meta.title}" workflow loaded.` : 'Workflow loaded.')
    } catch (err) {
      const message = errorMessage(err, 'Could not load workflow for this skill.')
      setWorkflowLoadError(message)
      toast.error(message)
    }
  }

  async function handleGenerate() {
    setIsGenerating(true)
    setGenerationStartedAt(Date.now())
    setGenerationNow(Date.now())
    setError(null)
    try {
      const next = await buildSkillPackage(jsonText)
      setResult(next)
      toast.success(next.usedLlm ? 'Skill Package generated and saved.' : 'Skill Package generated, saved, and completed with deterministic fallback.')
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not generate Skill Package.'
      setError(message)
      toast.error(message)
    } finally {
      setIsGenerating(false)
      setGenerationStartedAt(null)
      setGenerationNow(null)
    }
  }

  async function handleZipDownload() {
    if (!result) return
    try {
      await downloadSkillPackZip(result)
      toast.success('Skill package zip downloaded.')
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not export zip.'
      toast.error(message)
    }
  }

  return (
    <AppShell
      title="Skill Pack Builder"
      description="Load a saved skill’s workflow JSON or paste a payload, then generate skill_package/workflows/<name> plus the shared engine and README."
      mainClassName="overflow-y-auto"
      actions={
        result ? (
          <Button type="button" size="sm" onClick={() => void handleZipDownload()}>
            <Download className="size-3.5" />
            Download ZIP
          </Button>
        ) : null
      }
    >
      <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6">
          <Card className="border-white/8 bg-white/[0.035] shadow-none">
            <CardHeader className="border-b border-white/8">
              <CardTitle className="text-white">Source JSON</CardTitle>
              <CardDescription className="text-zinc-500">
                Choose one of your saved skills to load its workflow, or paste JSON below. Each generation is saved under `skill_package/workflows`.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 pt-4">
              <div className="rounded-xl border border-white/10 bg-black/20 p-4">
                <div className="flex items-start gap-3">
                  <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04]">
                    <Boxes className="size-5 text-zinc-400" />
                  </div>
                  <div className="min-w-0 flex-1 space-y-2">
                    <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-zinc-500">Saved skill</p>
                    {skillsQ.isLoading ? (
                      <Skeleton className="h-9 w-full rounded-lg bg-white/10" />
                    ) : skillsQ.isError ? (
                      <p className="text-sm text-red-300">{errorMessage(skillsQ.error, 'Could not load skills.')}</p>
                    ) : sortedSkills.length === 0 ? (
                      <p className="text-sm text-zinc-500">No saved skills yet. Create one in Human Edit first, then return here.</p>
                    ) : (
                      <Select
                        value={skillSelectValue}
                        onValueChange={(value) => {
                          setWorkflowLoadError(null)
                          if (value === NO_SKILL_SENTINEL) {
                            setSelectedSkillId('')
                            return
                          }
                          void loadWorkflowForSkill(value)
                        }}
                      >
                        <SelectTrigger size="sm" className="w-full border-white/15 bg-black/40 text-zinc-100">
                          <SelectValue placeholder="Select a skill…" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={NO_SKILL_SENTINEL} className="text-zinc-500">
                            None (paste JSON only)
                          </SelectItem>
                          {sortedSkills.map((skill) => (
                            <SelectItem key={skill.skill_id} value={skill.skill_id}>
                              <span className="truncate">{skill.title}</span>
                              <span className="ml-2 shrink-0 text-xs text-zinc-500">{skill.step_count} steps</span>
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                    {workflowLoadError ? (
                      <p className="text-xs text-red-400">{workflowLoadError}</p>
                    ) : selectedSkillId && sortedSkills.some((s) => s.skill_id === selectedSkillId) ? (
                      <p className="text-xs text-zinc-500">
                        Showing workflow for{' '}
                        <span className="text-zinc-300">{sortedSkills.find((s) => s.skill_id === selectedSkillId)?.title}</span>.
                      </p>
                    ) : null}
                  </div>
                </div>
              </div>
              <Textarea
                value={jsonText}
                onChange={(event) => {
                  setJsonText(event.target.value)
                  setError(null)
                  setWorkflowLoadError(null)
                }}
                placeholder='Paste workflow JSON here after choosing a skill, or edit the loaded payload directly.'
                className="min-h-[22rem] resize-y border-white/10 bg-black/20 font-mono text-xs leading-6 text-zinc-100 placeholder:text-zinc-500"
              />
              <div className="flex items-center justify-between gap-3">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
                    {detectedInputs.length} inputs detected
                  </Badge>
                  {estimatedGenerationSeconds != null ? (
                    <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
                      ~{formatDurationLabel(estimatedGenerationSeconds)} build
                    </Badge>
                  ) : null}
                  {result ? (
                    <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
                      {result.stepCount} steps
                    </Badge>
                  ) : null}
                </div>
                <Button type="button" onClick={() => void handleGenerate()} disabled={isGenerating}>
                  {isGenerating ? <LoaderCircle className="size-3.5 animate-spin" /> : <Package className="size-3.5" />}
                  Generate Skill Package
                </Button>
              </div>
              {isGenerating ? (
                <div className="rounded-xl border border-sky-400/20 bg-sky-500/[0.07] p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="space-y-1">
                      <p className="text-sm font-medium text-sky-100">Generating skill package</p>
                      <p className="text-xs text-sky-100/75">{generationStatusLabel}</p>
                    </div>
                    <Badge variant="outline" className="border-sky-300/20 bg-sky-300/10 text-sky-100">
                      {generationProgressValue}%
                    </Badge>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
                    <div
                      className="h-full rounded-full bg-linear-to-r from-sky-400 via-cyan-300 to-emerald-300 transition-[width] duration-300 ease-out"
                      style={{ width: `${generationProgressValue}%` }}
                    />
                  </div>
                  <p className="mt-2 text-[11px] uppercase tracking-[0.16em] text-sky-100/60">{generationCaption}</p>
                </div>
              ) : null}
            </CardContent>
          </Card>

          {error ? (
            <Card className="border-red-500/20 bg-red-500/5 shadow-none">
              <CardContent className="p-4 text-sm text-red-200">{error}</CardContent>
            </Card>
          ) : null}

          {result ? (
            <Card className="border-emerald-500/20 bg-emerald-500/5 shadow-none">
              <CardContent className="space-y-2 p-4 text-sm text-emerald-100">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="size-4" />
                  Skill Package ready at skill_package/workflows/{result.name}.
                </div>
                {result.warnings.map((warning) => (
                  <p key={warning} className="text-xs text-emerald-200/85">
                    {warning}
                  </p>
                ))}
              </CardContent>
            </Card>
          ) : null}
      </div>
    </AppShell>
  )
}
